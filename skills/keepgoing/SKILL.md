---
name: keepgoing
description: Organize, initialize, adopt, resume, or replace a software project with durable plans, evidence-backed lifecycle state, checkpoints, ratings, and fresh-context continuation. Use for explicit keepgoing requests or when the user asks this organizer to continue an already governed workspace; do not use for a narrow repair of completed governed work, which belongs to keepfixing.
---

# Keepgoing

Use the shared deterministic runtime at `scripts/keepgoing.py`; records alone never prove implementation.

1. Discover the workspace from the current path with `python <skill>/scripts/keepgoing.py --root . status`. If found, resume it. Never initialize a nested or duplicate `Project/`.
2. For a new or unmanaged project, read [references/specification.md](references/specification.md) and [references/profiles.md](references/profiles.md). Capture every authorized requirement, rule, concrete planned path, dependency, task step, acceptance criterion, and verification procedure in a complete JSON specification outside the target workspace. Run `initialize --dry-run` or `adopt --dry-run`, resolve collisions, then run the authorized operation.
3. Before an edit, call `path-check --task TASK-NNN --path Project/...`. Read the current plan, the exact source location, and only the history named by the continuation pointer. Implement the application change yourself; the runtime performs bookkeeping, not feature coding.
4. Move tasks through valid lifecycle states. A completion transition requires observed evidence and current hashes for implemented files. Close a plan only after all required tasks are complete; `complete-plan` preserves its exact bytes and hash before removing it from the active queue.
5. Use `context-check` only with real host telemetry or an explicitly labelled estimate. When unavailable, do not state a percentage; checkpoint after each meaningful unit. Read [references/workflow.md](references/workflow.md) for transition, checkpoint, and rating rules.
6. Run `detect-drift` and `validate` at checkpoints and completion. Recover a prepared record transaction before more edits. For generation replacement, read [references/recovery.md](references/recovery.md) and perform a dry run first.
7. Finish only when actual project behavior, required checks, plan/session/state records, ratings, and validation agree. Otherwise save a precise continuation or blocker.

Host hooks and automatic restart vary. Read [references/host-integration.md](references/host-integration.md) before claiming interception, exact context monitoring, or autonomous continuation.
