"""Daily browser history, queried from an isolated SQLite backup."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .client import LocalClient
from .common import ToolError, parse_json, write_new

BACKUP_LOCK_TIMEOUT = 3.0
BACKUP_RETRY_INTERVAL = 0.1
# Reserve space for the instruction and response in small local models.
# A byte budget is conservative, not a replacement for a model tokenizer.
HISTORY_BATCH_BYTES = 3600
HISTORY_BATCH_ITEMS = 60

SENSITIVE = re.compile(
    r"login|signin|sign-in|oauth|callback|reset|password|token|checkout|payment|account|auth",
    re.IGNORECASE,
)


def clean_url(raw):
    try:
        url = urlsplit(raw)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        if SENSITIVE.search(url.path) or SENSITIVE.search(url.query):
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


def read_history(path: Path, browser: str, day: dt.date, timezone: str):
    zone = ZoneInfo(timezone)
    start = dt.datetime.combine(day, dt.time(), zone).timestamp()
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), zone).timestamp()
    epoch, scale = (11644473600, 1_000_000) if browser == "chrome" else (-978307200, 1)
    lower, upper = (start + epoch) * scale, (end + epoch) * scale
    if not path.is_file():
        raise ToolError(f"找不到历史库：{path}；可用 --database 指定 profile 路径。")
    with tempfile.TemporaryDirectory(prefix="mcpm-history-") as tmp:
        # SQLite backup API includes committed WAL data, without an unsafe bare file copy.
        try:
            with (
                closing(
                    sqlite3.connect(
                        path.resolve().as_uri() + "?mode=ro",
                        uri=True,
                        timeout=BACKUP_RETRY_INTERVAL,
                    )
                ) as source,
                closing(sqlite3.connect(str(Path(tmp) / "snapshot.sqlite"))) as target,
            ):
                busy_since = None

                def check_backup_progress(status, remaining, total):
                    nonlocal busy_since
                    if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        now = time.monotonic()
                        if busy_since is None:
                            busy_since = now
                        elif now - busy_since >= BACKUP_LOCK_TIMEOUT:
                            raise ToolError("浏览器历史数据库暂时被锁定；请稍后重试。")
                    else:
                        busy_since = None

                source.backup(
                    target, pages=128, progress=check_backup_progress, sleep=BACKUP_RETRY_INTERVAL
                )
                if browser == "chrome":
                    query = """SELECT v.visit_time, u.title, u.url FROM visits v JOIN urls u ON u.id=v.url
                               WHERE v.visit_time >= ? AND v.visit_time < ? ORDER BY v.visit_time"""
                else:
                    query = """SELECT v.visit_time, v.title, i.url FROM history_visits v
                               JOIN history_items i ON i.id=v.history_item
                               WHERE v.visit_time >= ? AND v.visit_time < ? ORDER BY v.visit_time"""
                rows = target.execute(query, (lower, upper)).fetchall()
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


def escape(text):
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", text).replace("\r", " ").replace("\n", " ")


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


def render(entries, day, zone, groups=None):
    lines = [
        f"# 阅读回顾 · {day}",
        "",
        f"时区：{zone}。仅依据本机访问记录的标题和域名，不代表读完或理解页面。",
        "仅保留已知站点的公开页面编号，其他 URL 查询参数和片段已隐藏；规则过滤不能保证消除所有敏感内容。",
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
        safe_link = row["url"].replace("(", "%28").replace(")", "%29").replace(" ", "%20")
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
    entries = read_history(
        Path(args.database).expanduser() if args.database else default,
        args.browser,
        day,
        args.timezone,
    )
    groups = (
        summarize(entries, LocalClient.from_env()) if args.mode == "summary" and entries else None
    )
    result = render(entries, day, args.timezone, groups)
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
    parser.set_defaults(func=run)
