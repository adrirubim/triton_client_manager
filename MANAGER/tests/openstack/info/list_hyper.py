from pprint import pprint

import requests
from auth import return_token

token = return_token()

nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/os-hypervisors/detail"

# Make API request
response = requests.get(
    url,
    headers={"X-Auth-Token": token, "OpenStack-API-Version": "compute 2.53"},
    verify=False,
    timeout=30,
)
response.raise_for_status()
pprint(response.json())
exit()
# Parse response
data = response.json()
pprint(data)
