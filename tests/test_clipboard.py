"""Contract tests use fake inference; they do not claim model quality."""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from minicpm_tools import clipboard
from minicpm_tools.common import ToolError


class FakeClient:
    def __init__(self):
        self.prompts = []
        self.images = []

    def chat(self, prompt, system="", *, temperature=0.0):
        self.prompts.append((prompt, system))
        return "- [ ] 明天提交报告"

    def ocr(self, image):
        assert Path(image).is_file()
        self.images.append(Path(image))
        return "明天提交报告"


class ClipboardTests(unittest.TestCase):
    def test_all_three_text_actions_preserve_input_as_data(self):
        for action in ("translate", "rewrite", "todos"):
            client = FakeClient()
            result = clipboard.transform("明天提交报告", action, client, "English")
            self.assertTrue(result)
            self.assertEqual(client.prompts[0][0], "明天提交报告")
            self.assertEqual(
                client.prompts[0][1], clipboard.PROMPTS[action].format(language="English")
            )
        self.assertIn("English", clipboard.PROMPTS["translate"].format(language="English"))

    def test_empty_and_oversized_text_rejected_before_model(self):
        client = FakeClient()
        for text in ("  ", "x" * (clipboard.MAX_TEXT + 1)):
            with self.assertRaises(ToolError):
                clipboard.transform(text, "todos", client)
        self.assertEqual(client.prompts, [])

    def test_file_character_limit_accepts_utf8_and_rejects_extra_before_model(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.txt"
            args = argparse.Namespace(action="todos", apply=False, text=None, file=str(path),
                                      image=None, stdin=False, language="中文")
            client = FakeClient()
            with patch.object(clipboard.LocalClient, "from_env", return_value=client):
                path.write_text("鲸" * clipboard.MAX_TEXT, encoding="utf-8")
                clipboard.run(args)
                self.assertEqual(client.prompts[0][0], "鲸" * clipboard.MAX_TEXT)
                path.write_text("鲸" * (clipboard.MAX_TEXT + 1), encoding="utf-8")
                with self.assertRaisesRegex(ToolError, "文本过长"):
                    clipboard.run(args)
                self.assertEqual(len(client.prompts), 1)

    def test_large_text_file_is_not_fully_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large.txt"
            with path.open("wb") as stream:
                for _ in range(16):
                    stream.write(b"x" * (1024 * 1024))
            program = (
                "import json,sys,tracemalloc; from pathlib import Path; "
                "from minicpm_tools.clipboard import read_text_file; "
                "tracemalloc.start(); value=read_text_file(Path(sys.argv[1])); "
                "print(json.dumps([len(value),tracemalloc.get_traced_memory()[1]]))"
            )
            result = subprocess.run([sys.executable, "-c", program, str(path)], check=True,
                                    capture_output=True, text=True)
            length, peak = json.loads(result.stdout)
            self.assertEqual(length, clipboard.MAX_TEXT + 1)
            self.assertLess(peak, 2 * 1024 * 1024)

    def test_image_todos_removes_temporary_image(self):
        client = FakeClient()
        result = clipboard.process_snapshot(
            {"image_png": base64.b64encode(b"test PNG bytes").decode()}, "image-todos", client
        )
        self.assertEqual(result, "- [ ] 明天提交报告")
        self.assertFalse(client.images[0].exists())
        self.assertIn("明天提交报告", client.prompts[0][0])

    def test_missing_image_and_invalid_data_fail(self):
        for data in ({}, {"image_png": "invalid!!"}):
            with self.assertRaises(ToolError):
                clipboard.process_snapshot(data, "ocr", FakeClient())

    def test_model_failure_never_replaces_clipboard(self):
        args = argparse.Namespace(
            action="todos",
            apply=True,
            text=None,
            file=None,
            image=None,
            stdin=False,
            language="中文",
        )
        with (
            patch.object(
                clipboard, "bridge_call", return_value={"text": "input", "change_count": 7}
            ) as bridge,
            patch.object(clipboard.LocalClient, "from_env") as factory,
        ):
            factory.return_value.chat.side_effect = ToolError("服务不可用")
            with self.assertRaises(ToolError):
                clipboard.run(args)
        self.assertEqual(bridge.call_count, 1)

    def test_apply_passes_original_change_count(self):
        args = argparse.Namespace(
            action="todos",
            apply=True,
            text=None,
            file=None,
            image=None,
            stdin=False,
            language="中文",
        )
        with (
            patch.object(
                clipboard,
                "bridge_call",
                side_effect=[{"text": "input", "change_count": 17}, {"ok": True}],
            ) as bridge,
            patch.object(clipboard.LocalClient, "from_env", return_value=FakeClient()),
        ):
            clipboard.run(args)
        self.assertEqual(bridge.call_args.args, ("--replace", "17"))

    def test_preview_does_not_write(self):
        args = argparse.Namespace(
            action="todos",
            apply=False,
            text=None,
            file=None,
            image=None,
            stdin=False,
            language="中文",
        )
        with (
            patch.object(
                clipboard, "bridge_call", return_value={"text": "input", "change_count": 7}
            ) as bridge,
            patch.object(clipboard.LocalClient, "from_env", return_value=FakeClient()),
        ):
            clipboard.run(args)
        bridge.assert_called_once_with("--snapshot-text")

    def test_image_actions_request_only_image_snapshot(self):
        for action in ("ocr", "image-todos"):
            args = argparse.Namespace(
                action=action, apply=False, text=None, file=None, image=None, stdin=False,
                language="中文",
            )
            snapshot = {"image_png": base64.b64encode(b"test PNG bytes").decode()}
            with (
                patch.object(clipboard, "bridge_call", return_value=snapshot) as bridge,
                patch.object(clipboard.LocalClient, "from_env", return_value=FakeClient()),
            ):
                clipboard.run(args)
            bridge.assert_called_once_with("--snapshot-image")

    def test_old_bridge_is_detected_without_snapshot_or_gui(self):
        old_response = SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")
        with (
            patch.object(clipboard, "bridge_path", return_value=Path("/bridge")),
            patch.object(clipboard.subprocess, "run", return_value=old_response) as run,
            self.assertRaisesRegex(ToolError, "重新构建"),
        ):
            clipboard.bridge_call("--snapshot-text")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [
            "/bridge", "--bridge-version", "--self-test-timeouts", "--self-test"
        ])

    def test_bridge_probe_invalid_or_timeout_fails_before_read(self):
        for outcome in (
            SimpleNamespace(returncode=0, stdout="not json", stderr=""),
            SimpleNamespace(returncode=1, stdout='{"bridge_version": 2}', stderr=""),
            subprocess.TimeoutExpired("bridge", 5),
        ):
            with (
                patch.object(clipboard, "bridge_path", return_value=Path("/bridge")),
                patch.object(clipboard.subprocess, "run", side_effect=[outcome]) as run,
                self.assertRaisesRegex(ToolError, "重新构建"),
            ):
                clipboard.bridge_call("--snapshot-text")
            self.assertEqual(run.call_count, 1)

    def test_compatible_bridge_snapshot_runs_after_probe(self):
        responses = [
            SimpleNamespace(returncode=0, stdout='{"bridge_version": 2}', stderr=""),
            SimpleNamespace(returncode=0, stdout='{"change_count": 7, "text": "demo"}', stderr=""),
        ]
        with (
            patch.object(clipboard, "bridge_path", return_value=Path("/bridge")),
            patch.object(clipboard.subprocess, "run", side_effect=responses) as run,
        ):
            self.assertEqual(clipboard.bridge_call("--snapshot-text")["text"], "demo")
        self.assertEqual(run.call_args.args[0], ["/bridge", "--snapshot-text"])


if __name__ == "__main__":
    unittest.main()
