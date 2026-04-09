import logging
import random
import threading
import time
from typing import Callable, Optional

from utils.metrics import observe_backend_error

from .creation.creation import TritonCreation
from .deletion.deletion import TritonDeletion
from .info.data.server import TritonServer
from .info.info import TritonInfo
from .tritonerrors import (
    TritonMissingArgument,
    TritonMissingInstance,
    TritonServerStateChanged,
)

logger = logging.getLogger(__name__)

###################################
#        Triton Thread            #
###################################


class TritonThread(threading.Thread):
    def __init__(self, config: dict):
        super().__init__(name="Triton_Thread", daemon=True)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        # Re-entrant because `load()` may call helpers that snapshot/persist state.
        self._data_lock = threading.RLock()

        # --- Loop ---
        self.refresh_time = config["refresh_time"]
        self._health_failure_evict_threshold = int(config.get("health_failure_evict_threshold", 3))
        self._stale_evict_seconds = int(config.get("stale_evict_seconds", int(self.refresh_time) * 10))
        self._active_heal_restart_threshold = int(config.get("active_heal_restart_threshold", 2))
        self._active_heal_restart_cooldown_seconds = int(config.get("active_heal_restart_cooldown_seconds", 300))
        self._last_restart_attempt_by_container: dict[str, float] = {}

        # Expose circuit breaker governance for inference layer.
        self.circuit_breaker_failure_threshold = int(config.get("circuit_breaker_failure_threshold", 3))
        self.circuit_breaker_open_seconds = int(config.get("circuit_breaker_open_seconds", 30))

        # --- Crash recovery / persistence ---
        self._state_dir = self._default_state_dir()
        self._servers_state_path = self._state_dir / "servers.jsonl"

        # --- Data ---
        self.dict_servers: dict[tuple, TritonServer] = {}  # {(vm_id, container_id): TritonServer}

        # --- Handlers ---
        self.triton_info = TritonInfo(timeout=config["health_check_timeout"])
        self.triton_creation = TritonCreation(config)
        self.triton_deletion = TritonDeletion()

        # --- WebSocket (set by ClientManager) ---
        self.websocket: Optional[Callable[[dict], bool]] = None
        # --- Optional deps (set by ClientManager) ---
        self.docker = None

    @staticmethod
    def _default_state_dir():
        import os
        from pathlib import Path

        env = os.getenv("TCM_STATE_DIR")
        if env and str(env).strip():
            return Path(env).expanduser()
        # repo_root/.../apps/manager/classes/triton/tritonthread.py -> parents[4] == repo root
        repo_root = Path(__file__).resolve().parents[4]
        return repo_root / "state"

    def _persist_servers(self) -> None:
        """
        Persist a compact snapshot of dict_servers to a JSONL file.
        Each line is one server record; file is rewritten atomically.
        """
        import json
        import os
        from pathlib import Path

        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(self._servers_state_path) + ".tmp")

        with self._data_lock:
            servers = list(self.dict_servers.values())

        lines = []
        for s in servers:
            lines.append(
                json.dumps(
                    {
                        "vm_id": s.vm_id,
                        "vm_ip": s.vm_ip,
                        "container_id": s.container_id,
                        "model_name": s.model_name,
                        "status": s.status,
                        "protocol": s.protocol,
                        "inputs": s.inputs,
                        "outputs": s.outputs,
                        "consecutive_health_failures": int(s.consecutive_health_failures or 0),
                        "last_healthy_ts": float(s.last_healthy_ts or 0.0),
                        "ts": time.time(),
                    },
                    separators=(",", ":"),
                )
            )
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        os.replace(str(tmp), str(self._servers_state_path))

    def _rehydrate_servers(self) -> None:
        """
        Best-effort crash recovery:
        - Load persisted servers from state/servers.jsonl
        - Rebuild lightweight Triton clients (HTTP/gRPC) and verify readiness
        - Repopulate dict_servers so inference can resume after restart
        """
        import json
        from json import JSONDecodeError
        from pathlib import Path

        path = Path(self._servers_state_path)
        if not path.exists():
            return

        try:
            raw = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            logger.warning("[TritonThread] Failed to read persisted servers state; starting empty")
            return

        recovered: dict[tuple, TritonServer] = {}

        for line in raw:
            line = (line or "").strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except JSONDecodeError:
                continue

            vm_id = rec.get("vm_id") or ""
            vm_ip = rec.get("vm_ip") or ""
            container_id = rec.get("container_id") or ""
            model_name = rec.get("model_name") or ""
            protocol = rec.get("protocol") or None
            inputs = rec.get("inputs") or []
            outputs = rec.get("outputs") or []
            consecutive_health_failures = int(rec.get("consecutive_health_failures") or 0)
            last_healthy_ts = float(rec.get("last_healthy_ts") or 0.0)
            if not (vm_id and vm_ip and container_id):
                continue

            client = None
            try:
                from .constants import GRPC_PORT, HTTP_PORT

                if protocol == "grpc":
                    import tritonclient.grpc as grpcclient

                    client = grpcclient.InferenceServerClient(url=f"{vm_ip}:{GRPC_PORT}")
                else:
                    import tritonclient.http as httpclient

                    client = httpclient.InferenceServerClient(url=f"{vm_ip}:{HTTP_PORT}")
                    protocol = "http"
            except Exception:
                client = None

            # Verify health via TritonInfo (HTTP ready checks)
            healthy = self.triton_info.is_server_ready(vm_ip)
            status = "ready" if healthy else "unhealthy"
            if healthy and model_name:
                # Best-effort: mark unhealthy if model isn't ready
                if not self.triton_info.is_model_ready(vm_ip, model_name):
                    status = "unhealthy"

            recovered[(vm_id, container_id)] = TritonServer(
                vm_id=vm_id,
                vm_ip=vm_ip,
                container_id=container_id,
                client=client,
                model_name=model_name,
                inputs=inputs,
                outputs=outputs,
                status=status,
                protocol=protocol,
                consecutive_health_failures=consecutive_health_failures,
                last_healthy_ts=last_healthy_ts,
            )

        with self._data_lock:
            self.dict_servers = recovered

    def start(self):
        # Rehydrate before first health-check loop so dict_servers is populated after a crash.
        self._rehydrate_servers()
        self.load()
        self._persist_servers()
        self._ready_event.set()
        super().start()

    def wait_until_ready(self, timeout: int = 30) -> bool:
        return self._ready_event.wait(timeout)

    def stop(self):
        logger.info("[TritonThread] Stopping...")
        self._stop_event.set()

    def run(self):
        logger.info("[TritonThread] Started")
        while not self._stop_event.is_set():
            try:
                self.load()
                # Small jitter to avoid synchronized health-check bursts across servers.
                jitter = random.uniform(0.0, max(0.01, float(self.refresh_time) * 0.10))  # nosec B311
                time.sleep(float(self.refresh_time) + jitter)
            except Exception as e:
                observe_backend_error("triton")
                logger.info(" TritonThread main loop: %s", e)
        logger.info("[TritonThread] Stopped")

    def _send_alert(self, error: Exception):
        if self.websocket:
            try:
                alert_payload = {
                    "type": "alert",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "timestamp": time.time(),
                }
                self.websocket(alert_payload)
            except Exception as e:
                logger.info(" TritonThread failed to send alert: %s", e)

    def load(self) -> None:
        """Health-check all known servers; detect and alert on status changes."""

        # --- Copy ---
        with self._data_lock:
            servers = dict(self.dict_servers)

        # --- Iter throght ---
        now = time.time()
        for (vm_id, container_id), server in servers.items():
            try:
                # --- Check Health Server ---
                healthy = self.triton_info.is_server_ready(server.vm_ip)
                new_status = "ready" if healthy else "unhealthy"

                # --- Change Healthy -> Unhealthy ---
                with self._data_lock:
                    if healthy:
                        server.consecutive_health_failures = 0
                        server.last_healthy_ts = now
                    else:
                        server.consecutive_health_failures = int(server.consecutive_health_failures or 0) + 1

                    if new_status != server.status:
                        old_status = server.status
                        server.status = new_status
                        self._persist_servers()

                        # --- Send Alert --
                        self._send_alert(
                            TritonServerStateChanged(
                                server.vm_ip,
                                container_id,
                                [f"status: {old_status} -> {new_status}"],
                            )
                        )

                # Active healing: restart the container if health fails repeatedly (best-effort).
                if not healthy and server.consecutive_health_failures >= self._active_heal_restart_threshold:
                    self._attempt_active_heal_restart(server)

                # Zombie/stale eviction policy.
                self._evict_if_stale_or_zombie(vm_id, container_id, server, now=now)
            except Exception as e:
                observe_backend_error("triton")
                logger.info(f" Health check failed for ({vm_id}, {container_id[:12]}): {e}")

    def _attempt_active_heal_restart(self, server: TritonServer) -> None:
        if not self.docker:
            return
        cid = server.container_id
        now = time.time()
        last = float(self._last_restart_attempt_by_container.get(cid, 0.0))
        if now - last < float(self._active_heal_restart_cooldown_seconds):
            return
        self._last_restart_attempt_by_container[cid] = now
        try:
            ok = self.docker.restart_container(cid)
            if ok:
                logger.info(
                    "AUDIT_TRITON_ACTIVE_HEAL: restarted container due to repeated health failures",
                    extra={
                        "job_id": "-",
                        "job_type": "triton_active_heal",
                        "container_id": cid[:12],
                        "vm_ip": server.vm_ip,
                    },
                )
        except Exception as exc:
            logger.warning(
                "AUDIT_TRITON_ACTIVE_HEAL_FAILED: container restart attempt failed: %s",
                exc,
                extra={
                    "job_id": "-",
                    "job_type": "triton_active_heal",
                    "container_id": cid[:12],
                    "vm_ip": server.vm_ip,
                },
            )

    def _evict_if_stale_or_zombie(self, vm_id: str, container_id: str, server: TritonServer, *, now: float) -> None:
        """
        Evict stale/zombie servers:
        - If consecutive health failures exceed threshold, evict from dict_servers.
        - If last_healthy_ts is too old (stale), evict.
        """
        failures = int(server.consecutive_health_failures or 0)
        last_ok = float(server.last_healthy_ts or 0.0)
        stale = (last_ok > 0.0) and ((now - last_ok) >= float(self._stale_evict_seconds))
        too_many_failures = failures >= self._health_failure_evict_threshold
        if not (stale or too_many_failures):
            return
        reason = "stale" if stale else "consecutive_failures"
        with self._data_lock:
            popped = self.dict_servers.pop((vm_id, container_id), None)
            if popped:
                try:
                    popped.close()
                except Exception as exc:
                    logger.debug(
                        "AUDIT_TRITON_EVICTED_CLOSE_FAILED: %s",
                        exc,
                        extra={
                            "job_id": "-",
                            "job_type": "triton_evict",
                            "vm_ip": server.vm_ip,
                            "container_id": container_id[:12],
                        },
                    )
                self._persist_servers()
        logger.warning(
            "AUDIT_TRITON_EVICTED: server evicted from registry (%s)",
            reason,
            extra={"job_id": "-", "job_type": "triton_evict", "vm_ip": server.vm_ip, "container_id": container_id[:12]},
        )

    # -------------------------------------------- #
    #               LIFECYCLE                      #
    # -------------------------------------------- #

    def create_server(self, data: dict) -> TritonServer:
        """Create a TritonServer (wait, load model, build clients) and register it."""

        # --- Check ---
        if "vm_id" not in data:
            raise TritonMissingArgument("vm_id")
        if "vm_ip" not in data:
            raise TritonMissingArgument("vm_ip")
        if "minio" not in data:
            raise TritonMissingArgument("minio")
        if "container_id" not in data:
            raise TritonMissingArgument("container_id")

        # --- Optional ---
        data["triton"] = data.get("triton", {})

        # --- Create Server ---
        server = self.triton_creation.handle(**data)

        # --- Replace Dead ---
        with self._data_lock:
            existing = self.dict_servers.get((data["vm_id"], data["container_id"]))
            if existing:
                existing.close()
            self.dict_servers[(data["vm_id"], data["container_id"])] = server
            self._persist_servers()

        return server

    def delete_server(self, data: dict) -> None:
        """Unload all models on the server, close clients, and deregister."""

        # --- Catch ---
        if "vm_id" not in data:
            raise TritonMissingArgument("vm_id")
        if "container_id" not in data:
            raise TritonMissingArgument("container_id")

        vm_id = data["vm_id"]
        container_id = data["container_id"]

        # --- Fetch ---
        with self._data_lock:
            server = self.dict_servers.get((vm_id, container_id))

        # --- Delete ---
        if server:
            self.triton_deletion.handle(server.client, server.model_name)
            server.close()
        else:
            raise TritonMissingInstance(vm_id, container_id)

        # --- Remove ---
        with self._data_lock:
            self.dict_servers.pop((vm_id, container_id), None)
            self._persist_servers()

        logger.info(f" Deregistered ({vm_id}, {container_id[:12]})")
        return data

    def get_server(self, vm_ip: str, container_id: str) -> TritonServer | None:
        """
        Retrieve a registered server by (vm_ip, container_id).

        Note: dict_servers is keyed by (vm_id, container_id). We do not always
        have vm_id at inference time, so we match by container_id and vm_ip.
        """
        with self._data_lock:
            for (_vm_id, _container_id), server in self.dict_servers.items():
                if _container_id == container_id and server.vm_ip == vm_ip:
                    return server
        return None
