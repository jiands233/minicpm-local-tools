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
