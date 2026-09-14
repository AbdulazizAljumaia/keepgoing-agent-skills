# Lifecycle, evidence, checkpoint, and rating workflow

## Authority order

Current user/repository instructions authorize scope. `instructions/project.md` maps requirements; `structure.md` controls placement; active plans control unfinished implementation; committed checksummed ledger events control lifecycle; actual files and observed verification control implementation truth. `state.json` and Markdown indexes are validated views.

## Task and plan lifecycle

Use pending/ready → in progress → verification → complete. Failed checks return the task to in progress, verification pending, or blocked. A dependency must be complete before dependent work starts. Cancellation or supersession requires an authorized reason.

For completion, pass at least one observed evidence description and hash every implemented file with `--evidence-file`. Evidence becomes stale when any hashed file changes. `complete-plan` verifies task state, stores the exact active plan bytes as base64 plus SHA-256 in its closing session, updates indexes, then removes the active plan file.

## Sessions and checkpoints

One live invocation uses one session; do not allocate a session for each tool call. A fresh invocation after a committed checkpoint may use `resume --open-session`. An incomplete checkpoint must name plan/task, numbered step, next action, relevant paths, verification still needed, and actions not to repeat.

Measured context checkpoints at 70% usage or forecast. Estimated mode uses a conservative 65% threshold. Unavailable mode reports no percentage and requests a checkpoint after each coherent work unit. The runtime cannot restart a model by itself.

## Ratings

Rate completed task history from 1–10 across correctness 40%, reliability 20%, maintainability 15%, rule compliance 15%, and efficiency 10%. `N/A` removes a genuinely inapplicable dimension and normalizes remaining weights; missing applicable evidence is not N/A. Critical defects cap at 3, material acceptance failures at 5, and runtime behavior supported only by static inspection at 6. Aggregate unique task scores with task weights, never session averages.
