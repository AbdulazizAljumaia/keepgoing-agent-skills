# Getting started

This guide installs the skills, creates the Example Notes API workspace, and walks one task through the durable lifecycle. Python 3.10 or newer is the only runtime requirement.

## Install

Install for Codex from a clone:

```powershell
git clone https://github.com/AbdulazizAljumaia/keepgoing-agent-skills.git
Set-Location keepgoing-agent-skills
python scripts/install.py --agents codex --verify
```

The canonical copies are stored under `~/.agents/skills/keepgoing` and `~/.agents/skills/keepfixing`. Restart Codex after installation so it refreshes skill discovery.

To expose the same canonical package to every locally supported host, use:

```powershell
python scripts/install.py --agents all --verify
```

Use `--dry-run` to preview destinations. Use `--force` only after reviewing an existing destination that differs from the repository. A successful verification prints `"temporary_source_safe_to_delete": true`; the installed skills are physical canonical copies and do not depend on the clone.

## Invoke from an agent

Start a new project by giving the agent the goal and either a complete specification or enough requirements to create one:

```text
$keepgoing Initialize a governed notes API from the example specification, then resume the first eligible task.
```

Resume later from anywhere under the generated `Project/`:

```text
$keepgoing Resume this governed workspace from its durable continuation and show me the next task.
```

Use `$keepfixing` only for a completed task that needs a content-only correction. It cannot create, delete, rename, or move persistent paths.

## Run the example directly

From the repository root, copy the complete example specification to a working file outside the target workspace:

```powershell
Copy-Item skills/keepgoing/assets/workspace-spec.example.json notes-spec.json
python skills/keepgoing/scripts/keepgoing.py initialize --spec notes-spec.json --target notes-workspace --dry-run
python skills/keepgoing/scripts/keepgoing.py initialize --spec notes-spec.json --target notes-workspace
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace status
```

Initialization creates the organizer envelope, the standard application containers, the profile-native directories, and the active plan. It deliberately does not fabricate `notes.py` or `test_notes.py`; the coding agent creates those planned files while implementing `TASK-001`.

Before either planned file is edited, verify its authorization:

```powershell
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace path-check --task TASK-001 --path Project/apps/api/src/notes.py
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace path-check --task TASK-001 --path Project/apps/api/tests/test_notes.py
```

Start the task before implementation so the durable lifecycle reflects events as they happen:

```powershell
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace task-transition --task TASK-001 --to in_progress
```

After the agent implements both planned files, enter verification, run the project test command, and stop if it does not return exit code 0:

```powershell
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace task-transition --task TASK-001 --to verification
python -m unittest discover -s notes-workspace/Project/apps/api/tests -v
if ($LASTEXITCODE -ne 0) { throw "Notes API verification failed with exit code $LASTEXITCODE" }
```

Only after observing the test output and exit code, record completion and close the plan:

```powershell
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace task-transition --task TASK-001 --to complete --evidence "Observed Python unittest verification pass with exit code 0." --evidence-file Project/apps/api/src/notes.py --evidence-file Project/apps/api/tests/test_notes.py
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace complete-plan --plan PLAN-001
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace validate
```

`complete-plan` preserves the exact plan bytes and hash in the closing session before removing `plans/plan_1.md` from the active queue.

## Record an incomplete handoff

When work must stop before completion, save an executable continuation:

```powershell
python skills/keepgoing/scripts/keepgoing.py --root notes-workspace checkpoint --reason "Verification needs another run." --task TASK-001 --step 2 --next-action "Run the notes service tests and record the actual exit code." --relevant-path Project/apps/api/src/notes.py --verification-needed "Run the project test command."
```

A fresh agent process can then use `status` or `resume --open-session` to select that exact task and step.

## Strict correction example

After `TASK-001` has completed, a correction to an existing file begins with an explicit event ID and allowlist:

```powershell
python skills/keepfixing/scripts/keepfixing.py --root notes-workspace fix-begin --task TASK-001 --event-id FIX-NOTES-001 --file Project/apps/api/src/notes.py
```

Modify only the allowlisted existing file, run verification without leaving new paths in the workspace, and stop if it does not return exit code 0:

```powershell
python -m unittest discover -s notes-workspace/Project/apps/api/tests -v
if ($LASTEXITCODE -ne 0) { throw "Notes API regression verification failed with exit code $LASTEXITCODE" }
python skills/keepfixing/scripts/keepfixing.py --root notes-workspace fix-finish --event-id FIX-NOTES-001 --evidence "Observed Python unittest regression pass with exit code 0."
```

If verification fails, use `--failed --reason "exact observed failure and next action"`. The correction remains unresolved and no successful update is recorded.

## More detail

- [Workspace structure example](workspace-structure.md)
- [Behavioral acceptance evidence](acceptance.md)
- [Capability and host limits](capabilities.md)
- [Runtime command help](../skills/keepgoing/references/workflow.md)
