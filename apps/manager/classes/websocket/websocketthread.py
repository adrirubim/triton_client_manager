import asyncio
import json
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from utils.auth import SecurityError, validate_token
from utils.metrics import (
    AUTH_FAILURES_TOTAL,
    RATE_LIMIT_VIOLATIONS_TOTAL,
    WS_CONNECTIONS_TOTAL,
    WS_DISCONNECTIONS_TOTAL,
    WS_ERRORS_TOTAL,
    generate_metrics_response,
    observe_ws_message,
)

logger = logging.getLogger(__name__)


class WebSocketThread(threading.Thread):
    def __init__(
        self,
        host: str,
        port: int,
        valid_types: List[str],
        on_message: Callable[[str, dict], None],
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None,
        max_message_bytes: int = 64 * 1024,
        get_queue_stats: Optional[Callable[[], dict]] = None,
    ):
        """
        Initialize WebSocket server.

        Args:
            host: Host to bind to (e.g., "0.0.0.0")
            port: Port to listen on
            valid_types: List of valid message types (from config)
            on_message: Callback when client sends message (client_id, message)
            on_connect: Optional callback when client connects (client_id)
            on_disconnect: Optional callback when client disconnects (client_id)
        """
        super().__init__(name="WebSocket_Thread", daemon=True)

        self.host = host
        self.port = port
        self.valid_types = set(valid_types)  # Convert to set for O(1) lookup
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.max_message_bytes = max_message_bytes
        self.get_queue_stats = get_queue_stats

        # Auth / rate limiting configuration (optional, from websocket.yaml).
        self.auth_config: Dict = {}
        self.rate_limit_config: Dict = {}

        # Store active connections: {client_id: WebSocket}
        self.clients: Dict[str, WebSocket] = {}
        # Store auth context per client_id: {client_id: {"sub": ..., "tenant_id": ..., "roles": [...]}}
        self.client_auth: Dict[str, dict] = {}
        self.clients_lock = threading.Lock()

        # In‑memory rate limiting structures (per client UUID).
        self._rate_lock = threading.Lock()
        self._msg_timestamps: Dict[str, List[float]] = {}
        self._auth_fail_timestamps: Dict[str, List[float]] = {}

        # FastAPI app
        self.app = FastAPI()
        self._setup_routes()

        # Event loop for async operations
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()

    def _setup_routes(self):
        """Setup WebSocket and health check endpoints"""

        @self.app.get("/health")
        async def health():
            """Liveness probe for Kubernetes/load balancers."""
            return {"status": "ok"}

        @self.app.get("/ready")
        async def ready():
            """Readiness probe (server ready to accept connections)."""
            return {"status": "ready"}

        @self.app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint."""
            return generate_metrics_response(self.get_queue_stats)

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_client(websocket)

    def _validate_message(self, message: dict) -> tuple[bool, str]:
        """
        Validate message format.

        Returns:
            (is_valid, error_message)
        """
        # Check required fields
        if "uuid" not in message:
            return False, "Missing required field: 'uuid'"
        if "type" not in message:
            return False, "Missing required field: 'type'"
        if "payload" not in message:
            return False, "Missing required field: 'payload'"

        # Validate field types
        if not isinstance(message["uuid"], str):
            return False, "Field 'uuid' must be a string"
        if not isinstance(message["type"], str):
            return False, "Field 'type' must be a string"
        if not isinstance(message["payload"], dict):
            return False, "Field 'payload' must be a dictionary"

        # Validate type is in allowed list
        if message["type"] not in self.valid_types:
            return (
                False,
                f"Invalid type '{message['type']}'. Must be one of: {sorted(self.valid_types)}",
            )

        return True, ""

    async def _send_error(self, websocket: WebSocket, error_message: str):
        """Send error message to client"""
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "payload": {"message": error_message}})
            )
        except Exception as e:
            logger.error("Failed to send error: %s", e)

    def set_auth_and_rate_limits(
        self,
        auth_config: Optional[Dict] = None,
        rate_limit_config: Optional[Dict] = None,
    ) -> None:
        """Configure auth and rate limiting behavior.

        This is kept separate from __init__ to remain backwards compatible
        with existing call sites that only pass host/port/valid_types.
        """
        self.auth_config = auth_config or {}
        self.rate_limit_config = rate_limit_config or {}

    def _check_message_rate(self, client_id: str) -> bool:
        """Apply simple per-client message rate limiting if configured."""
        limit = self.rate_limit_config.get("messages_per_second_per_client") or 0
        if limit <= 0:
            return True

        now = time.time()
        window = 1.0

        with self._rate_lock:
            timestamps = self._msg_timestamps.setdefault(client_id, [])
            cutoff = now - window
            timestamps = [t for t in timestamps if t >= cutoff]
            if len(timestamps) >= limit:
                self._msg_timestamps[client_id] = timestamps
                RATE_LIMIT_VIOLATIONS_TOTAL.labels(scope="messages").inc()
                return False
            timestamps.append(now)
            self._msg_timestamps[client_id] = timestamps
        return True

    def _record_auth_failure(self, client_id: str) -> bool:
        """Record an auth failure and enforce per-client limits if configured."""
        limit = (
            self.rate_limit_config.get(
                "auth_failures_per_minute_per_client",
            )
            or 0
        )
        now = time.time()
        window = 60.0

        with self._rate_lock:
            timestamps = self._auth_fail_timestamps.setdefault(client_id, [])
            cutoff = now - window
            timestamps = [t for t in timestamps if t >= cutoff]
            timestamps.append(now)
            self._auth_fail_timestamps[client_id] = timestamps

            if limit > 0 and len(timestamps) > limit:
                RATE_LIMIT_VIOLATIONS_TOTAL.labels(scope="auth").inc()
                return False

        return True

    async def _handle_client(self, websocket: WebSocket):
        """Handle individual client connection"""
        client_id = None

        try:
            # Accept connection
            await websocket.accept()
            WS_CONNECTIONS_TOTAL.inc()
            logger.info(
                "Client connected, waiting for auth",
                extra={"client_uuid": "-", "job_id": "-", "job_type": "ws_auth"},
            )

            # ========== FIRST MESSAGE: AUTH ==========
            raw_msg = await websocket.receive_text()

            # Hard limit on message size to avoid abuse / OOM
            if len(raw_msg.encode("utf-8")) > self.max_message_bytes:
                await self._send_error(
                    websocket,
                    f"Message too large (>{self.max_message_bytes} bytes)",
                )
                await websocket.close(code=1009)  # Close with "message too big"
                return

            try:
                message = json.loads(raw_msg)
            except json.JSONDecodeError:
                await self._send_error(websocket, "Invalid JSON format")
                await websocket.close(code=1008)
                return

            # Validate message format
            is_valid, error = self._validate_message(message)
            if not is_valid:
                await self._send_error(websocket, error)
                await websocket.close(code=1008)
                return

            # First message MUST be auth
            if message["type"] != "auth":
                await self._send_error(websocket, "First message must be type 'auth'")
                await websocket.close(code=1008)
                return

            # Extract client ID from uuid
            client_id = message["uuid"]
            observe_ws_message(message.get("type", "unknown"))

            # Optional multi-tenant auth payload validation
            payload = message.get("payload", {}) or {}
            client_block = payload.get("client")
            roles = []
            tenant_id = None
            sub = None
            if client_block is not None:
                sub = client_block.get("sub")
                tenant_id = client_block.get("tenant_id")
                roles = client_block.get("roles", [])
                if (
                    not isinstance(sub, str)
                    or not isinstance(tenant_id, str)
                    or not isinstance(roles, list)
                ):
                    AUTH_FAILURES_TOTAL.labels(reason="invalid_payload").inc()
                    await self._send_error(
                        websocket,
                        "Invalid auth payload: expected 'client.sub', 'client.tenant_id', and 'client.roles'",
                    )
                    await websocket.close(code=1008)
                    return

            # Optional token validation (claims + optional cryptographic verification when configured).
            token = payload.get("token")
            try:
                ok, token_error = validate_token(token, self.auth_config)
            except SecurityError as exc:
                AUTH_FAILURES_TOTAL.labels(reason="auth_config").inc()
                await self._send_error(
                    websocket,
                    f"Auth configuration error: {exc}",
                )
                await websocket.close(code=1008)
                return
            if not ok:
                AUTH_FAILURES_TOTAL.labels(reason="token").inc()
                if not self._record_auth_failure(client_id):
                    await self._send_error(
                        websocket,
                        "Too many failed auth attempts for this client",
                    )
                    await websocket.close(code=1008)
                    return
                await self._send_error(
                    websocket,
                    f"Invalid token: {token_error}",
                )
                await websocket.close(code=1008)
                return

            # Check if client already connected
            with self.clients_lock:
                if client_id in self.clients:
                    await self._send_error(
                        websocket, f"UUID '{client_id}' is already connected"
                    )
                    await websocket.close(code=1008)
                    return

                # Store client connection and auth context
                self.clients[client_id] = websocket
                self.client_auth[client_id] = {
                    "sub": sub,
                    "tenant_id": tenant_id,
                    "roles": roles,
                }

            # Send auth confirmation
            await websocket.send_text(json.dumps({"type": "auth.ok"}))
            logger.info(
                "Client '%s' authenticated",
                client_id,
                extra={
                    "client_uuid": client_id,
                    "job_id": "-",
                    "job_type": "auth",
                },
            )

            # Notify connection callback
            if self.on_connect:
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.on_connect, client_id
                    )
                except Exception as e:
                    logger.exception("Error in on_connect callback: %s", e)

            # ========== SUBSEQUENT MESSAGES ==========
            while True:
                raw_msg = await websocket.receive_text()

                if len(raw_msg.encode("utf-8")) > self.max_message_bytes:
                    await self._send_error(
                        websocket,
                        f"Message too large (>{self.max_message_bytes} bytes)",
                    )
                    await websocket.close(code=1009)
                    break

                try:
                    message = json.loads(raw_msg)
                except json.JSONDecodeError:
                    await self._send_error(websocket, "Invalid JSON format")
                    continue  # Don't close connection, just skip this message

                # Validate message format
                is_valid, error = self._validate_message(message)
                if not is_valid:
                    await self._send_error(websocket, error)
                    continue  # Don't close connection, just skip this message

                # Verify UUID matches authenticated client
                if message["uuid"] != client_id:
                    await self._send_error(
                        websocket,
                        f"UUID mismatch. Expected '{client_id}', got '{message['uuid']}'",
                    )
                    await websocket.close(code=1008)
                    break

                # Rate limiting: messages per client (if enabled).
                if not self._check_message_rate(client_id):
                    await self._send_error(
                        websocket,
                        "Rate limit exceeded for this client (messages per second)",
                    )
                    await websocket.close(code=1008)
                    break

                # Attach auth context (if any) so downstream components can enforce roles/limits
                if client_id:
                    auth_ctx = self.client_auth.get(client_id, {})
                    message["_auth"] = auth_ctx

                # Call message handler in executor to avoid blocking async loop
                if self.on_message:
                    try:
                        observe_ws_message(message.get("type", "unknown"))
                        await asyncio.get_event_loop().run_in_executor(
                            None, self.on_message, client_id, message
                        )
                    except Exception as e:
                        logger.exception("Error in on_message callback: %s", e)

        except WebSocketDisconnect:
            WS_DISCONNECTIONS_TOTAL.inc()
            logger.info(
                "Client %s disconnected",
                client_id,
                extra={
                    "client_uuid": client_id or "-",
                    "job_id": "-",
                    "job_type": "disconnect",
                },
            )

        except Exception as e:
            WS_ERRORS_TOTAL.inc()
            logger.exception(
                "Error handling client %s: %s",
                client_id,
                e,
                extra={
                    "client_uuid": client_id or "-",
                    "job_id": "-",
                    "job_type": "ws_error",
                },
            )

        finally:
            # Remove client
            if client_id:
                with self.clients_lock:
                    self.clients.pop(client_id, None)
                    self.client_auth.pop(client_id, None)

                if self.on_disconnect:
                    try:
                        self.on_disconnect(client_id)
                    except Exception as e:
                        logger.exception("Error in on_disconnect callback: %s", e)

    def send_to_client(self, client_id: str, message: dict) -> bool:
        """
        Send message to specific client.
        Thread-safe.

        Args:
            client_id: ID of the client to send to
            message: Dictionary to send (will be JSON encoded)

        Returns:
            True if sent successfully, False otherwise
        """
        with self.clients_lock:
            websocket = self.clients.get(client_id)

        if not websocket:
            logger.warning(
                "Client %s not connected",
                client_id,
                extra={
                    "client_uuid": client_id,
                    "job_id": "-",
                    "job_type": "ws_send",
                },
            )
            return False

        if not self.loop:
            logger.warning(
                "Event loop not available",
                extra={
                    "client_uuid": client_id,
                    "job_id": "-",
                    "job_type": "ws_send",
                },
            )
            return False

        try:
            # Schedule send in the event loop
            future = asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps(message)), self.loop
            )
            # Wait for completion with timeout
            future.result(timeout=5.0)
            return True
        except Exception as e:
            logger.exception(
                "Failed to send to %s: %s",
                client_id,
                e,
                extra={
                    "client_uuid": client_id,
                    "job_id": "-",
                    "job_type": "ws_send",
                },
            )
            return False

    def send_to_first_client(self, message: dict) -> bool:
        """Send message to the first connected client (if any)."""
        with self.clients_lock:
            first_client_id = next(iter(self.clients), None)

        if not first_client_id:
            logger.debug(
                "No connected clients for alert delivery",
                extra={
                    "client_uuid": "-",
                    "job_id": "-",
                    "job_type": "ws_broadcast",
                },
            )
            return False

        return self.send_to_client(first_client_id, message)

    def broadcast(self, message: dict, exclude: Optional[str] = None):
        """
        Send message to all connected clients.

        Args:
            message: Dictionary to send (will be JSON encoded)
            exclude: Optional client_id to exclude from broadcast
        """
        with self.clients_lock:
            client_ids = list(self.clients.keys())

        for client_id in client_ids:
            if client_id != exclude:
                self.send_to_client(client_id, message)

    def get_connected_clients(self) -> list[str]:
        """Get list of currently connected client IDs"""
        with self.clients_lock:
            return list(self.clients.keys())

    def is_client_connected(self, client_id: str) -> bool:
        """Check if a specific client is connected"""
        with self.clients_lock:
            return client_id in self.clients

    def wait_until_ready(self, timeout=30) -> bool:
        """Wait until the uvicorn server has started and is accepting connections"""
        return self._ready_event.wait(timeout)

    def run(self):
        """Run the server in this thread"""
        logger.info(
            "Starting on %s:%s",
            self.host,
            self.port,
            extra={"client_uuid": "-", "job_id": "-", "job_type": "ws_server"},
        )

        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Configure uvicorn (ws="wsproto" avoids websockets.legacy deprecation warnings)
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            loop="asyncio",
            log_level="info",
            ws="wsproto",
        )
        server = uvicorn.Server(config)
        self._server = server  # For graceful stop: set should_exit from stop()

        # Signal ready once uvicorn has bound the socket.
        # Server.lifespan is set in _serve(), not __init__; we must set it before startup().
        async def _serve_with_ready():
            if not server.config.loaded:
                server.config.load()
            server.lifespan = server.config.lifespan_class(server.config)
            await server.startup()
            self._ready_event.set()
            await server.main_loop()
            await server.shutdown()

        # Run server
        try:
            self.loop.run_until_complete(_serve_with_ready())
        except Exception as e:
            logger.exception(
                "Server error: %s",
                e,
                extra={"client_uuid": "-", "job_id": "-", "job_type": "ws_server"},
            )
        finally:
            self._ready_event.set()  # Unblock any waiter if we failed to start
            self.loop.close()

    def stop(self):
        """Stop the server and close all connections"""
        logger.info(
            "Stopping",
            extra={"client_uuid": "-", "job_id": "-", "job_type": "ws_server"},
        )
        self._stop_event.set()

        # Signal uvicorn to exit gracefully (main_loop checks should_exit ~every 0.1s)
        if getattr(self, "_server", None):
            self._server.should_exit = True

        # Close all client connections so shutdown proceeds quickly
        with self.clients_lock:
            client_ids = list(self.clients.keys())

        for client_id in client_ids:
            try:
                with self.clients_lock:
                    websocket = self.clients.get(client_id)
                if websocket and self.loop:
                    asyncio.run_coroutine_threadsafe(websocket.close(), self.loop)
            except Exception as e:
                logger.warning(
                    "Error closing client %s: %s",
                    client_id,
                    e,
                    extra={
                        "client_uuid": client_id,
                        "job_id": "-",
                        "job_type": "ws_server",
                    },
                )
