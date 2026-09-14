# Example governed workspace

Read this reference when explaining the organizer layout, preparing an initialization specification, or deciding which record owns a piece of state.

## Example intent

The shipped `assets/workspace-spec.example.json` describes a generic Notes API with two requirements, one plan, one task, and two planned files:

- `Project/apps/api/src/notes.py`
- `Project/apps/api/tests/test_notes.py`

Initialization creates the fixed envelope and native directories first. It does not create those application files; the implementing agent does so only after `path-check` confirms `TASK-001` owns them.

## Envelope and ownership

```text
workspace/
|-- Project/                 Real application source and generated runtime data
|   `-- apps/api/            Generic-profile application root
|       |-- src/
|       `-- tests/
|-- instructions/           Scope, structure, rules, decisions, state, ledger
|-- plans/                  Full active instructions plus the plan index
|-- sessions/               Chronology, evidence, exact snapshots, handoffs
|-- rates/                  Per-session and aggregate evidence-backed ratings
`-- deprecated/             Fixed replacement marker and organizer-protected archives
```

Use the records according to their authority:

1. `instructions/project.md` maps user requirements to stable IDs and acceptance.
2. `instructions/structure.md` decides where application files may live.
3. `plans/plan_N.md` contains complete unfinished implementation instructions.
4. `instructions/ledger.jsonl` is the committed lifecycle authority; `state.json` is its validated fast snapshot.
5. `sessions/session_N.md` stores observed actions, evidence, exact completed-plan snapshots, and continuation.
6. `Project/` plus observed checks determine whether implementation actually works.

## Lifecycle example

```text
initialize
  -> PLAN-001 and TASK-001 are allocated
  -> path-check authorizes each planned file
  -> TASK-001 moves to in_progress
  -> agent implements notes.py and test_notes.py
  -> TASK-001 moves to verification
  -> agent runs the required tests and observes their exit code
  -> passing evidence plus both file hashes permit TASK-001 to complete
  -> complete-plan snapshots plan_1.md into session_1.md
  -> plan_1.md leaves the active queue
```

If work stops earlier, checkpoint with the exact task, step, next action, relevant paths, remaining verification, and actions not to repeat. If a completed file later needs a content-only correction, use keepfixing with an event ID and existing-file allowlist; do not add a path to disguise new scope as a fix.
