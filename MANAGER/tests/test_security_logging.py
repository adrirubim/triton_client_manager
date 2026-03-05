import logging

from classes.job.jobthread import JobThread


SECRET_TOKEN = "SECRET_TOKEN_TEST_123"


def _make_minimal_jobthread() -> JobThread:
    """
    Build a minimal JobThread instance suitable for unit testing logging
    behaviour without starting any real threads or backends.
    """

    return JobThread(
        max_workers_info=1,
        max_workers_management=1,
        max_workers_inference=1,
        max_executor_queue_info=1,
        max_executor_queue_management=1,
        max_executor_queue_inference=1,
        queue_cleanup_interval=3600,
        queue_idle_threshold=3600,
        max_queue_size_info_per_user=1,
        max_queue_size_management_per_user=1,
        max_queue_size_inference_per_user=1,
    )


def test_no_secrets_logged_when_info_queue_is_full(caplog) -> None:
    """
    When the per-user info queue is full and JobThread logs a warning about
    backpressure, the original payload (which may contain sensitive fields)
    must not be included in the log message.

    This exercises a realistic failure mode (backpressure / queue full) and
    asserts that a synthetic "secret" string never appears in the logs.
    """

    caplog.set_level(logging.WARNING)

    jt = _make_minimal_jobthread()

    user_id = "user-1"

    # Pre-fill the per-user info queue to its max size so that the next
    # put_nowait raises and triggers the warning path in on_message().
    queue = jt.get_or_create_queue(
        user_id=user_id,
        max_size=1,
        queue_dict=jt.info_queues,
    )
    queue.put_nowait(
        {
            "uuid": user_id,
            "type": "info",
            "payload": {"action": "queue_stats"},
        }
    )

    # Now send a second message whose payload contains a synthetic "secret".
    msg = {
        "uuid": user_id,
        "type": "info",
        "payload": {
            "action": "queue_stats",
            "token": SECRET_TOKEN,
        },
    }

    jt.on_message(user_id, msg)

    # Collect log messages and assert that the synthetic secret never appears.
    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert SECRET_TOKEN not in log_text, "Sensitive token leaked into logs"


def test_no_secrets_logged_when_management_queue_is_full(caplog) -> None:
    """
    Igual que el caso de info, pero ejercitando el flujo de `management`:
    cuando la cola per-user está llena y se registra el aviso de backpressure,
    el payload (que contiene un "secreto" sintético) no debe aparecer en logs.
    """

    caplog.set_level(logging.WARNING)

    jt = _make_minimal_jobthread()

    user_id = "user-mgmt-1"

    # Pre-fill management queue for this user.
    queue = jt.get_or_create_queue(
        user_id=user_id,
        max_size=1,
        queue_dict=jt.management_queues,
    )
    queue.put_nowait(
        {
            "uuid": user_id,
            "type": "management",
            "payload": {"action": "creation"},
        }
    )

    msg = {
        "uuid": user_id,
        "type": "management",
        "payload": {
            "action": "creation",
            "secret_field": SECRET_TOKEN,
        },
        # Autorizar el flujo de management.
        "_auth": {"roles": ["management"]},
    }

    jt.on_message(user_id, msg)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert SECRET_TOKEN not in log_text, "Sensitive token leaked into logs (management)"


def test_no_secrets_logged_when_inference_queue_is_full(caplog) -> None:
    """
    Mismo patrón para el flujo de `inference`: la cola llena provoca un aviso
    de backpressure pero nunca debe volcar el payload con el "secreto".
    """

    caplog.set_level(logging.WARNING)

    jt = _make_minimal_jobthread()

    user_id = "user-inf-1"

    queue = jt.get_or_create_queue(
        user_id=user_id,
        max_size=1,
        queue_dict=jt.inference_queues,
    )
    queue.put_nowait(
        {
            "uuid": user_id,
            "type": "inference",
            "payload": {"model_name": "demo-model"},
        }
    )

    msg = {
        "uuid": user_id,
        "type": "inference",
        "payload": {
            "model_name": "demo-model",
            "token": SECRET_TOKEN,
        },
        "_auth": {"roles": ["inference"]},
    }

    jt.on_message(user_id, msg)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert SECRET_TOKEN not in log_text, "Sensitive token leaked into logs (inference)"

