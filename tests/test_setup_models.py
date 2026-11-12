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


@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_registration_preserves_existing_modelfile_and_cleans_temporary(
    tmp_path, monkeypatch, returncode, existing_kind
):
    item = fixture_item()
    weights = tmp_path / item["destination"]
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"model fixture")
    old = tmp_path / ".local/modelfiles/text.Modelfile"
    old.parent.mkdir()
    target = tmp_path / "existing-user-file"
    target.write_text("original user content", encoding="utf-8")
    if existing_kind == "symlink":
        old.symlink_to(target)
    else:
        old.write_text("original user content", encoding="utf-8")
    seen = []

    def fake_create(command, **kwargs):
        path = Path(command[command.index("-f") + 1])
        assert path != old and path.is_file()
        assert str(weights) in path.read_text(encoding="utf-8")
        seen.append(path)
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(setup, "ollama_path", lambda root: "ollama")
    monkeypatch.setattr(setup.subprocess, "run", fake_create)
    components = {"text": {"kind": "text", "model_name": "fixture", "files": [item]}}
    if returncode:
        with pytest.raises(setup.SetupError, match="registration failed"):
            setup.register(components, ["text"], tmp_path)
    else:
        setup.register(components, ["text"], tmp_path)
    assert len(seen) == 1 and not seen[0].exists()
    assert old.read_text(encoding="utf-8") == "original user content"
    assert target.read_text(encoding="utf-8") == "original user content"
    assert old.is_symlink() == (existing_kind == "symlink")


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


