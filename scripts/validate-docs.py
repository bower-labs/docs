#!/usr/bin/env python3
"""Validate the Mintlify docs site before it ships.

Nine checks, all of which can genuinely fail on a realistic mistake:

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
5. Every `#anchor` in an internal link or a redirect destination names a real
   heading on the target page. A stale fragment fails silently: the reader
   lands at the top of the page. When this check was added, four were live,
   all on headings with an apostrophe or quotes, which Mintlify keeps in the
   anchor (`when-there’s-no-wi-fi`) while authors type them without.
6. Every redirect lands on a real page in one hop: its destination exists and
   is not itself a redirect source, and its source is not a live page (which
   would shadow the redirect).
7. No sentence of 10+ words appears on two pages. A fact written twice drifts
   the first time someone updates one copy; keep it on the page that owns it
   and link there. Exact matching only catches copy-paste; reworded repeats
   are a reviewer's job (AGENTS.md, "Concise, with one source of truth").
8. Every published page, `.mdx` or `.md`, is in the navigation. A page outside
   it has no sidebar entry, so readers and search engines reach it only by luck.
9. The Voice commands tables are as generated in bower-labs/bower (no hand
   edit, none missing or doubled), and no other page carries its own voice
   command or glasses button table.

It also prints the longest pages (not a failure): long pages are where
repetition and drift collect, so they are the first to trim.

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


MINTLIFY_DEFAULT_IGNORES = {"README.md", "LICENSE.md", "CHANGELOG.md", "CONTRIBUTING.md"}


def mintignored(path: Path) -> bool:
    """True when Mintlify will not publish this file: a default ignore, or a
    name or path listed in .mintignore (literal entries and `dir/` prefixes)."""
    rel = path.relative_to(ROOT)
    if str(rel) in MINTLIFY_DEFAULT_IGNORES:
        return True
    ignore = ROOT / ".mintignore"
    if not ignore.is_file():
        return False
    for raw in ignore.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.endswith("/") and str(rel).startswith(entry):
            return True
        if Path(str(rel)).match(entry):
            return True
    return False


def page_file(slug: str) -> Path | None:
    slug = slug.strip("/") or "index"
    for candidate in chain(
        (ROOT / f"{slug}{s}" for s in PAGE_SUFFIXES),
        (ROOT / slug / f"index{s}" for s in PAGE_SUFFIXES),
    ):
        if candidate.is_file():
            return candidate
    return None


def asset_exists(path: str) -> bool:
    candidate = ROOT / path.strip("/")
    return candidate.is_file()


# --- Anchors ----------------------------------------------------------------
#
# Mintlify's heading anchors, verified against `mint dev` for all 711 "plain"
# headings on the site (2026-10-16): lowercase, spaces to hyphens, `? . , : ( )
# /` dropped. It KEEPS apostrophes (as ’), curly quotes, `&`, `—` and most other
# symbols, and drops a few (`↔`), so those anchors cannot be predicted reliably.
# Rather than mirror that, a heading that something links to must be plain.

FRAGMENT_LINK_RE = re.compile(
    r"\]\((/[^)\s#]*)?#([^)\s]+)(?:\s+\"[^\"]*\")?\)|href=[\"'](/[^\"'\s#]*)?#([^\"'\s]+)[\"']"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
ID_ATTR_RE = re.compile(r"""\bid=["']([^"']+)["']""")
SNIPPET_IMPORT_RE = re.compile(r"""^import\s+\w+\s+from\s+["'](/snippets/[^"']+)["']""", re.M)
PLAIN_HEADING_RE = re.compile(r"^[A-Za-z0-9 ?.,:()/-]+$")


def heading_text(raw: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("**", "").replace("`", "").strip()


def mintlify_slug(raw: str) -> str:
    text = heading_text(raw).replace("'", "’").lower()
    text = re.sub(r"[^\w\s’-]", "", text)
    return re.sub(r"\s", "-", text.strip())


def page_anchors(path: Path, seen: set[Path] | None = None) -> dict[str, str]:
    """anchor -> heading text for one page, including imported snippets and
    explicit `id=` attributes (which map to themselves)."""
    seen = seen or set()
    seen.add(path)
    text = path.read_text(encoding="utf-8")
    anchors: dict[str, str] = {}
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            anchors.setdefault(mintlify_slug(heading.group(2)), heading_text(heading.group(2)))
        for anchor in ID_ATTR_RE.findall(line):
            anchors.setdefault(anchor, anchor)
    for snippet in SNIPPET_IMPORT_RE.findall(text):
        snippet_path = ROOT / snippet.lstrip("/")
        if snippet_path.is_file() and snippet_path not in seen:
            for anchor, label in page_anchors(snippet_path, seen).items():
                anchors.setdefault(anchor, label)
    return anchors


def check_anchor(
    where: str, page: str, fragment: str, redirects: dict[str, str], problems: list[str]
) -> None:
    page = page.strip("/") or "index"
    if page in redirects:
        page = redirects[page].split("#", 1)[0].strip("/") or "index"
    target = page_file(page)
    if target is None:
        return  # a missing page is check 3's (or check 6's) problem
    anchors = page_anchors(target)
    if fragment not in anchors:
        problems.append(
            f"{where}: '#{fragment}' is not a heading on /{page}. If you renamed the "
            f"heading, update this link. Headings that are linked to must use only "
            f"letters, digits, spaces, hyphens and ?.,:()/ (Mintlify keeps "
            f"apostrophes, quotes, & and dashes in the anchor)."
        )
    elif not PLAIN_HEADING_RE.match(anchors[fragment]) and fragment != anchors[fragment]:
        problems.append(
            f"{where}: '#{fragment}' links to the heading \"{anchors[fragment]}\" on "
            f"/{page}, whose anchor depends on punctuation. Reword the heading with "
            f"only letters, digits, spaces, hyphens and ?.,:()/, then update its links."
        )


# --- Duplicate sentences ----------------------------------------------------
#
# Changelog entries summarize the feature page they link to, by design, and
# snippets exist to be shared, so both are out of scope.
DUPLICATE_MIN_WORDS = 10
DUPLICATE_EXEMPT_DIRS = ("changelog", "snippets")


JSX_TEXT_ATTR_RE = re.compile(r"""\b(?:title|description)=["']([^"']+)["']""")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def prose_body(text: str) -> str:
    """Body prose of a page: no frontmatter, code, tables, JSX tags, imports,
    link targets or Markdown markup. Every block boundary (blank line, heading,
    list item, skipped line) is a newline, so a heading or a bullet never fuses
    with the sentence after it; hard-wrapped lines of one paragraph stay joined."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    parts: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if FENCE_RE.match(line):
            in_fence = not in_fence
            parts.append("\n")
            continue
        if in_fence or not stripped or stripped.startswith(("import ", "{/*")):
            parts.append("\n")
            continue
        if stripped.startswith("|"):  # a table: each cell is a block of its own
            parts.append("\n" + "\n".join(stripped.strip("|").split("|")) + "\n")
            continue
        attrs = JSX_TEXT_ATTR_RE.findall(line)
        if attrs:
            parts.append("\n" + "\n".join(attrs) + "\n")
        if stripped.startswith("<"):  # JSX: keep any text, as a block of its own
            parts.append("\n" + re.sub(r"<[^>]+>", " ", line) + "\n")
            continue
        if HEADING_RE.match(stripped):
            parts.append("\n" + stripped + "\n")
            continue
        if LIST_MARKER_RE.match(line):
            parts.append("\n" + LIST_MARKER_RE.sub("", line))
            continue
        parts.append(line)
    body = " ".join(parts)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"[*_`#>]", " ", body)


