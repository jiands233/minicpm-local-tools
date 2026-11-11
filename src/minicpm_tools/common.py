from __future__ import annotations

import json
import os
from pathlib import Path


class ToolError(Exception):
    """An actionable user-facing error."""


def write_new(path: Path, text: str) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ToolError(f"文件已存在，拒绝覆盖：{path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    return path


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ToolError("模型没有返回有效 JSON；未执行任何命令。请重试。") from exc
    if not isinstance(value, dict):
        raise ToolError("模型结果必须是 JSON 对象。")
    return value
