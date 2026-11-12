import json
from pathlib import Path

import pytest

from minicpm_tools.common import ToolError
from minicpm_tools.shell import generate, suggestion_risks


class Fake:
    def __init__(self, command):
        self.command = command

    def chat(self, _):
        return json.dumps({"command": self.command, "explanation": "模型可能错误地声称安全"})


@pytest.mark.parametrize(
    "command",
    [
        "find . -type f -size +100M -exec sh -c 'mv a b' \\\\;",
        "find . -type f -size +100M -execdir rm {} +",
        "find . -type f -size +100M -ok echo {} \\\\;",
        "find . -type f -size +100M -delete",
        "find . -type f -size +100M -fprint results",
        "find . -type f -size +100M > out.txt",
        "find . -type f -size +100M $(touch marker)",
        "ls .; rm file",
    ],
)
def test_read_only_suggestions_reject_detectable_side_effects(command):
    with pytest.raises(ToolError, match="只读需求"):
        generate("查找当前目录里大于100MB的文件", Path("."), Fake(command))


def test_plain_find_accepted_and_explicit_mutation_remains_previewable():
    find, _ = generate("查找大文件", Path("."), Fake("find . -type f -size +100M"))
    assert not suggestion_risks(find)
    rename, _ = generate(
        "查找并重命名txt文件", Path("."), Fake("find . -name '*.txt' -exec mv {} {}.md \\\\;")
    )
    assert suggestion_risks(rename)


def test_current_shell_is_inferred_from_parent_over_login_default(monkeypatch):
    from types import SimpleNamespace

    from minicpm_tools import shell

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(
        shell.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="/bin/bash\n")
    )
    assert shell.shell_context() == ("bash", "直接父进程")

    class Capture:
        def chat(self, prompt):
            self.prompt = prompt
            return json.dumps({"command": "pwd", "explanation": "显示目录"})

    client = Capture()
    shell.generate("查看目录", Path("."), client)
    assert "shell：bash" in client.prompt
    assert "shell：zsh" not in client.prompt


def test_shell_override_and_fallback_are_explicit(monkeypatch):
    from types import SimpleNamespace

    from minicpm_tools import shell

    monkeypatch.setattr(
        shell.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="python\n")
    )
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert shell.shell_context() == ("zsh", "默认登录 shell，当前终端可能不同")
    assert shell.shell_context("fish") == ("fish", "用户指定")
    monkeypatch.setenv("SHELL", "/tmp/not-a-shell\nexecute-dangerous")
    assert shell.shell_context() == ("未知", "无法检测，请用 --shell 指定")
    with pytest.raises(ToolError):
        shell.shell_context("zsh\ninjected")


def test_suggestion_uses_explicit_shell_in_model_prompt(monkeypatch, capsys, tmp_path):
    from types import SimpleNamespace

    from minicpm_tools import shell

    class Capture:
        def chat(self, prompt):
            self.prompt = prompt
            return json.dumps({"command": "pwd", "explanation": "显示目录"})

    model = Capture()
    monkeypatch.setattr(shell.LocalClient, "from_env", lambda: model)
    shell.run(
        SimpleNamespace(
            action="suggest", text="查看目录", cwd=str(tmp_path), shell="fish", execute=False
        )
    )
    assert "shell：fish" in model.prompt
    assert "终端上下文：fish（用户指定）" in capsys.readouterr().out
