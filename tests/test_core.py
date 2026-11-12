import datetime as dt
import sqlite3
from pathlib import Path

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
    if not any((directory / "ls").is_file() for directory in (Path("/usr/bin"), Path("/bin"))):
        pytest.skip("no ls binary at the trusted system paths")
    argv = execution_argv("ls -lh .")
    binary = Path(argv[0])
    assert binary.is_absolute()
    assert binary.parent in {Path("/usr/bin"), Path("/bin")}
    assert binary.name == "ls" and binary.is_file()
    assert argv[1:] == ["-lh", "."]


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


@pytest.mark.parametrize("browser", ["chrome", "safari"])
def test_fall_back_day_disambiguates_repeated_hour_and_includes_full_day(tmp_path, browser):
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    day = dt.date(2026, 11, 1)
    start = dt.datetime(2026, 11, 1, tzinfo=zone)
    moments = [
        start,
        dt.datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
        dt.datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1),
        dt.datetime(2026, 11, 1, 23, 59, tzinfo=zone),
        dt.datetime(2026, 11, 2, tzinfo=zone),
    ]
    path = tmp_path / "History"
    with sqlite3.connect(path) as db:
        if browser == "chrome":
            db.executescript("CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); CREATE TABLE visits(url INTEGER,visit_time INTEGER);")
        else:
            db.executescript("CREATE TABLE history_items(id INTEGER,url TEXT); CREATE TABLE history_visits(history_item INTEGER,title TEXT,visit_time REAL);")
        for number, moment in enumerate(moments, 1):
            url = f"https://example.com/{number}"
            if browser == "chrome":
                db.execute("INSERT INTO urls VALUES(?,?,?)", (number, str(number), url))
                db.execute("INSERT INTO visits VALUES(?,?)", (number, int((moment.timestamp() + 11644473600) * 1_000_000)))
            else:
                db.execute("INSERT INTO history_items VALUES(?,?)", (number, url))
                db.execute("INSERT INTO history_visits VALUES(?,?,?)", (number, str(number), moment.timestamp() - 978307200))
    records = read_history(path, browser, day, "America/New_York")
    assert [record["time"] for record in records] == ["00:00", "01:30 -0400", "01:30 -0500", "23:59"]


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


