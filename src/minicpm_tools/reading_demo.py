"""Synthetic Chrome history shared by the demonstration and acceptance checks."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

DAY = dt.date(2026, 11, 12)
ZONE = "Asia/Shanghai"
DEMO_ROWS = [
    ("Python 文件读取教程", "https://example.org/python/files?utm_source=demo"),
    ("Python 字典与列表", "https://example.org/python/collections"),
    ("Pandas 数据清洗入门", "https://example.org/python/pandas"),
    ("本地开发环境配置", "https://example.org/python/setup"),
    ("阳台种植薄荷", "https://example.com/garden/mint"),
    ("盆栽浇水指南", "https://example.com/garden/water"),
    ("如何播种番茄", "https://example.com/garden/tomato"),
    ("春季花园养护", "https://example.com/garden/spring"),
    ("京都公交出行指南", "https://example.net/travel/bus"),
    ("京都步行路线", "https://example.net/travel/walk"),
    ("旅行行李清单", "https://example.net/travel/packing"),
    ("京都博物馆参观信息", "https://example.net/travel/museum"),
    ("蓝鲸的生活习性", "https://example.org/ocean/whales"),
    ("海洋中的浮游生物", "https://example.org/ocean/plankton"),
    ("珊瑚礁生态简介", "https://example.org/ocean/coral"),
    ("海龟保护项目", "https://example.org/ocean/turtles"),
    ("首页", "https://example.com/"),
    ("首页", "https://example.net/"),
    ("登录账户", "https://example.org/login"),
]


def create_history(path: Path, rows=DEMO_ROWS):
    """Create a new synthetic database and return its open WAL connection."""
    # Callers provide a fresh path in their own private temporary directory.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            "CREATE TABLE urls(id INTEGER, title TEXT, url TEXT); "
            "CREATE TABLE visits(url INTEGER, visit_time INTEGER);"
        )
        start = dt.datetime(2026, 11, 12, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
        for number, (title, url) in enumerate(rows, 1):
            db.execute("INSERT INTO urls VALUES (?, ?, ?)", (number, title, url))
            db.execute("INSERT INTO visits VALUES (?, ?)",
                       (number, int((start + number * 1800 + 11644473600) * 1e6)))
        db.execute("INSERT INTO visits VALUES (?, ?)",
                   (1, int((start + 3601 + 11644473600) * 1e6)))
        db.commit()
        return db
    except BaseException:
        db.close()
        raise
