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


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=tracker",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        ("https://m.youtube.com/watch?v=9bZkp7q19f0", "https://m.youtube.com/watch?v=9bZkp7q19f0"),
        (
            "https://www.bilibili.com/video/BV1234567890/?p=2&session=private",
            "https://www.bilibili.com/video/BV1234567890/?p=2",
        ),
        (
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://youtube.com.evil.example/watch",
        ),
        ("https://www.youtube.com/watch?v=not-a-public-video-id", "https://www.youtube.com/watch"),
        (
            "https://www.bilibili.com/video/BV1234567890/?p=private",
            "https://www.bilibili.com/video/BV1234567890/",
        ),
    ],
)
def test_history_preserves_only_known_resource_parameters(original, expected):
    assert clean_url(original) == expected


def test_history_redaction_does_not_merge_different_pages(tmp_path):
    from minicpm_tools.history import render

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
    )
    moment = int((dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC).timestamp() + 11644473600) * 1e6)
    original = [
        ("OCR video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("Whale video", "https://www.youtube.com/watch?v=9bZkp7q19f0"),
        ("Article A", "https://example.com/article?id=1&session=secret-a"),
        ("Article B", "https://example.com/article?id=2&session=secret-b"),
    ]
    for serial, (title, url) in enumerate(original, 1):
        db.execute("INSERT INTO urls VALUES(?,?,?)", (serial, title, url))
        db.execute("INSERT INTO visits VALUES(?,?)", (serial, moment))
    db.execute("INSERT INTO visits VALUES(1,?)", (moment + 1000000,))
    db.commit()
    db.close()
    records = read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
    assert len(records) == 4
    assert records[0]["visits"] == 2
    assert records[0]["url"] != records[1]["url"]
    assert not records[0]["link_redacted"]
    assert records[2]["url"] == records[3]["url"] == "https://example.com/article"
    assert records[2]["link_redacted"] and records[3]["link_redacted"]
    report = render(records, "2026-11-12", "Asia/Shanghai")
    assert "Article A" in report and "Article B" in report
    assert report.count("可能无法回到原页面") == 2
    assert "secret-a" not in report and "secret-b" not in report and "session=" not in report
    assert "identity" not in records[0]


def test_history_source_open_failure_is_actionable(tmp_path, monkeypatch):
    path = tmp_path / "History"
    path.touch()

    def denied(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", denied)
    with pytest.raises(ToolError, match="访问权限"):
        read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")


def test_history_snapshot_open_failure_closes_source(tmp_path, monkeypatch):
    from unittest.mock import Mock

    path = tmp_path / "History"
    path.touch()
    source = Mock()
    connect = Mock(side_effect=[source, sqlite3.OperationalError("cannot create snapshot")])
    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(ToolError, match="历史数据库读取失败"):
        read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
    source.close.assert_called_once()


def test_history_exclusive_lock_fails_promptly_without_modifying_database(tmp_path, monkeypatch):
    import time

    from minicpm_tools import history

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE urls(id INTEGER, title TEXT, url TEXT); CREATE TABLE visits(url INTEGER, visit_time INTEGER);"
    )
    db.execute("BEGIN EXCLUSIVE")
    try:
        monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.25)
        start = time.monotonic()
        with pytest.raises(ToolError, match="被锁定"):
            read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
        assert time.monotonic() - start < 2
    finally:
        db.rollback()
        db.close()
    with sqlite3.connect(path) as check:
        assert check.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 0


def test_history_batches_bound_encoded_input_and_cover_all_records():
    from minicpm_tools.history import HISTORY_BATCH_BYTES, history_batches

    records = [{"id": i, "title": "合成标题" + "知识资料" * 70} for i in range(1, 61)]
    batches = list(history_batches(records))
    assert len(batches) > 1
    assert [row["id"] for batch in batches for row in batch] == list(range(1, 61))
    assert [row for batch in batches for row in batch] == records
    for batch in batches:
        request = "\n".join(f"{r['id']} {r['title']}" for r in batch)
        assert len(request.encode("utf-8")) <= HISTORY_BATCH_BYTES
        assert len(batch) <= 60

    class Fake:
        def chat(self, prompt, **kwargs):
            import json

            records = [line for line in prompt.splitlines() if line[:1].isdigit()]
            return json.dumps(
                {
                    "themes": [
                        {"label": "合成资料", "ids": [int(row.split(" ", 1)[0]) for row in records]}
                    ]
                },
                ensure_ascii=False,
            )

    grouped = summarize(records, Fake())
    assert [i for _, ids in grouped for i in ids] == list(range(1, 61))


