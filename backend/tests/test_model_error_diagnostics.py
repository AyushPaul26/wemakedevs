"""Model failure diagnostics identify causes without logging untrusted content."""
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from relay.api import app as relay_app
from relay.llm import ModelError, ModelResponseError


GENERIC_DETAIL = (
    "The model could not complete this investigation. "
    "Check provider settings and quota, then retry. Your previous memory is unchanged."
)


def request_failure(error, cause=None):
    # Exercise the application's actual exception handler without depending on
    # database availability or making a provider call.
    app = FastAPI()
    app.add_exception_handler(ModelError, relay_app.exception_handlers[ModelError])

    @app.get("/failure")
    def failure():
        raise error from cause

    with TestClient(app) as client:
        return client.get("/failure")


@pytest.mark.parametrize("error,category,reason", [
    (ModelError("The model provider is rate-limited. Please retry shortly."),
     "provider", "provider_rate_limited"),
    (ModelError("Model authentication failed. Check RELAY_MODEL_API_KEY in environment settings."),
     "provider", "provider_authentication"),
    (ModelError("The model provider is unavailable or timed out. Please retry."),
     "provider", "provider_transport"),
    (ModelError("The model provider is unavailable. Please retry or check the model configuration."),
     "provider", "provider_http_error"),
    (ModelResponseError("The model returned unreadable JSON. Please retry."),
     "response_validation", "response_json"),
    (ModelResponseError("The model returned an invalid response. Please retry."),
     "response_validation", "response_schema"),
    (ModelResponseError("The model cited evidence outside the retrieved graph. Please retry."),
     "response_validation", "citation_scope"),
    (ModelResponseError("The model cited an unavailable evidence version. Please retry."),
     "response_validation", "citation_version"),
    (ModelResponseError("The model omitted exact attachment citations. Please retry."),
     "response_validation", "citation_exact_missing"),
    (ModelResponseError("The model cited an unavailable report. Please retry."),
     "response_validation", "report_scope"),
])
def test_known_model_failures_log_stable_reason_and_keep_generic_response(caplog, error, category, reason):
    with caplog.at_level(logging.WARNING, logger="relay.api"):
        response = request_failure(error, RuntimeError("PRIVATE_PROVIDER_BODY"))
    assert response.status_code == 502
    assert response.json() == {"detail": GENERIC_DETAIL}
    records = [record for record in caplog.records if record.name == "relay.api"]
    assert len(records) == 1
    assert records[0].getMessage() == f"Model investigation failed category={category} reason={reason}"
    assert records[0].exc_info is None and records[0].stack_info is None
    assert "PRIVATE_PROVIDER_BODY" not in caplog.text
    assert str(error) not in caplog.text


@pytest.mark.parametrize("error", [
    ModelError("PRIVATE_API_KEY and generated text and user input"),
    ModelResponseError("PRIVATE_API_KEY and generated text and user input"),
    ModelError("The model provider is rate-limited. Please retry shortly. PRIVATE_API_KEY"),
    ModelError({"provider_response": "PRIVATE_API_KEY"}),
    ModelError("The model provider is rate-limited. Please retry shortly.", "PRIVATE_API_KEY"),
])
def test_unknown_model_error_never_logs_its_message_or_exception_chain(caplog, error):
    with caplog.at_level(logging.WARNING, logger="relay.api"):
        response = request_failure(error, RuntimeError("PRIVATE_PROVIDER_BODY"))
    assert response.status_code == 502
    assert response.json() == {"detail": GENERIC_DETAIL}
    records = [record for record in caplog.records if record.name == "relay.api"]
    assert len(records) == 1
    category = "response_validation" if isinstance(error, ModelResponseError) else "provider"
    assert records[0].getMessage() == f"Model investigation failed category={category} reason=unknown"
    assert records[0].exc_info is None and records[0].stack_info is None
    assert "PRIVATE_" not in caplog.text + response.text
