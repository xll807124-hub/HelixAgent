"""Install the pinned Gitleaks release after verifying its published SHA-256."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import tarfile
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def install() -> Path:
    config = json.loads((ROOT / "security/tools.json").read_text(encoding="utf-8"))["gitleaks"]
    system = platform.system()
    if system not in config["assets"] or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Supported security tool platforms: Windows/Linux x64")
    asset = config["assets"][system]
    url = ("https://github.com/gitleaks/gitleaks/releases/download/"
           f"v{config['version']}/{asset['filename']}")
    # The host and scheme are fixed above; no user-supplied URL is accepted.
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    data = response.content
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise RuntimeError("Gitleaks release checksum mismatch; installation aborted")
    name = "gitleaks.exe" if system == "Windows" else "gitleaks"
    # Read one known member only: never extract arbitrary archive paths.
    if system == "Windows":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            binary = archive.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = archive.extractfile(name)
            if member is None:
                raise RuntimeError("Gitleaks executable missing from archive")
            binary = member.read()
    dest = ROOT / ".tools" / "gitleaks" / config["version"] / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = dest.with_suffix(".download")
    pending.write_bytes(binary)
    pending.chmod(0o755)
    os.replace(pending, dest)
    return dest


if __name__ == "__main__":
    print(install())
