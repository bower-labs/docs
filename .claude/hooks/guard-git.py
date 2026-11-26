"""PreToolUse guard for Bash: blocks the git commands this repo forbids
(AGENTS.md): force-push (--force-with-lease is allowed), pushing to main,
deleting a remote branch, skipping hooks (--no-verify, -n, HUSKY=0,
core.hooksPath, another config file), running an arbitrary program through
git (--upload-pack, --receive-pack, --exec), and the commands that throw work
away (reset --hard, clean -f, checkout/switch/restore that discard edits or
reset a branch with -B/-C, stash clear, branch -D, update-ref -d, worktree
remove --force).

The command is split the way the shell splits it (quotes, &&, ;, |, newlines,
redirects), so a quoted flag is still a flag, a commit message is never read
as flags, and one command's flags never count against the next. Wrapped forms
are checked too: bash -c, eval, $(...), backticks, env/command/absolute paths,
xargs, text piped or fed by heredoc into a shell, inline aliases (-c alias.x=...)
and GIT_CONFIG_* variables. A heredoc that only feeds a message (git commit
-F - <<EOF) is text and is skipped. git accepts any unambiguous prefix of a
long option (--no-verif), so prefixes are matched. A `git push` whose
arguments the shell would expand ($F) cannot be checked, so it is blocked.
Exit 2 blocks the call; anything this cannot parse is blocked, never waved
through.

Merged from a sibling repo's guard and this repo's (#261), taking the
stricter rule wherever they differed. This copy is the website repo's at
1e1548d plus one docs addition, saved_alias(): an alias saved in a config file
(`alias.fp = push --force`) is checked as what it expands to. Self-contained (python3 standard library
only) so other repos can copy it. Tests: .claude/hooks/test-guard-git.py.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time

# Claude Code kills a hook at its timeout (10 s in settings.json) and a killed
# hook does not block, so the guard stops itself first and blocks.
DEADLINE = time.monotonic() + 8

OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;", "\n", "`"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
# Commands that only print or search text: a quoted "git push --force" given to
# them is a string, not a command (unless a shell reads their output).
TEXT_CMDS = {"echo", "printf", "grep", "egrep", "fgrep", "rg", "ag"}
# git's own options that take the next token as their value.
GIT_VALUE_OPTS = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                  "--config-env"}
# commit options whose value is the next token (a message must not read as flags).
COMMIT_VALUE_OPTS = {"-m", "-F", "-c", "-C", "-t", "--message", "--file", "--template",
                     "--reuse-message", "--reedit-message", "--author", "--date",
                     "--fixup", "--squash", "--trailer", "--cleanup"}
# Options of any tool (git commit, gh pr create) whose value is prose, not a command.
PROSE_OPTS = {"-m", "--message", "--body", "--title", "-t", "-b", "--notes"}
# Subcommands that run hooks, so skipping or redirecting the hooks matters.
HOOKED = {"commit", "push", "merge", "rebase", "am", "cherry-pick", "revert", "pull"}
PROTECTED = {"main", "master"}
# A pathspec that names the whole tree.
WHOLE_TREE = {".", "./", ":/", ":/*", ":(top)", "*", ".."}
# Subcommands that are unsafe when xargs appends arguments nobody can see.
XARGS_RISKY = {"push", "reset", "clean", "checkout", "restore", "switch", "branch",
               "stash", "update-ref", "worktree", "commit", "config"}
# Words that, after a command word the shell expands ($G), suggest a hidden git.
HIDDEN_GIT_WORDS = XARGS_RISKY | HOOKED
# A push argument the shell expands but that can only be a branch name.
SAFE_EXPANSIONS = {"$(git branch --show-current)", "$(git rev-parse --abbrev-ref HEAD)"}
# Env assignments that point git at another config file, which may set core.hooksPath.
CONFIG_FILE_ENV = ("GIT_CONFIG_GLOBAL=", "GIT_CONFIG_SYSTEM=", "GIT_CONFIG=")
# `<<EOF`, `<<-'END-MSG'`; not a `<<<` here-string.
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(['\"]?)([^\s'\"<>;|&()]+)\1")
# A heredoc opened on a line that runs a shell is commands, not a message.
SHELL_LINE_RE = re.compile(r"(^|[\s;&|(/])(sh|bash|zsh|dash|ksh|fish|eval|source)(\s|$)")
# git located by a substitution ($(which git) push -f) hides the git word.
HIDDEN_GIT_RE = re.compile(r"(\$\(|`)\s*(which|command\s+-v|type\s+-p)\s+git\s*(\)|`)")
# Text built by a substitution and then run: `$(echo git) reset --hard`,
# `eval $(echo git ...)`, `bash <(echo git push -f)`.
BUILT_GIT_RE = re.compile(r"(\$\(|<\(|`)\s*(echo|printf|cat)\b[^)`]*\bgit\b")
PROSE_BEFORE_RE = re.compile(r"(\s-[a-zA-Z]*m|--message|--body|--title|--subject|--notes)[\s=]+[\"']?$")
# Shell aliases and functions of a common zsh setup (oh-my-zsh's git plugin),
# live in Claude Code's Bash. The hook sees only the alias name, so each is
# expanded and the expansion is checked with the arguments that follow it.
OMZ_GIT = {
    "g": "git", "ga": "git add", "gaa": "git add --all", "gb": "git branch",
    "gbd": "git branch --delete", "gbD": "git branch --delete --force", "gbm": "git branch --move",
    "gc": "git commit --verbose", "gca": "git commit --verbose --all",
    "gcam": "git commit --all --message", "gcmsg": "git commit --message",
    "gcn": "git commit --verbose --no-edit", "gc!": "git commit --verbose --amend",
    "gca!": "git commit --verbose --all --amend", "gcn!": "git commit --verbose --no-edit --amend",
    "gcan!": "git commit --verbose --all --no-edit --amend",
    "gcans!": "git commit --verbose --all --signoff --no-edit --amend",
    "gco": "git checkout", "gcb": "git checkout -b", "gcB": "git checkout -B",
    "gcm": "git checkout main", "gcl": "git clone", "gclean": "git clean --interactive -d",
    "gcp": "git cherry-pick", "gf": "git fetch", "gl": "git pull", "gm": "git merge",
    "gp": "git push", "gpd": "git push --dry-run",
    "gpf": "git push --force-with-lease --force-if-includes", "gpf!": "git push --force",
    "gpsup": "git push --set-upstream origin HEAD",
    "gpsupf": "git push --set-upstream origin HEAD --force-with-lease --force-if-includes",
    "ggp": "git push origin HEAD", "ggf": "git push --force origin HEAD",
    "ggfl": "git push --force-with-lease origin HEAD", "ggl": "git pull origin HEAD",
    "gpristine": "git reset --hard && git clean --force -dfx",
    "gwipe": "git reset --hard && git clean --force -df",
    "grb": "git rebase", "grev": "git revert", "grh": "git reset", "grhh": "git reset --hard",
    "groh": "git reset origin/HEAD --hard", "grhs": "git reset --soft", "grs": "git restore",
    "grst": "git restore --staged", "gsta": "git stash push", "gstc": "git stash clear",
    "gsw": "git switch", "gswc": "git switch --create", "gwt": "git worktree",
    "gwtrm": "git worktree remove",
}
# Wrappers that run the next word as the command (`| env bash`, `| sudo sh`).
WRAPPERS = {"env", "sudo", "command", "exec", "nice", "nohup", "time", "doas"}
# -c keys whose value git runs as a program.
PROGRAM_KEYS = ("core.pager", "core.editor", "core.fsmonitor", "core.askpass", "sequence.editor",
                "diff.external", "gpg.program", "credential.helper", "pager.")
# A bash brace list (`--{hard,hard}`) expands before git sees it.
BRACE_RE = re.compile(r"\{[^{}]*(,|\.\.)[^{}]*\}")
# Words that open a command position, where zsh still expands an alias.
RESERVED = {"{", "then", "do", "else", "elif", "!", "time", "if", "while", "until"}
FORCE_PUSH = "force-push is not allowed; use --force-with-lease only if you must"
NO_VERIFY = "--no-verify skips the hooks; fix the failure instead"


def block(reason):
    print(f"Blocked by .claude/hooks/guard-git.sh: {reason}", file=sys.stderr)
    sys.exit(2)


def is_prefix(arg, option, shortest):
    """git takes any unambiguous prefix of a long option, down to `shortest`."""
    return len(arg) >= len(shortest) and option.startswith(arg)


def short_flags(arg, values=""):
    """The letters of a bundle like -uf, stopping at an option that takes a value."""
    if not arg.startswith("-") or arg.startswith("--") or arg == "-":
        return ""
    out = ""
    for ch in arg[1:]:
        out += ch
        if ch in values:
            break
    return out


def strip_heredocs(cmd):
    """Drop heredoc bodies that are text (a commit message, usually), so an
    apostrophe in one ("don't") cannot make the whole command unparseable.
    A body fed to a shell (bash <<EOF, cat <<EOF | sh) is kept: it is commands."""
    out, ends, keep = [], [], False
    for line in cmd.split("\n"):
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            elif keep:
                out.append(line)
            continue
        out.append(line)
        ends = [m.group(2) for m in HEREDOC_RE.finditer(line)]
        keep = bool(ends) and bool(SHELL_LINE_RE.search(line))
    if ends:
        # Usually `<<` inside quotes (git log --format='<<%an>>'), not a heredoc:
        # parse the command as written, which still fails closed on bad quoting.
        return cmd
    return "\n".join(out)


def tokens(cmd):
    # A backslash before a newline joins the lines, as the shell does (dropping
    # it inside single quotes too only errs toward blocking). A plain newline
    # ends a command just as `;` does, so it is punctuation here; so is an
    # unquoted backtick, which opens a command substitution just as `$(` does.
    # A `# comment` would swallow the newline after it and join two commands,
    # so every newline also gets a `;` (after a space, or shlex fuses them).
    text = strip_heredocs(cmd.replace("\\\n", "")).replace("\n", "\n ;")
    lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&`\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    return list(lex)


def segments(toks, with_ops=False):
    """Commands, split on the shell's operators (with the operator before each)."""
    seg, op, last = [], None, None
    for t in toks:
        if t in OPERATORS:
            if seg:
                yield (op, seg) if with_ops else seg
            seg, last = [], t
        else:
            if not seg:
                op = last
            seg.append(t)
    if seg:
        yield (op, seg) if with_ops else seg