def runtime_tree_component(root):
    """Tiny archive with the file/link shapes present in a Darwin runtime."""
    archive = root / ".local/runtime/ollama-darwin.tgz"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w:gz") as tar:
        directory = tarfile.TarInfo("lib")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)
        empty = tarfile.TarInfo("lib/empty")
        empty.type = tarfile.DIRTYPE
        empty.mode = 0o755
        tar.addfile(empty)
        for name, content, mode in [
            ("ollama", b"verified binary", 0o755),
            ("lib/core.dylib", b"verified library", 0o644),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = mode
            tar.addfile(info, io.BytesIO(content))
        for name, link, kind in [
            ("lib/alias.dylib", "core.dylib", tarfile.SYMTYPE),
            ("lib/hard.dylib", "lib/core.dylib", tarfile.LNKTYPE),
            ("lib-current", "lib", tarfile.SYMTYPE),
        ]:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = link
            tar.addfile(info)
    item = fixture_item(archive.read_bytes())
    item["destination"] = ".local/runtime/ollama-darwin.tgz"
    return {"kind": "runtime", "version": "test", "files": [item]}


def test_runtime_reuse_requires_all_files_and_preserves_missing_library_state(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_component(tmp_path, {"ollama": b"verified binary", "libsample": b"library"})
    target = tmp_path / ".local/runtime"
    binary = target / "ollama"
    binary.write_bytes(b"verified binary")
    binary.chmod(0o755)
    with pytest.raises(setup.SetupError, match="Incomplete runtime: missing libsample"):
        setup.install_runtime(component, tmp_path)
    assert binary.read_bytes() == b"verified binary"
    assert not (target / "libsample").exists()


def test_runtime_directory_symlink_hardlink_reuse_and_extra_files(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_tree_component(tmp_path)
    target = tmp_path / ".local/runtime"
    extra = target / "user-notes.txt"
    extra.write_text("keep this")
    setup.install_runtime(component, tmp_path)
    assert (target / "lib").is_dir() and not (target / "lib").is_symlink()
    assert (target / "lib/empty").is_dir()
    assert list((target / "lib/empty").iterdir()) == []
    assert (target / "lib/alias.dylib").is_symlink()
    assert setup.os.readlink(target / "lib/alias.dylib") == "core.dylib"
    assert (target / "lib-current").is_symlink()
    assert (target / "lib/hard.dylib").read_bytes() == b"verified library"
    assert (target / "lib/core.dylib").stat().st_ino == (target / "lib/hard.dylib").stat().st_ino
    setup.install_runtime(component, tmp_path)
    assert extra.read_text() == "keep this"


@pytest.mark.parametrize(
    "damage",
    [
        "missing-library",
        "modified-library",
        "wrong-symlink",
        "file-instead-of-dir",
        "lost-executable-bit",
        "missing-and-corrupt",
        "missing-empty-dir",
    ],
)
def test_runtime_reuse_rejects_incomplete_or_changed_tree(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_tree_component(tmp_path)
    target = tmp_path / ".local/runtime"
    setup.install_runtime(component, tmp_path)
    if damage == "missing-and-corrupt":
        (target / "lib/core.dylib").unlink()
        (target / "ollama").write_bytes(b"changed binary")
    elif damage == "missing-empty-dir":
        (target / "lib/empty").rmdir()
    elif damage == "missing-library":
        (target / "lib/core.dylib").unlink()
    elif damage == "modified-library":
        (target / "lib/core.dylib").write_bytes(b"changed library")
    elif damage == "wrong-symlink":
        (target / "lib/alias.dylib").unlink()
        (target / "lib/alias.dylib").symlink_to("hard.dylib")
    elif damage == "file-instead-of-dir":
        for path in (target / "lib").iterdir():
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        (target / "lib").rmdir()
        (target / "lib").write_bytes(b"not a directory")
    else:
        (target / "ollama").chmod(0o644)
    with pytest.raises(setup.SetupError, match="Incomplete runtime|differs from verified archive"):
        setup.install_runtime(component, tmp_path)
    if damage == "missing-and-corrupt":
        assert not (target / "lib/core.dylib").exists()
        assert (target / "ollama").read_bytes() == b"changed binary"
    elif damage == "missing-empty-dir":
        assert not (target / "lib/empty").exists()
    elif damage == "missing-library":
        assert not (target / "lib/core.dylib").exists()
    elif damage == "modified-library":
        assert (target / "lib/core.dylib").read_bytes() == b"changed library"
    elif damage == "wrong-symlink":
        assert setup.os.readlink(target / "lib/alias.dylib") == "hard.dylib"
    elif damage == "file-instead-of-dir":
        assert (target / "lib").read_bytes() == b"not a directory"
    else:
        assert not ((target / "ollama").stat().st_mode & 0o100)


def test_runtime_install_does_not_overwrite_concurrent_file(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_component(tmp_path, {"ollama": b"verified binary"})
    target = tmp_path / ".local/runtime/ollama"
    real_link = setup.os.link

    def concurrent_link(source, destination):
        if Path(destination) == target:
            target.write_bytes(b"new user file")
        return real_link(source, destination)

    monkeypatch.setattr(setup.os, "link", concurrent_link)
    with pytest.raises(setup.SetupError, match="appeared during installation"):
        setup.install_runtime(component, tmp_path)
    assert target.read_bytes() == b"new user file"


def appledouble_fixture(payload=b"finder metadata"):
    header = b"\x00\x05\x16\x07\x00\x02\x00\x00" + b"\0" * 16 + (1).to_bytes(2, "big")
    entry = (9).to_bytes(4, "big") + (38).to_bytes(4, "big") + len(payload).to_bytes(4, "big")
    return header + entry + payload


def test_runtime_appledouble_companions_are_optional_on_all_hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    component = runtime_component(
        tmp_path,
        {
            "ollama": b"binary",
            "metal/core.metallib": b"library",
            "metal/._core.metallib": appledouble_fixture(),
        },
    )
    target = tmp_path / ".local/runtime"
    setup.install_runtime(component, tmp_path)
    assert (target / "metal/core.metallib").read_bytes() == b"library"
    # Pure-Python extraction on both macOS/Linux retains sidecars in staging;
    # published runtime correctly excludes them, as BSD tar may do on macOS.
    assert not (target / "metal/._core.metallib").exists()
    setup.install_runtime(component, tmp_path)
    sidecar = target / "metal/._core.metallib"
    sidecar.write_bytes(b"user-owned extra file, do not overwrite")
    setup.install_runtime(component, tmp_path)
    assert sidecar.read_bytes() == b"user-owned extra file, do not overwrite"
    assert list((tmp_path / ".local").glob("mcpm-runtime-*")) == []


@pytest.mark.parametrize(
    "sidecar_bytes, companion",
    [
        (b"ordinary runtime data", True),
        (b"\x00\x05\x16\x07", True),
        (appledouble_fixture()[:-1], True),
        (appledouble_fixture(), False),
    ],
)
def test_dot_underscore_files_are_not_blindly_excluded(
    tmp_path, monkeypatch, sidecar_bytes, companion
):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    members = {"ollama": b"binary", "metal/._core.metallib": sidecar_bytes}
    if companion:
        members["metal/core.metallib"] = b"library"
    else:
        # A matching basename elsewhere is not a same-directory companion.
        members["core.metallib"] = b"library"
    component = runtime_component(tmp_path, members)
    target = tmp_path / ".local/runtime"
    setup.install_runtime(component, tmp_path)
    sidecar = target / "metal/._core.metallib"
    assert sidecar.read_bytes() == sidecar_bytes
    sidecar.unlink()
    with pytest.raises(setup.SetupError, match="Incomplete runtime: missing metal/._core.metallib"):
        setup.install_runtime(component, tmp_path)
    assert not sidecar.exists()
    assert list((tmp_path / ".local").glob("mcpm-runtime-*")) == []
