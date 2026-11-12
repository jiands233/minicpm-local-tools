"""Wrong or malformed local services must report actionable errors."""

import pytest

from minicpm_tools.cli import run_doctor
from minicpm_tools.client import LocalClient
from minicpm_tools.common import ToolError


@pytest.mark.parametrize("payload", [[], {}, {"data": None}, {"data": [None]}, {"data": [{}]}])
def test_doctor_handles_malformed_model_lists(monkeypatch, capsys, payload):
    monkeypatch.setattr(LocalClient, "_request", lambda *args: payload)
    assert run_doctor(None) == 1
    result = capsys.readouterr()
    assert result.out.count("模型列表格式无效") == 3
    assert "Traceback" not in result.err


def test_doctor_hides_custom_endpoint_paths_but_requests_actual_url(monkeypatch, capsys):
    address = "http://127.0.0.1:12345/v1/private-example-token"
    client = LocalClient(base_url=address)
    calls = []

    def fake_request(url, route):
        calls.append((url, route))
        return {"data": [{"id": name} for name in (client.model, client.ocr_model, client.embedding_model)]}

    monkeypatch.setattr(LocalClient, "from_env", lambda: client)
    monkeypatch.setattr(client, "_request", fake_request)
    assert run_doctor(None) == 0
    output = capsys.readouterr().out
    assert output.count("http://127.0.0.1:12345/[路径已隐藏]") == 3
    assert "private-example-token" not in output
    assert calls == [(address, "/models")] * 3


def test_doctor_keeps_standard_path_and_ipv6_origin(capsys, monkeypatch):
    client = LocalClient(base_url="http://[::1]:12345/v1")
    monkeypatch.setattr(LocalClient, "from_env", lambda: client)
    monkeypatch.setattr(client, "_request", lambda *args: {"data": []})
    assert run_doctor(None) == 1
    assert "http://[::1]:12345/v1" in capsys.readouterr().out


def test_embedding_oversized_number_reports_invalid_vector(monkeypatch):
    client = LocalClient()
    monkeypatch.setattr(
        client, "_request", lambda *args: {"data": [{"index": 0, "embedding": [10**400]}]}
    )
    with pytest.raises(ToolError, match="无效向量"):
        client.embed(["x"])


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:notaport/v1",
        "http://localhost:65536/v1",
        "http://localhost:0/v1",
        "http://[bad/v1",
        "http://user:secret@localhost/v1",
        "http://127.0.0.1/v1?token=secret",
    ],
)
def test_bad_local_address_rejected_without_echoing_sensitive_text(address):
    with pytest.raises(ToolError, match="模型地址无效") as exc:
        LocalClient(base_url=address)
    assert "secret" not in str(exc.value)
    assert address not in str(exc.value)


@pytest.mark.parametrize("timeout", ["bad", None, "nan", "-1", "0", "inf"])
def test_invalid_timeout_is_actionable(timeout):
    with pytest.raises(ToolError, match="模型超时秒数必须为正数"):
        LocalClient(timeout=timeout)


def test_httpx_invalid_url_fails_cleanly(monkeypatch):
    import httpx

    client = LocalClient()

    def broken(*args, **kwargs):
        raise httpx.InvalidURL("private URL details")

    monkeypatch.setattr(httpx.Client, "get", broken)
    with pytest.raises(ToolError) as exc:
        client._request(client.base_url, "/models")
    assert "private URL details" not in str(exc.value)


def test_context_overflow_is_actionable_without_echoing_private_error(monkeypatch):
    import httpx

    client = LocalClient()
    real_client = httpx.Client

    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "request (11013 tokens) exceeds the available context size (8192 tokens); private-input"
                }
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ToolError, match="输入超过模型上下文长度") as exc:
        client.chat("private-input")
    assert "private-input" not in str(exc.value)


def test_unrelated_400_remains_generic(monkeypatch):
    import httpx

    client = LocalClient()
    real_client = httpx.Client

    def handler(request):
        return httpx.Response(400, json={"error": {"message": "invalid model; private-input"}})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ToolError, match="本地模型请求失败") as exc:
        client.chat("private-input")
    assert "private-input" not in str(exc.value)
