from types import SimpleNamespace

import pytest

from src.gemini_gateway import GeminiGateway, GatewayError


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
