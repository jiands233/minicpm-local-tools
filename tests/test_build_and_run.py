"""Exercise the build script in an isolated fake project, never the real app."""

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def fake_project(tmp_path):
    root = tmp_path / "project"
    script_dir = root / "script"
    binary = root / "macos/.build/release/MiniCPMClipboard"
    commands = tmp_path / "commands"
    script_dir.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    binary.write_text("fake binary", encoding="utf-8")
    commands.mkdir()
    for name in ("swift", "pkill"):
        command = commands / name
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)
    open_marker = tmp_path / "opened"
    fake_open = commands / "open"
    fake_open.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(open_marker))}\n", encoding="utf-8")
    fake_open.chmod(0o755)
    source = Path(__file__).resolve().parents[1] / "script/build_and_run.sh"
    script = script_dir / source.name
    # Only the isolated copy is altered: the real macOS open is never invoked.
    script.write_text(source.read_text(encoding="utf-8").replace("/usr/bin/open", str(fake_open)))
    env = {key: value for key, value in os.environ.items() if not key.startswith("MINICPM_")}
    env["PATH"] = f"{commands}{os.pathsep}{os.defpath}"
    config = root / "macos/dist/MiniCPMClipboard.app/Contents/Resources/model-config.json"

    def run(*args, **variables):
        return subprocess.run(
            ["bash", str(script), *args],
            env=env | variables,
            text=True,
            capture_output=True,
            check=False,
        )

    return run, config, open_marker


def test_build_preserves_existing_configuration_until_explicit_update(fake_project):
    run, config, opened = fake_project
    assert run("--build-only", MINICPM_MODEL="custom", MINICPM_TIMEOUT="300").returncode == 0
    assert json.loads(config.read_text()) == {"MINICPM_MODEL": "custom", "MINICPM_TIMEOUT": "300"}

    # A terminal without the exports, or with only one changed, must not erase the rest.
    assert run("--build-only").returncode == 0
    assert run("--build-only", MINICPM_MODEL="other").returncode == 0
    assert json.loads(config.read_text()) == {"MINICPM_MODEL": "custom", "MINICPM_TIMEOUT": "300"}
    assert not opened.exists()

    # Explicit update is a full replacement: omitted keys revert to app defaults.
    assert run("--build-only", "--update-model-config", MINICPM_MODEL="other").returncode == 0
    assert json.loads(config.read_text()) == {"MINICPM_MODEL": "other"}
    assert run("--update-model-config", "--build-only").returncode == 0
    assert json.loads(config.read_text()) == {}
    assert not opened.exists()


def test_explicit_update_can_be_used_with_default_run(fake_project):
    run, config, opened = fake_project
    result = run("--update-model-config", MINICPM_MODEL="selected")
    assert result.returncode == 0, result.stderr
    assert json.loads(config.read_text()) == {"MINICPM_MODEL": "selected"}
    assert opened.exists()
    opened.unlink()
    result = run("run", "--update-model-config", MINICPM_MODEL="next")
    assert result.returncode == 0, result.stderr
    assert json.loads(config.read_text()) == {"MINICPM_MODEL": "next"}
    assert opened.exists()


def test_config_symlink_is_not_overwritten(fake_project, tmp_path):
    run, config, _ = fake_project
    target = tmp_path / "user-file"
    target.write_text("do not change", encoding="utf-8")
    config.parent.mkdir(parents=True)
    config.symlink_to(target)
    assert run("--build-only").returncode != 0
    assert run("--build-only", "--update-model-config").returncode != 0
    assert target.read_text(encoding="utf-8") == "do not change"
