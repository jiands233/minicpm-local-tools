import argparse
import sys

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


def run_doctor(args):
    from .client import LocalClient

    client = LocalClient.from_env()
    failed = False
    for label, url, model in (
        ("文本", client.base_url, client.model),
        ("OCR", client.ocr_url, client.ocr_model),
        ("Embedding", client.embedding_url, client.embedding_model),
    ):
        try:
            data = client._request(url, "/models")
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
            ):
                raise ToolError("本地服务的模型列表格式无效；请检查服务地址和 API 兼容性。")
            names = [row["id"] for row in rows]
            present = model in names or any(n == model + ":latest" for n in names)
            print(f"{label}: {url} · {model} · {'可见' if present else '服务可达，模型名称未匹配'}")
            failed |= not present
        except ToolError as exc:
            print(f"{label}: {exc}")
            failed = True
    return int(failed)