def prose_sentences(text: str):
    """(normalized, original) for each sentence of DUPLICATE_MIN_WORDS+ words."""
    for sentence in re.split(r"(?<=[.!?])\s+|\s*\n\s*", prose_body(text)):
        normalized = " ".join(re.sub(r"[^a-z0-9 ]", "", sentence.lower()).split())
        if len(normalized.split()) >= DUPLICATE_MIN_WORDS:
            yield normalized, " ".join(sentence.split())


def check_duplicates(pages: list[Path], problems: list[str]) -> None:
    where: dict[str, list[str]] = {}
    example: dict[str, str] = {}
    for path in pages:
        rel = path.relative_to(ROOT)
        if rel.parts[0] in DUPLICATE_EXEMPT_DIRS:
            continue
        for normalized, original in prose_sentences(path.read_text(encoding="utf-8")):
            files = where.setdefault(normalized, [])
            if str(rel) not in files:
                files.append(str(rel))
            example.setdefault(normalized, original)
    for normalized, files in sorted(where.items()):
        if len(files) > 1:
            problems.append(
                f"the same sentence is on {', '.join(files)}: \"{example[normalized][:120]}\". "
                f"Keep it on the page that owns the fact and link there from the others."
            )


# --- Voice commands -----------------------------------------------------------
#
# Every voice phrase and glasses button press lives in one list in
# bower-labs/bower (packages/shared/src/constants/voiceCommands.ts, decision
# 0013 there), rendered into VOICE_COMMANDS_PAGE between generated markers by
# `pnpm docs:voice:generate`. Each START marker carries the sha256 of the table
# it wraps, so a hand edit inside the markers fails here; the fix is to change
# the list in bower and regenerate. A "Say" or glasses "Press" table on any
# other page is a second copy of the list, which is how the help center ended
# up documenting timers that never existed (2026-10-27).

