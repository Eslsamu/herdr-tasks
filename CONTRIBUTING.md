# Contributing

Thanks for helping improve Herdr Tasks. The project deliberately stays small: Python standard library, SQLite, dependency-free browser assets, and no changes to Herdr itself.

## Development setup

```sh
git clone https://github.com/Eslsamu/herdr-tasks.git
cd herdr-tasks
python3 -m unittest -v
sh -n run.sh
```

Python 3.10 is the minimum supported version. Tests should also pass on the newest version in the CI matrix.

To try a local checkout in Herdr:

```sh
herdr plugin link "$PWD" --enabled
herdr plugin action invoke setup --plugin herdr-tasks
```

Use a disposable named Herdr session and a temporary `HERDR_TASKS_DB` when testing integration changes. Do not use a real task database as a fixture.

## Code map

| Area | Files |
| --- | --- |
| Queue rules, SQLite storage, Herdr identity, space binding, setup, and browser service | `herdr_tasks.py` |
| Optional terminal viewer | `queue_view.py` |
| Semantic browser shell and states | `web/index.html` |
| Polling, classification, rendering, and view preservation | `web/app.js` |
| Responsive layout, focus, color modes, and reduced motion | `web/styles.css` |
| Agent queue-maintenance contract | `skill/SKILL.md` |
| Herdr entry points and portable launcher | `herdr-plugin.toml`, `run.sh` |
| Synthetic demo fixture, deterministic capture, and media contract | `demo/`, `test_demo.py` |
| Behavioral tests and supported OS/Python matrix | `test_herdr_tasks.py`, `test_demo.py`, `.github/workflows/test.yml` |

Start queue-semantics changes in the store and its tests. Herdr lifecycle changes belong with identity, setup, and integration tests. HTTP or privacy changes belong with the browser payload/handler and browser tests. Browser behavior changes need both `web/` coverage and the manual browser checklist below. Agent-behavior changes must keep the installed skill and README examples aligned.

## Design constraints

Changes should preserve these properties:

- Agents own queue maintenance; the human viewer remains read-only.
- A browser capability is fixed to one session/workspace/board scope.
- Task data and durable conversation IDs never enter repository fixtures or screenshots.
- Existing Herdr panes and agent PTYs are never replaced to create a viewer.
- Resume retains identity; forks join explicitly.
- Runtime dependencies remain in the Python standard library unless there is a compelling reason to change that.
- Accessibility, keyboard operation, narrow viewports, and reduced motion are first-class requirements.

## Pull requests

Keep changes focused and include tests for behavior changes. Before opening a pull request:

```sh
python3 -W error::ResourceWarning -m unittest -v
sh -n run.sh
git diff --check
```

If browser UI changes, also verify:

- desktop and 390 px layouts;
- no horizontal overflow;
- task strings are inserted with `textContent`, never HTML;
- expanded rows, focus, and scroll survive polling;
- loading, empty, stale, and error states remain understandable.

Use generic names such as `SpaceName`, `ProjectName`, `Agent One`, and `Agent Two` in fixtures and documentation. Never commit real task data, capability URLs, session sockets, credentials, or user-specific paths.

## Reporting problems

Use a GitHub issue for ordinary bugs and feature proposals. Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). For a vulnerability or suspected data exposure, follow [SECURITY.md](SECURITY.md) instead.
