# Workspace structure example

The Example Notes API specification selects the `generic` profile and authorizes two application files. The organizer envelope stays the same across profiles; only the native application directories and planned files differ.

## Immediately after initialization

```text
notes-workspace/
|-- Project/                         Application source boundary
|   |-- .github/workflows/           Reserved CI container
|   |-- apps/
|   |   `-- api/
|   |       |-- src/                 Generic-backend source root
|   |       `-- tests/               Generic-backend local tests
|   |-- packages/                    Shared internal packages
|   |-- apis/                        API contracts and examples
|   |-- sql/                         SQL artifacts when planned
|   |-- tests/                       Cross-application integration/e2e tests
|   |-- config/                      Nonsecret environment configuration
|   |-- scripts/                     Project automation
|   |-- docs/                        Application documentation
|   |-- infra/                       Activated deployment definitions
|   `-- storage/                     Generated local runtime material
|-- instructions/
|   |-- project.md                   Scope, REQ-001/REQ-002, coverage, lineage
|   |-- structure.md                 Binding placement and path authority
|   |-- rules.md                     Project and organizer rules
|   |-- decisions.md                 Dated decisions and revisions
|   |-- capabilities.md              Observed host capabilities and limits
|   |-- state.json                   Validated fast runtime snapshot
|   `-- ledger.jsonl                 Checksummed prepared/committed events
|-- plans/
|   |-- plan_1.md                    Full active PLAN-001 instructions
|   `-- plan_index.md                Active/completed plan index and pointer
|-- sessions/
|   |-- session_1.md                 Chronology, evidence, snapshots, handoff
|   `-- session_sum.md               Concise unresolved-work index
|-- rates/
|   |-- session_1_rate.md            Per-session evidence-backed ratings
|   `-- Sessions_rate.md             Aggregate unique-task rating
`-- deprecated/                      Replacement marker and frozen archives
```

The fixed containers are created empty when they are not needed. Empty containers are reservations, not claims that a framework, deployment system, or database has been implemented.

The planned application files are named in `instructions/structure.md` and `plans/plan_1.md`, but they do not exist yet:

```text
Project/apps/api/src/notes.py
Project/apps/api/tests/test_notes.py
```

This ordering matters: requirements, structure authority, and a complete plan exist before application code is created.

## During implementation

The agent reads `state.json` plus the continuation pointer, opens the complete active plan, and calls `path-check` before editing. Once authorized, it creates only the planned files:

```text
Project/apps/api/
|-- src/
|   `-- notes.py
`-- tests/
    `-- test_notes.py
```

The runtime does not write the notes implementation. It records lifecycle transitions and hashes the real files only when observed verification supports completion.

## After a checkpoint

If the task remains unfinished, these records change together in a recoverable transaction:

- `instructions/state.json` stores the task state and structured continuation.
- `instructions/ledger.jsonl` appends prepared and committed checksum metadata.
- `plans/plan_1.md` retains full unfinished instructions and the next step.
- `sessions/session_1.md` records the action, evidence, failure, and handoff.
- `sessions/session_sum.md` points a fresh process to the unresolved task.

The application files remain the source of implementation truth. Organizer prose cannot turn missing or failing code into a completed task.

## After plan completion

When every required task and verification gate passes, `complete-plan` preserves the exact `plan_1.md` bytes as base64 with a SHA-256 hash in the closing session. Only then does it remove the active plan file:

```text
plans/
`-- plan_index.md                    PLAN-001 points to its session snapshot

sessions/
|-- session_1.md                     Contains the exact PLAN-001 snapshot
`-- session_sum.md                   No false unfinished pointer remains
```

Stable IDs are never reused within the generation. A later plan becomes `PLAN-002`, its first new task receives the next `TASK-NNN`, and a new session receives the next `SESSION-NNN`.

## Strict keepfixing behavior

`keepfixing` captures the complete path inventory before a correction. It may update the contents of an allowlisted existing file and existing organizer records, but the before/after persistent path set must be identical. A correction that needs a new route, migration, test file, or directory is blocked and belongs in an authorized keepgoing plan.

## Replacement archives

Explicit replacement preserves the five active groups (`Project`, `instructions`, `plans`, `sessions`, and `rates`) under a collision-free directory in `deprecated/`. The fixed `deprecated/replacement.json` marker stores predecessor and staged-generation manifests before the first move. Recovery verifies those manifests before it completes promotion or restores the predecessor.

For the agent-facing version bundled with installed skills, see [the example-workspace reference](../skills/keepgoing/references/example-workspace.md).
