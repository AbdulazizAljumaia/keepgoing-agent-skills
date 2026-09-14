# Initialization specification

Use this reference for `initialize`, `adopt`, plan allocation, or an authorized requirement revision.

## Required top-level fields

- `project_name`: concrete display name.
- `scope`: full authorized outcome and boundary.
- `profile`: `generic`, `angular`, `flutter`, or `php`.
- `requirements`: one or more objects with `title` and observable `acceptance`.
- `plans`: cohesive ordered plans. Every requirement number must be mapped.
- `rules`: material user/repository rules; omit only when none apply.
- `timezone`: optional IANA label or explicit UTC offset observed from the environment.

Each plan requires `title`, `outcome`, `scope`, `architecture`, `requirements`, `dependencies`, and `tasks`. Dependencies reference earlier 1-based plan numbers. Each task requires a title, exact `Project/` file paths, implementation steps, acceptance criteria, verification, and failure behavior. Optional fields include `weight`, `required`, `priority`, `preconditions`, `completion_conditions`, and `owner`.

The runtime rejects traversal, absolute application paths, paths outside the selected profile, unmapped requirements, forward dependencies, and incomplete plans. It assigns stable requirement, plan, task, session, event, transaction, workspace, and generation identifiers.

Use `assets/workspace-spec.example.json` as a concrete format example. Author the live specification in host-private temporary storage because it is an initialization input, not application source.

## Adoption

Run `adopt --dry-run` first. The preview identifies boundary-owned files it preserves and application candidates it would move under `Project/`. If the app already lives in `Project/`, the organizer must not create `Project/Project`. Existing implementation is observed/imported, not assigned invented historical completion evidence.

## Revisions

`requirement-revise` preserves the previous requirement, acceptance text, reason, and authorizing instruction. `plan-revise` preserves the prior exact plan bytes and hash. A new path belongs in a newly allocated authorized plan; keepfixing cannot revise scope or structure.
