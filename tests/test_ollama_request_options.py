from __future__ import annotations

from app.core import ollama_client
from app.core.config import settings
from app.core.ollama_client import OllamaChatMessage


def _payload(monkeypatch, *, num_ctx, keep_alive, temperature=0.0) -> dict:
    monkeypatch.setattr(settings, "ollama_num_ctx", num_ctx)
    monkeypatch.setattr(settings, "ollama_keep_alive", keep_alive)
    client = ollama_client.OllamaChatClient(
        base_url="http://ollama.test",
        api_key=None,
        model="qwen2.5:7b",
        timeout_seconds=5,
    )
    sent: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": "{}"}}

    def fake_send(path, payload):
        sent.append(payload)
        return _Response()

    monkeypatch.setattr(client, "_send_with_retries", fake_send)
    client.chat([OllamaChatMessage(role="user", content="x")], temperature=temperature)
    return sent[0]


def test_num_ctx_and_keep_alive_are_sent_when_configured(monkeypatch) -> None:
    payload = _payload(monkeypatch, num_ctx=12288, keep_alive="30m")

    assert payload["options"] == {"temperature": 0.0, "num_ctx": 12288}
    assert payload["keep_alive"] == "30m"


def test_unset_options_keep_server_defaults(monkeypatch) -> None:
    payload = _payload(monkeypatch, num_ctx=None, keep_alive=None, temperature=None)

    assert "options" not in payload
    assert "keep_alive" not in payload
