import os
from pprint import pprint

import openstack
from vm import VM


def main() -> None:
    # Prefer a repo-relative config path over a hardcoded local path.
    os.environ["OS_CLIENT_CONFIG_FILE"] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "openstack.yaml")
    )
    os.environ["OS_CLOUD"] = "kolla-admin"

    conn = openstack.connect()

    # Keystone-only sanity check (auth + catalog)
    print("Connected. Current project:", conn.current_project_id)

    # Compute call (needs Nova endpoint reachable from this host)
    print("\nServers:")
    first = next(conn.compute.servers(details=True))
    pprint(str(first))
    print()
    pprint(VM.from_server(first))


if __name__ == "__main__":
    main()
