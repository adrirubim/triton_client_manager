import time
from pprint import pprint

import requests
from auth import return_token

token = return_token()

nova_url = "https://c.c41.ch:8774/v2.1"
server_id = "194e54f6-53b9-4f9d-8a78-70138380f348"
url = f"{nova_url}/servers/{server_id}"

headers = {"X-Auth-Token": token, "OpenStack-API-Version": "compute 2.53"}

response = requests.delete(url, headers=headers, verify=False, timeout=30)
try:
    response.raise_for_status()
    data = response.json()
    pprint(data)
except Exception as e:
    print(f"ERRROR ->  {e}")

url = f"{nova_url}/servers/{server_id}"

for i in range(100):
    response = requests.get(url, headers=headers, verify=False, timeout=30)
    response.raise_for_status()
    pprint(response.json())
    time.sleep(1)
exit()