def test_history_escapes_terminal_controls_in_title_url_and_model_label(tmp_path):
    from minicpm_tools.history import render

    path = tmp_path / "History"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); "
            "CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
        )
        moment = int((dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC).timestamp() + 11644473600) * 1e6)
        db.execute(
            "INSERT INTO urls VALUES(1,?,?)",
            ("Page\x1b]52;c;payload\x07\u202e", "https://example.com/\x1b[0m/\u202e"),
        )
        db.execute("INSERT INTO visits VALUES(1,?)", (moment,))
    records = read_history(path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
    report = render(records, "2026-11-12", "Asia/Shanghai", [("Topic\x1b[0m\u202e", [1])])
    assert "\x1b" not in report and "\x07" not in report and "\u202e" not in report
    assert r"\x1b" in report and r"\x07" in report and r"\u202e" in report
    assert "%1B" in report and "%E2%80%AE" in report
    assert "https://example.com/" in report


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
            read_history(path, "safari", dt.date(2026, 11, 12), "Asia/Shanghai")
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


def test_history_summary_includes_domain_without_url_and_budgets_exact_request():
    import json

    from minicpm_tools.history import HISTORY_BATCH_BYTES, _history_prompt_line, history_batches

    records = [
        {
            "id": i,
            "title": "首页" + "测" * 288,
            "domain": f"site{i}." + "a" * 190 + ".example",
            "url": f"https://site{i}.example/private?secret=private-value-{i}",
        }
        for i in range(1, 5)
    ]
    batches = list(history_batches(records))
    assert len(batches) == 2
    for batch in batches:
        serialized = "\n".join(_history_prompt_line(record) for record in batch)
        assert len(serialized.encode("utf-8")) <= HISTORY_BATCH_BYTES

    class Capture:
        def __init__(self):
            self.prompts = []

        def chat(self, prompt, **kwargs):
            self.prompts.append(prompt)
            lines = [line for line in prompt.splitlines() if line[:1].isdigit()]
            ids = [int(line.split(" ", 1)[0]) for line in lines]
            return json.dumps({"themes": [{"label": "合成站点", "ids": ids}]})

    client = Capture()
    groups = summarize(records, client)
    assert [i for _, ids in groups for i in ids] == [1, 2, 3, 4]
    prompts = "\n".join(client.prompts)
    assert all(record["domain"] in prompts for record in records)
    assert "private-value" not in prompts and "/private?" not in prompts


def test_history_prompt_escapes_title_controls_so_they_cannot_add_record_lines():
    from minicpm_tools.history import _history_prompt_line

    line = _history_prompt_line({"id": 1, "title": "首页\r\n2 伪造\u20283 伪造", "domain": "site.example"})
    assert "\r" not in line and "\n" not in line
    assert "\u2028" not in line and line == "1 首页  2 伪造 3 伪造（域名：site.example）"


def test_history_summary_gets_filtered_hostname_not_url_or_port(tmp_path):
    import json

    path = tmp_path / "History"
    day = dt.date(2026, 11, 12)
    timestamp = (dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC).timestamp() + 11644473600) * 1_000_000
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); "
            "CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
        )
        db.execute("INSERT INTO urls VALUES(1,?,?)", ("首页", "https://example.org:8443/path?query=private"))
        db.execute("INSERT INTO urls VALUES(2,?,?)", ("private", "https://user:password@example.org/path"))
        db.executemany("INSERT INTO visits VALUES(?,?)", [(1, timestamp), (2, timestamp)])
    entries = read_history(path, "chrome", day, "UTC")
    assert len(entries) == 1

    class Capture:
        def chat(self, prompt, **kwargs):
            assert "example.org" in prompt
            assert all(secret not in prompt for secret in ("8443", "/path", "query", "private", "password"))
            return json.dumps({"themes": [{"label": "合成站点", "ids": [1]}]})

    assert summarize(entries, Capture()) == [("合成站点", [1])]


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


def _chrome_locked_fixture(path):
    """Committed synthetic fixture with a held exclusive lock and a zeroed rollback journal."""
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=PERSIST")
    db.executescript(
        "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
    )
    timestamp = dt.datetime(2026, 11, 12, 8, tzinfo=dt.UTC).timestamp()
    db.execute(
        "INSERT INTO urls VALUES(1,?,?)", ("Committed fixture", "https://example.com/article")
    )
    db.execute("INSERT INTO visits VALUES(1,?)", (int((timestamp + 11644473600) * 1e6),))
    db.commit()
    db.execute("BEGIN EXCLUSIVE")
    db.execute("UPDATE urls SET title = 'Uncommitted fixture' WHERE id = 1")
    return db


def test_locked_chrome_with_zeroed_journal_preserves_committed_fixture(tmp_path, monkeypatch):
    from minicpm_tools import history

    path = tmp_path / "History"
    db = _chrome_locked_fixture(path)
    try:
        journal = tmp_path / "History-journal"
        assert journal.read_bytes()[:8] == bytes(8)
        before = path.read_bytes()
        monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
        records = read_history(
            path, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai", allow_approximate_snapshot=True
        )
        assert [row["title"] for row in records] == ["Committed fixture"]
        assert path.read_bytes() == before
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_chrome_locked_snapshot_rejects_unsafe_sidecars(tmp_path, sidecar):
    from minicpm_tools.history import _copy_stable_chrome

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE fixture (a TEXT)")
    db.close()
    other = path.with_name(path.name + sidecar)
    payload = b"\x01\x02\x03\x04\x05\x06\x07\x08" if sidecar == "-journal" else b"live"
    other.write_bytes(payload)
    before = path.read_bytes()
    with pytest.raises(ToolError):
        _copy_stable_chrome(path, tmp_path / "copy.sqlite")
    assert other.read_bytes() == payload
    assert path.read_bytes() == before
    assert not (tmp_path / "copy.sqlite").exists()


