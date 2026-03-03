import logging

logger = logging.getLogger(__name__)

# --- Threaded Execution ---
from classes.websocket import WebSocketThread
from classes.openstack import OpenstackThread
from classes.docker import DockerThread
from classes.triton import TritonThread
from classes.job import JobThread  # -> Conccurent multiple threads (LOTS of REQUESTS)

from yaml import safe_load
import time


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
            self.config_job = safe_load(f)
        with open("config/docker.yaml", encoding="utf-8") as f:
            self.config_docker = safe_load(f)
        with open("config/openstack.yaml", encoding="utf-8") as f:
            self.config_openstack = safe_load(f)
        with open("config/websocket.yaml", encoding="utf-8") as f:
            self.config_websocket = safe_load(f)
        with open("config/triton.yaml", encoding="utf-8") as f:
            self.config_triton = safe_load(f)

    def setup(self):
        self.job = JobThread(**self.config_job)
        self.docker = DockerThread(self.config_docker)
        self.openstack = OpenstackThread(**self.config_openstack)
        self.triton = TritonThread(self.config_triton)
        self.websocket = WebSocketThread(**self.config_websocket, on_message=self.job.on_message)

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
    client = ClientManager()
    try:
        while client.running:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()


if __name__ == "__main__":
    main()
