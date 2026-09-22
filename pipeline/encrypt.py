"""Encrypt a built page with staticrypt for the restricted parts of the Pages site.

This repository and its GitHub Pages site are public. Pages carrying material from partner
documents that are not published are built in plaintext into the gitignored site_private/,
encrypted here, and only the encrypted file is written under pages/. The password is the
team's shared review password (override with SITE_PASSWORD); staticrypt's salt lives in the
committed .staticrypt.json so "remember me" survives rebuilds.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = os.environ.get("SITE_PASSWORD", "anticipation2026")


def encrypt_page(plain: Path, dest: Path, title: str, instructions: str, probes: list[str]) -> None:
    """Encrypt `plain` into `dest`. Refuses to write if any probe string (text that must only
    ever appear encrypted) survives in the output, or if the output still has headings."""
    enc_dir = plain.parent / f"{plain.stem}_encrypted"
    subprocess.run(
        [
            "npx",
            "-y",
            "staticrypt",
            str(plain),
            "-d",
            str(enc_dir),
            "-p",
            PASSWORD,
            "--short",
            "--remember",
            "30",
            "--template-title",
            title,
            "--template-instructions",
            instructions,
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
    )
    out = (enc_dir / plain.name).read_text()
    leaked = [p for p in probes if p and p in out]
    if leaked or "<h2" in out:
        raise SystemExit(
            f"FATAL: encrypted output of {plain.name} contains plaintext {leaked} — not written"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out)
    print(f"wrote {dest.relative_to(ROOT)} (encrypted, {len(out) // 1024} KB)")
