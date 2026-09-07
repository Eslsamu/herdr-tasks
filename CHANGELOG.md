# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [Unreleased]

## [0.3.3] - 2026-09-07

### Fixed

- Replace the default Option/Alt shortcut with the terminal-independent Herdr sequence `prefix+ctrl+t` (`Ctrl+B`, then `Ctrl+T` with the default prefix).
- Remove the macOS Meta-key requirement, which caused Option+T to type `†` in Apple Terminal for users without profile-level remapping.

## [0.3.2] - 2026-09-07

### Added

- Add a conflict-safe default `alt+t` shortcut, presented as Option+T on macOS and Alt+T on Linux, for opening the active space's browser queue.

### Changed

- Replace incorrect sidebar-menu instructions with the actual shortcut and command paths.
- Document the terminal-level Alt/Meta requirement instead of promising that every terminal forwards Option/Alt identically.

## [0.3.1] - 2026-09-07

### Added

- Add a deterministic, fully synthetic product demo with reproducible MP4, WebM, and poster outputs.

### Fixed

- Make cross-platform terminal interaction tests deterministic across ncurses implementations.
- Skip an unnecessary reverse-DNS lookup for numeric loopback that can stall under macOS Local Network Privacy, and allow slower cold starts.
- Close rejected browser mutation requests cleanly instead of parsing their bodies as new requests.

## [0.3.0] - 2026-09-07

### Added

- Read-only local browser viewer with live two-second updates.
- Space-pinned opaque URLs and a sanitized display-only API.
- Responsive desktop/mobile queue ledger with accessible task disclosures.
- Automatic viewer restart, stable URLs where the port remains available, and verified cleanup.
- Portable launcher for Herdr's non-login-shell plugin environment.

### Changed

- Browser view is now the default full-queue action.
- Compact terminal viewer remains available as an explicit fallback.
- Setup starts viewers for linked spaces and keeps the top-bar preview.

### Security

- Reject foreign hosts, invalid capability paths, and all HTTP mutation methods.
- Remove member actor and durable conversation IDs from browser responses.
- Add restrictive CSP, no-store, no-referrer, no-CORS, and same-origin headers.

## [0.2.0] - 2026-09-07

### Added

- Space-linked queues and automatic active-space top-bar summaries.
- Compact clickable terminal viewer that preserves existing PTYs.

## [0.1.0] - 2026-09-07

### Added

- Agent-owned SQLite task boards, ownership, atomic claims, dependencies, and Codex workflow skill.

[Unreleased]: https://github.com/Eslsamu/herdr-tasks/compare/v0.3.3...HEAD
[0.3.3]: https://github.com/Eslsamu/herdr-tasks/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Eslsamu/herdr-tasks/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Eslsamu/herdr-tasks/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Eslsamu/herdr-tasks/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Eslsamu/herdr-tasks/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Eslsamu/herdr-tasks/releases/tag/v0.1.0
