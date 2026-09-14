---
name: harness
description: Use at the start of work in this repository to load its operating contract, source specification, verified commands, permissions, and current GHL state before changing skill runtime or packaging files.
---

# Harness

1. Read `AGENTS.md` once and inspect `.Codex/ghl-state.json` if it exists.
2. Identify the exact source, test, reference, and installer files the task touches.
3. Treat `keepgoing_skill_development_prompt.md` as requirements authority and actual files/test output as implementation authority.
4. Check paths remain inside the repository and never expose secrets or mutate generated/live governed workspaces.
5. Run only commands listed in `AGENTS.md` or discovered from repository files; record their exit codes.
6. Update graph state after each demonstrated node transition and preserve errors immediately.
