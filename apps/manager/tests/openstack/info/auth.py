#!/usr/bin/env python3
import requests


def return_token():
    # ----- Config (set these however you like) -----
    os_auth_url = "https://c.c41.ch:5000/v3/auth/tokens"

    app_id = "2a4766424b5c4e7cb840483caa02d7e7"
    app_secret = "E_CXhD_Y30q06LAjLx0pJFoZKfkKd-1Bk2fq9b0AFKNEsBOFJMaisgVofvKJ6pfKZjXeHrFncJ3qOQOdA5euVg"

    # ----- 1) Get an UNscoped token: POST /v3/auth/tokens -----
    auth_payload = {
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {
                    "id": app_id,
                    "secret": app_secret,
                },
            }
            # Usually no scope needed: app creds are already tied to a project
        }
    }

    r = requests.post(
        url=os_auth_url,
        json=auth_payload,
        headers={"Accept": "application/json"},
        verify=False,
        timeout=30,
    )
    r.raise_for_status()

    token = r.headers["X-Subject-Token"]

    return token
