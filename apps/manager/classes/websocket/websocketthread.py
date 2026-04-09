import asyncio
import ipaddress
import json
import logging
import os
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from utils.log_safety import safe_log_id
from utils.auth import SecurityError, validate_token_and_get_claims
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

try:
    import orjson  # type: ignore
except Exception:  # noqa: BLE001
    orjson = None


def _json_loads(s: str):
    if orjson is not None:
        return orjson.loads(s)
    return json.loads(s)


def _json_dumps(obj: object) -> str:
    if orjson is not None:
        return orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


class WebSocketThread(threading.Thread):
    """
    WebSocket server thread (FastAPI + uvicorn).

    Message envelope (client → server):
    - `uuid`: client identifier (string). Must remain consistent for the life of the connection.
    - `type`: one of `auth`, `info`, `management`, `inference`.
    - `payload`: type-specific dict payload.

    Internal fields (server-only, never required from clients):
    - `_correlation_id`: injected UUID4 string for every inbound message (including `auth`).
      This is used for tracing across threads/handlers; logs should use `safe_log_id(...)`
      so the raw value never appears in output.
    - `_auth`: dict of verified auth context (`sub`, `tenant_id`, `roles`) attached after auth.

    Notes:
    - Backpressure NACKs are emitted by `JobThread` when per-user queues are full; see `docs/RUNBOOK.md`.
    """

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
        # Tenant-level token bucket (sum across all connections).
        # {tenant_id: {"tokens": float, "last": float}}
        self._tenant_buckets: Dict[str, dict] = {}

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
        async def metrics(request: Request):
            """Prometheus metrics endpoint."""
            # Restrict metrics to loopback/private addresses only.
            try:
                host = request.client.host if request.client else ""
                ip = ipaddress.ip_address(host)
                if not (ip.is_loopback or ip.is_private):
                    return JSONResponse(status_code=403, content={"detail": "Forbidden"})
            except Exception:
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
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
                _json_dumps(
                    {"type": "error", "payload": {"message": error_message}}
                )
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

        # Fail-fast safety: refuse insecure auth config outside development.
        env = (os.getenv("TCM_ENV", "development") or "development").lower()
        mode = (self.auth_config.get("mode") or "simple").lower()
        require_token = bool(self.auth_config.get("require_token", False))
        if env != "development" and (mode == "simple" or require_token is False):
            logger.critical(
                "SECURITY_FAIL_FAST: refusing to start with insecure auth configuration",
                extra={
                    "client_uuid": "-",
                    "job_id": "-",
                    "job_type": "ws_server",
                    "auth_mode": mode,
                    "require_token": require_token,
                    "tcm_env": env,
                },
            )
            raise SecurityError("Insecure auth config outside development (mode=simple or require_token=false)")

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

    def _check_tenant_rate(self, tenant_id: str) -> bool:
        """
        Apply a tenant-scoped token bucket if configured.

        This is in-memory per replica (defence-in-depth). For true global quotas
        across replicas, enforce limits at the gateway or via a shared store.
        """
        limit = int(self.rate_limit_config.get("messages_per_second_per_tenant") or 0)
        if limit <= 0:
            return True

        tid = str(tenant_id or "unknown")
        now = time.time()
        with self._rate_lock:
            b = self._tenant_buckets.get(tid)
            if b is None:
                b = {"tokens": float(limit), "last": now}
                self._tenant_buckets[tid] = b

            last = float(b.get("last", now))
            tokens = float(b.get("tokens", float(limit)))

            # Refill tokens (rate = limit tokens/sec), cap at limit.
            elapsed = max(0.0, now - last)
            tokens = min(float(limit), tokens + (elapsed * float(limit)))

            if tokens < 1.0:
                b["tokens"] = tokens
                b["last"] = now
                RATE_LIMIT_VIOLATIONS_TOTAL.labels(scope="tenant").inc()
                return False

            b["tokens"] = tokens - 1.0
            b["last"] = now
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
                message = _json_loads(raw_msg)
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

            # Correlation id for this incoming message (auth).
            message["_correlation_id"] = str(uuid.uuid4())

            # Optional multi-tenant auth payload validation
            payload = message.get("payload", {}) or {}

            # Token validation (strict mode returns verified claims).
            token = payload.get("token")
            try:
                ok, token_error, claims = validate_token_and_get_claims(token, self.auth_config)
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

            # IMPORTANT:
            # - In strict mode, derive identity from verified token claims.
            # - In development + simple mode, allow client-provided roles to support local testing.
            # - Outside development, never grant implicit privileges from client payload.
            env = (os.getenv("TCM_ENV", "development") or "development").lower()
            mode = (self.auth_config.get("mode") or "simple").lower()
            sub = None
            tenant_id = None
            roles: list[str] = []
            if mode == "strict":
                if isinstance(claims, dict):
                    raw_sub = claims.get("sub")
                    if isinstance(raw_sub, str):
                        sub = raw_sub
                    raw_tenant = claims.get("tenant_id") or claims.get("tenant")
                    if isinstance(raw_tenant, str):
                        tenant_id = raw_tenant
                    raw_roles = claims.get("roles") or claims.get("role") or claims.get("permissions") or []
                    if isinstance(raw_roles, str):
                        roles = [raw_roles]
                    elif isinstance(raw_roles, (list, tuple)):
                        roles = [r for r in raw_roles if isinstance(r, str)]

            if env == "development" and mode != "strict":
                client_block = payload.get("client") if isinstance(payload, dict) else None
                if isinstance(client_block, dict):
                    raw_roles = client_block.get("roles") or []
                    if isinstance(raw_roles, str):
                        roles = [raw_roles]
                    elif isinstance(raw_roles, (list, tuple)):
                        roles = [r for r in raw_roles if isinstance(r, str)]
                # Dev convenience: if roles are still empty, grant minimal local roles
                # so smoke tests can run without a JWT/claims pipeline.
                if not roles:
                    roles = ["inference", "management"]

            # Fail-safe: in non-development, simple mode must not yield any implicit privileges.
            if env != "development" and mode != "strict":
                roles = []

            # Check if client already connected
            with self.clients_lock:
                if client_id in self.clients:
                    await self._send_error(websocket, f"UUID '{client_id}' is already connected")
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
            await websocket.send_text(_json_dumps({"type": "auth.ok"}))
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
                    await asyncio.get_event_loop().run_in_executor(None, self.on_connect, client_id)
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
                    message = _json_loads(raw_msg)
                except Exception:
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

                # Correlation id for this incoming message.
                message["_correlation_id"] = str(uuid.uuid4())

                # Attach auth context (if any) so downstream components can enforce roles/limits
                if client_id:
                    auth_ctx = self.client_auth.get(client_id, {})
                    message["_auth"] = auth_ctx

                # Tenant-level quota (sum of all connections).
                tenant_id = (message.get("_auth") or {}).get("tenant_id")
                if not self._check_tenant_rate(str(tenant_id or "unknown")):
                    await websocket.send_text(
                        _json_dumps(
                            {
                                "type": "error",
                                "payload": {
                                    "code": "BACKPRESSURE_TENANT_LIMIT_REACHED",
                                    "message": "Tenant quota exceeded (messages per second).",
                                },
                            }
                        )
                    )
                    await websocket.close(code=1008)
                    break

                # Call message handler in executor to avoid blocking async loop
                if self.on_message:
                    try:
                        observe_ws_message(message.get("type", "unknown"))
                        corr = safe_log_id(message.get("_correlation_id"))
                        await asyncio.get_event_loop().run_in_executor(None, self.on_message, client_id, message)
                    except Exception as e:
                        logger.exception(
                            "Error in on_message callback: %s",
                            e,
                            extra={
                                "client_uuid": client_id or "-",
                                "job_id": "-",
                                "job_type": "ws_on_message",
                                "correlation_id": corr,
                            },
                        )

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

                # Memory hygiene: clear rate-limit state for this client ID.
                with self._rate_lock:
                    self._msg_timestamps.pop(client_id, None)
                    # IMPORTANT: do NOT clear auth-failure timestamps on disconnect.
                    # We want auth failure rate limiting to apply across reconnect attempts
                    # within the configured time window.

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
                websocket.send_text(_json_dumps(message)),
                self.loop,
            )

            # Fire-and-forget: never block worker threads on the async loop.
            def _done(f):
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "WebSocket send failed asynchronously for %s: %s",
                        client_id,
                        e,
                        extra={
                            "client_uuid": client_id,
                            "job_id": "-",
                            "job_type": "ws_send",
                        },
                    )

            future.add_done_callback(_done)
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
        # Fail-fast safety: if auth config was never set, treat as insecure outside development.
        env = (os.getenv("TCM_ENV", "development") or "development").lower()
        mode = (self.auth_config.get("mode") or "simple").lower()
        require_token = bool(self.auth_config.get("require_token", False))
        if env != "development" and (mode == "simple" or require_token is False):
            logger.critical(
                "SECURITY_FAIL_FAST: refusing to start with insecure auth configuration",
                extra={
                    "client_uuid": "-",
                    "job_id": "-",
                    "job_type": "ws_server",
                    "auth_mode": mode,
                    "require_token": require_token,
                    "tcm_env": env,
                },
            )
            raise RuntimeError("Refusing to start: insecure auth config outside development")
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
            # If port=0 was requested, uvicorn binds an ephemeral port. Capture it.
            try:
                if self.port == 0 and getattr(server, "servers", None):
                    srv = server.servers[0]
                    if getattr(srv, "sockets", None):
                        sock = srv.sockets[0]
                        self.port = int(sock.getsockname()[1])
            except Exception:
                # Best-effort only; do not fail server startup on introspection.
                logger.debug(
                    "Failed to introspect uvicorn bound port",
                    extra={"client_uuid": "-", "job_id": "-", "job_type": "ws_server"},
                )
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
