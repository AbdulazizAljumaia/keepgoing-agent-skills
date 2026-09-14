# Application profiles

The organizer envelope is stable; internal application layout follows the selected profile. Only paths named by an active task are editable even when their parent profile directory is permitted.

## Generic backend

Use `Project/apps/api/` for the runnable application, with native source, manifest, local tests, configuration, and optional container definition. Keep business behavior out of thin route handlers and declare concrete service/data boundaries in the plan.

## Angular

Use `Project/apps/web/`. Plan native entrypoints such as `src/index.html`, `src/main.ts`, `src/styles.scss`, `src/app/app.config.ts`, `src/app/app.routes.ts`, `angular.json`, `package.json`, and TypeScript configuration for the selected version. Place foundational services in `core`, reusable presentation in `shared`, and feature-owned UI/data/pages under `features/<feature>`. Client environment values are not secrets.

## Flutter

Use `Project/apps/flutter_app/` with `lib/core`, `lib/features/<feature>/{data,domain,presentation}`, `lib/shared`, tests, integration tests, declared assets, `pubspec.yaml`, analysis configuration, and only requested platform shells.

## Pure PHP

Use `Project/apps/web/`, with `public/` as the only document root and implementation/configuration outside it. Use one authoritative migration location and keep shared SQL artifacts under the planned SQL paths.

## Other frameworks

Do not select the nearest profile and pretend it is accurate. Record a new concrete profile and extend the runtime/tests in an authorized skill revision before initializing that project.
