import os
os.environ["OS_CLIENT_CONFIG_FILE"] = "/home/marco/avolu/git-InternetOne/triton_client_manager/MANAGER/config/openstack.yaml"
os.environ["OS_CLOUD"] = "kolla-admin"

import openstack
from pprint import pprint
from vm import VM
conn = openstack.connect()

 # Keystone-only sanity check (auth + catalog)
print("Connected. Current project:", conn.current_project_id)

# Compute call (needs Nova endpoint reachable from this host)
print("\nServers:")
first = next(conn.compute.servers(details=True))
pprint(str(first))
print()
pprint(VM.from_server(first))

