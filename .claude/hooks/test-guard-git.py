"""Feeds guard-git.sh the payload Claude Code sends and checks its verdict.

Run: python3 .claude/hooks/test-guard-git.py (CI and the pre-commit hook run it).
"""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).with_name("guard-git.sh")

BLOCK = [
    # force push, +refspec, --mirror
    "git push --force origin x",
    'git push "--force" origin x',
    "git push '-f' origin x",
    "git push --forc origin x",
    "git push -uf origin x",
    "git push origin +main",
    "git push origin +HEAD:main",
    "git push --mirror",
    # destructive local commands
    "git reset --hard origin/main",
    "git reset --ha",
    "git clean -fd",
    "git clean --force",
    "git checkout -- .",
    "git checkout .",
    "git checkout -- index.mdx",
    "git checkout -f main",
    "git restore .",
    "git restore index.mdx",
    "git restore --staged --worktree .",
    "git stash clear",
    "git branch -D old",
    "git branch -Dq old",
    "git branch --delete --force old",
    "git branch -df old",
    # skipping hooks
    "git commit --no-verify -m x",
    "git commit --no-verif -m x",
    "git commit -n -m x",
    "git commit -nm x",
    "git push --no-verify",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git config core.hooksPath /dev/null",
    "git config --unset core.hooksPath",
    # wrapped forms
    "cd /tmp && git push --force",
    "git status; git reset --hard",
    "git status\ngit push --force",
    'bash -c "git push --force"',
    "sh -c 'git clean -fdx'",
    "eval git reset --hard",
    'eval "git stash clear"',
    "env git push -f",
    "env GIT_TRACE=1 git push --force",
    "command git branch -D x",
    "/usr/bin/git reset --hard",
    "GIT_DIR=.git git push --force",
    "git -C ../other push --force",
    "git commit -F - <<'EOF'\nmsg\nEOF\ngit push origin +main",
]

ALLOW = [
    "git status",
    "git diff --stat",
    "git push -u origin feat/x",
    "git push --force-with-lease origin feat/x",
    "git push -n origin feat/x",
    "git log -n 3 && git commit -m x",
    "git push origin x && rm -f build.log",
    'git commit -m "block -f and -n in the guard"',
    'git commit -m "never git reset --hard or git push --force"',
    "git commit -mn",
    "git commit -F - <<'EOF'\nfix: block git push --force, -n and git branch -D\nEOF",
    "git reset --soft HEAD~1",
    "git reset HEAD index.mdx",
    "git clean -n",
    "git checkout main",
    "git checkout -b feat/x origin/main",
    "git restore --staged index.mdx",
    "git stash list",
    "git stash push -u -m wip-tag",
    "git branch -d merged",
    "git branch --format=%(refname)",
    "git worktree list",
    "python3 scripts/validate-docs.py",
    'echo "unbalanced',
    "",
]


def verdict(command, raw=None):
    payload = raw if raw is not None else json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}}
    )
    return subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True
    ).returncode


failures = []
for cmd in BLOCK:
    if verdict(cmd) != 2:
        failures.append(f"should block: {cmd!r}")
for cmd in ALLOW:
    if verdict(cmd) != 0:
        failures.append(f"should allow: {cmd!r}")
if verdict("", raw="{not json") != 2:
    failures.append("should block unreadable hook input")

for f in failures:
    print(f, file=sys.stderr)
print(f"guard-git: {len(BLOCK) + len(ALLOW) + 1 - len(failures)} passed, {len(failures)} failed")
sys.exit(1 if failures else 0)
