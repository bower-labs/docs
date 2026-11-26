"""Feeds guard-git.sh the payload Claude Code sends and checks every verdict.

Run: python3 .claude/hooks/test-guard-git.py (each repo wires it into its own CI).
Cases come from two files next to this one:
- guard-git.cases.json: shared by every repo that runs this guard, byte for
  byte, never edited in one repo. It pins guard-git.py by SHA-256.
- guard-git.cases.local.json: this repo's own. `overrides` (command -> "allow"
  or "block") replace a shared verdict, for a repo whose guard-git.policy.json
  is stricter; extra `cases`; and `shared_sha256`, the hash of the shared file
  it was copied at. An override for a command the shared file lacks, or has
  more than once (on a branch and on main), is an error.
Each case runs in a scratch repo holding the shared file's scratch_files and
scratch_config, on branch claude/test ("branch") or main ("main", which also
gets scratch_config_main), with HOME pointed at an empty directory so the
developer's own git config cannot change a verdict. `scratch_repos` adds more
(name -> branch, extra refs and config), for a case's `on` to name. A case's optional `cwd`
is sent as the payload's cwd. `policy_cases` run against a copy of the guard
with that policy file beside it (or none), so both the default and a stricter
policy are tested in every repo. Exit 1 on any mismatch.
Standard library only, so every repo can copy this runner unchanged.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXIT = {"block": 2, "allow": 0}
# Hook input that names no command to check: blocked, never waved through.
UNREADABLE = ("{not json", '{"tool_name":"Bash","tool_input":{"command":42}}', "{}",
              '{"tool_name":"Bash","tool_input":{}}', '{"tool_name":"Bash"}', "[]")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    with open(HERE / name, encoding="utf-8") as f:
        return json.load(f)


def isolated_env(home):
    """No GIT_* from an outer git hook (GIT_INDEX_FILE would aim the scratch
    repos at the outer commit's index), no system or user git config."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
    env.update({"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def scratch_repo(path, branch, files, refs, config, env):
    """A repo with known files, refs and config on a known branch, so the verdicts
    do not depend on which branch CI or a developer happens to have checked out."""
    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)
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
    for key, value in config.items():
        git("config", key, value)
    return path


def verdict(hook, payload, cwd, env):
    return subprocess.run(["bash", str(hook)], input=payload, capture_output=True, text=True,
                          cwd=cwd, env=env).returncode


def payload_for(command, cwd):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


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
    config = shared.get("scratch_config", {})
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp, "home")
        home.mkdir()
        env = isolated_env(home)
        repos = {
            "branch": scratch_repo(Path(tmp, "branch"), "claude/test", files, shared["scratch_refs"],
                                   config, env),
            "main": scratch_repo(Path(tmp, "main"), "main", files, shared["scratch_refs"],
                                 {**config, **shared.get("scratch_config_main", {})}, env),
        }
        for name, spec in shared.get("scratch_repos", {}).items():
            repos[name] = scratch_repo(Path(tmp, name), spec["branch"], files,
                                       shared["scratch_refs"] + spec.get("refs", []),
                                       {**config, **spec.get("config", {})}, env)

        def fill(text):
            return text.replace("{branch_repo}", str(repos["branch"])).replace(
                "{main_repo}", str(repos["main"]))

        def run(hook, c, label=""):
            on = c.get("on", "branch")
            cwd = fill(c["cwd"]) if "cwd" in c else repos[on]
            got = verdict(hook, payload_for(fill(c["command"]), cwd), repos[on], env)
            if got != EXIT.get(c["expect"]):
                failures.append(f"should {c['expect']} (on {on}{label}): {c['command']!r}")

        for c in cases:
            run(HERE / "guard-git.sh", c)
        # A copy of the guard with only the case's policy beside it (none if null).
        for n, c in enumerate(shared.get("policy_cases", [])):
            hooks = Path(tmp, f"policy-{n}")
            hooks.mkdir()
            for name in ("guard-git.sh", "guard-git.py"):
                shutil.copy2(HERE / name, hooks / name)
            if c["policy"] is not None:
                text = c["policy"] if isinstance(c["policy"], str) else json.dumps(c["policy"])
                (hooks / "guard-git.policy.json").write_text(text)
            run(hooks / "guard-git.sh", c, f", policy {json.dumps(c['policy'])}")
        for raw in UNREADABLE:
            if verdict(HERE / "guard-git.sh", raw, repos["branch"], env) != 2:
                failures.append(f"should block unreadable hook input: {raw!r}")
    for f in failures:
        print(f, file=sys.stderr)
    total = len(cases) + len(shared.get("policy_cases", [])) + len(UNREADABLE)
    print(f"guard-git: {total - len(failures)} passed, {len(failures)} failed "
          f"({len(shared['cases'])} shared, {len(shared.get('policy_cases', []))} policy, "
          f"{len(overrides)} overridden, {len(local.get('cases', []))} local; "
          f"shared source: {shared['source']})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
