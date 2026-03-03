from auth import return_token
import requests

token = return_token()
from pprint import pprint

nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/servers/detail"

# Make API request
response = requests.get(url, headers={"X-Auth-Token": token}, verify=False, timeout=30)
response.raise_for_status()

# Parse response
data = response.json()
pprint(data)
