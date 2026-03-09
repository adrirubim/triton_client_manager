import logging
import os
import time

from yaml import safe_load

from config_schema import DockerConfig, JobsConfig, TritonConfig, WebsocketConfig
from tcm.docker import DockerThread
from tcm.job import JobThread  # -> Conccurent multiple threads (LOTS of REQUESTS)
from tcm.openstack import OpenstackThread
from tcm.triton import TritonThread
from tcm.websocket import WebSocketThread
from utils.logging_config import configure_logging
from utils.metrics import UNSAFE_CONFIG_STARTUPS_TOTAL

logger = logging.getLogger(__name__)

########################################################
#                    Client Manager                    #
########################################################


class ClientManager:
    def __init__(self):

        self.running = True

        # --- Setup ---
        self.config()
        self.setup()

    # --- Init ----
    def config(self):

        with open("config/jobs.yaml", encoding="utf-8") as f:
            raw_jobs = safe_load(f)
        with open("config/docker.yaml", encoding="utf-8") as f:
            raw_docker = safe_load(f)
        with open("config/openstack.yaml", encoding="utf-8") as f:
            self.config_openstack = safe_load(f)
        with open("config/websocket.yaml", encoding="utf-8") as f:
            raw_websocket = safe_load(f)
        with open("config/triton.yaml", encoding="utf-8") as f:
            raw_triton = safe_load(f)

        try:
            jobs_cfg = JobsConfig(**(raw_jobs or {}))
            docker_cfg = DockerConfig(**(raw_docker or {}))
            websocket_cfg = WebsocketConfig(**(raw_websocket or {}))
            triton_cfg = TritonConfig(**(raw_triton or {}))
        except Exception as exc:
            UNSAFE_CONFIG_STARTUPS_TOTAL.labels(reason="invalid_yaml_config").inc()
            logger.critical("Invalid configuration detected: %s", exc)
            raise

        self.config_job = jobs_cfg.dict()
        self.config_docker = docker_cfg.dict()
        self.config_websocket = websocket_cfg.dict()
        self.config_triton = triton_cfg.dict()

        # Hardening checks for WebSocket auth configuration.
        auth_cfg = (self.config_websocket or {}).get("auth") or {}
        mode = auth_cfg.get("mode", "simple")
        jwks_url = auth_cfg.get("jwks_url")
        public_key_pem = auth_cfg.get("public_key_pem")
        algorithms = auth_cfg.get("algorithms") or []
        env = os.getenv("TCM_ENV", "development").lower()

        # Detect strict mode without any signature verification configured.
        if mode == "strict" and not (jwks_url or public_key_pem):
            UNSAFE_CONFIG_STARTUPS_TOTAL.labels(
                reason="strict_without_signature_verification",
            ).inc()
            logger.error(
                "Unsafe auth config detected: auth.mode='strict' sin JWKS/PEM; "
                "degradando explícitamente a mode='simple' para evitar falsa seguridad",
            )
            auth_cfg["mode"] = "simple"
            self.config_websocket["auth"] = auth_cfg

        # Detect HS* usage in non‑dev environments and refuse to start.
        uses_hs = any(
            isinstance(a, str) and a.upper().startswith("HS") for a in algorithms
        )
        if env in {"staging", "production"} and uses_hs and public_key_pem:
            UNSAFE_CONFIG_STARTUPS_TOTAL.labels(
                reason="hs_algorithm_in_non_dev_env",
            ).inc()
            logger.critical(
                "Insecure auth configuration: HS* algorithm configured via public_key_pem "
                "en entorno '%s'. Esta configuración solo se admite en dev.",
                env,
            )
            raise RuntimeError(
                "HS* algorithms are not allowed in staging/production for WebSocket auth",
            )

    def setup(self):
        self.job = JobThread(**self.config_job)
        self.docker = DockerThread(self.config_docker)
        self.openstack = OpenstackThread(**self.config_openstack)
        self.triton = TritonThread(self.config_triton)
        # WebSocket server configuration (auth/rate limits are optional keys).
        ws_cfg = dict(self.config_websocket)
        auth_cfg = ws_cfg.pop("auth", None)
        rate_cfg = ws_cfg.pop("rate_limits", None)

        self.websocket = WebSocketThread(
            **ws_cfg,
            on_message=self.job.on_message,
            get_queue_stats=self.job.get_queue_stats,
        )
        if auth_cfg or rate_cfg:
            self.websocket.set_auth_and_rate_limits(
                auth_config=auth_cfg,
                rate_limit_config=rate_cfg,
            )

        # --- Params for communication ---
        self.job.docker = self.docker
        self.job.openstack = self.openstack
        self.job.triton = self.triton
        self.docker.openstack = self.openstack

        # --- Send back response ---
        self.job.websocket = self.websocket.send_to_client
        self.docker.websocket = self.websocket.send_to_first_client
        self.openstack.websocket = self.websocket.send_to_first_client
        self.triton.websocket = self.websocket.send_to_first_client

        # --- Starting Threads with Synchronization ---
        logger.info("[ClientManager] Starting OpenStack thread...")
        self.openstack.start()
        if not self.openstack.wait_until_ready(timeout=30):
            raise TimeoutError("OpenStack thread failed to initialize")
        logger.info("[ClientManager] ✓ OpenStack ready")

        logger.info("[ClientManager] Starting Triton thread...")
        self.triton.start()
        if not self.triton.wait_until_ready(timeout=30):
            raise TimeoutError("Triton thread failed to initialize")
        logger.info("[ClientManager] ✓ Triton ready")

        logger.info("[ClientManager] Starting Docker thread...")
        self.docker.start()
        if not self.docker.wait_until_ready(timeout=30):
            raise TimeoutError("Docker thread failed to initialize")
        logger.info("[ClientManager] ✓ Docker ready")

        logger.info("[ClientManager] Starting Job thread...")
        self.job.start()
        if not self.job.wait_until_ready(timeout=30):
            raise TimeoutError("Job thread failed to initialize")
        logger.info("[ClientManager] ✓ Job ready")

        logger.info("[ClientManager] Starting WebSocket thread...")
        self.websocket.start()
        if not self.websocket.wait_until_ready(timeout=30):
            raise TimeoutError("WebSocket thread failed to initialize")
        logger.info("[ClientManager] ✓ Websocket ready")

        logger.info("[ClientManager] ✓ All threads started successfully")

    def stop(self):
        self.running = False
        self.job.stop()
        self.docker.stop()
        self.triton.stop()
        self.openstack.stop()
        self.websocket.stop()
        logger.info("Client disconnecting..")


def main():
    # Configure structured logging once at process start
    configure_logging()
    client = ClientManager()
    try:
        while client.running:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()


if __name__ == "__main__":
    main()
