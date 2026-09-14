# keepgoing + keepfixing

Provider-neutral coding-agent skills for durable project planning, execution records, fresh-context resumption, strict corrections, ratings, and recoverable project replacement.

Start with the [guided installation and Notes API walkthrough](docs/getting-started.md), then use the [annotated workspace structure](docs/workspace-structure.md) to see how application code, plans, sessions, state, ratings, and replacement archives fit together.

The repository contains two skills and one shared standard-library Python runtime:

- `keepgoing` initializes, adopts, resumes, validates, checkpoints, and explicitly replaces governed projects.
- `keepfixing` repairs an identified completed task while forbidding persistent path changes and reusing keepgoing's runtime.

## Install for installed agents

Python 3.10 or newer is required:

```powershell
git clone https://github.com/AbdulazizAljumaia/keepgoing-agent-skills.git
cd keepgoing-agent-skills
python scripts/install.py --agents all --verify
```

From an existing clone, the installation command is:

```powershell
python scripts/install.py --agents all --verify
```

This installs one canonical persistent copy under `~/.agents/skills` and links Claude's `~/.claude/skills` entries to it. Codex, OpenCode, and Grok discover the shared `.agents` root in the locally verified versions. Use `--skill-root PATH` for another host, and run `--dry-run` to preview every destination.

The temporary clone can be deleted after `python scripts/install.py --agents all --verify` and a fresh agent process confirms discovery. Installed paths never point back to the clone.

## Invoke

Use `$keepgoing` to initialize or resume organized work. Use `$keepfixing` for an existing completed task that must improve without adding or moving files.

Direct runtime help:

```powershell
python skills/keepgoing/scripts/keepgoing.py --help
python skills/keepfixing/scripts/keepfixing.py --help
```

Agent prompt examples:

```text
$keepgoing Initialize a governed notes API from the shipped example specification and resume TASK-001.
$keepgoing Resume this project from its durable continuation without repeating completed work.
$keepfixing Correct TASK-001 in its existing allowlisted files and preserve the original completion time.
```

Initialize from a complete specification:

```powershell
python skills/keepgoing/scripts/keepgoing.py initialize --spec path/to/spec.json --target path/to/workspace --dry-run
python skills/keepgoing/scripts/keepgoing.py initialize --spec path/to/spec.json --target path/to/workspace
```

## Validate

```powershell
python scripts/validate.py
```

The suite uses disposable workspaces for destructive and interruption scenarios. See `docs/acceptance.md` for the evidence map and `docs/capabilities.md` for honest host limitations.

## How the folders work

`Project/` contains the real application. The sibling `instructions/`, `plans/`, `sessions/`, and `rates/` directories record authority, unfinished work, evidence/handoffs, and ratings. `deprecated/` protects explicit replacement history. See the [full annotated example](docs/workspace-structure.md).

## Public-use note

No license has been granted in this repository. Public visibility permits inspection and GitHub-based installation but does not itself grant broader reuse rights.
