"""PreToolUse guard for Bash: blocks the git commands this repo forbids
(AGENTS.md): force-push (--force-with-lease is allowed), skipping hooks
(--no-verify, HUSKY=0, core.hooksPath), reset --hard, clean -f, and (added in
this repo) checkout/switch/restore that discards edits or resets a branch
(-B/-C), stash clear, branch -D, pushes to main, --upload-pack/--receive-pack
and GIT_CONFIG_GLOBAL/SYSTEM on a hooked command.

The command is split the way the shell splits it (quotes, &&, ;, |), so a
quoted flag is still a flag, a commit message is never read as flags, and one
command's flags never count against the next. git accepts any unambiguous
prefix of a long option (--no-verif), so prefixes are matched too. Exit 2
blocks the call; anything this cannot parse is blocked, never waved through.
"""

import json
import os
import re
import shlex
import subprocess
import sys

OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;", "\n", "`"}
# Commands that run their argument as shell code: only their quoted arguments
# are checked as nested commands, so `echo "git reset --hard"` is text.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "eval", "xargs"}
# Subcommands that run hooks, so --no-verify skips them.
HOOKED = ("commit", "push", "merge", "rebase", "am", "cherry-pick", "revert")
PROTECTED = {"main", "master"}
# `<<EOF`, `<<-'END-MSG'`; not a `<<<` here-string.
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(['\"]?)([^\s'\"<>;|&()]+)\1")
# Env assignments that point git at another config file, which may set core.hooksPath.
CONFIG_ENV = ("GIT_CONFIG_GLOBAL=", "GIT_CONFIG_SYSTEM=", "GIT_CONFIG=")
# git's own options that take the next token as their value.
GIT_VALUE_OPTS = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                  "--config-env"}
# commit options whose value is the next token (a message must not read as flags).
COMMIT_VALUE_OPTS = {"-m", "-F", "-c", "-C", "-t", "--message", "--file", "--template",
                     "--reuse-message", "--reedit-message", "--author", "--date",
                     "--fixup", "--squash", "--trailer", "--cleanup"}


def block(reason):
    print(f"Blocked by .claude/hooks/guard-git.sh: {reason}", file=sys.stderr)
    sys.exit(2)


def is_prefix(arg, option, shortest):
    """git takes any unambiguous prefix of a long option, down to `shortest`."""
    return len(arg) >= len(shortest) and option.startswith(arg)


def strip_heredocs(cmd):
    """Drop heredoc bodies: they are text (a commit message, usually), and an
    apostrophe in one ("don't") must not make the whole command unparseable."""
    lines, out, ends = cmd.split("\n"), [], []
    for line in lines:
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        out.append(line)
        ends = [m.group(2) for m in HEREDOC_RE.finditer(line)]
    if ends and "git" in cmd:
        block("a heredoc never closes; refusing rather than guessing where commands resume")
    return "\n".join(out)


def drop_redirects(seg):
    """`git checkout main 2>/dev/null`: a redirect and its target are not arguments."""
    out, skip = [], False
    for t in seg:
        if skip:
            skip = False
        elif t and set(t) <= set("<>&") and ("<" in t or ">" in t):
            skip = True
            if out and out[-1].isdigit():
                out.pop()
        else:
            out.append(t)
    return out


def is_rev(arg):
    try:
        return subprocess.run(["git", "rev-parse", "--verify", "--quiet", arg + "^{commit}"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def tokens(cmd):
    # A newline ends a command just as `;` does, so it is punctuation here;
    # a backtick opens a command substitution just as `$(` does.
    lex = shlex.shlex(strip_heredocs(cmd), posix=True, punctuation_chars="();<>|&`\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    return list(lex)


def segments(toks):
    """Commands, split on the shell's operators. A heredoc body (a commit
    message, usually) is text, not commands, so it is skipped to its delimiter."""
    seg, heredoc, pending = [], None, None
    for n, t in enumerate(toks):
        if heredoc is not None:
            if t == "\n":
                if seg == [heredoc]:
                    heredoc = None
                seg = []
            else:
                seg.append(t)
            continue
        if t in ("<<", "<<-") and n + 1 < len(toks):
            pending = toks[n + 1].lstrip("-")
        if t == "\n" and pending is not None:
            heredoc, pending = pending, None
        if t in OPERATORS:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(t)
    if seg:
        yield seg


def check_git(args, husky_off, config_env=False):
    """args: everything after the `git` token."""
    configs, i = [], 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in GIT_VALUE_OPTS and i + 1 < len(args):
            if args[i] in ("-c", "--config-env"):
                configs.append(args[i + 1])
            i += 2
        else:
            if args[i].startswith("--config-env="):
                configs.append(args[i].split("=", 1)[1])
            i += 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]
    if any(c.lower().startswith("core.hookspath") for c in configs):
        block("overriding core.hooksPath skips the hooks; fix the failure instead")
    if sub in HOOKED:
        if config_env:
            block("pointing git at another config file can skip the hooks")
        if husky_off and sub in ("commit", "push"):
            block("HUSKY=0 skips the hooks; fix the failure instead")
        if sub != "commit" and any(is_prefix(a, "--no-verify", "--no-veri") for a in rest):
            block("--no-verify skips the hooks; fix the failure instead")
    if any(a.startswith(("--upload-pack", "--receive-pack", "--exec=")) for a in rest):
        block("--upload-pack/--receive-pack/--exec run an arbitrary program")
    if sub == "config" and any(a.lower() == "core.hookspath" for a in rest):
        block("changing core.hooksPath skips the hooks")
    if sub == "push":
        for a in rest:
            if is_prefix(a, "--force", "--for") or a == "--mirror":
                block("force-push is not allowed; use --force-with-lease only if you must")
            if a.startswith("-") and not a.startswith("--") and "f" in a[1:]:
                block("force-push is not allowed; use --force-with-lease only if you must")
            if a.startswith("+"):
                block("a +refspec force-pushes; use --force-with-lease only if you must")
            if a == "--all" or a == "--branches":
                block("git push --all pushes main too; push your branch by name")
        refspecs = [a for a in rest if not a.startswith("-")][1:]  # after the remote
        for r in refspecs:
            dst = r.rsplit(":", 1)[-1].removeprefix("refs/heads/")
            if dst in PROTECTED:
                block("pushing to main is not allowed; push a branch and open a PR")
    if sub == "commit":
        skip = False
        for a in rest:
            if skip:
                skip = False
                continue
            if a in COMMIT_VALUE_OPTS:
                skip = True
                continue
            if a.startswith("--"):
                if is_prefix(a, "--no-verify", "--no-veri"):
                    block("--no-verify skips the hooks; fix the failure instead")
            elif a.startswith("-"):
                for ch in a[1:]:
                    if ch == "n":
                        block("-n (--no-verify) skips the hooks; fix the failure instead")
                    if ch in "mFcCt":  # the rest of the bundle is that option's value
                        break
    if sub == "reset" and any(is_prefix(a, "--hard", "--ha") for a in rest):
        block("git reset --hard discards work")
    if sub == "clean":
        for a in rest:
            if is_prefix(a, "--force", "--fo") or (
                a.startswith("-") and not a.startswith("--") and "f" in a[1:]
            ):
                block("git clean -f deletes untracked files")
    # Docs addition (re-sync with the reference when its hardening lands):
    # the other ways git throws away uncommitted or unmerged work.
    if sub in ("checkout", "switch"):
        positional, skip = [], False
        for a in rest:
            if skip:
                skip = False
            elif a in ("-B", "-C"):
                block(f"git {sub} {a} resets an existing branch; use -b/-c for a new one")
            elif a in ("-b", "-c", "--orphan"):
                skip = True
            elif not a.startswith("-"):
                positional.append(a)
        if (
            any(is_prefix(a, "--force", "--fo") or a == "-f" for a in rest)
            or any(is_prefix(a, "--discard-changes", "--di") for a in rest)
            or (sub == "checkout" and ("--" in rest[:-1] or "." in rest or len(positional) > 1))
            or (sub == "checkout" and len(positional) == 1
                and os.path.exists(positional[0]) and not is_rev(positional[0]))
        ):
            block(f"git {sub} of paths (or -f) discards uncommitted edits; commit a WIP instead")
    if sub == "restore":
        staged = any(a in ("--staged", "-S") for a in rest)
        worktree = any(a in ("--worktree", "-W") for a in rest)
        if worktree or not staged:
            block("git restore discards uncommitted edits; commit a WIP, or use --staged to unstage")
    if sub == "stash" and rest[:1] == ["clear"]:
        block("git stash clear drops every stash, and the stash is shared with other worktrees")
    if sub == "branch":
        short = [a for a in rest if a.startswith("-") and not a.startswith("--")]
        delete = any(is_prefix(a, "--delete", "--de") for a in rest) or any("d" in a for a in short)
        force = any(is_prefix(a, "--force", "--fo") for a in rest) or any("f" in a for a in short)
        if any("D" in a for a in short) or (delete and force):
            block("git branch -D deletes unmerged work; use -d, which refuses an unmerged branch")