VOICE_COMMANDS_PAGE = Path("ai-and-search/voice-commands-by-device.mdx")
VOICE_COMMANDS_TABLES = ("glassesIdle", "glassesButton", "live", "browserStandby", "protocolRun")
VOICE_BLOCK_RE = re.compile(
    r"^\{/\* VOICE_COMMANDS:(\w+) START sha256=([0-9a-f]{64})[^\n]*\*/\}\n(.*?)\n\{/\* VOICE_COMMANDS:\1 END \*/\}$",
    re.MULTILINE | re.DOTALL,
)
# A command table's header row, also when indented inside a component (<Tab>)
# or bolded. Only changelog entries may quote old command tables: they record
# what shipped then. Snippets are checked, since pages import them. A single
# example phrase in a sentence that links to the Voice commands page is allowed
# (the one-line mention the single-source rule permits); a table is a copy.
VOICE_TABLE_HEADER_RE = re.compile(r"^[ \t]*\|\s*\**(Say|Press)\**\s*\|", re.MULTILINE)
VOICE_TABLE_EXEMPT_DIRS = ("changelog",)


def voice_block_problems(text: str) -> list[str]:
    """What is wrong with the generated blocks on the Voice commands page."""
    problems = []
    found = {}
    for match in VOICE_BLOCK_RE.finditer(text):
        table, expected, body = match.groups()
        if table in found:
            # The generator rewrites only the first copy, so a second one goes stale.
            problems.append(f"{VOICE_COMMANDS_PAGE}: the generated '{table}' table appears twice; keep one.")
        found[table] = True
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != expected:
            problems.append(
                f"{VOICE_COMMANDS_PAGE}: the '{table}' table was edited by hand. Change "
                "packages/shared/src/constants/voiceCommands.ts in bower-labs/bower and run "
                "`pnpm docs:voice:generate` instead."
            )
    for table in VOICE_COMMANDS_TABLES:
        if table not in found:
            problems.append(f"{VOICE_COMMANDS_PAGE}: the generated '{table}' table or its markers are missing.")
    return problems


def voice_page_problems(rel: Path, text: str) -> list[str]:
    """What is wrong with one page: on the Voice commands page, its generated
    tables and anything written outside them; elsewhere, a command table."""
    problems = []
    if rel == VOICE_COMMANDS_PAGE:
        problems.extend(voice_block_problems(text))
        text = VOICE_BLOCK_RE.sub("", text)
    elif rel.parts[0] in VOICE_TABLE_EXEMPT_DIRS:
        return problems
    if VOICE_TABLE_HEADER_RE.search(text):
        problems.append(
            f"{rel} has a voice command or button table written by hand. Link to "
            f"/{VOICE_COMMANDS_PAGE.with_suffix('')} instead, where the one list is generated."
        )
    return problems


