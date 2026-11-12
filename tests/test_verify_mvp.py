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


@pytest.mark.parametrize(
    "command",
    [
        "find . -type f -size +100M -exec sh -c 'mv a b' \\\\;",
        "find . -type f -size +100M -execdir rm {} +",
        "find . -type f -size +100M -ok echo {} \\\\;",
        "find . -type f -size +100M -delete",
        "find . -type f -size +100M -fprint result",
        "find . -type f -size +100M > output",
        "find . -type f -size +100M $(touch marker)",
    ],
)
def test_large_file_acceptance_rejects_side_effects(command):
    with pytest.raises(verify.CheckFailure):
        verify.check_large_file_find(command)


def test_large_file_acceptance_requires_expected_scope_and_predicates():
    verify.check_large_file_find("find . -type f -size +100M")
    verify.check_large_file_find("find . -size +100M -type f -print")
    with pytest.raises(verify.CheckFailure):
        verify.check_large_file_find("find / -type f -size +100M")


def test_shell_acceptance_explicit_zsh_without_shell_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)

    class SyntheticRun:
        def __init__(self):
            self.directory = tmp_path
            self.calls = []

        def cli(self, *args, label, **kwargs):
            self.calls.append((args, label))
            if label == "shell-find":
                command = "find . -type f -size +100M"
            elif label == "shell-lsof":
                command = "lsof -i :8080"
            elif label == "shell-df":
                command = "df -h"
            elif label == "shell-rename-preview":
                return "建议命令（尚未执行）：\nrename .txt .md\n执行限制"
            elif label == "shell-explain":
                return "gzip notes"
            else:
                assert kwargs["expected"] == 1
                return ""
            return f"建议命令（尚未执行）：\n{command}\n"

    runner = SyntheticRun()
    verify.shell(runner)
    calls = [args for args, _ in runner.calls if args[1] in ("suggest", "explain")]
    assert len(calls) == 5
    assert all(args[-2:] == ("--shell", "zsh") for args in calls)
