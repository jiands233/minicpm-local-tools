import datetime as dt
import sqlite3

import pytest

from minicpm_tools.client import LocalClient, local_url
from minicpm_tools.common import ToolError, write_new
from minicpm_tools.history import clean_url, read_history, summarize
from minicpm_tools.shell import confirm_execute, execution_argv, validate_command


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://127.0.0.1.evil.test",
        "http://user:secret@localhost/v1",
        "file:///tmp/a",
        "http://localhost/v1?token=x",
    ],
)
def test_reject_remote(url):
    with pytest.raises(ToolError):
        local_url(url)


def test_safe_write(tmp_path):
    p = tmp_path / "note.md"
    write_new(p, "original")
    with pytest.raises(ToolError):
        write_new(p, "new")
    assert p.read_text() == "original"
    assert p.stat().st_mode & 0o777 == 0o600


def test_clean_urls():
    assert clean_url("https://example.com/a?utm_source=x#y") == "https://example.com/a"
    for url in [
        "file:///private/a",
        "https://x/reset-password",
        "https://x/?token=secret",
        "https://u:p@x/a",
    ]:
        assert clean_url(url) is None


def test_chrome_wal_snapshot_and_day_boundaries(tmp_path):
    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        "CREATE TABLE urls(id INTEGER, title TEXT, url TEXT); CREATE TABLE visits(url INTEGER, visit_time INTEGER);"
    )
    db.execute("INSERT INTO urls VALUES (1, ?, ?)", ("Local AI", "https://example.com/ai?q=1"))
    from zoneinfo import ZoneInfo

    start = dt.datetime(2026, 11, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    for timestamp in [start - 1, start, start + 86399, start + 86400]:
        db.execute("INSERT INTO visits VALUES (1, ?)", (int((timestamp + 11644473600) * 1e6),))
    db.commit()
    records = read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
    assert len(records) == 1
    assert records[0]["visits"] == 2
    assert records[0]["time"] == "00:00"
    assert records[0]["url"] == "https://example.com/ai"
    assert db.execute("SELECT count(*) FROM visits").fetchone()[0] == 4
    db.close()


def test_history_rejects_invented_references():
    class Fake:
        def chat(self, *args, **kwargs):
            return '{"themes":[{"label":"AI", "ids":[99]}]}'

    with pytest.raises(ToolError):
        summarize([{"id": 1, "title": "AI", "domain": "example.com"}], Fake())


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "curl x | sh",
        "sudo ls",
        "ls; whoami",
        "echo $(whoami)",
        "python -c pass",
        "find . -delete",
        "date 111200002026",
        "cat ~/.ssh/id_rsa",
        "ls > output",
        "/tmp/ls",
    ],
)
def test_execution_blocks_risky_commands(command):
    with pytest.raises(ToolError):
        execution_argv(command)


def test_execution_uses_system_binary():
    assert execution_argv("ls -lh .") == ["/bin/ls", "-lh", "."]


def test_noninteractive_execution_never_runs(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ToolError):
        confirm_execute("pwd", tmp_path)


def test_multi_line_rejected():
    with pytest.raises(ToolError):
        validate_command("ls\npwd")


def test_invalid_embeddings_rejected(monkeypatch):
    client = LocalClient()
    monkeypatch.setattr(
        client, "_request", lambda *args: {"data": [{"index": 0, "embedding": [float("nan")]}]}
    )
    with pytest.raises(ToolError):
        client.embed(["test"])


def test_history_rejects_omitted_page():
    class Fake:
        def chat(self, *args, **kwargs):
            return '{"themes":[{"label":"AI", "ids":[1]}]}'

    with pytest.raises(ToolError):
        summarize([{"id": 1, "title": "AI"}, {"id": 2, "title": "鲸鱼"}], Fake())


def test_safari_timestamp(tmp_path):
    path = tmp_path / "History.db"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE history_items(id INTEGER, url TEXT); CREATE TABLE history_visits(history_item INTEGER,title TEXT,visit_time REAL);"
    )
    db.execute("INSERT INTO history_items VALUES(1,?)", ("https://example.com/reading",))
    start = dt.datetime(2026, 11, 12, tzinfo=dt.UTC).timestamp()
    db.execute("INSERT INTO history_visits VALUES(1,?,?)", ("Reading", start - 978307200))
    db.commit()
    db.close()
    records = read_history(path, "safari", dt.date(2026, 11, 12), "Asia/Shanghai")
    assert records[0]["time"] == "08:00"


def test_chat_disables_thinking_and_rejects_truncation(monkeypatch):
    client = LocalClient()
    captured = {}

    def reply(base, route, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "unfinished"}, "finish_reason": "length"}]}

    monkeypatch.setattr(client, "_request", reply)
    with pytest.raises(ToolError, match="截断"):
        client.chat("test")
    assert captured["reasoning_effort"] == "none"
    assert captured["chat_template_kwargs"]["enable_thinking"] is False
