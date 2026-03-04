# Triton Client Manager – WebSocket SDK (cliente)

Pequeño SDK y ejemplos para integradores que quieran hablar con el WebSocket de
Triton Client Manager sin leer el código del servidor.

---

## Módulos

- `client.py`: cliente interactivo muy simple para pruebas manuales (`auth` vacío + `info.queue_stats`).
- `sdk.py`: SDK ligero pensado para integradores y tests de contrato.

---

## Quickstart (copiar/pegar y ejecutar)

Con el manager corriendo (por ejemplo en modo dev con `dev_server.py` en el puerto 8000):

```bash
cd MANAGER
.venv/bin/python -c "from _______WEBSOCKET.sdk import run_quickstart; run_quickstart('ws://127.0.0.1:8000/ws')"
```

Este comando:

1. Abre una conexión WebSocket a `ws://127.0.0.1:8000/ws`.
2. Envía un mensaje `auth` con:
   - `uuid`: `sdk-quickstart-client`
   - `payload.client.sub`: `user-sdk`
   - `payload.client.tenant_id`: `tenant-sdk`
   - `payload.client.roles`: `['inference', 'management']`
3. Envía un mensaje `info` con `payload.action = "queue_stats"`.
4. Imprime la respuesta JSON de `info_response` por stdout.

---

## Uso desde código Python

```python
import asyncio

from _______WEBSOCKET.sdk import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    auth_ctx = AuthContext(
        uuid="my-frontend-1",
        token="opaque-or-jwt-token",
        sub="user-123",
        tenant_id="tenant-abc",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, auth_ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Tests de contrato

El SDK se valida con `pytest` en `tests/test_client_sdk_contract.py`, que:

- Inicia un servidor de pruebas con `ws_server` (mocks para OpenStack/Docker/Triton).
- Usa `TcmWebSocketClient` para ejecutar el flujo `auth` + `info.queue_stats`.
- Comprueba que la respuesta cumple el contrato documentado en `docs/WEBSOCKET_API.md`.

