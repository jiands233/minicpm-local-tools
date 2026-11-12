"""Evaluation must separate role errors from missed or wrongly selected tasks."""

import importlib.util
from pathlib import Path

from minicpm_tools.common import ToolError

SPEC = importlib.util.spec_from_file_location(
    "evaluate_audio_owners", Path(__file__).parents[1] / "script/evaluate_audio_owners.py"
)
owner_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(owner_eval)


def test_owner_metrics_only_count_selected_ground_truth_tasks(monkeypatch):
    cases = [
        {"text": "小王向小李发报告。", "owner": "小王", "task": True},
        {"text": "向小赵发送报告。", "owner": None, "task": True},
        {"text": "小张需要复核结果。", "owner": "小张", "task": True},
        {"text": "小陈昨天已经完成报告。", "owner": None, "task": False},
    ]
    actions = [
        {"start": 0, "owner": "小王"},
        {"start": 1, "owner": "小赵"},
        {"start": 3, "owner": "小陈"},
    ]
    monkeypatch.setattr(owner_eval, "summarize", lambda segments, client: {"actions": actions})

    class Client:
        model = "fake"

        def __init__(self):
            self.results = iter(['{"owner":"小李"}', '{"owner":""}', ToolError("offline")])

        def chat(self, *args, **kwargs):
            result = next(self.results)
            if isinstance(result, Exception):
                raise result
            return result

    result = owner_eval.evaluate(Client(), cases)
    assert result["selected_expected_tasks"] == 2
    assert result["missed_expected_tasks"] == 1
    assert result["selected_non_tasks"] == 1
    assert result["verifier_failures"] == 1
    assert result["extra_verifier_calls"] == 3
    assert result["baseline"] == {
        "correct_owner": 1, "wrong_owner": 1, "missed_owner": 0, "correct_unknown": 0,
    }
    assert result["agreement_only"] == {
        "correct_owner": 0, "wrong_owner": 0, "missed_owner": 1, "correct_unknown": 1,
    }
