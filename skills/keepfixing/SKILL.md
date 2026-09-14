---
name: keepfixing
description: Improve or repair an identified completed task in an existing keepgoing-governed workspace while preserving its structure and modifying existing file contents only. Use for explicit keepfixing requests or clear dissatisfaction with completed governed work; do not initialize, add paths, restructure, or replace a project.
---

# Keepfixing

This skill delegates all state changes to the sibling keepgoing runtime through `scripts/keepfixing.py`. Install both skills together.

1. Run `python <skill>/scripts/keepfixing.py --root . status`. If no governed workspace or completed target exists, stop and explain that keepgoing initialization/adoption is required.
2. Resolve the affected stable task and its original acceptance/evidence. Call `fix-begin --task TASK-NNN --event-id <stable-id> --file Project/existing-path` for the smallest exact allowlist.
3. Modify existing file contents only. Do not add, delete, rename, or move any persistent path, allocate a session/plan/rating file, change structure authority, edit an applied migration, or silently switch to keepgoing.
4. Run verification without leaving new workspace paths. Prefer an isolated disposable copy or external output directory when the tool creates caches/build output.
5. Call `fix-finish --event-id <same-id> --evidence <observed-result>` only after success. On failure, use `--failed --reason <exact-next-action>`; no update token may be appended.
6. Confirm `validate` passes and that the path inventory is unchanged. A successful distinct event preserves `[complete][timestamp]` and appends exactly one `[updated][timestamp]`; retrying the same event ID is idempotent.

Read [references/fixing.md](references/fixing.md) for failure cases, ratings, and correction continuation.
