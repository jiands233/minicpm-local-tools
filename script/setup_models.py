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
        if path.exists():
            raise SetupError(
                f"Destination appeared during download: {item['destination']}; left untouched."
            )
        os.replace(temporary, path)
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


def install_runtime(component, root=ROOT):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SetupError("This pinned runtime setup is verified for Apple Silicon macOS only.")
    archive = destination(component["files"][0], root)
    if not verify(archive, component["files"][0]):
        raise SetupError(
            "Download/check the runtime archive first; installation never downloads implicitly."
        )
    target = root / ".local/runtime"
    binary = target / "ollama"
    if binary.is_file():
        if binary.is_symlink():
            raise SetupError("Existing runtime binary is a symlink; left untouched.")
        # --version can report the running server, not this client binary.
        with tarfile.open(archive) as tar:
            member = tar.getmember("ollama")
            if not member.isfile():
                raise SetupError("Expected regular Ollama binary in verified archive.")
            with tar.extractfile(member) as expected, binary.open("rb") as actual:
                while True:
                    expected_block = expected.read(4 * 1024 * 1024)
                    actual_block = actual.read(4 * 1024 * 1024)
                    if expected_block != actual_block:
                        raise SetupError(
                            "Existing Ollama binary differs from verified archive; left untouched."
                        )
                    if not expected_block:
                        break
        print(f"Ollama {component['version']} local binary matches verified archive.")
        return
    with tempfile.TemporaryDirectory(prefix="mcpm-runtime-", dir=root / ".local") as temp:
        staging = Path(temp)
        with tarfile.open(archive) as tar:
            # data filter rejects traversal, escaping links, special files and unsafe modes.
            tar.extractall(staging, filter="data")
        if not (staging / "ollama").is_file():
            raise SetupError("Verified archive did not contain expected Ollama binary.")
        items = list(staging.iterdir())
        if any(
            (target / item.name).exists() or (target / item.name).is_symlink() for item in items
        ):
            raise SetupError("Existing runtime files would be overwritten; left untouched.")
        target.mkdir(parents=True, exist_ok=True)
        for item in items:
            os.replace(item, target / item.name)
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
