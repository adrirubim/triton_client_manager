#!/usr/bin/env python3
from pprint import pprint
import os
import requests


def return_token():
    # ----- Config (set these however you like) -----
    OS_AUTH_URL = "https://c.c41.ch:5000/v3/auth/tokens"

    ID = "2a4766424b5c4e7cb840483caa02d7e7"
    SECRET = (
        "E_CXhD_Y30q06LAjLx0pJFoZKfkKd-1Bk2fq9b0AFKNEsBOFJMaisgVofvKJ6pfKZjXeHrFncJ3qOQOdA5euVg"
    )

    # ----- 1) Get an UNscoped token: POST /v3/auth/tokens -----
    auth_payload = {
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {
                    "id": ID,
                    "secret": SECRET,
                },
            }
            # Usually no scope needed: app creds are already tied to a project
        }
    }

    r = requests.post(
        url=OS_AUTH_URL,
        json=auth_payload,
        headers={"Accept": "application/json"},
        verify=False,
        timeout=30,
    )
    r.raise_for_status()

    token = r.headers["X-Subject-Token"]

    return token
