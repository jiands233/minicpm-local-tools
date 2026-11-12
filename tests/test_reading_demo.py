import json
import socket
import sys
from pathlib import Path

import pytest

from minicpm_tools import cli, history
from minicpm_tools.client import LocalClient
from minicpm_tools.reading_demo import create_history


def test_demo_is_offline_and_contains_only_synthetic_records(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("demo must not use network or create model client")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(LocalClient, "from_env", fail)
    monkeypatch.setenv("MINICPM_BASE_URL", "https://invalid.example")
    monkeypatch.setattr(sys, "argv", ["mcpm", "history", "--demo"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "演示：记录为虚构；主题为预录的 MiniCPM5-2B 输出" in out
    assert "标题信息不足，未归类" in out
    assert "记录 17、记录 18" in out
    assert "2 次访问" in out
    assert "链接参数已隐藏" in out
    assert "登录账户" not in out and "utm_source" not in out
    assert out.count("](") == 18


def test_demo_rejects_invalid_pre_recording_without_partial_output(monkeypatch, capsys):
    response = history._load_demo_response()
    response["themes"][0]["ids"][0] = 999
    monkeypatch.setattr(history, "_load_demo_response", lambda: response)
    monkeypatch.setattr(sys, "argv", ["mcpm", "history", "--demo"])
    assert cli.main() == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "不存在" in result.err


def test_demo_rejects_incompatible_options(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mcpm", "history", "--demo", "--database", "personal.db"])
    assert cli.main() == 1
    assert capsys.readouterr().out == ""


def test_demo_database_refuses_overwrite(tmp_path):
    path = tmp_path / "History"
    path.write_text("existing")
    with pytest.raises(FileExistsError):
        create_history(path)
    assert path.read_text() == "existing"


def test_demo_packaged_response_keeps_raw_model_output():
    path = Path(history.__file__).with_name("reading_demo_themes.json")
    data = json.loads(path.read_text())
    assert data["response"] == history.parse_json(data["raw_response"])