def check(cmd, depth=0):
    try:
        toks = tokens(cmd)
    except ValueError:
        if "git" in cmd:
            block("could not parse the command (unbalanced quotes?); refusing rather than guessing")
        return
    husky_off = any(t == "HUSKY=0" for t in toks)
    for t in toks:
        if t.startswith("GIT_CONFIG") and "=" in t and "hookspath" in t.lower():
            block("overriding core.hooksPath skips the hooks; fix the failure instead")
    config_env = any(t.startswith(CONFIG_ENV) for t in toks)
    segs = [drop_redirects(seg) for seg in segments(toks)]
    # `echo 'git reset --hard' | bash`: a shell anywhere reads the other commands' text.
    piped_shell = any(seg and os.path.basename(seg[0]) in SHELLS for seg in segs)
    for seg in segs:
        end = len(seg)
        for n, t in enumerate(seg):
            if t == "git" or t.endswith("/git"):
                check_git(seg[n + 1:], husky_off, config_env)
                end = n
                break
        # `bash -c "git push --force"` and `"$(git reset --hard)"`: check the
        # inner command too. Docs addition: only a shell's argument or a command
        # substitution, never other text such as a message or a grep pattern.
        if depth < 3:
            shell = piped_shell or any(os.path.basename(t) in SHELLS for t in seg[:end])
            for t in seg[:end]:
                if "git" in t and (
                    (shell and any(c.isspace() for c in t)) or "$(" in t or "`" in t
                ):
                    check(t, depth + 1)


try:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    block("could not read the hook input; refusing rather than guessing")
check(command if isinstance(command, str) else "")
sys.exit(0)
