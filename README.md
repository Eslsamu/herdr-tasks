# Herdr Tasks

**Talk to your agents. Watch the work. Don't manage cards.**

A small Herdr plugin for people who already work with several long-running agent conversations. Agents own a shared task board, record new requests, choose what comes next, and keep the status current. You get a read-only terminal overview.

```
 TASKS / agent-owned
 Product / Dev, GTM

 QUEUED                 DOING                 BLOCKED               DONE
 #8 Saved filters       #6 Fix CSV export     #5 Publish launch     #3 Signup flow
 Dev                    Dev                   GTM                   Dev
                        Testing quoted rows   Needs domain choice   Verified on mobile
```

No web app, server, model API, telemetry, external account, or Python package dependencies. Task data stays on your machine. Works with existing conversations; does not start, stop, fork, resume, or replace them.

## Install

Requires macOS/Linux, **Herdr 0.8.2+**, and **Python 3.10+ with curses**. The included workflow is for Codex; the CLI identifies agents through Herdr's durable session IDs.

Inside Herdr:

```sh
herdr plugin install Eslsamu/herdr-tasks --ref v0.1.0
herdr plugin action invoke setup --plugin herdr-tasks
```

Setup links the CLI into `~/.local/bin`, installs a Codex skill into `~/.codex/skills/herdr-tasks`, and adds **Ctrl+B, then Shift+T** to open the board. It backs up your Herdr config and leaves existing keybindings intact. If that shortcut is already used, setup skips it; use the plugin's **Tasks: view agent board** action instead.

If `~/.local/bin` is not on your PATH, use `~/.local/bin/herdr-tasks` or add that directory to your normal shell configuration. Existing Codex threads can read `herdr-tasks skill` immediately; new threads can discover the installed skill normally.

For a local checkout, substitute the install command with:

```sh
herdr plugin link /absolute/path/to/herdr-tasks --enabled
```

## Use it

Tell an agent:

> Read `herdr-tasks skill`, join the "Product" board, and maintain it for the work I give you. Record later requests without abandoning your current task. Keep the board current and work through the authorized queue.

Give the same board name to another agent to share it. Use different board names for unrelated projects. Then talk normally:

> After your current task, fix CSV export and add saved filters.

The agent records and orders those requests. You only open the viewer. The overlay initially selects the focused agent's board; **b** cycles boards, **j/k** scroll, **#** opens a task's details/history, and **q/Esc** closes it. Narrow terminals use a stacked view. Done shows the most recent 20 tasks; all tasks, including cancellations, remain available through the CLI.

An operator can enroll an existing agent without typing into its terminal:

```sh
herdr-tasks --agent your-agent-name join Product
```

Enrollment stores membership only. The agent still needs the workflow instruction to maintain the board.

## How agents coordinate

- Four visible states: queued, doing, blocked, done. Cancellation is retained in history.
- Each task has one owner. Claiming is atomic; two agents cannot claim the same task.
- One doing task per owner per board. `next` returns existing active work instead of starting another task.
- Priority 0 is highest; ties run oldest first. Optional dependencies must finish before a task starts.
- Only the owner can change active work or mark its outcome. Queued work can be reassigned by teammates.
- Completing, blocking, or cancelling requires an explanatory note. Claims and changes are recorded in history.
- Membership and ownership follow the conversation ID, not its pane number. Resume retains ownership; forks explicitly join as new members.

This is cooperative local coordination, **not a security boundary** between programs running as the same OS user. Explicit `--agent` targets are available to authorized operators. The plugin does not infer what a model is doing or verify its claims of completion.

### Deliberate limits

There are no hooks or background scheduler. A new request appears when the agent processes it at a safe boundary, not the instant you type it. The workflow tells an agent to continue through its authorized queue, but this plugin cannot wake an idle/offline thread, bypass usage limits, or guarantee model compliance. Assigning a task to an idle teammate does not automatically send that teammate a prompt.

Dependencies currently refer to existing tasks on the same board. Blocked tasks require explicit requeueing; cancelling a prerequisite does not silently release dependent tasks.

## CLI

Commands print JSON except the viewer and skill. Global options precede the command.

```sh
herdr-tasks join Product
herdr-tasks list
herdr-tasks add "Fix CSV export" --detail "Preserve quoted commas and Unicode."
herdr-tasks add "Write launch copy" --owner gtm --priority 4 --after 1
herdr-tasks next
herdr-tasks update 1 --note "Regression reproduced; testing the fix."
herdr-tasks update 1 --status done --note "Quoted fields fixed; regression tests pass."
herdr-tasks show 1
herdr-tasks --board Product list
herdr-tasks --board Product view
herdr-tasks --help
```

Read-only `boards`, explicit-board `list`, `show`, and `view` also work outside Herdr. Writes require a Herdr agent with a reported durable session ID. If an agent belongs to several boards, pass `--board NAME`.

## Data and removal

Default storage: `~/.local/state/herdr-tasks/tasks.db` (or `$XDG_STATE_HOME/herdr-tasks/tasks.db`). Set `HERDR_TASKS_DB` to override it. SQLite WAL handles concurrent readers/writers. Don't copy only the `.db` file during active writes: use SQLite's backup facility, or export a board snapshot with `herdr-tasks --board Product list`.

Task contents can be sensitive. Do not include credentials or unrelated private conversation content. The database is outside this repository and is never uploaded by the plugin.

To remove the integration inside Herdr:

```sh
herdr plugin action invoke uninstall --plugin herdr-tasks
herdr plugin uninstall herdr-tasks
```

For a linked local checkout, use `herdr plugin unlink herdr-tasks` as the second command. Cleanup removes only its own CLI/skill links and marked shortcut block. **Task data is kept.** No conversations are touched.

## Develop

```sh
python3 -m unittest -v
```

One Python program, SQLite, curses, and a Herdr manifest. The included tests cover ownership, concurrent claims, dependencies, resume/fork identity, and configuration integration. No package installation required.

MIT licensed.
