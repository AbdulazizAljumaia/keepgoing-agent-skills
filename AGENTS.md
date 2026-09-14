# Keepgoing Agent Skills — Operating Contract

## Stack

- Python 3.13 standard library for deterministic runtime behavior.
- Markdown and JSON for skill instructions, references, templates, and governed-workspace records.
- GitHub Actions for portable validation after publication.
- No runtime package manager or third-party Python dependency is required.

## Commands

- install: none required
- test: `python -m unittest discover -s tests -v`
- lint: none found
- typecheck: none found
- build: none required
- full validation: `python scripts/validate.py`

Run commands from the repository root. Do not report success without the command output and exit code.

## Architecture

- `skills/keepgoing/` is the canonical organizer skill and owns the shared Python runtime.
- `skills/keepfixing/` is the restricted repair skill and delegates all state changes to the keepgoing runtime.
- `scripts/install.py` installs or links both skills for supported agent hosts; provider adapters must not fork runtime logic.
- `tests/` validates observable workspace invariants with disposable temporary fixtures.
- `docs/` records supported host behavior and acceptance evidence without claiming unsupported hooks.
- `keepgoing_skill_development_prompt.md` is the source specification and remains unchanged.

## GHL Protocol

This project runs GHL: Harness → Graph → Node/Loop → Validation → Review → Finish.
Run `/ghl` for the full protocol. Graph state: `.Codex/ghl-state.json`.

## Rules

- Keep all deterministic bookkeeping in the keepgoing runtime; keepfixing may only call it in restricted mode.
- Keep skill entrypoints concise and route conditional detail to linked references.
- Use standard-library Python and portable path handling; support Windows, macOS, and Linux paths with spaces and non-ASCII names.
- Test destructive archive/recovery behavior only in disposable temporary fixtures.
- Never print secrets, follow escaping symlinks, overwrite an archive, fabricate host integrations, or treat a record as implementation evidence.
- Preserve the source prompt as the requirements authority and map limitations honestly in capability documentation.

## Security constraints

- Resolve and validate every managed path against the governed workspace before mutation.
- Reject traversal, escaping symlinks, case-colliding paths, and concurrent writers.
- Keep transaction/lock scratch data outside governed workspaces; keep persistent recovery markers explicit.
- Never read secret values for reporting or publish generated fixtures containing user data.

## Definition of Done

- Both skill folders pass the available skill validator.
- The complete behavioral test suite passes from a clean checkout.
- Cross-agent installation is exercised in an isolated fake home.
- A fresh process can resume solely from durable workspace records.
- A public GitHub repository exists at the reported URL and its pushed commit matches the validated local commit.
