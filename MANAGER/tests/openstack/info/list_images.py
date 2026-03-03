from auth import return_token
import requests
token = return_token()
from pprint import pprint
nova_url = "https://c.c41.ch:9292/v2"

url = f"{nova_url}/images"

# Make API request
response = requests.get(
    url,
    headers={"X-Auth-Token": token,"OpenStack-API-Version": "compute 2.53"},
    verify=False,
    timeout=30
)
response.raise_for_status()
pprint(response.json())
exit()
# Parse response
data = response.json()
pprint(data)