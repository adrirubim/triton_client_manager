from auth import return_token
import requests

token = return_token()
nova_url = "https://c.c41.ch:8774/v2.1"
vm_id = "99bc3aec-01c9-47c2-a15c-a4c4ec396853"
response = requests.post(
    f"{nova_url}/servers/{vm_id}/action",
    headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    json={"unpause": None},
    verify=False,
    timeout=30,
)
print(response)
