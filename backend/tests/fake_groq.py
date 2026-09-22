import json
from types import SimpleNamespace


class FakeGroqClient:
    """Stands in for groq.AsyncGroq; returns a fixed JSON-array response."""

    def __init__(self, response_text: str | None = None, response_json: list | None = None):
        if response_json is not None:
            response_text = json.dumps(response_json)
        self._response_text = response_text or "[]"
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )
        self.calls: list[dict] = []

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._response_text)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])
