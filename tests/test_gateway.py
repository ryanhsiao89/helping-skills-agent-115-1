from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.gemini_gateway import (
    GeminiGateway,
    GatewayError,
    is_invalid_api_key_error,
    is_timeout_error,
)


class FakeInteractions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="測試回應")


class FakeClient:
    def __init__(self):
        self.interactions = FakeInteractions()


def test_dialogue_request_is_stateless_and_uses_thinking_level_for_gemini_3(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.8-flash")
    fake = FakeClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)

    result = gateway.generate_text(
        prompt="hello",
        system_instruction="system",
        temperature=0.35,
    )

    assert result.text == "測試回應"
    assert fake.interactions.kwargs["store"] is False
    assert fake.interactions.kwargs["generation_config"]["thinking_level"] == "low"
    assert "temperature" not in fake.interactions.kwargs["generation_config"]
    assert "extra_body" not in fake.interactions.kwargs
    assert fake.interactions.kwargs["timeout"] == 45.0


class TimeoutInteractions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise TimeoutError("request timed out")


class TimeoutClient:
    def __init__(self):
        self.interactions = TimeoutInteractions()


def test_dialogue_timeout_stops_without_duplicate_config_retry(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.8-flash")
    fake = TimeoutClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)

    with pytest.raises(GatewayError, match="等待超過 45 秒"):
        gateway.generate_text(
            prompt="hello",
            system_instruction="system",
            temperature=0.35,
        )

    assert fake.interactions.calls == 1



def test_custom_timeout_message_uses_requested_seconds(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.8-flash")
    fake = TimeoutClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)

    with pytest.raises(GatewayError, match="等待超過 15 秒"):
        gateway.generate_text(
            prompt="請只回覆 OK。",
            system_instruction="只回覆 OK。",
            temperature=0.0,
            timeout_seconds=15.0,
        )

    assert fake.interactions.calls == 1



class AssessmentProbe(BaseModel):
    value: str


class QuotaError(RuntimeError):
    status_code = 429


class FallbackInteractions:
    def __init__(self):
        self.models = []

    def create(self, **kwargs):
        model = kwargs["model"]
        self.models.append(model)
        if model == "gemini-3.8-flash":
            raise QuotaError("RESOURCE_EXHAUSTED: quota exceeded")
        return SimpleNamespace(output_text='{"value":"ok"}')


class FallbackClient:
    def __init__(self):
        self.interactions = FallbackInteractions()


def test_structured_evaluator_falls_back_to_flash_lite_on_quota(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.5-flash-lite")
    fake = FallbackClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)

    result = gateway.generate_structured(
        prompt="evaluate",
        system_instruction="system",
        temperature=0.0,
        schema=AssessmentProbe,
        model_name="gemini-3.8-flash",
        fallback_model_name="gemini-3.5-flash-lite",
    )

    assert result.parsed.value == "ok"
    assert result.model_name == "gemini-3.5-flash-lite"
    assert fake.interactions.models == [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
    ]


class InvalidKeyError(RuntimeError):
    status_code = 400


class InvalidKeyInteractions:
    def __init__(self):
        self.models = []

    def create(self, **kwargs):
        self.models.append(kwargs["model"])
        raise InvalidKeyError("API_KEY_INVALID: API key not valid")


class InvalidKeyClient:
    def __init__(self):
        self.interactions = InvalidKeyInteractions()


def test_structured_evaluator_does_not_fallback_on_invalid_key(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.5-flash-lite")
    fake = InvalidKeyClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)

    with pytest.raises(GatewayError, match="API Key 無效"):
        gateway.generate_structured(
            prompt="evaluate",
            system_instruction="system",
            temperature=0.0,
            schema=AssessmentProbe,
            model_name="gemini-3.8-flash",
            fallback_model_name="gemini-3.5-flash-lite",
        )

    assert fake.interactions.models == ["gemini-3.8-flash"]



def test_timeout_classifier_recognizes_timeout_errors():
    assert is_timeout_error(TimeoutError("request timed out")) is True
    assert is_timeout_error(RuntimeError("temporary service error")) is False


def test_invalid_key_classifier_only_matches_explicit_invalid_key():
    assert is_invalid_api_key_error(
        RuntimeError("API_KEY_INVALID: API key not valid")
    ) is True
    assert is_invalid_api_key_error(
        RuntimeError("RESOURCE_EXHAUSTED: quota exceeded")
    ) is False



class EmptyThenTextInteractions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(output_text="")
        return SimpleNamespace(output_text="第二次成功")


class EmptyThenTextClient:
    def __init__(self):
        self.interactions = EmptyThenTextInteractions()


def test_dialogue_retries_once_when_model_returns_empty_text(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.5-flash-lite")
    fake = EmptyThenTextClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)
    monkeypatch.setattr("src.gemini_gateway.time.sleep", lambda _seconds: None)

    result = gateway.generate_text(
        prompt="hello",
        system_instruction="system",
        temperature=0.35,
    )

    assert result.text == "第二次成功"
    assert fake.interactions.calls == 2


class AlwaysEmptyInteractions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(output_text="")


class AlwaysEmptyClient:
    def __init__(self):
        self.interactions = AlwaysEmptyInteractions()


def test_dialogue_empty_text_twice_returns_friendly_message(monkeypatch):
    gateway = GeminiGateway(("test-key",), "gemini-3.5-flash-lite")
    fake = AlwaysEmptyClient()
    monkeypatch.setattr(gateway, "_client", lambda _key: fake)
    monkeypatch.setattr("src.gemini_gateway.time.sleep", lambda _seconds: None)

    with pytest.raises(GatewayError, match="不代表 API Key 無效"):
        gateway.generate_text(
            prompt="hello",
            system_instruction="system",
            temperature=0.35,
        )

    assert fake.interactions.calls == 2
