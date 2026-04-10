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
from utils.config_env import overlay_openstack_config
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

        # Apply environment variable overlays for secrets/runtime overrides.
        # This keeps YAML files free of real secrets and enables environment-specific deployments.
        self.config_openstack = overlay_openstack_config(self.config_openstack or {})

        # Hardening checks for WebSocket auth configuration.
        auth_cfg = (self.config_websocket or {}).get("auth") or {}
        mode = auth_cfg.get("mode", "simple")
        jwks_url = auth_cfg.get("jwks_url")
        public_key_pem = auth_cfg.get("public_key_pem")
        algorithms = auth_cfg.get("algorithms") or []
        env = os.getenv("TCM_ENV", "development").lower()

        # Strict mode without signature verification is allowed only in development.
        # In staging/production we fail fast to avoid a "false sense of security".
        if mode == "strict" and not (jwks_url or public_key_pem):
            UNSAFE_CONFIG_STARTUPS_TOTAL.labels(
                reason="strict_without_signature_verification",
            ).inc()
            if env in {"staging", "production"}:
                logger.critical(
                    "Unsafe auth config: auth.mode='strict' requires JWKS/PEM in '%s' "
                    "(configure auth.jwks_url or auth.public_key_pem). Refusing to start.",
                    env,
                )
                raise RuntimeError(
                    "Unsafe auth config: strict mode requires signature verification in staging/production",
                )
            logger.warning(
                "Auth config warning: auth.mode='strict' without JWKS/PEM in '%s'. "
                "Token signatures will not be verified; only claim semantics may be enforced. "
                "This is supported for development only.",
                env,
            )

        # Detect HS* usage in non‑dev environments and refuse to start.
        uses_hs = any(isinstance(a, str) and a.upper().startswith("HS") for a in algorithms)
        if env in {"staging", "production"} and uses_hs and public_key_pem:
            UNSAFE_CONFIG_STARTUPS_TOTAL.labels(
                reason="hs_algorithm_in_non_dev_env",
            ).inc()
            logger.critical(
                "Insecure auth configuration: HS* algorithm configured via public_key_pem "
                "in environment '%s'. This configuration is only supported in dev.",
                env,
            )
            raise RuntimeError(
                "HS* algorithms are not allowed in staging/production for WebSocket auth",
            )

        # Hardening checks for Docker Remote API transport (staging/production).
        docker_cfg_dict = self.config_docker or {}
        remote_scheme = (docker_cfg_dict.get("remote_api_scheme") or "http").lower()
        tls_verify = bool(docker_cfg_dict.get("remote_api_tls_verify", True))
        client_cert = docker_cfg_dict.get("remote_api_client_cert_path")
        client_key = docker_cfg_dict.get("remote_api_client_key_path")

        if env in {"staging", "production"}:
            if remote_scheme != "https":
                UNSAFE_CONFIG_STARTUPS_TOTAL.labels(reason="docker_remote_api_http").inc()
                logger.critical(
                    "Unsafe Docker Remote API config: remote_api_scheme=%r in '%s'. "
                    "Use remote_api_scheme=https with TLS verification. Refusing to start.",
                    remote_scheme,
                    env,
                )
                raise RuntimeError("Unsafe Docker Remote API config (HTTP in staging/production)")

            if not tls_verify:
                UNSAFE_CONFIG_STARTUPS_TOTAL.labels(reason="docker_remote_api_tls_noverify").inc()
                logger.critical(
                    "Unsafe Docker Remote API config: remote_api_tls_verify=false in '%s'. " "Refusing to start.",
                    env,
                )
                raise RuntimeError("Unsafe Docker Remote API config (TLS verify disabled)")

            # If mTLS is configured, require both cert and key.
            if bool(client_cert) ^ bool(client_key):
                UNSAFE_CONFIG_STARTUPS_TOTAL.labels(reason="docker_remote_api_mtls_incomplete").inc()
                logger.critical(
                    "Invalid Docker Remote API mTLS config in '%s': you must set both "
                    "remote_api_client_cert_path and remote_api_client_key_path.",
                    env,
                )
                raise RuntimeError("Invalid Docker Remote API mTLS config (cert/key mismatch)")

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
        # Enable active healing actions (restart containers) from TritonThread.
        self.triton.docker = self.docker

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