def test_history_batch_rejects_oversized_single_title():
    from minicpm_tools.history import history_batches

    with pytest.raises(ToolError, match="单条阅读记录过长"):
        list(history_batches([{"id": 1, "title": "测" * 1300}]))


def test_history_splits_invalid_batches_and_keeps_validated_order():
    import json

    class PartialFailure:
        def __init__(self):
            self.calls = []

        def chat(self, prompt, **kwargs):
            ids = [int(line.split(" ", 1)[0]) for line in prompt.splitlines() if line[:1].isdigit()]
            self.calls.append(ids)
            if len(ids) > 2:
                return json.dumps({"themes": [{"label": "坏编号", "ids": [999]}]})
            return json.dumps({"themes": [{"label": "合成主题", "ids": ids}]})

    client = PartialFailure()
    rows = [{"id": i, "title": f"资料{i}"} for i in range(1, 5)]
    assert summarize(rows, client) == [("合成主题", [1, 2]), ("合成主题", [3, 4])]
    assert client.calls == [[1, 2, 3, 4], [1, 2], [3, 4]]


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"themes":[{"label":"", "ids":[1]}]}',
        '{"themes":[{"label":"test", "ids":[1,1]}]}',
        '{"themes":[{"label":"test", "ids":[true]}]}',
        '{"themes":[{"label":"test", "ids":[99]}]}',
    ],
)
def test_history_single_record_invalid_result_never_fabricates(bad):
    class BadClient:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt, **kwargs):
            self.calls += 1
            return bad

    client = BadClient()
    with pytest.raises(ToolError, match="--mode list"):
        summarize([{"id": 1, "title": "资料"}], client)
    assert client.calls == 1


def test_history_retry_budget_and_no_partial_output():
    class AlwaysBad:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt, **kwargs):
            self.calls += 1
            return '{"themes":[{"label":"错误", "ids":[999]}]}'

    client = AlwaysBad()
    with pytest.raises(ToolError, match="--mode list"):
        summarize([{"id": i, "title": "标题"} for i in range(1, 61)], client)
    assert client.calls <= 7  # one original + six additional, never exponential


def test_history_http_error_is_not_retried():
    class Offline:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt, **kwargs):
            self.calls += 1
            raise ToolError("本地模型请求失败（HTTPStatusError）")

    client = Offline()
    with pytest.raises(ToolError, match="HTTPStatusError"):
        summarize([{"id": 1, "title": "one"}, {"id": 2, "title": "two"}], client)
    assert client.calls == 1


def test_history_json_error_split_and_later_bad_single_fails():
    import json

    class BadSecond:
        def chat(self, prompt, **kwargs):
            ids = [int(line.split(" ", 1)[0]) for line in prompt.splitlines() if line[:1].isdigit()]
            if len(ids) > 1:
                return "bad json"
            return json.dumps({"themes": [{"label": "good", "ids": [1]}]})

    with pytest.raises(ToolError, match="--mode list"):
        summarize([{"id": 1, "title": "one"}, {"id": 2, "title": "two"}], BadSecond())


def test_history_does_not_retry_connection_error_after_split():
    class OfflineAfterBad:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "not json"
            raise ToolError("本地模型请求失败（ConnectError）")

    client = OfflineAfterBad()
    with pytest.raises(ToolError, match="ConnectError"):
        summarize([{"id": 1, "title": "one"}, {"id": 2, "title": "two"}], client)
    assert client.calls == 2


def test_history_budget_exhaustion_does_not_return_partial_data():
    import json

    class BadSecondHalf:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt, **kwargs):
            self.calls += 1
            ids = [int(line.split(" ", 1)[0]) for line in prompt.splitlines() if line[:1].isdigit()]
            if ids == [1, 2, 3, 4]:
                return json.dumps({"themes": [{"label": "valid", "ids": ids}]})
            return json.dumps({"themes": [{"label": "bad", "ids": [999]}]})

    client = BadSecondHalf()
    with pytest.raises(ToolError, match="--mode list"):
        summarize([{"id": i, "title": "title"} for i in range(1, 9)], client)
    assert client.calls <= 7
