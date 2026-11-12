"""The action diagnostic must expose failed batches and classification errors."""

import importlib.util
import json
from pathlib import Path

from minicpm_tools.common import ToolError

SPEC = importlib.util.spec_from_file_location(
    "evaluate_audio_actions", Path(__file__).parents[1] / "script/evaluate_audio_actions.py"
)
action_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(action_eval)


def test_fixture_has_unambiguous_single_source_phrases():
    fixture = json.loads(action_eval.FIXTURE.read_text(encoding="utf-8"))
    for batch in fixture["batches"]:
        for index, case in enumerate(batch["cases"]):
            segment = action_eval.Segment(index, index + 0.5, case["text"])
            assert action_eval.source_phrases([segment]) == [segment]
            assert isinstance(case["task"], bool)
            assert case["owner"] is None or case["owner"] in case["text"]


def test_scoring_reports_false_positives_and_misses():
    rows = [
        {"selected": True, "expected_task": True},
        {"selected": True, "expected_task": False},
        {"selected": False, "expected_task": True},
        {"selected": False, "expected_task": False},
    ]
    assert action_eval.scores(rows) == {
        "true_positive": 1, "false_positive": 1, "true_negative": 1, "false_negative": 1,
        "precision": 0.5, "recall": 0.5, "false_positive_rate": 0.5,
    }
    assert action_eval.scores([])["precision"] is None


def test_owner_scores_exclude_missed_tasks_and_selected_non_tasks():
    rows = [
        {"selected": True, "expected_task": True, "expected_owner": "Alice", "predicted_owner": "Alice"},
        {"selected": True, "expected_task": True, "expected_owner": None, "predicted_owner": "Bob"},
        {"selected": True, "expected_task": True, "expected_owner": "Carol", "predicted_owner": None},
        {"selected": True, "expected_task": True, "expected_owner": None, "predicted_owner": None},
        {"selected": False, "expected_task": True, "expected_owner": "David", "predicted_owner": None},
        {"selected": True, "expected_task": False, "expected_owner": None, "predicted_owner": "Eve"},
    ]
    assert action_eval.owner_scores(rows) == {
        "correct_owner": 1, "wrong_owner": 1, "missed_owner": 1, "correct_unknown": 1,
    }


def test_failed_batch_is_unscored_and_raw_responses_are_retained(monkeypatch):
    fixture = {"batches": [
        {"name": "good", "cases": [{"text": "Do it.", "kind": "task", "task": True, "owner": None}]},
        {"name": "failed", "cases": [{"text": "A story.", "kind": "narrative", "task": False, "owner": None}]},
    ]}

    class Client:
        model = "fake"

        def chat(self, prompt, **kwargs):
            return "raw response"

    def fake_summarize(segments, client):
        client.chat("summary")
        client.chat("actions")
        if segments[0].text == "A story.":
            raise ToolError("bad model reply")
        return {"actions": [{"start": 0}]}

    monkeypatch.setattr(action_eval, "summarize", fake_summarize)
    result = action_eval.evaluate(Client(), fixture)
    assert result["total_cases"] == 2 and result["scored_cases"] == 1
    assert result["scores"]["true_positive"] == 1
    assert result["scores"]["true_negative"] == 0
    assert result["failed_batches"][0]["unscored_cases"] == 1
    assert result["failed_batches"][0]["model_responses"] == ["raw response", "raw response"]


def test_only_second_call_replaces_the_prompt():
    class Client:
        def chat(self, prompt, **kwargs):
            return prompt

    client = action_eval.ActionPromptOverride(Client(), "new action instruction")
    assert client.chat("overview instruction") == "overview instruction"
    assert client.chat("old instruction资料：\nfictional data") == (
        "new action instruction\n资料：\nfictional data"
    )
