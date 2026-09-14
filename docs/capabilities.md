# Capability report

## Verified in this release

- Standard-library Python runtime with stable IDs, strict lifecycle transitions, requirement/plan/task/session registries, exact plan snapshots, evidence file hashes, ratings, structured continuation, and JSON output/exit codes.
- Workspace discovery from nested application paths and archive-boundary protection.
- Host-private single-writer ownership using live local process evidence; age alone never breaks a lock.
- Checksummed prepared/committed ledger metadata with host-private recovery bundles, state/derived-view authority checks, safe truncated-tail preservation, and roll-forward of interrupted record transactions.
- Exact planned-path preflight, direct-drift detection, stale-evidence detection, traversal rejection, and escaping link/junction checks.
- Strict keepfixing path-inventory enforcement, existing-file allowlists, failed-correction state, deduplicated successful update events, and preservation of original completion timestamps.
- Measured, estimated, and unavailable context modes. The acceptance fixture's 70% event is explicitly simulated host input.
- Dry-run adoption/replacement, verified generation archives, portable collision-free names, fixed recovery marker, forward recovery, and predecessor lineage.
- Persistent cross-agent installation under `.agents/skills`, with Claude links/copies under `.claude/skills`, including replacement of unsafe checkout links/junctions and post-source-deletion verification in a disposable fake home.

## Host evidence

Local inspection used Claude Code 2.1.270, Codex CLI 0.154.0, OpenCode 1.18.19, and Grok CLI 1.0.30. Codex, OpenCode, and Grok documented or resolved the user `.agents/skills` root; Claude documented `.claude/skills`, which the installer supplies from the same canonical package. Gemini was not installed and was not claimed as validated.

## Honest limits

- Direct edits made outside the runtime cannot be universally intercepted; they are detected at drift validation/checkpoint. No provider-independent edit hook exists.
- Context usage is exact only when a host supplies authoritative current-window values. The runtime does not inspect hidden model state.
- Durable records enable a fresh invocation to resume; the skill cannot restart a model or force a host to continue unless that host exposes and runs a separately verified adapter.
- Multi-file filesystem atomicity is not promised. Prepared events, external staging, hashes, backups, and replacement markers make supported operations recoverable.
- Network/shared-filesystem locking semantics are host-dependent; this release validates local single-host coordination.
- Public GitHub visibility and provider discovery are separate. A user must install the repository or plugin; a URL alone is not automatically loaded.
- No project license was selected, so public visibility is not a grant of reuse rights.
