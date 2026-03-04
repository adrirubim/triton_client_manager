from pprint import pprint

import requests
from auth import return_token

token = return_token()

nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/servers/detail"

# Make API request
response = requests.get(url, headers={"X-Auth-Token": token}, verify=False, timeout=30)
response.raise_for_status()

# Parse response
data = response.json()
pprint(data)
