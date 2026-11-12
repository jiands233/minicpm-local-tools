"""Clipboard transforms with a native macOS compare-before-replace bridge."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .client import LocalClient
from .common import ToolError

ACTIONS = ("translate", "rewrite", "todos", "ocr", "image-todos")
PROMPTS = {
    "translate": (
        "You are a translation engine. Translate all user input into {language}, "
        "including greetings. Preserve meaning and do not add recipients or facts. "
        "Output only the translation."
    ),
    "rewrite": (
        "You are a careful copy editor. Make the input concise in its original language. "
        "Preserve ALL concrete information: who does what, to which destination, and by what time. "
        "Remove only filler words. Do not summarize or drop a destination. "
        "Output only the edited text."
    ),
    "todos": (
        "Extract only concrete future tasks explicitly stated in the source text. "
        "Omit discussions, completed actions, and tentative or unscheduled plans. "
        "Copy each task in its original language as a Markdown checkbox starting with - [ ]. "
        "Preserve original names and dates; never invent them. "
        "If there are no tasks, output 未发现明确待办. Output only the checklist."
    ),
}
MAX_TEXT = 24000


def bridge_path() -> Path:
    configured = os.environ.get("MINICPM_CLIPBOARD_BRIDGE")
    if configured:
        path = Path(configured).expanduser()
    else:
        root = Path(__file__).resolve().parents[2]
        path = root / "macos/.build/release/MiniCPMClipboard"
    if not path.is_file():
        raise ToolError("尚未构建原生剪贴板桥接器。请运行 ./script/build_and_run.sh --build-only。")
    return path


def bridge_call(*args: str, text: str | None = None) -> dict:
    try:
        result = subprocess.run(
            [str(bridge_path()), *args],
            input=text,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError("原生剪贴板桥接失败或超时。") from exc
    if result.returncode:
        raise ToolError(result.stderr.strip() or "无法访问剪贴板。")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ToolError("原生桥接器返回了无效数据。") from exc


def transform(text: str, action: str, client: LocalClient, language: str = "中文") -> str:
    if action not in PROMPTS:
        raise ToolError(f"不支持的文本动作：{action}")
    if not text.strip():
        raise ToolError("剪贴板或输入文本为空。")
    if len(text) > MAX_TEXT:
        raise ToolError(f"文本过长（上限 {MAX_TEXT} 字符）；请缩短后重试。")
    target_language = {"中文": "Chinese", "zh": "Chinese", "en": "English", "英文": "English"}.get(
        language, language
    )
    prompt = PROMPTS[action].format(language=target_language)
    result = client.chat(text, system=prompt, temperature=0.0).strip()
    if not result:
        raise ToolError("模型未返回内容，剪贴板未修改。")
    return result


def process_snapshot(
    snapshot: dict, action: str, client: LocalClient, language: str = "中文"
) -> str:
    if action in ("ocr", "image-todos"):
        encoded = snapshot.get("image_png")
        if not encoded:
            raise ToolError("剪贴板没有可识别图片，请先复制一张中英文截图。")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ToolError("剪贴板图片数据无效。") from exc
        # Temporary image is mode 0600, deleted even when inference fails.
        with tempfile.TemporaryDirectory(prefix="minicpm-clipboard-") as temp:
            path = Path(temp) / "clipboard.png"
            path.write_bytes(image_bytes)
            path.chmod(0o600)
            result = client.ocr(path).strip()
        if not result:
            raise ToolError("OCR 未返回文字，剪贴板未修改。")
        return transform(result, "todos", client, language) if action == "image-todos" else result
    return transform(snapshot.get("text", ""), action, client, language)


def run(args: argparse.Namespace) -> int:
    if args.apply and (args.text is not None or args.file or args.image or args.stdin):
        raise ToolError("--apply 只用于当前剪贴板；文件/文本输入请预览后自行复制。")
    client = LocalClient.from_env()
    snapshot = None
    if args.image:
        if args.action not in ("ocr", "image-todos"):
            raise ToolError("--image 需要 ocr 或 image-todos 动作。")
        path = Path(args.image).expanduser().resolve(strict=True)
        result = client.ocr(path).strip()
        if not result:
            raise ToolError("OCR 未返回文字。")
        if args.action == "image-todos":
            result = transform(result, "todos", client, args.language)
    elif args.text is not None or args.file or args.stdin:
        text = (
            args.text
            if args.text is not None
            else (
                Path(args.file).expanduser().read_text(encoding="utf-8")
                if args.file
                else sys.stdin.read(MAX_TEXT + 1)
            )
        )
        result = transform(text, args.action, client, args.language)
    else:
        snapshot = bridge_call(
            "--snapshot-image" if args.action in ("ocr", "image-todos") else "--snapshot-text"
        )
        result = process_snapshot(snapshot, args.action, client, args.language)
    if args.apply:
        assert snapshot is not None
        # Native bridge checks changeCount immediately before replacing.
        bridge_call("--replace", str(snapshot["change_count"]), text=result)
        print("处理完成，结果已写回剪贴板。")
    else:
        print(result)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("clipboard", help="剪贴板文本改写、翻译、待办或中英文 OCR")
    parser.add_argument("action", choices=ACTIONS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="直接处理文本，不读取剪贴板")
    source.add_argument("--file", help="读取 UTF-8 文本文件")
    source.add_argument("--stdin", action="store_true", help="从标准输入读取文本")
    source.add_argument("--image", help="识别图片文件，不读取剪贴板")
    parser.add_argument("--language", default="中文", help="翻译目标语言，默认中文")
    parser.add_argument("--apply", action="store_true", help="将结果写回当前剪贴板（默认只预览）")
    parser.set_defaults(func=run)
