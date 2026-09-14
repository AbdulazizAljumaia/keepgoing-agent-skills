# Transactions, validation, and generation recovery

Use this reference when validation reports a prepared transaction, damaged ledger tail, concurrent ownership, or an explicitly authorized project replacement.

## Normal record recovery

Mutations acquire a host-private single-writer lock and compare the loaded committed revision before allocating IDs. They append a checksummed `TX_PREPARED` event containing only operation metadata, state/write checksums, target paths, and a reference to a host-private recovery bundle; raw record contents are not duplicated in the append-only ledger. The bundle stages the intended state and writes outside the governed workspace, after which replacements are applied and `TX_COMMITTED` is appended. `recover` rolls a complete prepared write set forward or rebuilds state/derived views from the latest committed snapshot. A malformed final ledger fragment is preserved under the host-private recovery directory before the valid prefix is restored. Hash-chain corruption, a missing bundle, or a checksum mismatch blocks automatic recovery.

Atomic multi-file commit is not claimed. The design provides a recoverable journal and idempotent transaction/event identities. Filesystems that cannot replace from host-private staging may briefly require a same-directory temporary fallback; validation discloses persistent drift.

## Replacement

Replacement requires explicit user authorization and `replace --dry-run`. The runtime builds a complete new generation in host-private staging, writes `deprecated/replacement.json`, moves the current `Project`, `instructions`, `plans`, `sessions`, and `rates` into a unique portable dated archive, verifies its manifest, and promotes the new canonical generation. `deprecated/` never moves into itself.

If interrupted, invoke `recover-replacement` from the original boundary. When staging is intact, recovery completes promotion. When staging is lost, recovery preserves partial new content privately and restores the predecessor without overwriting an active path. Replacement does not authorize deployment, live-database destruction, credential changes, or unrelated external mutations.
