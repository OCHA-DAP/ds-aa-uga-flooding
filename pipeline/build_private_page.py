"""Build the password-protected partner page: pages/partner/index.html.

Some material shaping this design comes from partner documents that are not public — at
present FAO's draft Mt Elgon flood AAP. This repository and its GitHub Pages site are
public, so that material never appears in committed source or in the public pages:

  * the content lives in config/private_frameworks.local.json (gitignored);
  * this script renders it, with images embedded as data URIs so nothing is fetchable on
    its own, into site_private/ (gitignored);
  * staticrypt encrypts that page into pages/partner/index.html, and only the encrypted
    file is committed.

Run:  uv run python pipeline/build_private_page.py      (needs npx for staticrypt)
The password is the team's shared review password; set SITE_PASSWORD to override.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import markdown
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pages as bp
import zones_map

from src.frameworks import EXTERNAL, load_private

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "site_private"
DEST = ROOT / "pages" / "partner" / "index.html"
PASSWORD = os.environ.get("SITE_PASSWORD", "anticipation2026")


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def fao_trigger_table() -> str:
    d = pd.read_csv(bp.OUT / "fao_elgon_triggers.csv")
    d = d[(d.scope == "any of the 7 districts") & (d.events == "major")]
    show = d[["rule", "per_year", "recall", "precision"]].rename(
        columns={
            "rule": "reading of Trigger 3",
            "per_year": "activations per year",
            "recall": "major events caught",
            "precision": "activations with an event",
        }
    )
    return bp.table(
        show,
        {
            "activations per year": lambda v: f"{v:.1f}",
            "major events caught": lambda v: f"{v:.0%}",
            "activations with an event": lambda v: f"{v:.0%}",
        },
    )


def framework_card(fw) -> str:
    notes = "".join(f"<li>{bp.e(n)}</li>" for n in fw.notes)
    return (
        f"<h3>{bp.e(fw.org)} — {bp.e(fw.label)}</h3>"
        f"<p><strong>Districts:</strong> {bp.e(', '.join(fw.districts))}<br>"
        f"<strong>Trigger:</strong> {bp.e(fw.trigger)}<br>"
        f"<strong>Status:</strong> {bp.e(fw.status)}<br>"
        f"<strong>Source:</strong> {bp.e(fw.source)}</p>" + (f"<ul>{notes}</ul>" if notes else "")
    )


def page(priv: dict) -> str:
    fws = priv["frameworks"]
    BUILD.mkdir(exist_ok=True)
    map_png = BUILD / "zones_coverage_map_with_partners.png"
    zones_map.main(frameworks={**EXTERNAL, **fws}, out=map_png)

    section = []
    for block in priv["results_section"]:
        if block == "@@FAO_TABLE@@":
            section.append(fao_trigger_table())
        else:
            section.append(
                block.replace(
                    'src="fao_elgon_triggers.png"',
                    f'src="{data_uri(bp.OUT / "fao_elgon_triggers.png")}"',
                )
            )

    parts = [
        bp.HEAD.format(
            v=bp.ASSET_VERSION,
            title="Partner draft plans",
            sub="Restricted. Material from partner documents that are not yet public, and our analysis of it.",
        ),
        "<p>Everything on the public pages of this site comes from public sources or from our own analysis. This page "
        "holds what does not: the substance of partner plans shared with the team in draft. It is password protected "
        "because the documents themselves are unpublished — please do not forward it outside the team, and check "
        "with the country team before quoting it to the partner concerned.</p>",
        "<h2>Coverage including partner drafts</h2>",
        f'<figure><img src="{data_uri(map_png)}" alt="Map of Uganda with the trigger zones and all known flood AA coverage, including partner drafts">'
        "<figcaption>As on the public coverage page, with unpublished partner drafts added to the coverage panels.</figcaption></figure>",
        "<h2>The drafts</h2>",
        *[framework_card(fw) for fw in fws.values()],
        *section,
        "<h2>Harmonising triggers, including the drafts</h2>",
        bp.harmonisation_table(
            frameworks={**EXTERNAL, **fws},
            short={**bp.SHORT_TRIGGER, **priv.get("short_trigger", {})},
            tags=priv.get("tag", {}),
            notes=priv.get("harmonisation_notes", {}),
        ),
        "<h2>Research notes</h2>",
        markdown.markdown(priv["research_notes_4a"], extensions=["tables"]),
        bp.FOOT.format(today=bp.TODAY).replace(
            "<code>pipeline/build_pages.py</code>", "<code>pipeline/build_private_page.py</code>"
        ),
    ]
    return bp.add_heading_anchors("\n".join(parts))


def main() -> None:
    priv = load_private()
    if not priv:
        print(
            "No config/private_frameworks.local.json — nothing to build (the file is gitignored by design)."
        )
        return
    BUILD.mkdir(exist_ok=True)
    plain = BUILD / "index.html"
    plain.write_text(page(priv))
    enc = BUILD / "encrypted"
    subprocess.run(
        [
            "npx",
            "-y",
            "staticrypt",
            str(plain),
            "-d",
            str(enc),
            "-p",
            PASSWORD,
            "--short",
            "--remember",
            "30",
            "--template-title",
            "Uganda flood AA — partner drafts",
            "--template-instructions",
            "Restricted: unpublished partner material. Password shared internally.",
        ],
        check=True,
    )
    out = (enc / "index.html").read_text()
    # belt and braces: the encrypted file must not contain any of the plaintext
    probe = next(iter(priv["frameworks"].values())).trigger[:40]
    if probe in out or "<h2>" in out:
        raise SystemExit("FATAL: encrypted output contains plaintext — not writing it to pages/")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(out)
    print(f"wrote {DEST.relative_to(ROOT)} (encrypted, {len(out) // 1024} KB)")


if __name__ == "__main__":
    main()
