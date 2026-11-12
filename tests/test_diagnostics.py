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
