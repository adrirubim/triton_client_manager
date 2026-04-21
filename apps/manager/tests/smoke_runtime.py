"""
Runtime smoke test: JobThread DI, WebSocket auth, info queue_stats.
Uses mocks for OpenStack/Docker/Triton. Run from apps/manager: python tests/smoke_runtime.py
"""

import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
# Ensure repo root is importable so `import src.*` works in CI.
_repo_root = os.path.abspath(os.path.join(_here, "..", "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_here, ".."))
sys.path.insert(0, _here)  # keep tests/ importable for smoke flows


def _create_mock_thread(name, attrs=None):
    """Minimal mock thread for DI."""
    t = type(name, (), {})()
    for k, v in (attrs or {}).items():
        setattr(t, k, v)
    t.dict_containers = getattr(t, "dict_containers", {})
    t.dict_servers = getattr(t, "dict_servers", {})
    return t


def run_smoke(include_ws_client=False):
    from utils.logging_config import configure_logging

    configure_logging()

    from yaml import safe_load

    from classes.job import JobThread
    from classes.websocket import WebSocketThread

    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    with open(os.path.join(config_dir, "jobs.yaml"), encoding="utf-8") as f:
        config_job = safe_load(f)
    with open(os.path.join(config_dir, "websocket.yaml"), encoding="utf-8") as f:
        config_ws = safe_load(f)

    mock_docker = _create_mock_thread("DockerThread", {"dict_containers": {}})
    mock_openstack = _create_mock_thread("OpenstackThread")
    mock_triton = _create_mock_thread("TritonThread", {"dict_servers": {}})

    job = JobThread(**config_job)
    job.docker = mock_docker
    job.openstack = mock_openstack
    job.triton = mock_triton
    job.websocket = None

    ws_cfg = dict(config_ws)
    auth_cfg = ws_cfg.pop("auth", None)
    rate_cfg = ws_cfg.pop("rate_limits", None)

    ws = WebSocketThread(
        **ws_cfg,
        on_message=job.on_message,
        get_queue_stats=job.get_queue_stats,
    )
    if auth_cfg or rate_cfg:
        ws.set_auth_and_rate_limits(auth_config=auth_cfg, rate_limit_config=rate_cfg)
    job.websocket = ws.send_to_client

    job.start()
    ws.start()
    if not job.wait_until_ready(5):
        raise RuntimeError("JobThread failed to initialize")
    if not ws.wait_until_ready(10):
        raise RuntimeError("WebSocket failed to initialize")

    port = config_ws["port"]

    try:
        import asyncio

        from websockets import connect as ws_connect
    except ImportError:
        print("[SKIP] websockets not installed; auth/info tests skipped")
        return {
            "startup": True,
            "auth": None,
            "info": None,
            "reason": "websockets required",
        }

    results = {"startup": True, "auth": False, "info": False}

    async def _test():
        uri = f"ws://127.0.0.1:{port}/ws"
        async with ws_connect(uri) as sock:
            auth_msg = {"type": "auth", "uuid": "smoke-test-client", "payload": {}}
            await sock.send(json.dumps(auth_msg))
            r = json.loads(await sock.recv())
            results["auth"] = r.get("type") == "auth.ok"
            if not results["auth"]:
                return
            await asyncio.sleep(0.2)
            info_msg = {
                "type": "info",
                "uuid": "smoke-test-client",
                "payload": {"action": "queue_stats"},
            }
            await sock.send(json.dumps(info_msg))
            r = json.loads(await sock.recv())
            results["info"] = r.get("type") == "info_response" and r.get("payload", {}).get("status") == "success"

    asyncio.run(_test())

    if include_ws_client:
        from devtools.ws_client import test_multiple_clients

        uri = f"ws://127.0.0.1:{port}/ws"
        try:
            asyncio.run(test_multiple_clients(uri=uri, keep_alive_sec=1))
            results["ws_client"] = True
        except Exception as e:
            results["ws_client"] = False
            results["ws_client_error"] = str(e)

    job.stop()
    ws.stop()
    ws.join(timeout=5)  # Wait for graceful shutdown before process exit
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Smoke test for Triton Client Manager")
    parser.add_argument(
        "--with-ws-client",
        action="store_true",
        help="Run devtools.ws_client multi-client scenario as part of smoke",
    )
    args = parser.parse_args()

    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        r = run_smoke(include_ws_client=args.with_ws_client)
        print(json.dumps(r, indent=2))
        if r.get("auth") is False or (r.get("info") is False and r.get("auth") is not None):
            sys.exit(1)
        if r.get("ws_client") is False:
            sys.exit(1)
    except Exception as e:
        print(f"SMOKE FAILED: {e}")
        raise
