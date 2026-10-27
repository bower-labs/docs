#!/usr/bin/env python3
"""Planted cases for validate-docs.py's detectors, so a detector cannot go
blind and stay green (check 7 did once: headings fused with the next
sentence hid 18% of sentences). Run: python3 scripts/test-validate-docs.py"""

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("validate_docs", HERE / "validate-docs.py")
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)

TARGET = "Bower signs you out after thirty minutes of inactivity in every workspace."
NORMALIZED = "bower signs you out after thirty minutes of inactivity in every workspace"

PLANTED = {
    "after a heading": f"## Idle timeout\n{TARGET} More text.\n",
    "mid-paragraph": f"Some words first. {TARGET} And after.\n",
    "as a bullet": f"- {TARGET}\n",
    "hard-wrapped": "Bower signs you out after thirty minutes\nof inactivity in every workspace.\n",
    "in a one-line Note": f"<Note>{TARGET}</Note>\n",
    "in a table cell": f"| Setting | Value |\n| --- | --- |\n| Timeout | {TARGET} |\n",
    "in a title attribute": f'<Step title="{TARGET}">\n',
}


def planted_site_failures() -> list[str]:
    """Run the real validator on a copy of the site with a second command table
    planted, so the check's wiring into main() is held, not just its helper."""
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        shutil.copytree(vd.ROOT, site, ignore=shutil.ignore_patterns(".git", ".claude", "node_modules"))
        capture = site / "bower-glasses" / "capture.mdx"
        capture.write_text(
            capture.read_text(encoding="utf-8") + "\n| Say | What happens |\n| --- | --- |\n| *\"Go live\"* | Starts. |\n",
            encoding="utf-8",
        )
        run = subprocess.run(
            [sys.executable, str(site / "scripts" / "validate-docs.py")], capture_output=True, text=True
        )
    if run.returncode == 0 or "written by hand" not in run.stdout + run.stderr:
        return ["validate-docs.py passes a site with a second command table: check_voice_commands is not run"]
    return []


def main() -> None:
    failures = []
    for case, text in PLANTED.items():
        found = {n for n, _ in vd.prose_sentences(text)}
        if NORMALIZED not in found:
            failures.append(f"check 7 does not see a sentence {case}: got {sorted(found)}")

    slugs = {
        "What is on a run record?": "what-is-on-a-run-record",
        "How do I see the runs of a protocol?": "how-do-i-see-the-runs-of-a-protocol",
        "Step **A.1** and `code`": "step-a1-and-code",
    }
    for heading, expected in slugs.items():
        if vd.mintlify_slug(heading) != expected:
            failures.append(f"slug of {heading!r} is {vd.mintlify_slug(heading)!r}, not {expected!r}")
    if not vd.PLAIN_HEADING_RE.match("What is on a run record?"):
        failures.append("a plain heading is not treated as plain")
    if vd.PLAIN_HEADING_RE.match("What's on a run record?"):
        failures.append("a heading with an apostrophe is treated as plain")

    if not vd.mintignored(vd.ROOT / "README.md"):
        failures.append("README.md should be ignored by Mintlify by default")
    if vd.mintignored(vd.ROOT / "ASSISTANT.md"):
        failures.append("a root ASSISTANT.md is published by Mintlify and must count for check 8")

    body = "| Say | What happens |\n| --- | --- |\n| *\"Take a photo\"* | Takes a photo. |"
    good = "\n\n".join(
        f"{{/* VOICE_COMMANDS:{table} START sha256={vd.hashlib.sha256(body.encode()).hexdigest()} x */}}\n"
        f"{body}\n{{/* VOICE_COMMANDS:{table} END */}}"
        for table in vd.VOICE_COMMANDS_TABLES
    )
    if vd.voice_block_problems(good):
        failures.append(f"generated voice tables are flagged: {vd.voice_block_problems(good)}")
    edited = good.replace("Takes a photo.", "Takes a picture.", 1)
    if not any("edited by hand" in p for p in vd.voice_block_problems(edited)):
        failures.append("a hand edit inside a generated voice table is not caught")
    if not any("missing" in p for p in vd.voice_block_problems(good.split("\n\n", 1)[1])):
        failures.append("a missing generated voice table is not caught")
    page = vd.VOICE_COMMANDS_PAGE
    if vd.voice_page_problems(page, good):
        failures.append(f"the generated Voice commands page is flagged: {vd.voice_page_problems(page, good)}")
    say = "| Say | What happens |\n| --- | --- |\n| *\"Go live\"* | Starts. |\n"
    second_copies = {
        "on another page": (Path("bower-glasses/capture.mdx"), f"Intro.\n\n{say}"),
        "indented in a <Tab>": (
            Path("bower-glasses/capture.mdx"),
            "<Tabs>\n  <Tab title=\"Glasses\">\n    " + say.replace("\n", "\n    ") + "</Tab>\n</Tabs>\n",
        ),
        "with a bold header": (Path("bower-glasses/capture.mdx"), say.replace("| Say |", "| **Say** |")),
        "in a snippet": (Path("snippets/glasses-visual-guide.mdx"), say),
        "on the Voice commands page outside the markers": (page, f"{good}\n\n{say}"),
        "as a glasses Press table": (Path("bower-glasses/capture.mdx"), "| Press | What |\n| --- | --- |\n"),
    }
    for case, (rel, text) in second_copies.items():
        if not any("written by hand" in p for p in vd.voice_page_problems(rel, text)):
            failures.append(f"a hand-written command table {case} is not caught")
    if vd.voice_page_problems(Path("changelog/2026-03-22-wake-word-standby.mdx"), say):
        failures.append("a changelog entry quoting an old command table is flagged")
    failures.extend(planted_site_failures())

    if failures:
        print("\n".join(f"✖ {f}" for f in failures))
        raise SystemExit(1)
    print(f"✔ {len(PLANTED)} planted repeats seen, {len(slugs)} slugs, plain-heading and ignore rules hold")


if __name__ == "__main__":
    main()