def test_chrome_locked_snapshot_rejects_source_symlinks(tmp_path):
    from minicpm_tools.history import _copy_stable_chrome

    target = tmp_path / "original"
    sqlite3.connect(target).close()
    link = tmp_path / "History"
    link.symlink_to(target)
    with pytest.raises(ToolError, match="符号链接"):
        _copy_stable_chrome(link, tmp_path / "copy.sqlite")


def test_chrome_locked_snapshot_rejects_changes_during_copy(tmp_path, monkeypatch):
    from minicpm_tools import history

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE fixture(a TEXT)")
    db.close()
    real_copy = history.shutil.copyfileobj

    def copy_then_modify(reader, writer, length):
        real_copy(reader, writer, length)
        with path.open("ab") as dest:
            dest.write(b"synthetic change")

    monkeypatch.setattr(history.shutil, "copyfileobj", copy_then_modify)
    with pytest.raises(ToolError, match="变化"):
        history._copy_stable_chrome(path, tmp_path / "copy.sqlite")


def test_empty_chrome_journal_is_a_permitted_non_hot_state(tmp_path):
    from minicpm_tools.history import _copy_stable_chrome

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE fixture(a TEXT)")
    db.close()
    (tmp_path / "History-journal").write_bytes(b"")
    copy = tmp_path / "copy.sqlite"
    _copy_stable_chrome(path, copy)
    assert copy.read_bytes() == path.read_bytes()
    assert copy.stat().st_mode & 0o777 == 0o600


def test_locked_copy_checks_source_again_after_integrity(tmp_path, monkeypatch):
    from minicpm_tools import history

    path = tmp_path / "History"
    db = _chrome_locked_fixture(path)
    original = history._read_snapshot

    def query_then_change(target, browser, lower, upper, check_integrity=False):
        result = original(target, browser, lower, upper, check_integrity)
        if check_integrity:
            with path.open("ab") as output:
                output.write(b"synthetic concurrent change")
        return result

    monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
    monkeypatch.setattr(history, "_read_snapshot", query_then_change)
    try:
        with pytest.raises(ToolError, match="验证期间发生变化"):
            read_history(
                path,
                "chrome",
                dt.date(2026, 11, 12),
                "Asia/Shanghai",
                allow_approximate_snapshot=True,
            )
    finally:
        db.rollback()
        db.close()


def test_locked_copy_integrity_check_twice():
    from minicpm_tools.history import _read_snapshot

    class FakeTarget:
        def __init__(self):
            self.checks = 0

        def execute(self, query, params=()):
            if "integrity_check" in query:
                self.checks += 1
                rows = [("ok",)] if self.checks == 1 else [("synthetic damage",)]
            else:
                rows = []

            class Result:
                def fetchall(self):
                    return rows

            return Result()

    target = FakeTarget()
    with pytest.raises(ToolError, match="完整性检查失败"):
        _read_snapshot(target, "chrome", 0, 1, check_integrity=True)
    assert target.checks == 2


@pytest.mark.parametrize("sync", ["OFF", "NORMAL", "FULL"])
def test_chrome_copy_rejects_uncommitted_spilled_pages(tmp_path, sync):
    """SQLite can flush dirty pages before commit; the active journal forbids copying."""
    from minicpm_tools.history import _copy_stable_chrome

    path = tmp_path / "History"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=PERSIST")
    db.execute("PRAGMA cache_size=3")
    db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, val TEXT)")
    db.executemany("INSERT INTO t(val) VALUES (?)", [(("old" + str(i)) * 500,) for i in range(200)])
    db.commit()
    db.execute(f"PRAGMA synchronous={sync}")
    db.execute("BEGIN EXCLUSIVE")
    db.execute("UPDATE t SET val=REPLACE(val,'old','new')")
    try:
        # Database pages have spilled but the transaction is not committed.
        assert (tmp_path / "History-journal").read_bytes()[:8] != bytes(8)
        with pytest.raises(ToolError, match="日志处于活动状态"):
            _copy_stable_chrome(path, tmp_path / "copy.sqlite")
        assert not (tmp_path / "copy.sqlite").exists()
    finally:
        db.rollback()
        db.close()


