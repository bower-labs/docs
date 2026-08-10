#!/usr/bin/env python3
"""Validate the Mintlify docs site before it ships.

Three checks, all of which can genuinely fail on a realistic mistake:

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

Run: python3 scripts/validate-docs.py
Exit 0 = clean, 1 = problems found (printed with file:line where known).
"""

from __future__ import annotations

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

    if problems:
        fail(problems)

    print(
        f"✔ docs.json valid · {len(nav_pages)} navigation pages resolve · "
        f"internal links across {len(known_pages)} pages resolve"
    )


if __name__ == "__main__":
    main()
