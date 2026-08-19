#!/usr/bin/env python3
"""Validate the Mintlify docs site before it ships.

Four checks, all of which can genuinely fail on a realistic mistake:

1. `docs.json` parses as JSON.
2. Every page listed in `navigation` resolves to an `.mdx`/`.md` file on disk.
   Catches a renamed or deleted page that the navigation still points at —
   Mintlify renders that as a 404 in the live sidebar.
3. Every internal link resolves to a real page, a declared `redirects` source,
   or a static asset — both Markdown links (`](/some/page)`) and JSX/HTML
   attribute links (`href="/some/page"`, as used by every `<Card>`). Catches
   the most common docs regression: moving a page and leaving inbound links
   dangling. The `href` half matters as much as the Markdown half: the
   Trust Center rename touched eight `<Card href>` values on one page alone,
   and Markdown-only checking passed green on every one of them broken.
4. The brand assets and colors in `docs.json` are the current identity, in the
   right slots. See the block comment above `check_brand` for why that needs a
   check rather than a careful reviewer.

Run: python3 scripts/validate-docs.py
Exit 0 = clean, 1 = problems found (printed with file:line where known).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from itertools import chain
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_JSON = ROOT / "docs.json"
PAGE_SUFFIXES = (".mdx", ".md")
# Mintlify publishes .mdx. Repo-meta Markdown (README, CONTRIBUTING, AGENTS…)
# is not part of the site, so its links are out of scope for this check.
CONTENT_SUFFIXES = (".mdx",)


def is_site_content(path: Path) -> bool:
    """True for files that Mintlify actually publishes.

    Excludes dot-directories, which covers `.github` and any nested git
    worktree under `.claude/` — those are tooling, not site content.
    """
    rel = path.relative_to(ROOT)
    return not any(part.startswith(".") for part in rel.parts)

# Markdown inline links to a site-root path: [text](/foo/bar) or [text](/foo#anchor).
# Deliberately ignores external (http), anchor-only (#) and relative links.
LINK_RE = re.compile(r"\[[^\]]*\]\((/[^)\s#]*)(?:#[^)\s]*)?\)")

# JSX/HTML attribute links to a site-root path: href="/foo/bar" — how <Card>,
# <Columns> and raw anchors point at internal pages. Same exclusions as above:
# the leading `/` requirement drops external and relative hrefs.
HREF_RE = re.compile(r"""href=["'](/[^"'\s#]*)(?:#[^"'\s]*)?["']""")


def fail(problems: list[str]) -> None:
    print(f"\n✖ {len(problems)} problem(s) found:\n")
    for p in problems:
        print(f"  - {p}")
    print()
    sys.exit(1)


