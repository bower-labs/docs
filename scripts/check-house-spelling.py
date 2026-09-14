#!/usr/bin/env python3
"""House spelling guard — American English in help-centre prose.

Bower's house style went American on 2026-08-09. The rule list lives in the
Notion tone-of-voice doc and is extracted to `scripts/voice-rules.json`; this
script enforces its `mustFlag.spelling` half. The same extract and an
equivalent check live in `bower-labs/bower` and `bower-labs/website`, so a
researcher reads one dialect across the app, the help center and the marketing
site. Refreshing the Notion doc means refreshing all three copies.

Python rather than Node because this repo has no Node toolchain — `docs-ci.yml`
sets up Python 3.12 for `validate-docs.py` and nothing else. Same rules file,
repo-native runner.

What is scanned: MDX/MD prose, including frontmatter `title` and `description`,
because both render. What is NOT:

* fenced and inline code — a snippet is not our prose;
* URLs and link targets — `/organisation/notes` is a PATH. Renaming the
  `organisation/` directory is a URL migration needing redirects (the
  Trust Center rename is the worked example), not a spelling fix, so paths are
  excluded and the decision is left where it belongs;
* the words inside an `import`/`export` line.

Run: python3 scripts/check-house-spelling.py [--list] [--fix]
Exit 0 = clean, 1 = violations.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "scripts" / "voice-rules.json"

# `.claude` holds agent config AND nested git worktrees — another branch's
# checkout is not this branch's prose, and linting it reports violations no
# commit here can fix. The website hook skips `.claude/` for the same reason.
SKIP_DIRS = {".git", ".claude", "node_modules", "images", "logo"}

# Explicit inflections rather than suffix rules: `analyse` -> `analyze` is not
# an `-ise` -> `-ize` swap (it ends `-yse`), and the `-e` verbs DROP that `e`
# before `-ing`, so `organise` + `ing` is `organiseing`. A suffix-built pattern
# silently misses `organising`, `analysing` and `summarising` — the commonest
# forms in prose.
BASE = {
    "organise": "organize",
    "organisation": "organization",
    "organisational": "organizational",
    "optimise": "optimize",
    "optimisation": "optimization",
    "standardise": "standardize",
    "prioritise": "prioritize",
    "recognise": "recognize",
    "analyse": "analyze",
    "personalise": "personalize",
    "summarise": "summarize",
    "formalise": "formalize",
    "categorise": "categorize",
    "centre": "center",
    "behaviour": "behavior",
    "colour": "color",
    "licence": "license",
    "catalogue": "catalog",
    "litre": "liter",
    "metre": "meter",
    "fibre": "fiber",
    "labelling": "labeling",
    "modelling": "modeling",
    "signalling": "signaling",
    "programme": "program",
}
EXTRA = {
    "behavioural": "behavioral",
    "organisational": "organizational",
    "labelled": "labeled",
    "modelled": "modeled",
    "signalled": "signaled",
    "catalogued": "cataloged",
    "cataloguing": "cataloging",
    "catalogues": "catalogs",
}


def inflections(terms: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for term in terms:
        gb = term.lower()
        us = BASE.get(gb)
        if not us:
            continue
        out[gb] = us
        if gb.endswith("e"):
            out[gb + "s"] = us + "s"
            out[gb + "d"] = us + "d"
            out[gb[:-1] + "ing"] = us[:-1] + "ing"
        else:
            out[gb + "s"] = us + "s"
            out[gb + "ed"] = us + "ed"
            out[gb + "ing"] = us + "ing"
    out.update(EXTRA)
    return out


def blank(match: re.Match[str]) -> str:
    """Same length, same newlines — so offsets survive for `--fix`."""
    return re.sub(r"[^\n]", " ", match.group(0))


def mask(text: str) -> str:
    """Blank everything that is not prose, preserving offsets."""
    text = re.sub(r"```[\s\S]*?```", blank, text)  # fenced code
    text = re.sub(r"`[^`\n]*`", blank, text)  # inline code
    text = re.sub(r"\]\([^)]*\)", blank, text)  # link targets
    text = re.sub(r'href="[^"]*"', blank, text)  # JSX hrefs
    text = re.sub(r"https?://\S+", blank, text)  # bare URLs
    text = re.sub(r"(?m)^(import|export)\s.*$", blank, text)  # MDX imports
    return text


WORD_RE = re.compile(r"[A-Za-z]+")


def scan(table: dict[str, str]) -> list[tuple[Path, int, str, str, str]]:
    hits: list[tuple[Path, int, str, str, str]] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".mdx", ".md"} or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        raw = path.read_text(encoding="utf-8")
        masked = mask(raw)
        for num, line in enumerate(masked.split("\n"), 1):
            for m in WORD_RE.finditer(line):
                us = table.get(m.group(0).lower())
                if us:
                    hits.append((path, num, m.group(0), us, line.strip()[:100]))
    return hits


def fix(table: dict[str, str]) -> int:
    changed = 0
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".mdx", ".md"} or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        raw = path.read_text(encoding="utf-8")
        masked = mask(raw)
        out: list[str] = []
        last = 0
        for m in WORD_RE.finditer(masked):
            us = table.get(m.group(0).lower())
            if not us:
                continue
            word = raw[m.start() : m.end()]
            if word.lower() != m.group(0).lower():
                continue  # masked and raw disagree: leave it alone
            out.append(raw[last : m.start()])
            out.append(us.capitalize() if word[0].isupper() else us)
            last = m.end()
            changed += 1
        if out:
            out.append(raw[last:])
            path.write_text("".join(out), encoding="utf-8")
    return changed


def main() -> int:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    table = inflections(rules["mustFlag"]["spelling"])

    if "--fix" in sys.argv:
        print(f"fixed {fix(table)} occurrence(s) — READ THE DIFF")
        return 0

    hits = scan(table)
    if "--list" in sys.argv:
        for path, num, word, us, ctx in hits:
            print(f"{path.relative_to(ROOT)}:{num}: {word!r} -> {us!r}\n    {ctx}")
        print(f"\n{len(hits)} total")
        return 0

    if hits:
        print(f"\n✖ {len(hits)} British spelling(s) in help-centre prose:\n", file=sys.stderr)
        for path, num, word, us, ctx in hits[:40]:
            print(f"  {path.relative_to(ROOT)}:{num}  {word!r} -> {us!r}\n    {ctx}", file=sys.stderr)
        if len(hits) > 40:
            print(f"  … and {len(hits) - 40} more", file=sys.stderr)
        print(
            "\nHouse style is American. `python3 scripts/check-house-spelling.py --fix`\n"
            "rewrites them; read the diff. Paths and code are excluded by design.\n",
            file=sys.stderr,
        )
        return 1

    print(f"OK — 0 violations (rules v{rules['sourceVersion']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
