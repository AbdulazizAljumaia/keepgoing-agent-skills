# Strict correction workflow

keepfixing targets existing completed work only. `fix-begin` captures the complete persistent path inventory, structure hash, current project hashes, task identity, original completion history, and an exact existing-file allowlist. It records the correction in the latest existing session and does not allocate organizer paths.

During correction:

- Modify only allowlisted existing file contents.
- Do not add, delete, rename, move, scaffold, restructure, revise `structure.md`, or edit an applied migration.
- Run artifact-producing checks in a disposable copy or configure output outside the workspace.
- If a correct repair inherently requires a new path or migration, finish independent permitted work and block with the smallest required keepgoing scope change.

`fix-finish` compares persistent paths, structure authority, and changed project hashes. A successful episode needs observed evidence and appends one update event to the original completed task while preserving its original completion time/session. The stable event ID makes retries idempotent. A failed episode marks verification pending, can lower the current rating, records the exact continuation, and appends no successful update token.

Correction ratings update the original task and originating session contribution. A correction is not a new task and must not inflate project completion or rating counts.
