"""Feeds guard-git.sh the payload Claude Code sends and checks its verdict.

Run: python3 .claude/hooks/test-guard-git.py (CI runs it; the pre-commit hook
runs it when .claude/hooks/ changes). Cases come from guard-git.cases.json,
shared byte for byte with the other repos that copy this guard, and
guard-git.overrides.json, this repo's own. Each verdict runs in a scratch repo
holding the fixture files, on the case's branch, so it does not depend on the
branch CI or a developer has checked out.
"""

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "guard-git.sh"
# Run from a git hook (pre-commit), git exports GIT_INDEX_FILE and friends; the
# scratch repos and the guard must not write into the outer commit's index.
ENV = {k: v for k, v in os.environ.items()
       if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
# A developer's own ~/.gitconfig and system config (aliases, hooksPath) must not
# reach the guard, so verdicts match CI's. HOME is set to the scratch dir below.
ENV["GIT_CONFIG_NOSYSTEM"] = "1"

shared = json.loads((HERE / "guard-git.cases.json").read_text(encoding="utf-8"))
overrides = json.loads((HERE / "guard-git.overrides.json").read_text(encoding="utf-8"))
FILES = shared["fixture_files"] + overrides.get("fixture_files", [])
REFS = shared["fixture_refs"]
CONFIG = overrides.get("fixture_config", {})
CONFIG_MAIN = overrides.get("fixture_config_main", {})  # only in the main scratch repo
# An override replaces the shared case with the same command and branch.
key = lambda c: (c.get("command", c.get("raw")), c["branch"])
replaced = {key(c) for c in overrides["cases"]}
CASES = [c for c in shared["cases"] if key(c) not in replaced] + overrides["cases"]
bad = [c for c in CASES if c.get("expect") not in ("allow", "deny")
       or c.get("branch") not in ("claude/test", "main") or ("command" in c) == ("raw" in c)]
if bad:
    sys.exit(f"guard-git: malformed cases (expect allow|deny, branch claude/test|main, "
             f"one of command/raw): {bad[:3]}")


def scratch_repo(path, branch):
    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=ENV)
    path.mkdir(parents=True)
    git("init", "-q", "-b", branch)
    for name in FILES:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text("x\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    for ref in REFS:
        git("update-ref", ref, "HEAD")
    for name, value in {**CONFIG, **(CONFIG_MAIN if branch == "main" else {})}.items():
        git("config", name, value)
    return path


def run(case, repos):
    if "raw" in case:
        payload, label = case["raw"], case["raw"]
    else:
        label = case["command"].replace("{branch_repo}", str(repos["claude/test"]))
        label = label.replace("{main_repo}", str(repos["main"]))
        body = {"tool_name": "Bash", "tool_input": {"command": label}}
        if "cwd" in case:  # the payload's cwd, which the guard moves into
            body["cwd"] = case["cwd"].replace("{main_repo}", str(repos["main"]))
        payload = json.dumps(body)
    got = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True,
                         cwd=repos[case["branch"]], env=ENV).returncode
    want = 2 if case["expect"] == "deny" else 0
    return None if got == want else f"should {case['expect']} on {case['branch']}: {label!r}"


with tempfile.TemporaryDirectory() as tmp:
    ENV["HOME"] = tmp
    repos = {"claude/test": scratch_repo(Path(tmp, "branch"), "claude/test"),
             "main": scratch_repo(Path(tmp, "main"), "main")}
    # The guard only reads the scratch repos, so the cases can run side by side.
    with ThreadPoolExecutor(max_workers=8) as pool:
        failures = [f for f in pool.map(lambda c: run(c, repos), CASES) if f]

for f in failures:
    print(f, file=sys.stderr)
print(f"guard-git: {len(CASES) - len(failures)} passed, {len(failures)} failed "
      f"({len(shared['cases'])} shared, {len(overrides['cases'])} docs overrides)")
sys.exit(1 if failures else 0)
