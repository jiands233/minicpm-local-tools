#!/usr/bin/env python3
"""Explicit, checksum-verified local model setup. Uses only Python stdlib + curl."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from itertools import pairwise
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("models.json")


class SetupError(Exception):
    pass


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise SetupError("Unsupported model manifest version")
    return data["components"]


def destination(item, root=ROOT):
    path = root / item["destination"]
    if not path.resolve().is_relative_to((root / ".local").resolve()) or path.is_symlink():
        raise SetupError("Model destination must remain inside .local and cannot be a symlink")
    return path


def verify(path, item):
    if not path.is_file() or path.stat().st_size != item["size"]:
        return False
    digest = hashlib.sha256()
    blob = (
        hashlib.sha1(b"blob " + str(item["size"]).encode() + b"\0")
        if "git_blob_sha1" in item
        else None
    )
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
            if blob:
                blob.update(block)
    return digest.hexdigest() == item["sha256"] and (
        blob is None or blob.hexdigest() == item["git_blob_sha1"]
    )


def source_url(component, item):
    if component["kind"] == "runtime":
        return item["url"]
    return f"https://huggingface.co/{component['repo']}/resolve/{component['revision']}/{quote(item['path'])}"


def download_file(component, item, root=ROOT):
    path = destination(item, root)
    if path.exists():
        if verify(path, item):
            print(f"Verified existing: {item['destination']}", flush=True)
            return path
        raise SetupError(
            f"Existing file failed checksum: {item['destination']}. Move/remove it explicitly before retrying."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".download", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        print(f"Downloading {item['path']} ({item['size'] / 1_000_000:.1f} MB)", flush=True)
        # No verbose/header/error output: CDN redirect URLs can contain signed credentials.
        # -q disables user curlrc; no cookies, headers or tokens are supplied.
        result = subprocess.run(
            [
                "curl",
                "-q",
                "--fail",
                "--location",
                "--silent",
                "--retry",
                "3",
                "--connect-timeout",
                "30",
                "--max-time",
                "7200",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--output",
                str(temporary),
                source_url(component, item),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            raise SetupError(
                f"Download failed for {item['path']} (curl exit {result.returncode}); no model file was published."
            )
        if not verify(temporary, item):
            raise SetupError(f"SHA256/size mismatch for {item['path']}; downloaded file discarded.")
        # The target can appear at any time after the initial existence check.
        # A same-directory hard link publishes atomically without replacing it.
        # os.replace here would silently clobber a file created during download.
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise SetupError(
                f"Destination appeared during download: {item['destination']}; left untouched."
            ) from exc
        print(f"Verified SHA256: {item['path']}", flush=True)
        return path
    finally:
        temporary.unlink(missing_ok=True)


def check_components(components, selected, root=ROOT):
    ok = True
    for key in selected:
        for item in components[key]["files"]:
            valid = verify(destination(item, root), item)
            print(f"{'OK' if valid else 'MISSING/INVALID'} {key}: {item['destination']}")
            ok &= valid
    return ok


def ollama_path(root=ROOT):
    local = root / ".local/runtime/ollama"
    if local.is_file():
        return str(local)
    installed = shutil.which("ollama")
    if not installed:
        raise SetupError("Ollama not found. Install the pinned runtime first; see docs/models.md.")
    return installed


def modelfile(component, root=ROOT):
    lines = []
    for item in component["files"]:
        path = destination(item, root)
        if not verify(path, item):
            raise SetupError(
                f"Missing or invalid weights: {item['destination']}; run download/check first."
            )
        # JSON quoting is valid for Modelfile paths and handles spaces.
        lines.append("FROM " + json.dumps(str(path)))
    lines.append("PARAMETER num_ctx 8192")
    if component["kind"] == "text":
        lines.extend(["PARAMETER temperature 0", "PARAMETER top_p 0.95"])
    elif component["kind"] == "ocr":
        lines.append("PARAMETER temperature 0")
    return "\n".join(lines) + "\n"


def register(components, selected, root=ROOT):
    binary = ollama_path(root)
    env = dict(
        os.environ,
        OLLAMA_HOST="127.0.0.1:11434",
        OLLAMA_MODELS=str(root / ".local/models"),
        OLLAMA_NO_CLOUD="1",
    )
    for key in selected:
        component = components[key]
        if not component.get("model_name"):
            raise SetupError(f"{key} is not an Ollama model; it does not require register.")
        text = modelfile(component, root)
        directory = root / ".local/modelfiles"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.Modelfile"
        path.write_text(text, encoding="utf-8")
        print(
            f"Registering verified {key} as {component['model_name']} on 127.0.0.1:11434",
            flush=True,
        )
        # FROM uses verified local files, so create never pulls weights remotely.
        result = subprocess.run(
            [binary, "create", component["model_name"], "-f", str(path)], env=env, check=False
        )
        if result.returncode:
            raise SetupError(
                f"Ollama registration failed for {key}; start script/serve_models.sh first."
            )


def same_file_bytes(expected, actual):
    with expected.open("rb") as left, actual.open("rb") as right:
        while True:
            left_block = left.read(4 * 1024 * 1024)
            right_block = right.read(4 * 1024 * 1024)
            if left_block != right_block:
                return False
            if not left_block:
                return True


def is_appledouble_sidecar(path):
    """Recognize a valid v2 AppleDouble companion, not arbitrary ._ filenames.

    BSD tar on macOS can absorb these into xattrs instead of materializing them.
    Python/Linux extraction retains them as files; neither form is a runtime
    dependency. The corresponding entry must exist in the same staging directory.
    """
    if not path.name.startswith("._") or path.name[2:] in {"", ".", ".."}:
        return False
    if path.is_symlink() or not path.is_file():
        return False
    companion = path.with_name(path.name[2:])
    if not companion.exists() and not companion.is_symlink():
        return False
    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(26)
        if len(header) != 26 or header[:8] != b"\x00\x05\x16\x07\x00\x02\x00\x00":
            return False
        count = int.from_bytes(header[24:26], "big")
        table_end = 26 + count * 12
        if table_end > size:
            return False
        identifiers = set()
        spans = []
        for _ in range(count):
            entry = stream.read(12)
            identifier = int.from_bytes(entry[:4], "big")
            offset = int.from_bytes(entry[4:8], "big")
            length = int.from_bytes(entry[8:12], "big")
            if identifier in identifiers or offset < table_end or offset + length > size:
                return False
            identifiers.add(identifier)
            if length:
                spans.append((offset, offset + length))
        spans.sort()
        return all(left[1] <= right[0] for left, right in pairwise(spans))


def verify_runtime_tree(staging, target, entries):
    """Check every extracted member, without following installed symlinks."""
    for expected in entries:
        relative = expected.relative_to(staging)
        actual = target / relative
        mismatch = (
            f"Existing runtime member differs from verified archive: {relative}; left untouched."
        )
        if not actual.exists() and not actual.is_symlink():
            raise SetupError(
                f"Incomplete runtime: missing {relative}; existing files left untouched."
            )
        if expected.is_symlink():
            if not actual.is_symlink() or os.readlink(actual) != os.readlink(expected):
                raise SetupError(mismatch)
        elif actual.is_symlink():
            raise SetupError(mismatch)
        elif expected.is_dir():
            if not actual.is_dir():
                raise SetupError(mismatch)
        elif expected.is_file():
            if not actual.is_file() or not same_file_bytes(expected, actual):
                raise SetupError(mismatch)
            # A byte-identical executable that has lost execute permission is
            # still unusable. Compare the owner bit, not umask-dependent group bits.
            if bool(expected.stat().st_mode & 0o100) != bool(actual.stat().st_mode & 0o100):
                raise SetupError(mismatch)
        else:
            raise SetupError(f"Unsupported runtime archive member: {relative}")


def install_runtime(component, root=ROOT):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SetupError("This pinned runtime setup is verified for Apple Silicon macOS only.")
    archive = destination(component["files"][0], root)
    if not verify(archive, component["files"][0]):
        raise SetupError(
            "Download/check the runtime archive first; installation never downloads implicitly."
        )
    target = root / ".local/runtime"
    with tempfile.TemporaryDirectory(prefix="mcpm-runtime-", dir=root / ".local") as temp:
        staging = Path(temp)
        with tarfile.open(archive) as tar:
            # Apply the same traversal/link validation to fresh installs and reuse.
            tar.extractall(staging, filter="data")
        binary = staging / "ollama"
        if binary.is_symlink() or not binary.is_file():
            raise SetupError("Verified archive did not contain expected regular Ollama binary.")
        # rglob does not descend into symlink directories; parents sort before children.
        entries = [item for item in sorted(staging.rglob("*")) if not is_appledouble_sidecar(item)]
        if any(
            (target / item.relative_to(staging)).exists()
            or (target / item.relative_to(staging)).is_symlink()
            for item in entries
        ):
            verify_runtime_tree(staging, target, entries)
            print(f"Ollama {component['version']} complete local runtime matches verified archive.")
            return
        target.mkdir(parents=True, exist_ok=True)
        for item in entries:
            destination_path = target / item.relative_to(staging)
            try:
                if item.is_symlink():
                    os.symlink(os.readlink(item), destination_path)
                elif item.is_dir():
                    destination_path.mkdir(mode=item.stat().st_mode & 0o777)
                elif item.is_file():
                    # Exclusive link publication also preserves executable modes.
                    # Never replace a file that appeared after the preflight check.
                    os.link(item, destination_path)
                else:
                    raise SetupError(
                        f"Unsupported runtime archive member: {item.relative_to(staging)}"
                    )
            except FileExistsError as exc:
                raise SetupError(
                    "Runtime destination appeared during installation; existing file left untouched. "
                    "Installation is incomplete; inspect .local/runtime before retrying."
                ) from exc
    print(f"Installed Ollama {component['version']} inside .local/runtime; no system installation.")


def main(argv=None):
    components = load_manifest()
    parser = argparse.ArgumentParser(
        description="Explicit downloads and pinned SHA256 verification for local models"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser(
        "download", help="Download explicitly selected components, verify before publish"
    )
    download.add_argument("components", choices=list(components), nargs="+")
    check = commands.add_parser("check", help="Verify local files, no network")
    check.add_argument("components", choices=list(components), nargs="*")
    register_parser = commands.add_parser(
        "register", help="Register selected verified weights with local Ollama"
    )
    register_parser.add_argument(
        "components", choices=[k for k, v in components.items() if v.get("model_name")], nargs="+"
    )
    commands.add_parser(
        "install-runtime", help="Extract a previously downloaded and verified runtime"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            for key in args.components:
                for item in components[key]["files"]:
                    download_file(components[key], item)
        elif args.command == "check":
            return 0 if check_components(components, args.components or list(components)) else 1
        elif args.command == "register":
            register(components, args.components)
        elif args.command == "install-runtime":
            install_runtime(components["runtime"])
        return 0
    except (SetupError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled; unfinished download removed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
