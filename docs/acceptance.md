# Behavioral acceptance evidence

Run `python scripts/validate.py` from the repository root. Destructive and interrupted operations run only in disposable temporary fixtures.

| Scenario | Automated evidence | Status |
| --- | --- | --- |
| Fresh initialization | `test_01_fresh_initialization` | Pass |
| Initialization repeated | `test_02_repeated_initialization_is_idempotent` | Pass |
| Resume from nested app path | `test_03_resume_from_nested_application_path` | Pass |
| Invocation inside an archive | `test_04_archive_invocation_is_protected` | Pass |
| Framework profile selection | `test_05_framework_profiles_share_envelope_and_differ_inside` | Pass |
| Unplanned path | `test_06_unplanned_path_is_rejected_and_drift_detected` | Pass |
| Complete-plan handoff | `test_07_complete_plan_preserves_exact_snapshot` | Pass |
| Plan spanning sessions | `test_08_plan_spanning_sessions_keeps_original_completion_sessions` | Pass |
| Partial task | `test_09_partial_task_checkpoint_is_executable` | Pass |
| Fresh-context resume | `test_10_fresh_process_resume_uses_saved_records` | Pass (new subprocess) |
| Exact context boundary | `test_11_exact_context_boundary_and_forecast` | Pass (simulated input) |
| Unknown context usage | `test_12_unknown_context_never_fabricates_percentage` | Pass |
| Interrupted checkpoint/record transaction | `test_13_interrupted_record_transaction_rolls_forward` | Pass (injected failure) |
| Disk/write failure | `test_14_disk_write_failure_preserves_prior_snapshot` | Pass (injected failure) |
| Damaged state or truncated event | `test_15_damaged_state_and_truncated_tail_are_recovered` | Pass |
| One keepfixing correction | `test_16_one_keepfixing_correction_preserves_completion` | Pass |
| Repeated corrections and retry | `test_17_repeated_corrections_are_distinct_and_idempotent` | Pass |
| keepfixing needs a new file | `test_18_keepfixing_blocks_new_persistent_path` | Pass |
| keepfixing metadata | `test_19_keepfixing_metadata_creates_no_workspace_path` | Pass |
| Failed correction verification | `test_20_failed_correction_stays_unresolved_without_update` | Pass |
| Rating aggregation | `test_21_rating_aggregation_uses_unique_weighted_tasks` | Pass |
| Empty or unfinished project | `test_22_unfinished_project_never_claims_ten` | Pass |
| User scope revision | `test_23_scope_revision_preserves_superseded_requirement` | Pass |
| Blocked dependency | `test_24_blocked_dependency_does_not_hide_independent_work` | Pass |
| External source changes | `test_25_external_source_change_invalidates_evidence` | Pass |
| Explicit replacement | `test_26_explicit_replacement_preserves_history_and_lineage` | Pass |
| Interrupted replacement | `test_27_interrupted_replacement_recovers_each_boundary_class` | Pass (three injected boundaries) |
| Archive naming collision | `test_28_archive_name_collision_uses_portable_suffix` | Pass |
| Path and platform handling | `test_29_path_platform_and_symlink_boundaries` | Pass on Windows junction or symlink-capable hosts; otherwise reported as host skip |
| Concurrent access | `test_30_concurrent_writer_cannot_consume_shared_state` | Pass |
| Nested active/archive initialization boundaries | `test_31_initialization_rejects_nested_active_and_archive_targets` | Pass |
| Adoption collision preservation | `test_32_adoption_refuses_user_owned_organizer_collision` | Pass |
| Completion requires plan closure | `test_33_status_requires_plan_closure_before_completion` | Pass |
| Ledger authority and derived-view validation | `test_34_state_and_derived_views_are_checked_against_authority` | Pass |
| Strict correction change and boundary protection | `test_35_successful_fix_requires_change_and_protects_boundary_content` | Pass |
| Serialized stale-writer rejection | `test_36_stale_serialized_writer_cannot_erase_allocated_plan` | Pass |
| Prepared ledger metadata and private recovery bundle | `test_37_prepared_ledger_is_checksum_metadata_not_raw_records` | Pass |
| Replacement baseline tamper rejection | `test_38_replacement_recovery_rejects_tampered_archive` | Pass |
| Cross-filesystem verified move fallback | `test_39_verified_move_falls_back_across_filesystems` | Pass |
| Shipped Notes API specification and documented envelope | `test_43_shipped_example_spec_generates_documented_envelope` | Pass |

Additional tests cover adoption preview/execution, lossless plan revisions, isolated installation, provider exposure, runtime dependency resolution, and dry-run non-mutation.