def test_chrome_locked_snapshot_rejects_symlinked_parent(tmp_path):
    from minicpm_tools.history import _copy_stable_chrome

    real = tmp_path / "real"
    real.mkdir()
    target = real / "History"
    db = sqlite3.connect(target)
    db.execute("CREATE TABLE fixture(a TEXT)")
    db.close()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ToolError, match="符号链接"):
        _copy_stable_chrome(link / "History", tmp_path / "copy.sqlite")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org/authors/alice", "https://example.org/authors/alice"),
        ("https://example.org/authority/report", "https://example.org/authority/report"),
        ("https://example.org/article?author=alice", "https://example.org/article"),
        ("https://example.org/article?%61uthor=alice&author=bob", "https://example.org/article"),
        ("https://example.org/tokenization/guide", "https://example.org/tokenization/guide"),
        ("https://example.org/oauth/authorize", None),
        ("https://example.org/auth/login", None),
        ("https://example.org/reset-password", None),
        ("https://example.org/%74oken/details", None),
        ("https://example.org/%2561uth/%256cogin", None),
        ("https://example.org/AuTh/Login", None),
        ("https://example.org/article?access_token=secret", None),
        ("https://example.org/article?author=a&%74oken=secret", None),
        ("https://example.org/article?author=a;%2574oken=secret", None),
        ("https://example.org/article?author=a&Access-Token=secret", None),
        ("https://example.org/article?author=a&session=secret", "https://example.org/article"),
        ("https://example.org/article?redirect=access_token%3Dsecret", None),
        ("https://example.org/%252525252574oken/details", None),
        ("https://@example.org/article", None),
    ],
)
def test_history_url_filter_handles_boundaries_and_encoding(url, expected):
    assert clean_url(url) == expected


def test_history_author_pages_are_retained_while_credentials_are_filtered(tmp_path):
    from minicpm_tools.history import render

    database = tmp_path / "History"
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); "
            "CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
        )
        moment = int((dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC).timestamp() + 11644473600) * 1e6)
        fixtures = [
            ("Author page", "https://example.org/authors/alice"),
            ("Public article", "https://example.org/article?author=alice&session=private"),
            ("Credential page", "https://example.org/article?%74oken=secret"),
            ("Authentication", "https://example.org/oauth/authorize"),
        ]
        for number, (title, url) in enumerate(fixtures, 1):
            db.execute("INSERT INTO urls VALUES(?,?,?)", (number, title, url))
            db.execute("INSERT INTO visits VALUES(?,?)", (number, moment))
    records = read_history(database, "chrome", dt.date(2026, 11, 12), "Asia/Shanghai")
    assert [entry["title"] for entry in records] == ["Author page", "Public article"]
    output = render(records, dt.date(2026, 11, 12), "Asia/Shanghai")
    assert "https://example.org/authors/alice" in output
    assert "https://example.org/article" in output
    assert "session=private" not in output and "token=secret" not in output
    assert "链接参数已隐藏" in output


