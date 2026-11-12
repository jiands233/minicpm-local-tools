#!/usr/bin/env python3
"""Diagnose action extraction on a fixed set of fictional utterances.

This is a small editorially labelled diagnostic, not an accuracy benchmark or
real audio evaluation. No user recordings, clipboard or history are read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from minicpm_tools.audio import Segment, source_phrases, summarize
from minicpm_tools.client import LocalClient
from minicpm_tools.common import ToolError, write_new

FIXTURE = Path(__file__).resolve().parents[1] / "examples/audio-action-eval.json"


class ActionPromptOverride:
    """Replace only the second model call of a single one-chunk summary."""

    def __init__(self, client, prompt):
        self.client = client
        self.prompt = prompt
        self.calls = 0
        self.responses = []

    def chat(self, prompt, **kwargs):
        self.calls += 1
        if self.calls == 2 and self.prompt is not None:
            marker = "资料：\n"
            if marker not in prompt:
                raise ToolError("无法定位待办请求中的资料，未发送替换提示词。")
            prompt = self.prompt.rstrip() + "\n" + marker + prompt.split(marker, 1)[1]
        if self.calls > 2:
            raise ToolError("评估批次超过一个摘要块，不能安全替换待办提示词。")
        response = self.client.chat(prompt, **kwargs)
        self.responses.append(response)
        return response


def scores(rows):
    counts = Counter()
    for row in rows:
        key = ("true_" if row["selected"] == row["expected_task"] else "false_")
        key += "positive" if row["selected"] else "negative"
        counts[key] += 1
    tp, fp = counts["true_positive"], counts["false_positive"]
    tn, fn = counts["true_negative"], counts["false_negative"]
    return {
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 3) if fp + tn else None,
    }


def owner_scores(rows):
    counts = Counter()
    for row in rows:
        if not row["selected"] or not row["expected_task"]:
            continue
        expected, actual = row["expected_owner"], row["predicted_owner"]
        if expected is None:
            counts["correct_unknown" if actual is None else "wrong_owner"] += 1
        elif actual == expected:
            counts["correct_owner"] += 1
        elif actual is None:
            counts["missed_owner"] += 1
        else:
            counts["wrong_owner"] += 1
    return {key: counts[key] for key in ("correct_owner", "wrong_owner", "missed_owner", "correct_unknown")}


def evaluate(client, fixture, prompt=None):
    if not isinstance(fixture.get("batches"), list):
        raise ToolError("评估集缺少 batches。")
    batches, all_rows, failures = [], [], []
    seen_names = set()
    for batch in fixture["batches"]:
        name, cases = batch["name"], batch["cases"]
        if name in seen_names or not cases:
            raise ToolError("评估批次名称重复或批次为空。")
        seen_names.add(name)
        segments = [Segment(float(i), float(i) + 0.5, case["text"]) for i, case in enumerate(cases)]
        for segment in segments:
            phrases = source_phrases([segment])
            if len(phrases) != 1 or phrases[0].text != segment.text:
                raise ToolError("每个样本必须恰好形成一个原文片段。")
        wrapper = ActionPromptOverride(client, prompt)
        try:
            notes = summarize(segments, wrapper)
        except ToolError as exc:
            # Never score a failed batch as all-negative.
            failures.append({
                "batch": name, "error": str(exc), "unscored_cases": len(cases),
                "model_responses": wrapper.responses,
            })
            continue
        if wrapper.calls != 2:
            raise ToolError("评估批次的模型调用数异常。")
        selected = Counter(int(action["start"]) for action in notes["actions"])
        owners = {}
        for action in notes["actions"]:
            owner = action.get("owner")
            owners.setdefault(int(action["start"]), owner if owner and owner != "未提及" else None)
        if any(i < 0 or i >= len(cases) for i in selected):
            raise ToolError("模型返回了无法映射到评估样本的时间戳。")
        rows = [{
            "batch": name, "text": case["text"], "kind": case["kind"],
            "expected_task": case["task"], "expected_owner": case["owner"],
            "selected": bool(selected[i]), "action_count": selected[i], "predicted_owner": owners.get(i),
        } for i, case in enumerate(cases)]
        batches.append({"name": name, "scores": scores(rows), "model_responses": wrapper.responses})
        all_rows.extend(rows)
    return {
        "model": client.model,
        "input_kind": "fictional handwritten utterances; not recordings or a representative benchmark",
        "label_definition": fixture.get("description"),
        "prompt": "custom action prompt" if prompt is not None else "production action prompt",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
        "total_cases": sum(len(batch["cases"]) for batch in fixture["batches"]),
        "scored_cases": len(all_rows), "failed_batches": failures,
        "scores": scores(all_rows), "owner_scores_for_selected_tasks": owner_scores(all_rows),
        "batches": batches, "cases": all_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="新建结果文件，不覆盖现有文件")
    parser.add_argument("--action-prompt-file", help="只供实验的待办提示词文本文件，不含资料")
    args = parser.parse_args()
    prompt = Path(args.action_prompt_file).read_text(encoding="utf-8") if args.action_prompt_file else None
    if prompt is not None and (not prompt.strip() or "资料：\n" in prompt):
        parser.error("待办提示词不能为空，也不能包含资料分隔符。")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate(LocalClient.from_env(), fixture, prompt)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        print(write_new(Path(args.output), encoded))
    else:
        print(encoded, end="")
    return 1 if result["failed_batches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
