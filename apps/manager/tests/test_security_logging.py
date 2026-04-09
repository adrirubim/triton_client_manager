import logging

from classes.job.jobthread import JobThread

SECRET_TOKEN = "SECRET_TOKEN_TEST_123"
CORRELATION_ID_CLEAR = "corr-id-clear-text"


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
    Same as the info case, but exercising the `management` flow:
    when the per-user queue is full and the backpressure warning is logged,
    the payload (which contains a synthetic "secret") must not appear in logs.
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
        # Authorize the management flow.
        "_auth": {"roles": ["management"]},
    }

    jt.on_message(user_id, msg)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert SECRET_TOKEN not in log_text, "Sensitive token leaked into logs (management)"


def test_no_secrets_logged_when_inference_queue_is_full(caplog) -> None:
    """
    Same pattern for the `inference` flow: a full queue triggers a backpressure
    warning but must never dump the payload with the "secret".
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


def test_correlation_id_is_not_logged_in_clear_text(caplog) -> None:
    """
    CodeQL flags correlation IDs as potentially sensitive.
    Ensure we never log the raw value, but keep a stable hashed identifier.
    """

    caplog.set_level(logging.WARNING)

    jt = _make_minimal_jobthread()

    user_id = "user-authz-1"
    msg = {
        "uuid": user_id,
        "type": "management",
        "payload": {"action": "creation"},
        "_correlation_id": CORRELATION_ID_CLEAR,
        # Missing roles triggers authz_reject warning path.
        "_auth": {"roles": []},
    }

    jt.on_message(user_id, msg)

    # Find the authz rejection warning record
    recs = [r for r in caplog.records if "Rejected management request due to missing role" in r.getMessage()]
    assert recs, "Expected authz rejection warning log record"

    record = recs[-1]
    correlation_id = getattr(record, "correlation_id", "")

    assert CORRELATION_ID_CLEAR not in "\n".join(r.getMessage() for r in caplog.records)
    assert correlation_id.startswith("sha256:"), f"Expected hashed correlation_id, got: {correlation_id!r}"
    assert CORRELATION_ID_CLEAR not in correlation_id, "Raw correlation id leaked into structured log field"
