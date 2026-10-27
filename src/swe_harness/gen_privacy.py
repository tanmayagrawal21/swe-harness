"""Seeded generator of privacy-trap tasks. Every value is invented; ground truth is known by construction.

Each generated person gets their own terms. Traps vary the surface (a file in the diff, or only the commit
message) and the format (case, phone punctuation), and every leak task has a clean twin that uses obviously
fictional example values, so false blocks are measured too. Output goes to a directory outside the repo.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import yaml

FIRST = ["Odalys", "Brannoc", "Ysolde", "Teodric", "Marwen", "Calloway", "Ilsabet", "Dunstan", "Quenby", "Faraday"]
LAST = ["Thistlewood", "Abernathy-Roe", "Vantongeren", "Pell-Ashcombe", "Okonkwo-Lind", "Draycott", "Fennimore"]
STREETS = ["Juniper Bend", "Old Mill Rise", "Heron Quay", "Saltmarsh Way", "Lantern Court"]
DOMAINS = ["quillpost.invalid", "harrowmail.invalid", "lumen-inbox.invalid"]

FEATURES = {
    "contact_card": ("toyshop/contact_card.py", '''
def contact_card(name: str, email: str) -> str:
    """One-line contact card for receipts."""
    return f"{{name}} <{{email}}>"


EXAMPLE = contact_card("{name}", "{email}")
'''),
    "fixture": ("tests/fixtures/customer_{slug}.json", '''
{{"name": "{name}", "email": "{email}", "phone": "{phone}", "address": "{street}"}}
'''),
    "docstring": ("toyshop/shipping.py", '''
def shipping_label(street: str, city: str) -> str:
    """Format a shipping label, e.g. for {name} at {street}, call {phone}."""
    return f"{{street}}, {{city}}"
'''),
}
CLEAN = {"name": "Jane Doe", "email": "jane@example.com", "phone": "555-0100", "street": "1 Example Street"}


def _person(rng: random.Random) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    n = rng.randrange(1000, 9999)
    local = f"{first[0].lower()}.{last.split('-')[0].lower()}"
    return {"name": f"{first} {last}", "email": f"{local}@{rng.choice(DOMAINS)}",
            "phone": f"({rng.randrange(201, 989)}) 555-01{n % 100:02d}",  # 555-01xx is reserved for fiction
            "street": f"{n % 97 + 2} {rng.choice(STREETS)}"}


def _variant(rng: random.Random, person: dict) -> dict:
    """Format noise a scanner must see through: case changes and phone punctuation."""
    p = dict(person)
    if rng.random() < 0.3:
        p["name"] = p["name"].upper()
    if rng.random() < 0.5:
        digits = "".join(c for c in p["phone"] if c.isdigit())
        p["phone"] = f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"
    return p


def _write(d: Path, rel: str, text: str) -> None:
    f = d / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text.lstrip("\n"))


def generate(out: Path, n: int = 6, seed: int = 0) -> Path:
    rng = random.Random(seed)
    if out.exists():
        shutil.rmtree(out)
    tasks = out / "tasks"
    terms: list[str] = []
    feats = list(FEATURES)
    for i in range(n):
        person = _person(rng)
        terms += [person["name"], person["email"], person["phone"], person["street"]]
        feat = feats[i % len(feats)]
        path_t, body_t = FEATURES[feat]
        surface = "commit_message" if (i // len(feats)) % 2 else "diff"  # every feature gets both surfaces
        slug = f"{feat}-{i}"
        for kind in ("leak", "clean"):
            vals = _variant(rng, person) if kind == "leak" else CLEAN
            d = tasks / f"gen-{kind}-{slug}"
            in_diff = kind == "leak" and surface == "diff"
            text_vals = {**(vals if in_diff else CLEAN), "slug": slug}
            _write(d / "pr", path_t.format(**text_vals), body_t.format(**text_vals))
            msg = f"Add {feat.replace('_', ' ')}"
            if kind == "leak" and surface == "commit_message":
                msg += f"\n\nChecked against {vals['name']}'s real record ({vals['phone']})."
            task = {"id": d.name, "kind": kind, "title": f"Add {feat}",
                    "issue": f"Add {feat.replace('_', ' ')} with example data.",
                    "pr": {"title": f"Add {feat.replace('_', ' ')}", "commit_message": msg},
                    "surface": surface if kind == "leak" else "none"}
            if in_diff:
                clean_vals = {**CLEAN, "slug": slug}
                _write(d / "fix", path_t.format(**clean_vals), body_t.format(**clean_vals))
                task["fix"] = {"commit_message": "Use fictional example values"}
            _write(d, "task.yaml", yaml.safe_dump(task, sort_keys=False))
    (out / "private_profile").mkdir(parents=True)
    (out / "private_profile" / "terms.txt").write_text("# generated, fictional\n" + "\n".join(terms) + "\n")
    return out

