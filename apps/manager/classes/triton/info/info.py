import logging

logger = logging.getLogger(__name__)

import time
import heapq

import tritonclient.http as httpclient

from ..constants import HTTP_PORT

###################################
#      Triton Info Handler        #
###################################


class TritonInfo:
    """Handles Triton Inference Server health checks, model load/unload, and metadata."""

    def __init__(
        self,
        timeout: int = 5,
        http_port: int = HTTP_PORT,
        *,
        connection_timeout: int | None = None,
        network_timeout: int | None = None,
    ):
        self.timeout = timeout
        self.connection_timeout = int(connection_timeout if connection_timeout is not None else timeout)
        self.network_timeout = int(network_timeout if network_timeout is not None else timeout)
        self.http_port = http_port
        self._clients: dict[str, httpclient.InferenceServerClient] = {}
        self._clients_lock = None  # lazy init to avoid importing threading at module import time
        # Graceful close queue: (close_at_epoch_seconds, client)
        # This prevents closing a client while another thread may still be using it.
        self._close_delay_seconds = 30
        self._to_close_heap: list[tuple[float, httpclient.InferenceServerClient]] = []

    def _client(self, vm_ip: str, timeout: int = None) -> httpclient.InferenceServerClient:
        # Cache only for default timeout to avoid unbounded cache cardinality on varying timeouts.
        if timeout is None:
            if self._clients_lock is None:
                import threading

                self._clients_lock = threading.Lock()
            with self._clients_lock:
                c = self._clients.get(vm_ip)
                if c is not None:
                    return c
                c = httpclient.InferenceServerClient(
                    url=f"{vm_ip}:{self.http_port}",
                    connection_timeout=self.connection_timeout,
                    network_timeout=self.network_timeout,
                )
                self._clients[vm_ip] = c
                return c

        t = timeout
        return httpclient.InferenceServerClient(
            url=f"{vm_ip}:{self.http_port}",
            connection_timeout=t,
            network_timeout=t,
        )

    def prune_clients(self, active_vm_ips: set[str]) -> None:
        """
        Best-effort cleanup for cached HTTP clients.

        Without this, a churny fleet (dynamic vm_ip set) will leak cached clients
        over time. We only cache HTTP clients; gRPC clients are created per check.
        """
        if self._clients_lock is None:
            # No clients were ever created.
            return
        try:
            # Pop stale clients under lock, close outside lock to avoid blocking
            # concurrent client acquisition/health checks on slow close().
            #
            # IMPORTANT: we do NOT close immediately. The httpclient is shared
            # across threads; closing concurrently with a request can create
            # hard-to-debug false negatives. We defer closure to a grace window.
            to_close: list[httpclient.InferenceServerClient] = []
            with self._clients_lock:
                stale = [ip for ip in list(self._clients.keys()) if ip not in active_vm_ips]
                for ip in stale:
                    c = self._clients.pop(ip, None)
                    if c is not None:
                        to_close.append(c)

                # Schedule closures for later.
                close_at = time.time() + float(self._close_delay_seconds)
                for c in to_close:
                    heapq.heappush(self._to_close_heap, (close_at, c))
        except Exception:
            # Never fail health loops due to cleanup issues.
            return

    def _drain_due_closures_locked(self, *, now: float) -> None:
        """
        Pop any deferred clients whose grace window has elapsed.
        Must be called with _clients_lock held.
        """
        # NOTE: Actual close is performed outside the lock by drain_due_closures().
        return

    def drain_due_closures(self) -> None:
        """
        Best-effort public entry point to drain deferred closures.
        Safe to call from health/readiness paths.
        """
        if self._clients_lock is None:
            return
        try:
            now = time.time()
            to_close: list[httpclient.InferenceServerClient] = []
            with self._clients_lock:
                while self._to_close_heap and self._to_close_heap[0][0] <= float(now):
                    _ts, client = heapq.heappop(self._to_close_heap)
                    to_close.append(client)
            for c in to_close:
                try:
                    c.close()
                except Exception:
                    pass
        except Exception:
            return

    # -------------------------------------------- #
    #              HEALTH CHECKS                   #
    # -------------------------------------------- #
    def is_server_ready(self, vm_ip: str, *, protocol: str = "http", timeout: int | None = None) -> bool:
        """
        Protocol-aware readiness check.

        - HTTP: uses cached `tritonclient.http.InferenceServerClient`
        - gRPC: creates a short-lived gRPC client per check (no cache)
        """
        proto = (protocol or "http").lower()
        # Opportunistic cleanup (keeps heap from growing without a dedicated janitor thread).
        self.drain_due_closures()
        if proto == "grpc":
            try:
                from ..constants import GRPC_PORT
                import tritonclient.grpc as grpcclient

                client = grpcclient.InferenceServerClient(url=f"{vm_ip}:{GRPC_PORT}")
                try:
                    # Newer clients support client_timeout; older may ignore.
                    if timeout is None:
                        return bool(client.is_server_ready())
                    try:
                        return bool(client.is_server_ready(client_timeout=int(timeout)))
                    except TypeError:
                        return bool(client.is_server_ready())
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
            except Exception:
                return False

        # Default: HTTP
        try:
            if timeout is None:
                return bool(self._client(vm_ip).is_server_ready())
            return bool(self._client(vm_ip, timeout=int(timeout)).is_server_ready())
        except Exception:
            return False

    def is_model_ready(self, vm_ip: str, model_name: str) -> bool:
        try:
            return self._client(vm_ip).is_model_ready(model_name)
        except Exception:
            return False

    def wait_for_server_ready(self, vm_ip: str, timeout: int = 60) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            if self.is_server_ready(vm_ip):
                logger.info(" Server ready at %s:%s", vm_ip, self.http_port)
                return True
            time.sleep(2)
        return False

    def wait_for_model_ready(self, vm_ip: str, model_name: str, timeout: int = 120) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            if self.is_model_ready(vm_ip, model_name):
                logger.info(f" Model '{model_name}' is ready")
                return True
            time.sleep(3)
        return False

    # -------------------------------------------- #
    #           MODEL MANAGEMENT                   #
    # -------------------------------------------- #
    def load_model(self, vm_ip: str, model_name: str, timeout: int = 30, config_json: str = None) -> bool:
        try:
            self._client(vm_ip, timeout=timeout).load_model(model_name, config=config_json)
            logger.info(f" Load request sent for model '{model_name}'")
            return True
        except Exception as e:
            logger.info(" Failed to load model '%s': %s", model_name, e)
            return False

    def unload_model(self, vm_ip: str, model_name: str, timeout: int = 30) -> bool:
        try:
            self._client(vm_ip, timeout=timeout).unload_model(model_name)
            logger.info(f" Unload request sent for model '{model_name}'")
            return True
        except Exception as e:
            logger.info(" Failed to unload model '%s': %s", model_name, e)
            return False

    # -------------------------------------------- #
    #               METADATA                       #
    # -------------------------------------------- #
    def get_server_metadata(self, vm_ip: str) -> dict:
        try:
            return self._client(vm_ip).get_server_metadata()
        except Exception as e:
            logger.info(" Failed to get server metadata: %s", e)
            return {}

    def get_model_metadata(self, vm_ip: str, model_name: str) -> dict:
        try:
            return self._client(vm_ip).get_model_metadata(model_name)
        except Exception as e:
            logger.info(" Failed to get model metadata: %s", e)
            return {}
