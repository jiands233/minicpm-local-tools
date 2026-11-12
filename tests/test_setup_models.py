"""Installer tests use tiny fake payloads, never download real models."""

import hashlib
import importlib.util
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "setup_models", Path(__file__).parents[1] / "script/setup_models.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def fixture_item(content=b"model fixture"):
    return {
        "path": "test.gguf",
        "destination": ".local/gguf/test.gguf",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_corrupt_download_never_published(tmp_path, monkeypatch):
    item = fixture_item()

    def fake_curl(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_bytes(b"wrong")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(setup.subprocess, "run", fake_curl)
    component = {"kind": "text", "repo": "owner/model", "revision": "a" * 40}
    with pytest.raises(setup.SetupError, match="mismatch"):
        setup.download_file(component, item, tmp_path)
    assert not (tmp_path / item["destination"]).exists()
    assert list((tmp_path / ".local/gguf").iterdir()) == []


def test_download_verifies_then_reuses_without_network(tmp_path, monkeypatch):
    content = b"model fixture"
    item = fixture_item(content)
    calls = []

    def fake_curl(command, **kwargs):
        calls.append(command)
        assert command[0:2] == ["curl", "-q"]
        Path(command[command.index("--output") + 1]).write_bytes(content)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(setup.subprocess, "run", fake_curl)
    component = {"kind": "text", "repo": "owner/model", "revision": "b" * 40}
    path = setup.download_file(component, item, tmp_path)
    assert path.read_bytes() == content
    setup.download_file(component, item, tmp_path)
    assert len(calls) == 1
    assert "/" + "b" * 40 + "/" in calls[0][-1]


def test_existing_bad_file_and_outside_destination_preserved(tmp_path):
    item = fixture_item()
    path = tmp_path / item["destination"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"do not clobber")
    with pytest.raises(setup.SetupError, match="Existing file failed"):
        setup.download_file({}, item, tmp_path)
    assert path.read_bytes() == b"do not clobber"
    with pytest.raises(setup.SetupError, match="inside .local"):
        setup.destination({"destination": "../escape"}, tmp_path)


def test_small_config_checks_git_blob_identity(tmp_path):
    content = b'{"config":true}\n'
    item = fixture_item(content)
    item["git_blob_sha1"] = hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()
    path = tmp_path / "config.json"
    path.write_bytes(content)
    assert setup.verify(path, item)
    item["git_blob_sha1"] = "0" * 40
    assert not setup.verify(path, item)


def test_modelfile_uses_verified_paths_and_embedded_template(tmp_path):
    item = fixture_item()
    path = tmp_path / item["destination"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"model fixture")
    text = setup.modelfile({"kind": "text", "files": [item]}, tmp_path)
    assert str(path) in text
    assert "TEMPLATE" not in text
    assert "PARAMETER temperature 0" in text
    path.write_bytes(b"bad")
    with pytest.raises(setup.SetupError, match="invalid weights"):
        setup.modelfile({"kind": "text", "files": [item]}, tmp_path)


def runtime_component(root, members):
    archive = root / ".local/runtime/ollama-darwin.tgz"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(content))
    item = fixture_item(archive.read_bytes())
    item["destination"] = ".local/runtime/ollama-darwin.tgz"
    return {"kind": "runtime", "version": "test", "files": [item]}


def test_runtime_install_reuse_and_tampered_binary_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_component(tmp_path, {"ollama": b"verified binary", "libsample": b"lib"})
    setup.install_runtime(component, tmp_path)
    binary = tmp_path / ".local/runtime/ollama"
    assert binary.read_bytes() == b"verified binary"

    def no_execution(*args, **kwargs):
        pytest.fail("version command must not be used to identify runtime")

    monkeypatch.setattr(setup.subprocess, "run", no_execution)
    setup.install_runtime(component, tmp_path)
    binary.write_bytes(b"tampered binary")
    with pytest.raises(setup.SetupError, match="differs from verified archive"):
        setup.install_runtime(component, tmp_path)
    assert binary.read_bytes() == b"tampered binary"


def test_runtime_archive_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_component(tmp_path, {"../../escape": b"unsafe", "ollama": b"binary"})
    with pytest.raises(tarfile.FilterError):
        setup.install_runtime(component, tmp_path)
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / ".local/runtime/ollama").exists()


def test_download_concurrent_destination_is_never_clobbered(tmp_path, monkeypatch):
    item = fixture_item()
    component = {"kind": "text", "repo": "owner/model", "revision": "b" * 40}

    def fake_curl(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_bytes(b"model fixture")
        return subprocess.CompletedProcess(command, 0)

    real_link = setup.os.link
    destination = tmp_path / item["destination"]

    def concurrent_link(source, target):
        # Simulate another process creating the destination at the publish point.
        destination.write_bytes(b"other process data")
        return real_link(source, target)

    monkeypatch.setattr(setup.subprocess, "run", fake_curl)
    monkeypatch.setattr(setup.os, "link", concurrent_link)
    with pytest.raises(setup.SetupError, match="appeared during download"):
        setup.download_file(component, item, tmp_path)
    assert destination.read_bytes() == b"other process data"
    assert sorted(p.name for p in destination.parent.iterdir()) == [destination.name]
