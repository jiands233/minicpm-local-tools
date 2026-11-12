"""Daily browser history, queried from an isolated SQLite backup."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, unquote_plus, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .client import LocalClient
from .common import ToolError, parse_json, write_new

BACKUP_LOCK_TIMEOUT = 3.0
BACKUP_RETRY_INTERVAL = 0.1
# Reserve space for the instruction and response in small local models.
# A byte budget is conservative, not a replacement for a model tokenizer.
HISTORY_BATCH_BYTES = 3600
HISTORY_BATCH_ITEMS = 60

# Match whole path components (or separated words such as reset-password),
# rather than substrings: /authors and /authority are ordinary public pages.
SENSITIVE_PATH = re.compile(
    r"(?<![a-z0-9])(?:login|log[-_]?in|signin|sign[-_]?in|oauth2?|callback|"
    r"reset|password|token|checkout|payment|account|auth(?:entication|orize|orization)?)(?![a-z0-9])",
    re.IGNORECASE,
)
# Query values are stripped in the rendered URL, but explicit credential fields
# are still excluded from the report. Exact keys avoid misclassifying `author`.
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "auth",
        "authorization",
        "oauth",
        "oauth_token",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "reset_token",
        "password",
        "passwd",
        "pass",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "key",
        "code",
        "state",
    }
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?:^|[?&;\s])(?:access_token|refresh_token|id_token|api_key|apikey|"
    r"password|passwd|client_secret|token)\s*=",
    re.IGNORECASE,
)


def _decode_safely(value: str, *, plus: bool = False) -> str:
    """Decode bounded layers; fail closed when percent escapes keep changing."""
    decode = unquote_plus if plus else unquote
    for _ in range(4):
        next_value = decode(value, errors="strict")
        if next_value == value:
            return value
        value = next_value
    if decode(value, errors="strict") != value:
        raise ValueError("excessive URL encoding")
    return value


def _has_sensitive_query(query: str) -> bool:
    # Treat both separators as potentially meaningful, even though parse_qsl
    # normally accepts only '&'; the output never retains unknown parameters.
    fields = re.split(r"[&;]", query)
    if len(fields) > 100:
        raise ValueError("too many query fields")
    for field in fields:
        raw_key, _, raw_value = field.partition("=")
        key = _decode_safely(raw_key, plus=True).casefold()
        value = _decode_safely(raw_value, plus=True)
        normalized_key = re.sub(r"[^a-z0-9]", "", key)
        if (
            key in SENSITIVE_QUERY_KEYS
            or normalized_key
            in {
                "accesstoken",
                "refreshtoken",
                "idtoken",
                "clientsecret",
                "apikey",
                "authorizationcode",
            }
            or normalized_key.endswith("token")
            or SENSITIVE_PATH.search(key)
            or SENSITIVE_ASSIGNMENT.search(value)
        ):
            return True
    return False


def clean_url(raw):
    try:
        url = urlsplit(raw)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
        ):
            return None
        if SENSITIVE_PATH.search(_decode_safely(url.path)) or _has_sensitive_query(url.query):
            return None
        # Preserve only known public resource selectors. Unknown query fields and
        # fragments can contain credentials or private search text, so omit them.
        parameters = parse_qsl(url.query, keep_blank_values=True, max_num_fields=100)
        retained = []
        if (
            url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}
            and url.path == "/watch"
        ):
            retained = [
                (key, value)
                for key, value in parameters
                if key == "v" and re.fullmatch(r"[A-Za-z0-9_-]{11}", value)
            ][:1]
        elif url.hostname in {"bilibili.com", "www.bilibili.com"} and url.path.startswith(
            "/video/"
        ):
            retained = [
                (key, value)
                for key, value in parameters
                if key == "p" and re.fullmatch(r"[1-9][0-9]{0,4}", value)
            ][:1]
        return urlunsplit((url.scheme, url.netloc, url.path, urlencode(retained), ""))
    except ValueError:
        return None


class _HistoryLocked(ToolError):
    """SQLite backup could not acquire a read lock within the bounded wait."""


def _identity(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _sidecar_state(path: Path):
    """Only Chrome rollback-journal databases with an absent/zeroed journal are eligible."""
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(path) + suffix).lstat()
        except FileNotFoundError:
            continue
        raise ToolError("Chrome 历史库有 WAL/共享内存文件，不能安全复制；请关闭浏览器后重试。")
    journal = Path(str(path) + "-journal")
    try:
        entry = journal.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(entry.st_mode):
        raise ToolError("Chrome 日志不是普通文件，不能安全复制；请关闭浏览器后重试。")
    fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        header = os.read(fd, 8)
        non_hot = (opened.st_size == 0 and header == b"") or header == bytes(8)
        if _identity(entry) != _identity(opened) or not non_hot:
            raise ToolError("Chrome 日志处于活动状态或正在变化；请关闭浏览器后重试。")
        if _identity(os.fstat(fd)) != _identity(opened) or _identity(journal.lstat()) != _identity(
            opened
        ):
            raise ToolError("Chrome 日志正在变化；请稍后重试。")
        return _identity(opened)
    finally:
        os.close(fd)


def _copy_stable_chrome(path: Path, dest: Path):
    """Best-effort locked-DB copy; no WAL/hot journal or observable change permitted."""
    try:
        if Path(os.path.abspath(path)) != path.resolve(strict=True):
            raise ToolError("Chrome 历史库路径含符号链接；不能安全复制。")
        entry = path.lstat()
        if not stat.S_ISREG(entry.st_mode):
            raise ToolError("Chrome 历史库不是普通文件或是符号链接；不能安全复制。")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if _identity(entry) != _identity(before):
                raise ToolError("Chrome 历史库正在变化；请稍后重试。")
            header = os.read(fd, 100)
            if (
                len(header) < 100
                or header[:16] != b"SQLite format 3\x00"
                or header[18:20] != b"\x01\x01"
            ):
                raise ToolError("Chrome 历史库不是受支持的回滚日志格式；请关闭浏览器后重试。")
            sidecar = _sidecar_state(path)
            os.lseek(fd, 0, os.SEEK_SET)
            # dest belongs to a private TemporaryDirectory, created with mode 0600.
            out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(out, "wb") as writer, os.fdopen(os.dup(fd), "rb") as reader:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
            if (
                _identity(os.fstat(fd)) != _identity(before)
                or _identity(path.lstat()) != _identity(before)
                or _sidecar_state(path) != sidecar
            ):
                raise ToolError("Chrome 历史库或日志在复制期间发生变化；请稍后重试。")
            return (_identity(before), sidecar)
        finally:
            os.close(fd)
    except ToolError:
        raise
    except OSError as exc:
        raise ToolError("无法安全复制 Chrome 历史库；请检查权限或关闭浏览器后重试。") from exc


def _read_snapshot(target, browser, lower, upper, check_integrity=False):
    if check_integrity:
        result = target.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise ToolError("Chrome 历史快照完整性检查失败；请关闭浏览器后重试。")
    if browser == "chrome":
        query = """SELECT v.visit_time, u.title, u.url FROM visits v JOIN urls u ON u.id=v.url
                   WHERE v.visit_time >= ? AND v.visit_time < ? ORDER BY v.visit_time"""
    else:
        query = """SELECT v.visit_time, v.title, i.url FROM history_visits v
                   JOIN history_items i ON i.id=v.history_item
                   WHERE v.visit_time >= ? AND v.visit_time < ? ORDER BY v.visit_time"""
    rows = target.execute(query, (lower, upper)).fetchall()
    if check_integrity and target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ToolError("Chrome 历史快照完整性检查失败；请关闭浏览器后重试。")
    return rows


def read_history(
    path: Path,
    browser: str,
    day: dt.date,
    timezone: str,
    *,
    allow_approximate_snapshot: bool = False,
    snapshot_info: dict | None = None,
):
    zone = ZoneInfo(timezone)
    start = dt.datetime.combine(day, dt.time(), zone).timestamp()
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), zone).timestamp()
    epoch, scale = (11644473600, 1_000_000) if browser == "chrome" else (-978307200, 1)
    lower, upper = (start + epoch) * scale, (end + epoch) * scale
    if not path.is_file():
        raise ToolError(f"找不到历史库：{path}；可用 --database 指定 profile 路径。")
    with tempfile.TemporaryDirectory(prefix="mcpm-history-") as tmp:
        try:
            try:
                with (
                    closing(
                        sqlite3.connect(
                            path.resolve().as_uri() + "?mode=ro",
                            uri=True,
                            timeout=BACKUP_RETRY_INTERVAL,
                        )
                    ) as source,
                    closing(sqlite3.connect(str(Path(tmp) / "backup.sqlite"))) as target,
                ):
                    busy_since = None

                    def check_backup_progress(status, remaining, total):
                        nonlocal busy_since
                        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                            now = time.monotonic()
                            if busy_since is None:
                                busy_since = now
                            elif now - busy_since >= BACKUP_LOCK_TIMEOUT:
                                raise _HistoryLocked("浏览器历史数据库暂时被锁定；请稍后重试。")
                        else:
                            busy_since = None

                    source.backup(
                        target,
                        pages=128,
                        progress=check_backup_progress,
                        sleep=BACKUP_RETRY_INTERVAL,
                    )
                    rows = _read_snapshot(target, browser, lower, upper)
            except _HistoryLocked as exc:
                if browser != "chrome" or not allow_approximate_snapshot:
                    raise ToolError(
                        "浏览器历史数据库被锁定，无法生成一致快照；请关闭浏览器后重试。"
                        + (
                            " 如接受未提交内容风险，可显式指定 --allow-approximate-snapshot。"
                            if browser == "chrome"
                            else ""
                        )
                    ) from exc
                copy_path = Path(tmp) / "copy.sqlite"
                identity, sidecar = _copy_stable_chrome(path, copy_path)
                with closing(sqlite3.connect(copy_path.as_uri() + "?mode=ro", uri=True)) as target:
                    rows = _read_snapshot(target, browser, lower, upper, check_integrity=True)
                if _identity(path.lstat()) != identity or _sidecar_state(path) != sidecar:
                    raise ToolError("Chrome 历史库在快照验证期间发生变化；请稍后重试。")
                print(
                    "警告：已使用无锁近似快照，可能包含未提交内容；完整性检查不能保证事务一致。"
                    "需要一致结果请关闭浏览器后重试。",
                    file=sys.stderr,
                )
                if snapshot_info is not None:
                    snapshot_info["approximate"] = True
        except sqlite3.Error as exc:
            raise ToolError("历史数据库读取失败，请检查浏览器类型、访问权限和数据库结构。") from exc
    result = []
    seen = {}
    for timestamp, title, raw in rows:
        url = clean_url(raw)
        if not url:
            continue
        # Redaction must not collapse distinct resources. Only the digest stays
        # in memory; the original URL/query is never written to the report.
        identity = hashlib.sha256(raw.encode("utf-8")).digest()
        if identity in seen:
            seen[identity]["visits"] += 1
            continue
        entry = {
            "id": len(result) + 1,
            "time": dt.datetime.fromtimestamp(timestamp / scale - epoch, zone).strftime("%H:%M"),
            "title": str(title or urlsplit(url).hostname).replace("\n", " ")[:300],
            "url": url,
            "domain": urlsplit(url).hostname,
            "visits": 1,
            "link_redacted": urlsplit(raw).query != urlsplit(url).query
            or bool(urlsplit(raw).fragment),
        }
        seen[identity] = entry
        result.append(entry)
    return result


_UNSAFE_DISPLAY = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def escape(text):
    # Browser page titles and model labels can contain terminal escape sequences
    # or bidi controls. Keep their visible representation without interpreting it.
    text = text.replace("\r", " ").replace("\n", " ")
    text = _UNSAFE_DISPLAY.sub(lambda match: ascii(match.group())[1:-1], text)
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", text)


def history_batches(entries):
    """Preserve order while accounting for IDs and UTF-8 title bytes."""
    batch, size = [], 0
    for entry in entries:
        line = f"{entry['id']} {entry['title']}"
        line_bytes = len(line.encode("utf-8"))
        if line_bytes > HISTORY_BATCH_BYTES:
            raise ToolError("单条阅读记录过长，无法安全提交模型；请使用 --mode list。")
        extra = line_bytes + (1 if batch else 0)
        if batch and (len(batch) >= HISTORY_BATCH_ITEMS or size + extra > HISTORY_BATCH_BYTES):
            yield batch
            batch, size = [], 0
            extra = line_bytes
        batch.append(entry)
        size += extra
    if batch:
        yield batch


class InvalidHistorySummary(ToolError):
    """Model response fails the structure or complete-reference checks."""


def _validate_summary(response, batch):
    """Validate the entire response before releasing any group to the caller."""
    allowed = {entry["id"] for entry in batch}
    themes = response.get("themes")
    if not isinstance(themes, list) or not 1 <= len(themes) <= 6:
        raise InvalidHistorySummary("模型主题结构不合格。")
    groups, used = [], []
    for group in themes:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get("label"), str)
            or not group["label"].strip()
            or not isinstance(group.get("ids"), list)
        ):
            raise InvalidHistorySummary("模型主题结构不合格。")
        ids = group["ids"]
        if not ids or any(type(i) is not int or i not in allowed for i in ids):
            raise InvalidHistorySummary("模型引用了不存在的页面。")
        used.extend(ids)
        groups.append((group["label"].strip()[:80], ids))
    if set(used) != allowed or len(used) != len(set(used)):
        raise InvalidHistorySummary("模型主题遗漏或重复了记录。")
    return groups


# Total additional calls, not recursion depth. Each split costs two calls.
HISTORY_BATCH_RETRIES = 6


def _summarize_batch(batch, client, remaining):
    prompt = "\n".join(f"{e['id']} {e['title']}" for e in batch)
    # Transport/HTTP/service errors must propagate immediately; only an actual
    # returned but invalid model response is eligible for splitting.
    raw = client.chat(
        "请把下列记录分成最多6个主题。只返回JSON对象，themes是数组，每项label是主题名，"
        "ids是对应编号数组。所有记录编号必须出现。\n" + prompt
    )
    try:
        try:
            response = parse_json(raw)
        except ToolError as exc:
            raise InvalidHistorySummary("模型未返回有效 JSON。") from exc
        return _validate_summary(response, batch)
    except InvalidHistorySummary as exc:
        if len(batch) <= 1 or remaining[0] < 2:
            raise ToolError(f"{exc} 已停止重试，请使用 --mode list 导出原始列表。") from exc
        remaining[0] -= 2
        mid = len(batch) // 2
        # Evaluate both halves before returning; callers never receive partial groups.
        return _summarize_batch(batch[:mid], client, remaining) + _summarize_batch(
            batch[mid:], client, remaining
        )


def summarize(entries, client):
    """Model labels groups; all page URLs/text are rendered from original evidence."""
    groups = []
    for batch in history_batches(entries):
        groups.extend(_summarize_batch(batch, client, [HISTORY_BATCH_RETRIES]))
    return groups


def render(entries, day, zone, groups=None, *, approximate=False):
    lines = [
        f"# 阅读回顾 · {day}",
        "",
        f"时区：{zone}。仅依据本机访问记录的标题和域名，不代表读完或理解页面。",
        "仅保留已知站点的公开页面编号，其他 URL 查询参数和片段已隐藏；规则过滤不能保证消除所有敏感内容。",
        "",
    ]
    if approximate:
        lines += [
            "> ⚠️ 此结果来自无锁近似快照，可能包含未提交内容；完整性检查不能保证事务一致。",
            "",
        ]
    if groups:
        lines += ["## 主题（模型归类，请核对）", ""]
        for label, ids in groups:
            lines.append(f"- **{escape(label)}**：" + "、".join(f"记录 {i}" for i in ids))
        lines.append("")
    lines += ["## 页面记录", ""]
    if not entries:
        lines.append("当天没有符合筛选条件的访问记录。")
    for row in entries:
        safe_link = _UNSAFE_DISPLAY.sub(lambda match: quote(match.group(), safe=""), row["url"])
        safe_link = safe_link.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
        redaction = " · 链接参数已隐藏，可能无法回到原页面" if row.get("link_redacted") else ""
        lines.append(
            f"- {row['id']}. {row['time']} [{escape(row['title'])}]({safe_link}) · {escape(row['domain'])} · {row['visits']} 次访问{redaction}"
        )
    return "\n".join(lines) + "\n"


def run(args):
    try:
        zone = ZoneInfo(args.timezone)
    except KeyError as exc:
        raise ToolError("无效时区；例如 Asia/Shanghai。") from exc
    today = dt.datetime.now(zone).date()
    day = (
        today - dt.timedelta(days=1)
        if args.date == "yesterday"
        else today
        if args.date == "today"
        else dt.date.fromisoformat(args.date)
    )
    default = Path.home() / (
        "Library/Application Support/Google/Chrome/Default/History"
        if args.browser == "chrome"
        else "Library/Safari/History.db"
    )
    snapshot_info = {}
    entries = read_history(
        Path(args.database).expanduser() if args.database else default,
        args.browser,
        day,
        args.timezone,
        allow_approximate_snapshot=args.allow_approximate_snapshot,
        snapshot_info=snapshot_info,
    )
    groups = (
        summarize(entries, LocalClient.from_env()) if args.mode == "summary" and entries else None
    )
    result = render(
        entries, day, args.timezone, groups, approximate=snapshot_info.get("approximate", False)
    )
    if args.output_dir:
        print(write_new(Path(args.output_dir) / f"{day}-reading.md", result))
    else:
        print(result, end="")


def register(subparsers):
    parser = subparsers.add_parser("history", help="本地浏览历史每日回顾")
    parser.add_argument("--browser", choices=["chrome", "safari"], default="chrome")
    parser.add_argument("--database", help="自定义 History SQLite 路径（不会修改源文件）")
    parser.add_argument("--date", default="today", help="today / yesterday / YYYY-MM-DD")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--mode", choices=["list", "summary"], default="list")
    parser.add_argument("--output-dir", help="保存目录；省略时只预览")
    parser.add_argument(
        "--allow-approximate-snapshot",
        action="store_true",
        help="仅 Chrome 锁定时允许无锁近似复制，可能包含未提交内容；默认拒绝",
    )
    parser.set_defaults(func=run)
