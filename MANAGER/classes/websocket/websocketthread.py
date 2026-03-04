import asyncio
import json
import logging
import threading
from typing import Callable, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

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

        # Store active connections: {client_id: WebSocket}
        self.clients: Dict[str, WebSocket] = {}
        self.clients_lock = threading.Lock()

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

    async def _handle_client(self, websocket: WebSocket):
        """Handle individual client connection"""
        client_id = None

        try:
            # Accept connection
            await websocket.accept()
            logger.info("Client connected, waiting for auth")

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

            # Check if client already connected
            with self.clients_lock:
                if client_id in self.clients:
                    await self._send_error(
                        websocket, f"UUID '{client_id}' is already connected"
                    )
                    await websocket.close(code=1008)
                    return

                # Store client connection
                self.clients[client_id] = websocket

            # Send auth confirmation
            await websocket.send_text(json.dumps({"type": "auth.ok"}))
            logger.info("Client '%s' authenticated", client_id)

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
                    continue  # Don't close connection, just skip this message

                # Call message handler in executor to avoid blocking async loop
                if self.on_message:
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None, self.on_message, client_id, message
                        )
                    except Exception as e:
                        logger.exception("Error in on_message callback: %s", e)

        except WebSocketDisconnect:
            logger.info("Client %s disconnected", client_id)

        except Exception as e:
            logger.exception("Error handling client %s: %s", client_id, e)

        finally:
            # Remove client
            if client_id:
                with self.clients_lock:
                    self.clients.pop(client_id, None)

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
            logger.warning("Client %s not connected", client_id)
            return False

        if not self.loop:
            logger.warning("Event loop not available")
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
            logger.exception("Failed to send to %s: %s", client_id, e)
            return False

    def send_to_first_client(self, message: dict) -> bool:
        """Send message to the first connected client (if any)."""
        with self.clients_lock:
            first_client_id = next(iter(self.clients), None)

        if not first_client_id:
            logger.debug("No connected clients for alert delivery")
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
        logger.info("Starting on %s:%s", self.host, self.port)

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
            logger.exception("Server error: %s", e)
        finally:
            self._ready_event.set()  # Unblock any waiter if we failed to start
            self.loop.close()

    def stop(self):
        """Stop the server and close all connections"""
        logger.info("Stopping")
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
                logger.warning("Error closing client %s: %s", client_id, e)
