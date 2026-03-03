from auth import return_token
import requests
token = return_token()
from pprint import pprint
nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/servers/349fb3b1-563c-4323-9b40-24a5c54dcca2"

headers = {
    "X-Auth-Token": token,
    "OpenStack-API-Version": "compute 2.53"}

response = requests.get(
    url,
    headers=headers,
    verify=False,
    timeout=30
)
response.raise_for_status()
pprint(response.json())
exit()