from auth import return_token
import requests
token = return_token()
from pprint import pprint
nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/os-keypairs"

# Make API request
response = requests.get(
    url,
    headers={"X-Auth-Token": token,"OpenStack-API-Version": "compute 2.53"},
    verify=False,
    timeout=30
)
response.raise_for_status()

# Parse response
data = response.json()
pprint(data["keypairs"][0]["keypair"]["public_key"][0])