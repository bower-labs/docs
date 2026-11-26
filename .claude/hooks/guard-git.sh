#!/usr/bin/env bash
# PreToolUse guard for Bash: the rules live in guard-git.py. Any failure to run
# it (no python3, a crash) blocks the call rather than allowing it.
python3 "$(dirname "$0")/guard-git.py"
rc=$?
[ "$rc" -eq 0 ] && exit 0
[ "$rc" -eq 2 ] || echo "Blocked by .claude/hooks/guard-git.sh: the guard itself failed (exit $rc)" >&2
exit 2
