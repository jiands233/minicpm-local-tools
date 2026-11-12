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
    calls = []

    def fake_request(client, url, route):
        calls.append((url, route))
        return {"data": [{"id": client.model}]}

    monkeypatch.setenv("MINICPM_BASE_URL", address)
    monkeypatch.delenv("MINICPM_OCR_URL", raising=False)
    monkeypatch.delenv("MINICPM_EMBED_URL", raising=False)
    monkeypatch.setattr(LocalClient, "_request", fake_request)
    assert run_doctor(None) == 0
    output = capsys.readouterr().out
    assert output.count("http://127.0.0.1:12345/[路径已隐藏]") == 3
    assert "private-example-token" not in output
    assert calls == [(address, "/models")] * 3


def test_doctor_keeps_standard_path_and_ipv6_origin(capsys, monkeypatch):
    monkeypatch.setenv("MINICPM_BASE_URL", "http://[::1]:12345/v1")
    monkeypatch.delenv("MINICPM_OCR_URL", raising=False)
    monkeypatch.delenv("MINICPM_EMBED_URL", raising=False)
    monkeypatch.setattr(LocalClient, "_request", lambda *args: {"data": []})
    assert run_doctor(None) == 1
    assert "http://[::1]:12345/v1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "invalid_var,label", [("MINICPM_BASE_URL", "文本"), ("MINICPM_OCR_URL", "OCR"),
                          ("MINICPM_EMBED_URL", "Embedding")],
)
def test_doctor_isolates_invalid_service_and_preserves_other_configuration(
    monkeypatch, capsys, invalid_var, label
):
    addresses = {
        "MINICPM_BASE_URL": "http://127.0.0.1:10001/v1/private-a",
        "MINICPM_OCR_URL": "http://[::1]:10002/custom/private-b",
        "MINICPM_EMBED_URL": "http://localhost:10003/v1/private-c",
    }
    for key, value in addresses.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(invalid_var, "http://user:secret@localhost/v1/private-token")
    monkeypatch.setenv("MINICPM_MODEL", "custom-text")
    monkeypatch.setenv("MINICPM_OCR_MODEL", "custom-ocr")
    monkeypatch.setenv("MINICPM_EMBED_MODEL", "custom-embed")
    monkeypatch.setenv("MINICPM_TIMEOUT", "12.5")
    calls = []
    def request(client, url, route):
        calls.append((url, route, client.model, client.timeout))
        return {"data": [{"id": client.model}]}
    monkeypatch.setattr(LocalClient, "_request", request)
    assert run_doctor(None) == 1
    result = capsys.readouterr().out
    assert f"{label}: 模型地址无效" in result
    assert len(calls) == 2 and all(call[1] == "/models" and call[3] == 12.5 for call in calls)
    assert {call[0] for call in calls} == {value for key, value in addresses.items() if key != invalid_var}
    assert result.count("· 可见") == 2
    assert all(secret not in result for secret in ("secret", "private-token", "private-a", "private-b", "private-c"))


def test_doctor_invalid_shared_timeout_reports_each_service_without_requests(monkeypatch, capsys):
    monkeypatch.setenv("MINICPM_TIMEOUT", "nan")
    monkeypatch.setattr(LocalClient, "_request", lambda *args: pytest.fail("request attempted"))
    assert run_doctor(None) == 1
    out = capsys.readouterr().out
    assert all(f"{name}: 模型超时秒数必须为正数" in out for name in ("文本", "OCR", "Embedding"))


def test_doctor_invalid_base_affects_unset_inherited_services(monkeypatch, capsys):
    monkeypatch.setenv("MINICPM_BASE_URL", "http://localhost:bad/v1")
    monkeypatch.delenv("MINICPM_OCR_URL", raising=False)
    monkeypatch.delenv("MINICPM_EMBED_URL", raising=False)
    assert run_doctor(None) == 1
    out = capsys.readouterr().out
    assert out.count("模型地址无效") == 3


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


@pytest.mark.parametrize("message", [
    "max_tokens must be <= 1024; private-input",
    "maximum output tokens is 1024; private-input",
])
def test_output_token_parameter_error_is_not_misdiagnosed_as_long_input(monkeypatch, message):
    import httpx

    client = LocalClient()
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"error": {"message": message}})),
            **kwargs,
        ),
    )
    with pytest.raises(ToolError, match="本地模型请求失败") as exc:
        client.chat("hi")
    assert "private-input" not in str(exc.value)


def test_input_token_overflow_without_context_word_is_actionable():
    from minicpm_tools.client import _context_overflow

    assert _context_overflow("input tokens exceed the maximum of 8192")
    assert _context_overflow("The maximum context length is 8192 tokens")
