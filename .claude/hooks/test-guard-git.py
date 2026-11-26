"""Feeds guard-git.sh the payload Claude Code sends and checks every verdict.

Run: python3 .claude/hooks/test-guard-git.py (CI runs it through pnpm test).
Cases come from two files next to this one:
- guard-git.cases.json: shared across the Bower repos, byte-identical, never
  edited in one repo (its header names its source repo and commit).
- guard-git.cases.local.json: this repo's intentional differences, as
  `overrides` (command -> "allow" or "block", replacing a shared verdict) and
  extra local `cases`, and `shared_sha256`, the hash of the shared file it
  was copied at. An override for a command the shared file lacks, or has more
  than once (on a branch and on main), is an error.
The shared file pins guard-git.py by hash too, so editing the guard, or the
shared file, in one repo alone fails here. Copying across repos stays manual.
Each verdict runs in a scratch repo holding the shared file's scratch_files,
on branch claude/test ("branch") or main ("main"). Exit 1 on any mismatch.
Standard library only, so other repos can copy this runner unchanged.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "guard-git.sh"
# Run from a git hook, git exports GIT_INDEX_FILE and friends; the scratch
# repos and the guard must not write into the outer commit's index.
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
EXIT = {"block": 2, "allow": 0}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    with open(HERE / name, encoding="utf-8") as f:
        return json.load(f)


def scratch_repo(path, branch, files, refs):
    """A repo with known files and refs on a known branch, so the verdicts do not
    depend on which branch CI or a developer happens to have checked out."""
    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=ENV)
    path.mkdir(parents=True)
    git("init", "-q", "-b", branch)
    for name in files:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text("x\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    for ref in refs:
        git("update-ref", ref, "HEAD")
    return path


def verdict(payload, cwd):
    return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True,
                          cwd=cwd, env=ENV).returncode


def main():
    shared, local = load("guard-git.cases.json"), load("guard-git.cases.local.json")
    overrides = local.get("overrides", {})
    failures = []
    # The pins: the guard is the one the shared cases were written for, and the
    # shared file is the one this repo last copied (not edited in place).
    if sha256(HERE / "guard-git.py") != shared["guard_sha256"]:
        failures.append("guard-git.py differs from the guard_sha256 the shared cases pin; "
                        "change the guard and guard-git.cases.json together")
    if sha256(HERE / "guard-git.cases.json") != local.get("shared_sha256"):
        failures.append("guard-git.cases.json differs from the shared_sha256 in "
                        "guard-git.cases.local.json; copy the shared file whole, then update the pin")
    counts = {}
    for c in shared["cases"]:
        counts[c["command"]] = counts.get(c["command"], 0) + 1
    for cmd, expect in overrides.items():
        if cmd not in counts:
            failures.append(f"override for a command the shared file does not have: {cmd!r}")
        elif counts[cmd] > 1:
            failures.append(f"override for a command the shared file has more than once: {cmd!r}; "
                            "add a local case instead")
        if expect not in EXIT:
            failures.append(f"override must be allow or block: {cmd!r}")
    cases = [{**c, "expect": overrides.get(c["command"], c["expect"])} for c in shared["cases"]]
    cases += local.get("cases", [])
    files = sorted(set(shared["scratch_files"]) | set(local.get("scratch_files", [])))
    with tempfile.TemporaryDirectory() as tmp:
        repos = {on: scratch_repo(Path(tmp, on), b, files, shared["scratch_refs"])
                 for on, b in (("branch", "claude/test"), ("main", "main"))}
        for c in cases:
            on = c.get("on", "branch")
            cmd = c["command"].replace("{branch_repo}", str(repos["branch"])).replace(
                "{main_repo}", str(repos["main"]))
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
            if verdict(payload, repos[on]) != EXIT.get(c["expect"]):
                failures.append(f"should {c['expect']} (on {on}): {c['command']!r}")
        for raw in ("{not json", '{"tool_name":"Bash","tool_input":{"command":42}}'):
            if verdict(raw, repos["branch"]) != 2:
                failures.append(f"should block unreadable hook input: {raw!r}")
    for f in failures:
        print(f, file=sys.stderr)
    total = len(cases) + 2
    print(f"guard-git: {total - len(failures)} passed, {len(failures)} failed "
          f"({len(shared['cases'])} shared from {shared['source']}, {len(overrides)} overridden, "
          f"{len(local.get('cases', []))} local)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
