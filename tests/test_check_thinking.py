import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from minicpm_tools.common import ToolError

SPEC = importlib.util.spec_from_file_location(
    "check_thinking", Path(__file__).resolve().parents[1] / "script/check_thinking.py"
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def response(content="answer", **fields):
    return {"choices": [{"message": {"content": content, **fields}, "finish_reason": "stop"}]}


def test_parameter_matrix_changes_only_controls():
    fixture = {"content": "synthetic"}
    payloads = [check.payload_for(fixture, "local-model", key) for key in check.VARIANTS]
    assert "chat_template_kwargs" not in payloads[0] and "reasoning_effort" not in payloads[0]
    assert payloads[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in payloads[1]
    assert payloads[2]["reasoning_effort"] == "none"
    assert "chat_template_kwargs" not in payloads[2]
    assert payloads[3] == payloads[0] | check.VARIANTS["both"]
    for payload in payloads:
        assert {k: v for k, v in payload.items()
                if k not in {"chat_template_kwargs", "reasoning_effort"}} == payloads[0]


def test_raw_response_observations_do_not_strip_thinking():
    raw = response("<think>reason</think>answer", reasoning_content="steps", reasoning=None)
    observations = check.inspect_response(raw)
    assert observations["think_marker"] and observations["reasoning_nonempty"]
    assert set(observations["reasoning_fields"]) == {"reasoning", "reasoning_content"}
    assert raw["choices"][0]["message"]["content"].startswith("<think>")
    assert not check.inspect_response(response(reasoning=""))["reasoning_nonempty"]
    raw["choices"][0]["finish_reason"] = "length"
    assert check.inspect_response(raw)["truncated"]
    assert not check.inspect_response(response(None, thinking="unfinished"))["content_nonempty"]


@pytest.mark.parametrize("kind", ["ok", "http_error", "timeout", "malformed", "redirect"])
def test_request_records_raw_errors_and_refuses_redirects(kind):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if kind == "http_error":
            return httpx.Response(400, json={"error": "synthetic failure"})
        if kind == "malformed":
            return httpx.Response(200, json={"choices": []})
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://example.org"})
        return httpx.Response(200, json=response("<think>raw</think>answer"))

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False,
                      trust_env=False) as client:
        result = check.run_case(client, "http://127.0.0.1:11434/v1", {"model": "test"})
    assert len(calls) == 1 and result["seconds"] >= 0
    assert result["status"] == ("ok" if kind == "ok" else "error")
    if kind == "ok":
        assert "<think>raw</think>" in result["raw_response"]
    elif kind != "timeout":
        assert "raw_response" in result and "error_type" in result


def test_external_address_rejected_before_request():
    with pytest.raises(ToolError):
        check.run_case(None, "https://example.org/v1", {})


def test_ocr_fixture_order_and_known_text(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import ImageFont

    font = ImageFont.load_default()
    monkeypatch.setattr(ImageFont, "truetype", lambda *a, **kw: font)
    fixtures = check.make_fixtures(tmp_path, "synthetic-font")
    assert fixtures[0]["kind"] == "text"
    for fixture in fixtures[1:]:
        payload = check.payload_for(fixture, "ocr", "both")
        blocks = payload["messages"][0]["content"]
        assert blocks[0]["type"] == "image_url"
        assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert blocks[1] == {"type": "text", "text": "Text Recognition:"}
        assert (tmp_path / fixture["image_file"]).read_bytes().startswith(b"\x89PNG")
        assert fixture["source"] in check.OCR_TEXTS.values()


def test_main_continues_failed_cases_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check, "provenance", lambda: {"commit": "test"})
    fixtures = [{"name": k, "kind": "text" if k == "text" else "ocr", "content": k}
                for k in ("text", "ocr-zh", "ocr-en")]
    monkeypatch.setattr(check, "make_fixtures", lambda *a: fixtures)
    monkeypatch.setattr(check, "metadata", lambda *a: {})
    options = []
    real_client = httpx.Client

    def client(**kwargs):
        options.append(kwargs)
        return real_client(transport=httpx.MockTransport(
            lambda r: httpx.Response(503, json={"error": "offline"})), **kwargs)

    monkeypatch.setattr(check.httpx, "Client", client)
    for _ in range(2):
        assert check.main([]) == 1
    reports = list((tmp_path / ".local/acceptance").glob("thinking-*/report.json"))
    assert len(reports) == 2
    for path in reports:
        report = json.loads(path.read_text())
        assert report["complete"] and len(report["cases"]) == 12
        assert all(row["status"] == "error" for row in report["cases"])
        with pytest.raises(FileExistsError):
            check.save_json(path, {})
    assert all(not o["trust_env"] and not o["follow_redirects"] for o in options)


def test_report_must_stay_ignored_and_url_validated_first(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    for args in (["--output-dir", str(tmp_path / "docs")],
                 ["--base-url", "https://example.org"], ["--timeout", "nan"]):
        with pytest.raises(SystemExit) as exc:
            check.main(args)
        assert exc.value.code == 2
    assert not (tmp_path / ".local").exists()
