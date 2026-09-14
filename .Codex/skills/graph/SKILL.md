---
name: graph
description: Use when a repository task spans skill instructions, shared runtime, installer, tests, documentation, or publication and therefore needs evidence-based routing between multiple owning nodes.
---

# Graph

1. Write the request, completion criteria, and unresolved facts to `.Codex/ghl-state.json`.
2. Route instruction design to `ARCHITECT`, runtime or installer changes to `IMPLEMENT`, unexplained failures to `DEBUG`, completed work to `TEST`, green results to `REVIEW`, and approved publication to `FINISH`.
3. Enter a node only when its evidence-backed precondition is satisfied.
4. Record the current and previous node, artifacts, observations, errors, and attempt counts on every transition.
5. Replan immediately when observed evidence contradicts the pending route.
6. Finish only when the operating contract and public-publication criteria are demonstrated.
