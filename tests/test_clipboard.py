"""Contract tests use fake inference; they do not claim model quality."""

import argparse
import base64
import unittest
from pathlib import Path
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
        bridge.assert_called_once_with("--snapshot")


if __name__ == "__main__":
    unittest.main()
