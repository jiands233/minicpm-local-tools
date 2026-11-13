#!/usr/bin/env python3
"""Opt-in thinking-parameter comparison with synthetic inputs and raw responses.

No downloads, registration, personal data, or changes to the production client.
Requires the pdf extra (Pillow) and a Chinese font for the OCR fixtures.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from minicpm_tools.client import LocalClient, local_url
from minicpm_tools.common import ToolError

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {
    "baseline": {},
    "template_only": {"chat_template_kwargs": {"enable_thinking": False}},
    "reasoning_only": {"reasoning_effort": "none"},
    "both": {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    },
}
TEXT = ('把以下虚构标题按主题分组，仅返回 JSON：'
        '{"themes":[{"label":"主题","ids":[1]}]}。每个编号恰好出现一次。\n'
        '1 Python 文件操作\n2 Python 异常处理\n3 阳台薄荷种植\n4 阳台浇水指南')
OCR_TEXTS = {
    "zh": "实验课程通知\n请在周五下午三点前提交报告。",
    "en": "Course notice\nPlease submit the report by Friday at 3 PM.",
}


def save_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def make_fixtures(directory, font_path):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(font_path), 32)
    fixtures = [{"name": "text", "kind": "text", "content": TEXT}]
    for language, source in OCR_TEXTS.items():
        image = Image.new("RGB", (1000, 200), "white")
        ImageDraw.Draw(image).multiline_text((30, 30), source, font=font, fill="black", spacing=15)
        path = directory / f"synthetic-ocr-{language}.png"
        with path.open("xb") as handle:
            image.save(handle, format="PNG")
        data = path.read_bytes()
        fixtures.append({
            "name": f"ocr-{language}", "kind": "ocr", "source": source,
            "image_file": path.name, "image_sha256": hashlib.sha256(data).hexdigest(),
            "content": [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(data).decode(),
                }},
                {"type": "text", "text": "Text Recognition:"},
            ],
        })
    return fixtures


def payload_for(fixture, model, variant):
    return {
        "model": model, "messages": [{"role": "user", "content": fixture["content"]}],
        "temperature": 0.0, "top_p": 0.95, "max_tokens": 2048, "stream": False,
        **VARIANTS[variant],
    }


def inspect_response(response):
    choice = response["choices"][0]
    message = choice["message"]
    if not isinstance(message, dict):
        raise TypeError("invalid message")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise TypeError("invalid content")
    reasoning = {k: v for k, v in message.items() if "reasoning" in k.lower()}
    if "thinking" in message:
        reasoning["thinking"] = message["thinking"]
    text = content or ""
    return {
        "think_marker": bool(re.search(r"</?think\b", text, re.IGNORECASE)),
        "reasoning_fields": list(reasoning),
        "reasoning_nonempty": any(bool(v) for v in reasoning.values()),
        "content_nonempty": bool(text.strip()),
        "finish_reason": choice.get("finish_reason"),
        "truncated": choice.get("finish_reason") == "length",
    }


def run_case(http, base, payload):
    # Validate at the request boundary, even if invoked separately from main().
    base = local_url(base)
    started = time.monotonic()
    result = {"status": "error", "request": payload}
    try:
        response = http.post(base + "/chat/completions", json=payload)
        result.update(http_status=response.status_code, raw_response=response.text)
        response.raise_for_status()
        result["observations"] = inspect_response(response.json())
        result["status"] = "ok"
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        # Raw synthetic response stays in the private report, never stdout.
        result["error_type"] = type(exc).__name__
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def metadata(http, base, model):
    parts = urlsplit(local_url(base))
    origin = f"{parts.scheme}://{parts.netloc}"
    result = {"model": model, "origin": origin}
    for route in ("version", "tags"):
        try:
            response = http.get(origin + "/api/" + route)
            response.raise_for_status()
            data = response.json()
            if route == "version":
                result["runtime_version"] = data["version"]
            else:
                names = {model, model if ":" in model else model + ":latest"}
                result["model_metadata"] = [
                    row for row in data["models"] if row.get("name") in names
                ]
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            result[route + "_error"] = type(exc).__name__
    return result


def provenance():
    result = {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        result["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        result["dirty"] = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip())
    except (OSError, subprocess.CalledProcessError):
        result["commit"] = "unknown"
    return result


def main(argv=None):
    env = LocalClient.env_options()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=env["base_url"])
    parser.add_argument("--ocr-url", default=env["ocr_url"])
    parser.add_argument("--model", default=env["model"])
    parser.add_argument("--ocr-model", default=env["ocr_model"])
    parser.add_argument("--timeout", type=float, default=env["timeout"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/acceptance")
    parser.add_argument("--font", type=Path,
                        default=Path("/System/Library/Fonts/STHeiti Medium.ttc"))
    args = parser.parse_args(argv)
    try:
        text_base = local_url(args.base_url)
        ocr_base = local_url(args.ocr_url or args.base_url)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ToolError("超时秒数必须为有限正数。")
        output = args.output_dir.expanduser().resolve()
        # Raw responses must remain in an ignored project-local directory.
        if not output.is_relative_to((ROOT / ".local").resolve()):
            raise ToolError("报告目录必须位于本项目 .local/ 内。")
    except ToolError as exc:
        parser.error(str(exc))
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="thinking-", dir=output))
    report = {
        "schema_version": 1, "input_kind": "synthetic only",
        "started_at": dt.datetime.now(dt.UTC).isoformat(), "provenance": provenance(),
        "complete": False, "cases": [],
        "limitations": [
            "One request per fixture and parameter variant; not an accuracy benchmark.",
            "Absence of visible reasoning does not prove a parameter was recognized.",
            "Does not test whole-machine offline use or private browser history.",
        ],
    }
    save_json(directory / "started.json", report)
    print(f"报告目录：{directory}", flush=True)
    exit_code = 1
    try:
        fixtures = make_fixtures(directory, args.font)
        save_json(directory / "fixtures.json", fixtures)
        # Do not use LocalClient.chat(), which strips thinking text.
        with httpx.Client(timeout=args.timeout, trust_env=False, follow_redirects=False) as http:
            report["services"] = {
                "text": metadata(http, text_base, args.model),
                "ocr": metadata(http, ocr_base, args.ocr_model),
            }
            for fixture in fixtures:
                base = text_base if fixture["kind"] == "text" else ocr_base
                model = args.model if fixture["kind"] == "text" else args.ocr_model
                for variant in VARIANTS:
                    name = f"{fixture['name']}-{variant}"
                    print(f"Checking {name}…", flush=True)
                    case = run_case(http, base, payload_for(fixture, model, variant))
                    case.update(fixture=fixture["name"], variant=variant)
                    save_json(directory / f"{name}.json", case)
                    report["cases"].append(case)
                    print(f"  {case['status']} ({case['seconds']}s)", flush=True)
        report["complete"] = True
        exit_code = int(any(
            c["status"] != "ok" or c["observations"]["truncated"]
            or not c["observations"]["content_nonempty"] for c in report["cases"]
        ))
    except KeyboardInterrupt:
        report["error_type"] = "KeyboardInterrupt"
        exit_code = 130
    except (OSError, ImportError, ValueError) as exc:
        report["error_type"] = type(exc).__name__
        print("无法完成对照，请检查 Pillow、字体和本地输出目录。", flush=True)
    finally:
        report["exit_code"] = exit_code
        report["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
        save_json(directory / "report.json", report)
    print(f"结果：{directory / 'report.json'}（退出码 {exit_code}）", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
