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