def _journal_off_spilled_history(path, *, stale_journal):
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA journal_mode=OFF").fetchone()[0].lower() == "off"
    db.execute("PRAGMA cache_size=3")
    db.executescript(
        "CREATE TABLE urls(id INTEGER,title TEXT,url TEXT); CREATE TABLE visits(url INTEGER,visit_time INTEGER);"
    )
    timestamp = int((dt.datetime(2026, 11, 12, 8, tzinfo=dt.UTC).timestamp() + 11644473600) * 1e6)
    db.executemany(
        "INSERT INTO urls VALUES(?,?,?)",
        [(i, "committed" * 180, f"https://example.com/{i}") for i in range(1, 201)],
    )
    db.executemany("INSERT INTO visits VALUES(?,?)", [(i, timestamp) for i in range(1, 201)])
    db.commit()
    db.execute("BEGIN EXCLUSIVE")
    db.execute("UPDATE urls SET title=replace(title,'committed','uncommitted')")
    if stale_journal:
        Path(str(path) + "-journal").write_bytes(bytes(8))
    return db


@pytest.mark.parametrize("stale_journal", [False, True])
def test_locked_chrome_default_rejects_journal_off_spilled_pages_without_model(
    tmp_path, monkeypatch, stale_journal
):
    from argparse import Namespace

    from minicpm_tools import history

    path = tmp_path / "History"
    db = _journal_off_spilled_history(path, stale_journal=stale_journal)
    monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
    monkeypatch.setattr(
        history.LocalClient, "from_env", lambda: pytest.fail("model must not be called")
    )
    args = Namespace(
        timezone="Asia/Shanghai",
        date="2026-11-12",
        database=str(path),
        browser="chrome",
        mode="summary",
        output_dir=str(tmp_path / "output"),
        allow_approximate_snapshot=False,
    )
    try:
        with pytest.raises(ToolError, match="被锁定.*一致快照"):
            history.run(args)
        assert not (tmp_path / "output").exists()
    finally:
        db.close()


@pytest.mark.parametrize("stale_journal", [False, True])
def test_approximate_snapshot_warns_and_labels_possible_uncommitted_content(
    tmp_path, monkeypatch, capsys, stale_journal
):
    from minicpm_tools import history

    path = tmp_path / "History"
    db = _journal_off_spilled_history(path, stale_journal=stale_journal)
    monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
    info = {}
    try:
        entries = read_history(
            path,
            "chrome",
            dt.date(2026, 11, 12),
            "Asia/Shanghai",
            allow_approximate_snapshot=True,
            snapshot_info=info,
        )
        assert any("uncommitted" in row["title"] for row in entries), (
            "fixture must demonstrate spilled uncommitted content"
        )
        assert info == {"approximate": True}
        assert "可能包含未提交内容" in capsys.readouterr().err
        markdown = history.render(
            entries, dt.date(2026, 11, 12), "Asia/Shanghai", approximate=info["approximate"]
        )
        assert "可能包含未提交内容" in markdown
    finally:
        db.close()


def test_safari_rejects_locked_database_even_with_approximate_opt_in(tmp_path, monkeypatch):
    from minicpm_tools import history

    path = tmp_path / "History.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE fixture(id INTEGER)")
    db.execute("BEGIN EXCLUSIVE")
    monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
    try:
        with pytest.raises(ToolError, match="被锁定.*一致快照"):
            read_history(
                path,
                "safari",
                dt.date(2026, 11, 12),
                "Asia/Shanghai",
                allow_approximate_snapshot=True,
            )
    finally:
        db.close()


def test_cli_approximate_output_is_labeled(tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    from minicpm_tools import history

    path = tmp_path / "History"
    db = _journal_off_spilled_history(path, stale_journal=False)
    monkeypatch.setattr(history, "BACKUP_LOCK_TIMEOUT", 0.15)
    args = Namespace(
        timezone="Asia/Shanghai",
        date="2026-11-12",
        database=str(path),
        browser="chrome",
        mode="list",
        output_dir=str(tmp_path / "notes"),
        allow_approximate_snapshot=True,
    )
    try:
        history.run(args)
        output = (tmp_path / "notes/2026-11-12-reading.md").read_text()
        assert "可能包含未提交内容" in output
        assert "可能包含未提交内容" in capsys.readouterr().err
    finally:
        db.close()
