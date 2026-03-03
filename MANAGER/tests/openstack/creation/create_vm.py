from auth import return_token
import requests
token = return_token()
from pprint import pprint
nova_url = "https://c.c41.ch:8774/v2.1"

url = f"{nova_url}/servers"
data = {
  "server": {
    "name": "nice",
    "imageRef": "aa2fa70e-5b72-43aa-98c8-35b5f3776efa",  # ubuntu-24.04-minimal-arm64
    "flavorRef": "81bba11e-0bd5-459f-b19c-1ef014555c52", # arm.small
    "networks": [{"uuid": "3a6c74a4-37da-4a15-b584-7c32290a6551"}], # public
    "key_name": "armoneM", # 
    "config_drive": True, # DUNNO
    "security_groups": [{"name": "sc-icmp-ssh"}]
  }
}

headers = {
    "X-Auth-Token": token,
    "OpenStack-API-Version": "compute 2.53",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
# Make API request
response = requests.post(
    url,
    headers=headers,
    verify=False,
    json = data,
    timeout=30
)
response.raise_for_status()
data = response.json()
pprint(data)

