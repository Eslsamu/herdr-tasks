# Herdr Tasks

**Talk to your agents. Watch the work. Don't manage cards.**

A small Herdr plugin for people who already work with several long-running agent conversations. Agents own a shared task board, record new requests, choose what comes next, and keep the status current. You get a read-only terminal overview.

```
 Product / Tasks                                      [Close]
 1 now · 1 next · 1 waiting

 Now · 1
 v #6  Dev · Fix CSV export
    Preserve quoted commas and Unicode.
    Update: Testing the parser fix.

 Waiting · 1
 > #5  GTM · Publish launch
   Needs domain choice

 Next · 1
 > #8  Dev · Saved filters

 > Finished · 4
```

No web app, server, model API, telemetry, external account, or Python package dependencies. Task data stays on your machine. Works with existing conversations; does not start, stop, fork, resume, or replace them.

## Install

Requires macOS/Linux, **Herdr 0.8.2+**, and **Python 3.10+ with curses**. The included workflow is for Codex; the CLI identifies agents through Herdr's durable session IDs.

Inside Herdr:

```sh
herdr plugin install Eslsamu/herdr-tasks --ref v0.2.0
herdr plugin action invoke setup --plugin herdr-tasks
```

Setup links the CLI into `~/.local/bin`, installs a Codex skill into `~/.codex/skills/herdr-tasks`, and adds a live current-space summary to Herdr's top tab bar. It backs up your config and preserves unrelated settings. **No shortcut is assigned by default.** Use Herdr's plugin action **Tasks: open space queue**, or `herdr-tasks open`.

For an optional shortcut, run `herdr-tasks setup --key alt+t` with a binding your terminal actually delivers. This is an example, not a universal Mac keyboard recommendation. Configured conflicts are rejected. Running setup without `--key` removes the plugin's previous shortcut, including the old Ctrl+B / Shift+T binding.

If your config already defines `tab_bar_right` as an inline array, setup preserves it. Add this entry to that array to enable the summary: `{ type = "command", command = "~/.local/bin/herdr-tasks status", interval_seconds = 2, timeout_seconds = 1 }`. Existing array-of-table entries coexist automatically. Herdr's status text is not clickable and may be hidden when the tab row is too narrow.

If `~/.local/bin` is not on your PATH, use `~/.local/bin/herdr-tasks` or add that directory to your normal shell configuration. Existing Codex threads can read `herdr-tasks skill` immediately; new threads can discover the installed skill normally.

For a local checkout, substitute the install command with:

```sh
herdr plugin link /absolute/path/to/herdr-tasks --enabled
```

## Use it

Tell an agent:

> Read `herdr-tasks skill`, join the "Product" board, and maintain it for the work I give you. Record later requests without abandoning your current task. Keep the board current and work through the authorized queue.

Joining links that queue to the agent's Herdr space. Give the same queue name to other agents in that space; different spaces get different queues. Bindings use session socket and workspace ID, so renaming a space does not change the binding. Then talk normally:

> After your current task, fix CSV export and add saved filters.

The agent records and orders those requests. You only open the viewer. It opens **below the focused terminal**, using about 30% of that terminal's height, and keeps the other panes intact. It is a normal split, not an overlay or popup. Drag Herdr's divider if you want more space. Reopening in the same tab reuses the existing viewer.

**Click a task** or press **Enter/Space** to expand its description inline. **Arrows/j/k** select tasks; **mouse wheel/PageUp/PageDown** scroll. Finished/cancelled work is under a collapsed history row. **[Close]**, **q**, or **Esc** closes only the viewer; the original terminal regains its split space and the top-bar summary remains. Classic xterm and SGR mouse reports depend on the terminal's advertised capabilities.

The layout stays a single ordered list at every width. Short panes show a scroll range. Your agents continue working while it is open; typing goes to whichever pane you focus.

An operator can enroll an existing agent without typing into its terminal:

```sh
herdr-tasks --agent your-agent-name join Product
```

Enrollment links membership and the space queue; it does not send a prompt or start work. The agent still needs the workflow instruction to maintain the board.

Link a pre-0.2.0 queue without changing its membership or tasks using `herdr-tasks --board Product bind-space --workspace w1`. Existing bindings are not silently overwritten. A queue can be linked to only one space; cross-space coordination stays explicit through `--board`. No Herdr binary modification or agent restart is required.

## How agents coordinate

- A vertical queue: current work, waiting items, next requests, and collapsed finished history. Task states remain queued, doing, blocked, done, or cancelled.
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

Read-only `boards`, explicit-board `list`, `show`, and `view` also work outside Herdr. Task writes require a Herdr agent with a reported durable session ID. Default commands use the calling agent's space binding, or legacy conversation membership when no binding exists. Use `--board NAME` for explicit selection. Operator integration commands such as `bind-space` and `open` require Herdr context but do not pretend to be an agent.

## Data and removal

Default storage: `~/.local/state/herdr-tasks/tasks.db` (or `$XDG_STATE_HOME/herdr-tasks/tasks.db`). Set `HERDR_TASKS_DB` to override it. SQLite WAL handles concurrent readers/writers. Don't copy only the `.db` file during active writes: use SQLite's backup facility, or export a board snapshot with `herdr-tasks --board Product list`.

Task contents can be sensitive. Do not include credentials or unrelated private conversation content. The database is outside this repository and is never uploaded by the plugin.

To remove the integration inside Herdr:

```sh
herdr plugin action invoke uninstall --plugin herdr-tasks
herdr plugin uninstall herdr-tasks
```

For a linked local checkout, use `herdr plugin unlink herdr-tasks` as the second command. Cleanup removes only its own CLI/skill links and marked status/shortcut block. **Task data is kept.** Close task viewers with their [Close] button before removing the plugin. No conversations are touched.

## Develop

```sh
python3 -m unittest -v
```

One Python program, SQLite, curses, and a Herdr manifest. The included tests cover ownership, concurrent claims, dependencies, resume/fork identity, and configuration integration. No package installation required.

MIT licensed.