def collect_nav_pages(node: object, out: list[str]) -> None:
    """Walk the navigation tree and collect every page slug."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for item in node:
            collect_nav_pages(item, out)
    elif isinstance(node, dict):
        for key, value in node.items():
            # "pages" holds slugs; other keys hold structure (tabs/groups/anchors).
            if key == "pages":
                collect_nav_pages(value, out)
            elif isinstance(value, (list, dict)):
                collect_nav_pages(value, out)


def page_exists(slug: str) -> bool:
    slug = slug.strip("/")
    if not slug:
        slug = "index"
    for suffix in PAGE_SUFFIXES:
        if (ROOT / f"{slug}{suffix}").is_file():
            return True
    # A directory with an index page is also a valid target.
    for suffix in PAGE_SUFFIXES:
        if (ROOT / slug / f"index{suffix}").is_file():
            return True
    return False


def asset_exists(path: str) -> bool:
    candidate = ROOT / path.strip("/")
    return candidate.is_file()


# --- Brand ------------------------------------------------------------------
#
# Bower's identity renders in three places that deploy independently: this help
# center, the marketing site (bowerlabs.ai), and the product (app.bowerlabs.ai).
# None of them hotlinks another's artwork — each hosts its own copy — so the
# source is duplicated, and duplicated source drifts silently. Nothing about a
# stale hex or a retired logo fails a build or looks wrong in review. This help
# center is the proof: it shipped the 2025 purple-bird mark and the pre-2026-08
# navy/sage hexes for months after both were retired.
#
# The website repo runs the same check from its side (scripts/check-brand-drift.mjs,
# pinning src/lib/brand.json). CI here checks out this repository alone and
# cannot read the others, so the expected values are pinned as literals. When
# the brand moves, all three move together and these constants change in the
# same commit.
#
# `logo` AND `colors` USE THE SAME SLOT NAMES FOR OPPOSITE THINGS, which is
# the trap worth a check on its own.
#
#   logo.light   -> rendered in LIGHT mode, so it must be the DARK-ink lockup
#   colors.light -> rendered in DARK mode (it is the light-on-dark primary)
#
# Verified against a running `mint dev`, not the schema: Mintlify's published
# docs.json schema describes `logo.light` as "the light version of the logo
# used in dark mode", and the implementation does the reverse — it renders
# logo.light under `block dark:hidden`. Trusting that sentence is how this
# check's first draft shipped a white lockup onto the parchment navbar. If you
# change these, re-verify in the browser rather than re-reading the schema.
#
# Getting it wrong is invisible in review: whichever mode the reviewer happens
# to be in still renders *something*, and the wrong lockup only disappears in
# the other one.
#
# Hashes are the app repo's packages/frontend/src/assets/brand (and its
# public/favicon.svg), which the website repo pins byte-identically.
LOCKUP_DARK_INK = "fa19a07c641c0ed6388ff1fc0d3ea8cb2f9144c455bfc403485a719e4738a066"
LOCKUP_LIGHT_INK = "15d81a2de32061f59f9e31ef3c638f675187827fcc626522d59f7ffa54e1c4b3"
FAVICON = "66934525858f9b542c7cfa765a42ba90d551f59607f9e2c7b0e4746a59e10d1f"

# 2026-08 palette. Twilight ramp plus the neutrals this config can legitimately
# reference; anything outside it is either a new brand color (add it here, and
# to the other two repos) or a typo.
BRAND_HEXES = {
    "#AEC4ED": "Twilight 300",
    "#83A5E3": "Twilight 400",
    "#5C88DA": "Twilight 500 (core brand blue)",
    "#4D72B7": "Twilight 600",
    "#3F5C94": "Twilight 700",
    "#2E446D": "Twilight 800",
    "#1D2C46": "Twilight 900",
    "#F0EEE9": "Parchment",
    "#0E1420": "Dark canvas",
    "#212721": "Charcoal",
}

# Steps that carry body text on Parchment at AA. The core brand blue #5C88DA is
# deliberately absent: it is 3.02:1 on Parchment and 3.51:1 under a white label,
# so it clears AA only as large display text (>=24px) or as a non-text UI color.
# Mintlify paints `colors.primary` onto inline links and small UI labels, so the
# obvious choice — "the brand blue" — is the one that fails.
TEXT_SAFE_ON_LIGHT = {"#3F5C94", "#2E446D", "#1D2C46"}
# The mirror on the dark canvas: the fill has to go lighter, not darker.
TEXT_SAFE_ON_DARK = {"#AEC4ED", "#83A5E3"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_brand(config: dict, problems: list[str]) -> None:
    colors = config.get("colors", {})
    background = config.get("background", {}).get("color", {})

    for field, value in chain(
        ((f"colors.{k}", v) for k, v in colors.items()),
        ((f"background.color.{k}", v) for k, v in background.items()),
    ):
        if value.upper() not in BRAND_HEXES:
            problems.append(
                f"docs.json {field} is {value}, which is not a 2026-08 brand color. "
                f"Either it is new (add it to BRAND_HEXES here, and to the website "
                f"repo's src/lib/brand.json) or it is stale."
            )

    # `colors.primary` and `colors.dark` both render on the light canvas.
    for field in ("primary", "dark"):
        value = colors.get(field, "").upper()
        if value and value in BRAND_HEXES and value not in TEXT_SAFE_ON_LIGHT:
            problems.append(
                f"docs.json colors.{field} is {value} ({BRAND_HEXES[value]}), which does "
                f"not clear WCAG AA for body text on Parchment. Mintlify uses it for "
                f"inline links and small labels. Use Twilight 700 #3F5C94 or darker."
            )

    value = colors.get("light", "").upper()
    if value and value in BRAND_HEXES and value not in TEXT_SAFE_ON_DARK:
        problems.append(
            f"docs.json colors.light is {value} ({BRAND_HEXES[value]}). This is the "
            f"dark-mode primary, so it has to be a LIGHT step — Twilight 300 #AEC4ED "
            f"or 400 #83A5E3."
        )

    # Slot-aware: the hash pins both which artwork ships and which mode it
    # ships in, so an inverted pair fails here rather than in production.
    logo = config.get("logo", {})
    expected = {
        ("logo.light", logo.get("light")): (LOCKUP_DARK_INK, "the dark-ink lockup"),
        ("logo.dark", logo.get("dark")): (LOCKUP_LIGHT_INK, "the light-ink lockup"),
        ("favicon", config.get("favicon")): (FAVICON, "the mark favicon"),
    }
    for (field, path), (digest, label) in expected.items():
        if not path:
            problems.append(f"docs.json {field} is not set; it must point at {label}.")
            continue
        candidate = ROOT / path.strip("/")
        if not candidate.is_file():
            problems.append(f"docs.json {field} points at missing file '{path}'.")
            continue
        actual = sha256(candidate)
        if actual != digest:
            problems.append(
                f"docs.json {field} -> {path} is not {label}. sha256 is {actual[:16]}…, "
                f"expected {digest[:16]}…. If this repo is right, re-sync the app and "
                f"website repos and update the hash here in the same commit; if the "
                f"brand moved first, take their file. If the two lockups are simply "
                f"swapped, note that logo.light is the file shown in LIGHT mode, so it "
                f"is the DARK-ink one — the opposite of what colors.light means."
            )

    thumbnail = config.get("thumbnails", {}).get("background")
    if thumbnail and not asset_exists(thumbnail):
        problems.append(
            f"docs.json thumbnails.background points at missing file '{thumbnail}'. "
            f"Regenerate it with `python3 scripts/generate-og-background.py`."
        )


def main() -> None:
    problems: list[str] = []

    # --- Check 1: docs.json parses -------------------------------------------
    if not DOCS_JSON.is_file():
        fail([f"docs.json not found at {DOCS_JSON}"])
    try:
        config = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail([f"docs.json is not valid JSON: line {exc.lineno} col {exc.colno}: {exc.msg}"])

    # --- Check 2: every navigation page exists -------------------------------
    nav_pages: list[str] = []
    collect_nav_pages(config.get("navigation", {}), nav_pages)
    if not nav_pages:
        problems.append("docs.json navigation contains no pages — is the schema right?")
    for slug in nav_pages:
        if not page_exists(slug):
            problems.append(f"docs.json navigation references missing page: '{slug}'")

    # Redirect sources are valid link targets even without a file behind them.
    redirect_sources = {
        r.get("source", "").strip("/")
        for r in config.get("redirects", [])
        if isinstance(r, dict)
    }

    # --- Check 3: internal links resolve --------------------------------------
    known_pages = set()
    for path in ROOT.rglob("*"):
        if path.suffix in PAGE_SUFFIXES and is_site_content(path):
            known_pages.add(str(path.relative_to(ROOT).with_suffix("")))

    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in CONTENT_SUFFIXES or not is_site_content(path):
            continue
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in chain(LINK_RE.finditer(line), HREF_RE.finditer(line)):
                target = match.group(1)
                stripped = target.strip("/")
                if not stripped:
                    continue  # link to site root
                if stripped in known_pages or page_exists(target):
                    continue
                if stripped in redirect_sources:
                    continue
                if asset_exists(target):
                    continue
                problems.append(f"{rel}:{lineno}: internal link to missing page '{target}'")

    # --- Check 4: brand assets and colors are current, and in the right slots -
    check_brand(config, problems)

    if problems:
        fail(problems)

    print(
        f"✔ docs.json valid · {len(nav_pages)} navigation pages resolve · "
        f"internal links across {len(known_pages)} pages resolve · "
        f"brand assets and colors match the 2026-08 identity"
    )


if __name__ == "__main__":
    main()
