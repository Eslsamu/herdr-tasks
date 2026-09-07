---
name: herdr-tasks
description: Maintain an agent-owned task board for an existing Herdr conversation. Use when asked to manage a Herdr Tasks board, add work for later, or when this conversation has already joined a herdr-tasks board. Humans give requests in chat; agents maintain the board.
---

# Herdr Tasks

Use `herdr-tasks` in a Herdr agent pane. Each queue is linked to one workspace in one Herdr session. Ownership identifies the conversation; a resumed conversation retains ownership. A fork must explicitly join and does not inherit task ownership. No model API, daemon, prompt injection, or background task execution is provided by this plugin.

## First use

Read `herdr-tasks --help`. Only join a board the user placed in scope:

If the command is not on PATH, use `~/.local/bin/herdr-tasks` for the commands below. No shell configuration changes are required.

```sh
herdr-tasks join "Project name"
herdr-tasks list
```

`join` links the queue to the calling agent's space. If the space already has a queue, join its existing name. Default list/add/next commands use that space's queue, falling back to conversation membership for legacy unlinked work. Explicit `--board NAME` remains available for authorized cross-space coordination. Moving an agent into another space does not transfer its old tasks.

Members share a queue; tasks have one owner. Normal commands operate as the calling agent. `--agent NAME` is for explicit operator enrollment or coordination, not a way to take another agent's active work. This is local coordination, not an access-control boundary against programs running as the same OS user.

## Own the work

1. At the beginning of each turn on an enrolled board, read `herdr-tasks list`. Reconcile it with the user's latest requests and actual progress. Do not infer completed work from an idle terminal.
2. Turn requests into small, actionable tasks. Search the existing list before adding; amend or combine duplicate requests. Capture meaningful user intent in `--detail`. Do not copy credentials, mailbox contents, or unrelated conversation history into tasks.
3. When the user adds work during a task, record it immediately at your next safe tool boundary. Keep the current task going unless the user explicitly changes its priority. The task enters this list when you process the message, not at the instant the user types it.
4. Take one task at a time using `next` or `start`. `next` returns your current task if one is already doing. Claim before working; never work a task assigned to another member. Separate agents should work separate files or agree on ownership first.
5. Keep the latest note useful, record blockers with a reason, and mark done only when the outcome is achieved and relevant verification passes. A note is required for done, blocked, and cancelled. Preserve cancelled work as history.
6. After finishing, run `next` again and continue while ready, user-authorized work exists. No need for the human to move cards or approve routine task bookkeeping. Existing approval requirements for external actions, cost, credentials, or destructive actions still apply.
7. When no ready work remains, report briefly and stop. A blocked task needs explicit requeueing after its blocker resolves. Do not spin, send yourself `continue`, fabricate new work, or start another Codex process.

The board records work; it cannot keep a stopped/limited/offline agent alive or wake an idle thread. If a teammate is idle when work is assigned, coordinate through the existing Herdr messaging workflow only when authorized. Never interrupt a running teammate to force it to read the board.

## Commands

Global options go BEFORE the command: `herdr-tasks --board "Project name" list`.

```sh
herdr-tasks add "Fix CSV export" --detail "Preserve quoted commas and Unicode; verify with an example."
herdr-tasks add "Add saved filters" --owner dev --priority 4 --after 12
herdr-tasks next
herdr-tasks start 12
herdr-tasks update 12 --note "Reproduced the issue; testing the parser fix."
herdr-tasks update 12 --status done --note "Fixed quoted fields; regression check passes."
herdr-tasks update 13 --status blocked --note "Waiting for the user's choice of filter behavior."
herdr-tasks update 13 --status queued --note "Behavior clarified; ready to implement."
herdr-tasks update 14 --owner reviewer
herdr-tasks show 12
```

`add` assigns to yourself by default. `--owner` names an already enrolled agent. An unassigned queued task can be claimed by any board member. Dependencies must already exist on this board; all must be done before a task starts. Priority 0 is highest; tasks of equal priority run oldest first. `update --unassign` releases queued work to the shared pool. Active work can only be updated by its owner; reassign only after returning it to queued.

Do not modify the database directly. Do not write task data into the plugin repository. The human's viewer is a read-only compact pane with clickable descriptions; the top bar shows the current space's summary. Both refresh automatically. Closing the viewer closes only that temporary pane, not its queue or any agent. Do not use `layout.apply` to add or remove a viewer: it replaces live terminals. The human talks to you, not to a card-management form.