def reads_stdin_as_code(op, seg):
    """`... | bash`, `| sh -s`, `| eval`: a shell fed by a pipe with no script
    operand. `bash scripts/x.sh` runs a file and does not read the other text."""
    if op not in ("|", "|&"):
        return False
    n = 0
    while n < len(seg) and (os.path.basename(seg[n]) in WRAPPERS or seg[n].startswith("-")
                            or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[n])):
        n += 1
    word = seg[n] if n < len(seg) else ""
    if os.path.basename(word) not in SHELLS | {"eval", "source", "."}:
        return False
    args = seg[n + 1:]
    return not any(not a.startswith("-") or "c" in short_flags(a) for a in args)


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


def git_out(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd or None)
        return r.returncode, r.stdout.strip()
    except OSError:
        return 1, ""


def is_rev(arg, cwd=None):
    """A commit, or a branch git would create from origin (checkout <name>)."""
    return any(git_out("rev-parse", "--verify", "--quiet", ref + "^{commit}", cwd=cwd)[0] == 0
               for ref in (arg, "refs/remotes/origin/" + arg))


def config_key_is_dangerous(key):
    """Config that skips the hooks, runs a program, lets clean delete files or
    changes what a push does. One list for -c, `git config` and GIT_CONFIG_*."""
    key = key.lower()
    return (key.startswith(("core.hookspath", "include", "core.sshcommand", "clean.requireforce"))
            or key.startswith(PROGRAM_KEYS)
            or key.endswith((".textconv", ".command", ".uploadpack", ".receivepack", ".driver",
                             ".program", ".helper", ".cmd"))
            or bool(re.match(r"^remote\..+\.(mirror|push)$", key))
            or key.startswith("push.default"))


