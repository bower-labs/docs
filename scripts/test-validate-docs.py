#!/usr/bin/env python3
"""Planted cases for validate-docs.py's detectors, so a detector cannot go
blind and stay green (check 7 did once: headings fused with the next
sentence hid 18% of sentences). Run: python3 scripts/test-validate-docs.py"""

import importlib.util
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

    if failures:
        print("\n".join(f"✖ {f}" for f in failures))
        raise SystemExit(1)
    print(f"✔ {len(PLANTED)} planted repeats seen, {len(slugs)} slugs, plain-heading and ignore rules hold")


if __name__ == "__main__":
    main()
