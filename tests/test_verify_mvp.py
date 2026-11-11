"""The opt-in real-model harness must reject weak or contradictory evidence."""

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "verify_mvp", Path(__file__).parents[1] / "script/verify_mvp.py"
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def audio_fixture():
    quotes = [
        "Alice will send the first report tomorrow.",
        "We still need to organize references.",
        "We will discuss the extra experiment next week.",
    ]
    summary = "\n".join(
        f"- [ ] {q}（负责人：未提及；截止：未提及）[00:00:00.000–00:00:01.000]" for q in quotes
    )
    return summary, "\n".join(quotes)


def test_audio_acceptance_requires_all_three_grounded_tasks():
    summary, transcript = audio_fixture()
    assert verify.check_audio(summary, transcript)["source_quotes_checked"] == 3
    with pytest.raises(verify.CheckFailure, match="exactly"):
        verify.check_audio("\n".join(summary.splitlines()[:2]), transcript)
    with pytest.raises(verify.CheckFailure, match="transcript quote"):
        verify.check_audio(summary.replace("first report", "secret report"), transcript)
    with pytest.raises(verify.CheckFailure, match="Completed"):
        verify.check_audio(summary.replace("references.", "references after cleaning."), transcript)


def test_preview_label_is_required():
    assert verify.command_from_preview("建议命令（尚未执行）：\ndf -h .\n") == "df -h ."
    with pytest.raises(verify.CheckFailure):
        verify.command_from_preview("df -h .")


def test_command_failure_retains_evidence_and_cannot_pass(tmp_path):
    run = verify.Run(tmp_path)
    with pytest.raises(verify.CheckFailure, match="exit 7"):
        run.command(
            [sys.executable, "-c", "import sys; print('diagnostic'); sys.exit(7)"],
            label="intentional fixture failure",
        )
    assert run.calls[0]["exit_code"] == 7
    assert run.calls[0]["stdout"].strip() == "diagnostic"