def substitutions(tok):
    """The commands inside $(...) and `...` in one token."""
    start = tok.find("$(")
    if start != -1 and tok.rfind(")") > start:
        yield tok[start + 2:tok.rfind(")")]
    for inner in re.findall(r"`([^`]*)`", tok):
        yield inner


def run_git(args):
    left = DEADLINE - time.monotonic()
    if left <= 0:
        block("checking this command took too long; refusing rather than guessing")
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=left)
    except subprocess.TimeoutExpired:
        block("checking this command took too long; refusing rather than guessing")
    except OSError:
        block("could not run git to read its aliases; refusing rather than guessing")


_COMMANDS = []
# Set once any part of the command changes where git reads config, so a nested
# `bash -c "git fp"` after `cd ../b &&` is judged as moved too.
MOVED = [False]


def past_deadline():
    if time.monotonic() > DEADLINE:
        block("checking this command took too long; refusing rather than guessing")


def git_commands():
    if not _COMMANDS:
        found = run_git(["--list-cmds=main,others,nohelpers"])
        if found.returncode != 0:
            block("could not list git's commands; refusing rather than guessing")
        _COMMANDS.append(set(found.stdout.split()))
    return _COMMANDS[0]


def saved_alias(sub, repo_dir, ctx):
    """Docs addition: an alias saved in a config file (`alias.fp = push --force`
    in ~/.gitconfig) is what `git fp` runs. git ignores an alias that shares a
    command's name, so only a name git does not know as a command counts. When
    the command changes where git looks (cd, --git-dir, GIT_DIR, HOME, a -C the
    shell expands), the alias cannot be read from here, so it is blocked."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", sub):
        return None
    unreadable = (f"git {sub} may be an alias in a repo or config this cannot read; "
                  "spell the git command out")
    if MOVED[0] or ctx["moved"] or (repo_dir and re.search(r"[$~`*?\[{]", repo_dir)):
        if sub not in git_commands():
            block(unreadable)
        return None
    found = run_git((["-C", repo_dir] if repo_dir else []) + ["config", "--get", "alias." + sub])
    if sub in git_commands():
        return None
    if found.returncode not in (0, 1):  # 128: a -C or repo git cannot open
        block(unreadable)
    return found.stdout.strip() if found.returncode == 0 else None


def check_alias(value, rest, ctx, depth, configs=(), repo_dir=None):
    """An alias is a command in disguise: check what it expands to, with the
    same one-off config (-c core.hooksPath=...) the outer command set."""
    if value.startswith("!"):
        # The shell command's own git runs under this -C and these -c values,
        # which this cannot follow into it, so its aliases count as moved.
        if repo_dir or any(c.lower().startswith("alias.") for c in configs):
            MOVED[0] = True
        check(value[1:], depth + 1)
    else:
        # Docs change: alias.* configs carry through, so `-c alias.a=b -c "alias.b=push
        # --force" a` is followed to the end (check() caps the depth).
        # The expansion runs where the alias was found, so a chain keeps the -C.
        outer = [x for c in configs for x in ("-c", c)] + (["-C", repo_dir] if repo_dir else [])
        try:
            check_git(outer + tokens(value) + rest, ctx, depth + 1)
        except ValueError:
            block("could not parse an alias; refusing rather than guessing")


def check_git(args, ctx, depth=0, via_xargs=False):
    """args: everything after the `git` token. ctx: flags set for the whole command."""
    if depth > 4:
        block("an alias expands to another alias too many times")
    past_deadline()
    configs, i, repo_dir = [], 0, None
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            repo_dir = os.path.join(repo_dir or "", args[i + 1])  # where git will run
        if a.startswith("--config-env"):
            env = a.partition("=")[2] if "=" in a else (args[i + 1] if i + 1 < len(args) else "")
            if "hookspath" in env.lower() or env.lower().startswith("alias."):
                block("--config-env for core.hooksPath or an alias cannot be checked")
        if a in GIT_VALUE_OPTS and i + 1 < len(args):
            if a == "-c":
                configs.append(args[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(args):
        if via_xargs:
            block("xargs supplies git's subcommand, which cannot be checked")
        return
    sub, rest = args[i], args[i + 1:]
    if "$" in sub or "`" in sub:
        block("git's subcommand comes from a shell expansion, which cannot be checked")
    if via_xargs and sub in XARGS_RISKY:
        block(f"xargs appends arguments to git {sub} that cannot be checked")
    if sub in XARGS_RISKY | HOOKED:
        skip = False
        for a in rest:
            if skip:  # a message is text, so `-m "$MSG"` is fine
                skip = False
                continue
            if a in COMMIT_VALUE_OPTS or a in PROSE_OPTS or short_flags(a, "mFcCt").endswith("m"):
                skip = True
                continue
            if a in SAFE_EXPANSIONS or a.partition("=")[0] in ("--message", "--format", "--pretty"):
                continue
            if "$" in a or "`" in a or BRACE_RE.search(a):
                block(f"git {sub} with a shell expansion ($..., {{a,b}}) cannot be checked; "
                      "spell the arguments out")
    # git uses the last value of a key, so one inline alias is checked once (a
    # repeated -c alias.a=... cannot fan the check out past the hook's timeout).
    configs = list({c.partition("=")[0].lower(): c for c in configs}.values())
    inline_alias = False
    for c in configs:
        key, _, value = c.partition("=")
        if key.lower() == "alias." + sub.lower():
            inline_alias = True
            check_alias(value, rest, ctx, depth, configs, repo_dir)
        if config_key_is_dangerous(key) and not key.lower().startswith("core.hookspath"):
            block(f"-c {key} can run a program, let clean delete files or change what push does")
    if not inline_alias:
        value = saved_alias(sub, repo_dir, ctx)
        if value is not None:
            if depth > 4:
                block("an alias expands to another alias too many times")
            check_alias(value, rest, ctx, depth, configs, repo_dir)
    for a in rest:
        opt = a.partition("=")[0]
        if (is_prefix(opt, "--upload-pack", "--up") or is_prefix(opt, "--receive-pack", "--rece")
                or (sub in ("push", "send-pack") and is_prefix(opt, "--exec", "--exe"))
                or (sub in ("clone", "ls-remote") and "u" in short_flags(a, "u"))):
            block("--upload-pack/--receive-pack/--exec run an arbitrary program")
    if sub in HOOKED:
        if any(c.lower().startswith("core.hookspath") for c in configs):
            block("overriding core.hooksPath skips the hooks; fix the failure instead")
        if ctx["config_file"]:
            block("pointing git at another config file can skip the hooks")
        if ctx["husky_off"] and sub in ("commit", "push"):
            block("HUSKY=0 skips the hooks; fix the failure instead")
        if sub != "commit" and any(is_prefix(a, "--no-verify", "--no-veri") for a in rest):
            block(NO_VERIFY)
    if sub == "config":
        for n, a in enumerate(rest):
            # Reading it (`git config core.hooksPath`, --get) is fine; a value or --unset is not.
            if a.lower() == "core.hookspath" and (
                n + 1 < len(rest) or any(is_prefix(r.partition("=")[0], "--unset-all", "--uns")
                                      or r == "unset" for r in rest)
            ):
                block("changing core.hooksPath skips the hooks")
            if config_key_is_dangerous(a) and a.lower() != "core.hookspath" and n + 1 < len(rest):
                block(f"setting {a} can run a program, let clean delete files or change what push does")
            if (a in ("remove-section", "rename-section") or is_prefix(a, "--remove-section", "--rem")
                    or is_prefix(a, "--rename-section", "--ren")):
                block("removing or renaming a config section can drop core.hooksPath")
        for n, a in enumerate(rest):
            if a.lower().startswith("alias.") and n + 1 < len(rest):
                value = rest[n + 1].strip()
                if value.startswith("!") or value.split()[:1] and value.split()[0] in XARGS_RISKY:
                    block("an alias for a shell command or for git " + value.split()[0].lstrip("!")
                          + " hides what later runs; spell the command out")
                check_alias(value, [], ctx, depth)
    if sub == "push":
        for a in rest:
            if a in SAFE_EXPANSIONS:
                continue
            if "$" in a or "`" in a:
                block("git push with a shell expansion ($...) cannot be checked; "
                      "spell the arguments out (git push -u origin HEAD works)")
            if is_prefix(a, "--force", "--for") or is_prefix(a, "--mirror", "--mi"):
                block(FORCE_PUSH)
            flags = short_flags(a, "o")
            if "f" in flags:
                block(FORCE_PUSH)
            if "d" in flags or is_prefix(a, "--delete", "--del"):
                block("deleting a remote branch is not allowed; ask a person to do it")
            if a.startswith("+") or ":+" in a:
                block("a +refspec force-pushes; use --force-with-lease only if you must")
            if a.startswith(":") and len(a) > 1:
                block("a :branch refspec deletes the remote branch; ask a person to do it")
            if is_prefix(a, "--no-verify", "--no-veri"):
                block(NO_VERIFY)
            if (is_prefix(a, "--all", "--al") or is_prefix(a, "--branches", "--br")
                    or is_prefix(a, "--prune", "--pru")):
                block("git push --all/--prune touches main too; push your branch by name")
        positional, skip = [], False
        for a in rest:
            if skip:
                skip = False
            elif a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
                skip = True
            elif not a.startswith("-"):
                positional.append(a)
        has_repo = any(a.startswith("--repo") for a in rest)  # --repo X / --repo=X
        refspecs = positional if has_repo else positional[1:]  # after the remote
        if any("*" in r for r in refspecs):
            block("a wildcard refspec pushes main too; push your branch by name")
        # git resolves `heads/main` and `refs/heads/main` to main as well.
        dsts = [r.rsplit(":", 1)[-1].removeprefix("refs/").removeprefix("heads/")
                for r in refspecs]
        if not dsts or any(d in ("HEAD", "@") for d in dsts):
            dsts.append(git_out("branch", "--show-current", cwd=repo_dir)[1])
        if any(d in PROTECTED for d in dsts):
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
                    block(NO_VERIFY)
            elif "n" in short_flags(a, "mFcCt"):
                block("-n (--no-verify) skips the hooks; fix the failure instead")
    if sub == "reset" and any(is_prefix(a, "--hard", "--ha") for a in rest):
        block("git reset --hard discards work")
    if sub == "clean":
        for a in rest:
            if is_prefix(a, "--force", "--fo") or "f" in short_flags(a, "e"):
                block("git clean -f deletes untracked files")
    if sub in ("checkout", "switch"):
        positional, skip = [], False
        for a in rest:
            if skip:
                skip = False
            elif a in ("-B", "-C") or is_prefix(a, "--force-create", "--force-") or (
                    a.startswith("-") and not a.startswith("--")
                                       and ("B" in short_flags(a, "bBcC")
                                            or (sub == "switch" and "C" in short_flags(a, "bBcC")))):
                block(f"git {sub} {a} resets an existing branch; use -b/-c for a new one")
            elif a in ("-b", "-c") or is_prefix(a, "--orphan", "--orp"):
                skip = True
            elif not a.startswith("-"):
                positional.append(a)
        if (is_prefix_any(rest, "--force", "--for") or "f" in "".join(short_flags(a, "bBcC") for a in rest)
                or is_prefix_any(rest, "--discard-changes", "--di")):
            block(f"git {sub} -f discards local changes")
        # One positional is fine only when git resolves it as a branch or commit;
        # anything else is a path (relative to a cwd this hook cannot see) or a glob.
        # After -b/--orphan/--track the positional is a start point, not a path.
        tracking = any(a in ("-t", "-b") or is_prefix(a.partition("=")[0], "--track", "--tr")
                       or is_prefix(a, "--orphan", "--orp")
                       for a in rest)
        if sub == "checkout" and (
            "--" in rest[:-1] or any(a in WHOLE_TREE for a in rest) or len(positional) > 1
            or (len(positional) == 1 and not tracking and (
                any(c in positional[0] for c in "*?[") or not is_rev(positional[0], repo_dir)))
        ):
            block("git checkout of paths discards uncommitted edits; commit a WIP instead")
    if sub in ("checkout", "restore") and is_prefix_any(
            [a.partition("=")[0] for a in rest], "--pathspec-from-file", "--pathspec-f"):
        block(f"git {sub} --pathspec-from-file discards edits in every listed path")
    if sub == "restore":
        flags = "".join(short_flags(a, "s") for a in rest)
        staged = "S" in flags or is_prefix_any(rest, "--staged", "--stag")
        worktree = "W" in flags or is_prefix_any(rest, "--worktree", "--w")
        if worktree or not staged:
            block("git restore discards uncommitted edits; commit a WIP, or use --staged to unstage")
    if sub in ("rebase", "pull"):
        for n, a in enumerate(rest):
            opt, eq, val = a.partition("=")
            if is_prefix(opt, "--exec", "--ex") or opt == "-x":
                cmd = val if eq else (rest[n + 1] if n + 1 < len(rest) else "")
                check(cmd, depth + 1)
            elif a.startswith("-x") and len(a) > 2:
                check(a[2:], depth + 1)
    if sub in ("filter-branch", "filter-repo"):
        block(f"git {sub} rewrites history; ask a person to do it")
    if sub == "read-tree" and any(is_prefix(a, "--reset", "--res") for a in rest):
        block("git read-tree --reset discards local changes")
    if sub == "checkout-index" and any("f" in short_flags(a) or is_prefix(a, "--force", "--fo")
                                       for a in rest):
        block("git checkout-index -f overwrites local changes")
    if sub == "stash" and rest[:1] == ["drop"]:
        block("git stash drop deletes a stash, and the stash is shared by all worktrees")
    if sub == "stash" and rest[:1] == ["clear"]:
        block("git stash clear drops every stash, and the stash is shared by all worktrees")
    if sub == "branch":
        flags = "".join(short_flags(a) for a in rest)
        delete = "d" in flags or is_prefix_any(rest, "--delete", "--del")
        force = "f" in flags or is_prefix_any(rest, "--force", "--for")
        if "D" in flags or (delete and force):
            block("git branch -D deletes unmerged work; use -d")
        if force or "M" in flags or "C" in flags:
            block("git branch -f/-M/-C moves or overwrites an existing branch; create a new one")
    if sub == "submodule" and "foreach" in rest:
        check(" ".join(rest[rest.index("foreach") + 1:]), depth + 1)
    if sub == "update-ref" and any(a == "-d" or is_prefix(a, "--delete", "--de") for a in rest):
        block("git update-ref -d deletes a ref")
    if sub == "worktree" and rest[:1] == ["remove"] and any(
        is_prefix(a, "--force", "--fo") or "f" in short_flags(a) for a in rest[1:]
    ):
        block("git worktree remove --force deletes uncommitted work")


def is_prefix_any(args, option, shortest):
    return any(is_prefix(a, option, shortest) for a in args)


def command_word(seg):
    """The first token that is not a VAR=value assignment or a reserved word."""
    for t in seg:
        if t not in RESERVED and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            return t
    return ""


def check(cmd, depth=0):
    if depth > 4:
        block("the command nests too deeply to check")
    past_deadline()
    if HIDDEN_GIT_RE.search(cmd):
        block("git found through a substitution ($(which git)) cannot be checked; call git")
    for m in BUILT_GIT_RE.finditer(cmd):
        if not PROSE_BEFORE_RE.search(cmd[:m.start()]):
            block("a git command built by a substitution ($(echo git ...)) cannot be checked")
    try:
        toks = tokens(cmd)
    except ValueError:
        if "git" in cmd:
            block("could not parse the command (unbalanced quotes?); refusing rather than guessing")
        return
    ctx = {
        "husky_off": "HUSKY=0" in toks,
        "config_file": any(t.startswith(CONFIG_FILE_ENV) for t in toks),
        # Docs addition: the command may change where git reads aliases from.
        "moved": ("env" in toks and any(t in ("-C", "--chdir") or t.startswith("--chdir=")
                                        for t in toks)) or any(
            t in ("cd", "pushd", "popd", "eval", "source") or t.startswith(("--git-dir", "--work-tree"))
                     or re.match(r"^(GIT_[A-Z_]+|HOME|XDG_CONFIG_HOME)=", t) for t in toks),
    }
    # `. ./env.sh`: a dot in command position is `source`.
    if ctx["moved"] or any(t == "." and (n == 0 or toks[n - 1] in OPERATORS)
                           for n, t in enumerate(toks)):
        MOVED[0] = True
    for t in toks:
        m = re.match(r"^GIT_CONFIG_(KEY_\d+|VALUE_\d+|PARAMETERS)=(.*)$", t, re.S)
        if m:
            keys = ([m.group(2)] if m.group(1).startswith("KEY")
                    else re.findall(r"'([^'=]+)'=", m.group(2)) if m.group(1) == "PARAMETERS" else [])
            if ("hookspath" in m.group(2).lower() or "alias." in m.group(2).lower()
                    or any(config_key_is_dangerous(k) for k in keys)):
                block("setting core.hooksPath, an alias or a program through GIT_CONFIG_* "
                      "is not allowed")
        # GIT_EDITOR=..., GIT_SEQUENCE_EDITOR=...: git runs the value as a command.
        m = re.match(r"^(GIT_EDITOR|GIT_SEQUENCE_EDITOR|GIT_EXTERNAL_DIFF|GIT_PAGER|GIT_SSH_COMMAND"
                     r"|GIT_ASKPASS|GIT_SSH|EDITOR|VISUAL|PAGER)=(.*)$", t, re.S)
        if m and "git" in m.group(2):
            check(m.group(2), depth + 1)
    raw_segs = list(segments(toks))
    # `echo 'git reset --hard' | bash`: a shell reading a pipe runs the other commands' text.
    piped_shell = any(reads_stdin_as_code(op, s) for op, s in segments(toks, with_ops=True))
    if piped_shell and "git" not in cmd and any(
            os.path.basename(t) in ("base64", "xxd", "openssl", "gunzip", "zcat", "rev") for t in toks):
        block("decoded or transformed text piped into a shell cannot be checked")
    for raw in raw_segs:
        seg = drop_redirects(raw)
        for n, t in enumerate(seg):
            if os.path.basename(t) in TEXT_CMDS:
                break  # `xargs grep git`, `echo git push`: git is an argument here
            if t == "git" or t.endswith("/git"):
                via_xargs = any(os.path.basename(x) == "xargs" for x in seg[:n])
                check_git(seg[n + 1:], ctx, depth, via_xargs)
                break
        word = command_word(seg)
        if word in OMZ_GIT:
            at = seg.index(word)
            assigns = [t for t in seg[:at] if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
            check(" ".join([*map(shlex.quote, assigns), OMZ_GIT[word],
                            *map(shlex.quote, seg[at + 1:])]), depth + 1)
        if "git" in word and ("$" in word or "`" in word or BRACE_RE.search(word)
                              or word.startswith("{")):
            block("a git command word built by a shell expansion cannot be checked")
        if (word.startswith("$") or any(c in word for c in "`{*?[")) and any(
                t in HIDDEN_GIT_WORDS for t in seg):
            block("the command comes from a shell expansion, which cannot be checked")
        for n, t in enumerate(seg):
            # bash -c "git push --force", sudo sh -ec '...', xargs sh -c '...'
            if os.path.basename(t) in SHELLS:
                for m in range(n + 1, len(seg) - 1):
                    if "c" in short_flags(seg[m]):
                        check(seg[m + 1], depth + 1)
                        break
        base = os.path.basename(word)
        # git and gh take quoted text (messages, --grep, --body, --subject) that is
        # not run, except in the few subcommands that execute a string.
        runs_strings = base == "git" and any(
            t in ("foreach", "run") or t.startswith("-x") or is_prefix(t.partition("=")[0], "--exec", "--ex")
            for t in seg)
        quiet = (base == "gh" or (base == "git" and not runs_strings)) and not piped_shell
        text_only = base in TEXT_CMDS and not piped_shell
        if piped_shell and os.path.basename(word) in TEXT_CMDS:
            # `echo git reset --hard | sh`: the unquoted words are the shell's input.
            words = seg[seg.index(word) + 1:]
            if "git" in " ".join(words):
                check(" ".join(words), depth + 1)
        for n, t in enumerate(raw):
            for inner in substitutions(t):
                check(inner, depth + 1)
            if os.path.basename(t) in TEXT_CMDS and not piped_shell:
                text_only = True  # find ... -exec grep "git push --force" {} +
            # A quoted command in an unknown wrapper (watch "git push -f", a
            # here-string). Prose (a commit message, a PR body) and text given
            # to echo/grep are not commands, so they are skipped.
            prose = n > 0 and (raw[n - 1] in PROSE_OPTS
                               or short_flags(raw[n - 1], "mFcCt").endswith("m"))
            if quiet or prose and base in ("git", "gh") or text_only \
                    or not any(c.isspace() for c in t):
                continue
            if piped_shell and "git" in t or re.search(r"(^|[;&|\n]\s*)git\s", t.strip()):
                check(t, depth + 1)


try:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    # Docs addition: git reads aliases from where the command runs, which is the
    # payload's cwd, not necessarily the hook's.
    if isinstance(payload.get("cwd"), str) and os.path.isdir(payload["cwd"]):
        os.chdir(payload["cwd"])
except Exception:
    block("could not read the hook input; refusing rather than guessing")
if not isinstance(command, str):
    block("the hook input has no readable command; refusing rather than guessing")
check(command)
sys.exit(0)
