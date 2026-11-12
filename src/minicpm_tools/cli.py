import argparse
import sys
from urllib.parse import urlsplit

from .common import ToolError


def main():
    parser = argparse.ArgumentParser(prog="mcpm", description="五个本地 AI 小工具 · 数据留在本机")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    sub = parser.add_subparsers(dest="tool", required=True)
    from . import audio, clipboard, history, search, shell

    for module in (clipboard, search, audio, history, shell):
        module.register(sub)
    doctor = sub.add_parser("doctor", help="检查本地服务与配置")
    doctor.set_defaults(func=run_doctor)
    args = parser.parse_args()
    try:
        return args.func(args) or 0
    except (ToolError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


def _doctor_address(url):
    """Show the local origin while hiding custom paths that may contain secrets."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if parts.path in {"", "/", "/v1"}:
        return origin + parts.path
    return origin + "/[路径已隐藏]"


def run_doctor(args):
    from .client import LocalClient

    config = LocalClient.env_options()
    failed = False
    for label, url, model in (
        ("文本", config["base_url"], config["model"]),
        ("OCR", config["ocr_url"] or config["base_url"], config["ocr_model"]),
        ("Embedding", config["embedding_url"] or config["base_url"], config["embedding_model"]),
    ):
        try:
            # Validate each service independently, retaining the same shared
            # timeout and local-only address rules as normal client requests.
            client = LocalClient(base_url=url, model=model, timeout=config["timeout"])
            url = client.base_url
            data = client._request(url, "/models")
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
            ):
                raise ToolError("本地服务的模型列表格式无效；请检查服务地址和 API 兼容性。")
            names = [row["id"] for row in rows]
            present = model in names or any(n == model + ":latest" for n in names)
            print(f"{label}: {_doctor_address(url)} · {model} · {'可见' if present else '服务可达，模型名称未匹配'}")
            failed |= not present
        except ToolError as exc:
            print(f"{label}: {exc}")
            failed = True
    return int(failed)
