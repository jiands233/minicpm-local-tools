"""Wire-level multimodal ordering for the local OpenAI-compatible client."""

import base64
import json

import httpx
import pytest

from minicpm_tools.client import LocalClient


@pytest.mark.parametrize(
    ("suffix", "mime", "data"),
    [
        (".png", "image/png", b"\x89PNG\r\n\x1a\nsynthetic"),
        (".jpg", "image/jpeg", b"\xff\xd8\xffsynthetic"),
    ],
)
def test_ocr_sends_image_before_instruction(monkeypatch, tmp_path, suffix, mime, data):
    image = tmp_path / f"example{suffix}"
    image.write_bytes(data)
    requests = []
    real_client = httpx.Client

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "recognized"}, "finish_reason": "stop"}]}
        )

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    client = LocalClient(ocr_url="http://127.0.0.1:19400/v1", ocr_model="local-ocr")

    assert client.ocr(image) == "recognized"
    assert len(requests) == 1
    assert str(requests[0].url) == "http://127.0.0.1:19400/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "local-ocr"
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
                },
                {"type": "text", "text": "Text Recognition:"},
            ],
        }
    ]


def test_plain_text_chat_keeps_string_content(monkeypatch):
    captured = {}

    def fake_request(base, route, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    client = LocalClient()
    monkeypatch.setattr(client, "_request", fake_request)
    assert client.chat("hello", system="guidance") == "ok"
    assert captured["messages"] == [
        {"role": "system", "content": "guidance"},
        {"role": "user", "content": "hello"},
    ]
