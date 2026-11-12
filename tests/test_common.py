"""Exclusive output must not leave partial files or remove another file."""

import os

import pytest

from minicpm_tools import common
from minicpm_tools.common import ToolError


@pytest.mark.parametrize("failure", [OSError("disk failure"), KeyboardInterrupt()])
def test_write_new_removes_only_its_partial_file(tmp_path, monkeypatch, failure):
    target = tmp_path / "report.md"
    real_fdopen = os.fdopen

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, text):
            self.stream.write(text[:4])
            raise failure

    monkeypatch.setattr(common.os, "fdopen", lambda *a, **kw: FailingWriter(real_fdopen(*a, **kw)))
    with pytest.raises(type(failure)):
        common.write_new(target, "complete report")
    assert not target.exists()


def test_write_new_preserves_replacement_created_during_failure(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    real_fdopen = os.fdopen

    class ReplacedWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, text):
            target.unlink()
            target.write_text("other process data", encoding="utf-8")
            raise OSError("simulated failure")

    monkeypatch.setattr(common.os, "fdopen", lambda *a, **kw: ReplacedWriter(real_fdopen(*a, **kw)))
    with pytest.raises(OSError, match="simulated"):
        common.write_new(target, "complete report")
    assert target.read_text(encoding="utf-8") == "other process data"


def test_write_new_closes_descriptor_if_fdopen_fails(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    descriptors = []

    def fail_open(fd, *args, **kwargs):
        descriptors.append(fd)
        raise OSError("cannot create stream")

    monkeypatch.setattr(common.os, "fdopen", fail_open)
    with pytest.raises(OSError, match="cannot create stream"):
        common.write_new(target, "report")
    assert not target.exists()
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_write_new_closes_fd_and_preserves_path_if_identity_unavailable(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    real_open, real_fstat = os.open, os.fstat
    descriptors = []

    def tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        descriptors.append(fd)
        return fd

    def fail_target_stat(fd):
        if descriptors and fd == descriptors[0]:
            raise OSError("cannot check identity")
        return real_fstat(fd)

    with monkeypatch.context() as context:
        context.setattr(common.os, "open", tracked_open)
        context.setattr(common.os, "fstat", fail_target_stat)
        with pytest.raises(OSError, match="cannot check identity"):
            common.write_new(target, "report")
    # Without an identity it is unsafe to unlink a potentially replaced path.
    assert target.exists() and target.stat().st_size == 0
    with pytest.raises(OSError):
        real_fstat(descriptors[0])


def test_write_new_rejects_existing_file(tmp_path):
    target = tmp_path / "report.md"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(ToolError, match="拒绝覆盖"):
        common.write_new(target, "new")
    assert target.read_text(encoding="utf-8") == "existing"