def check_voice_commands(pages: list[Path], problems: list[str]) -> None:
    for path in pages:
        problems.extend(voice_page_problems(path.relative_to(ROOT), path.read_text(encoding="utf-8")))


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

    # --- Check 5: anchors resolve ---------------------------------------------
    redirect_entries = [
        r for r in config.get("redirects", []) if isinstance(r, dict) and r.get("source")
    ]
    redirects = {r["source"].strip("/"): r.get("destination", "") for r in redirect_entries}
    if len(redirects) != len(redirect_entries):
        seen_sources: set[str] = set()
        for r in redirect_entries:
            source = r["source"].strip("/")
            if source in seen_sources:
                problems.append(f"docs.json has two redirects from '/{source}'; keep one.")
            seen_sources.add(source)
    content_pages = [
        p for p in sorted(ROOT.rglob("*.mdx")) if is_site_content(p)
    ]
    for path in content_pages:
        rel = path.relative_to(ROOT)
        own = str(rel.with_suffix(""))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in FRAGMENT_LINK_RE.finditer(line):
                page = match.group(1) or match.group(3) or own
                fragment = match.group(2) or match.group(4)
                check_anchor(f"{rel}:{lineno}", page, fragment, redirects, problems)

    # --- Check 6: every redirect lands on a page in one hop -------------------
    for source, destination in redirects.items():
        dest_page, _, fragment = destination.partition("#")
        dest_page = dest_page.strip("/")
        if ":" in source or "*" in source or destination.startswith(("http://", "https://")):
            continue  # a wildcard maps a whole tree; an external URL is not ours to check
        if page_file(source) is not None:
            problems.append(
                f"docs.json redirect '/{source}' is shadowed by a live page with that "
                f"path. Delete the page or the redirect."
            )
        if dest_page in redirects:
            problems.append(
                f"docs.json redirect '/{source}' -> '{destination}' chains through another "
                f"redirect. Point it at '{redirects[dest_page]}' directly."
            )
        elif page_file(dest_page) is None:
            problems.append(f"docs.json redirect '/{source}' points at missing page '{destination}'.")
        elif fragment:
            check_anchor(f"docs.json redirect '/{source}'", dest_page, fragment, redirects, problems)

    # --- Check 7: no sentence repeated across pages ---------------------------
    check_duplicates(content_pages, problems)

    # --- Check 9: voice commands are the generated list, written once ---------
    check_voice_commands(content_pages, problems)

    # --- Check 8: every page is in the navigation ------------------------------
    # Mintlify also publishes .md files (a root ASSISTANT.md was live at
    # /ASSISTANT), except the ones it ignores by default or by .mintignore.
    nav_set = {slug.strip("/") for slug in nav_pages}
    published_md = [
        p for p in sorted(ROOT.rglob("*.md"))
        if is_site_content(p) and not mintignored(p)
    ]
    for path in content_pages + published_md:
        rel = path.relative_to(ROOT)
        if rel.parts[0] == "snippets":
            continue
        if str(rel.with_suffix("")) not in nav_set:
            problems.append(f"{rel} is not in docs.json navigation, so nothing in the sidebar leads to it.")

    if problems:
        fail(problems)

    word_counts = sorted(
        (
            (len(prose_body(p.read_text(encoding="utf-8")).split()), p)
            for p in content_pages
            if p.relative_to(ROOT).parts[0] not in DUPLICATE_EXEMPT_DIRS
        ),
        reverse=True,
    )
    print("Longest pages (words of prose; trim these first):")
    for words, path in word_counts[:5]:
        print(f"  {words:>5}  {path.relative_to(ROOT)}")
    print(
        f"✔ docs.json valid · {len(nav_pages)} navigation pages resolve · "
        f"internal links across {len(known_pages)} pages resolve · "
        f"brand assets and colors match the 2026-08 identity · anchors and "
        f"{len(redirects)} redirects resolve · no sentence repeated across pages · every page in the navigation · voice commands written once"
    )


if __name__ == "__main__":
    main()
