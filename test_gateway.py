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


def test_dialogue_request_is_stateless_and_preserves_temperature(monkeypatch):
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
    assert fake.interactions.kwargs["extra_body"]["generation_config"]["temperature"] == 0.35
