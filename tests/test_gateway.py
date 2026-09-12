from types import SimpleNamespace

from src.gemini_gateway import GeminiGateway


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
