#!/usr/bin/env python3
"""Agent-owned boards in Herdr. Python 3.10+, standard library only."""
import argparse
import curses
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import unicodedata

from queue_view import ui, counts, clip

VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
STATUSES = ("queued", "doing", "blocked", "done", "cancelled")
MARK_START = "# herdr-tasks:begin"
MARK_END = "# herdr-tasks:end"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, limit=20000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit,
            f"Expected nonempty text of at most {limit} characters")
    return value.strip()


def clean(value):
    # Terminal content is untrusted task text, never escape sequences.
    return "".join(c if c == "\n" or not unicodedata.category(c).startswith("C") else " "
                   for c in str(value))


def herdr(*args):
    require(os.environ.get("HERDR_ENV") == "1", "Run this command inside Herdr")
    result = subprocess.run([os.environ.get("HERDR_BIN_PATH", "herdr"), *args],
                            capture_output=True, text=True, timeout=15)
    require(result.returncode == 0, result.stderr.strip() or result.stdout.strip())
    return result.stdout


def api(*args):
    return json.loads(herdr(*args))["result"]


def session_key():
    require(os.environ.get("HERDR_ENV") == "1" and os.environ.get("HERDR_SOCKET_PATH"), "Run inside a named Herdr session")
    return str(Path(os.environ["HERDR_SOCKET_PATH"]).resolve())


def status_context():
    # Herdr runs status commands on its server, not inside a managed pane.
    # HERDR_ENV is deliberately absent there; only these active-context values
    # identify the queue. Do not fall back to a caller pane or another session.
    path = os.environ.get("HERDR_SOCKET_PATH", "")
    workspace = os.environ.get("HERDR_ACTIVE_WORKSPACE_ID", "")
    require(path and Path(path).is_absolute() and workspace, "No active Herdr status context")
    return str(Path(path).resolve()), workspace


def rpc(method, params):
    """Only needed for split ratios, not exposed by this Herdr CLI version."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(session_key())
        connection.sendall((json.dumps({"id":"herdr-tasks", "method":method, "params":params})+"\n").encode())
        with connection.makefile("r") as stream:
            result = json.loads(stream.readline())
    require("error" not in result, str(result.get("error")))
    return result["result"]


def identity(target=None):
    pane = None
    if target is None:
        pane = api("pane", "current", "--current")["pane"]
        target = pane["pane_id"]
    agent = api("agent", "get", target)["agent"]
    session = agent.get("agent_session") or {}
    require(session.get("kind") == "id" and session.get("value"),
            "Herdr has not reported a durable conversation ID for this agent yet")
    if not agent.get("name") and pane is None:
        pane = api("pane", "get", agent["pane_id"])["pane"]
    return {"id": f"{session.get('agent', agent.get('agent'))}:{session['value']}",
            "name": agent.get("name") or (pane or {}).get("label") or agent["pane_id"]}


def actor_workspace(target=None):
    return api("agent","get",target)["agent"]["workspace_id"] if target else api("pane","current","--current")["pane"]["workspace_id"]


def db_path():
    if os.environ.get("HERDR_TASKS_DB"):
        return Path(os.environ["HERDR_TASKS_DB"]).expanduser().resolve()
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "herdr-tasks" / "tasks.db"


class Store:
    def __init__(self, path=None, readonly=False):
        self.path = Path(path) if path else db_path()
        if readonly:
            self.db = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=1, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        require(self.db.execute("PRAGMA user_version").fetchone()[0] in (0, 1, 2),
                "This database needs a newer herdr-tasks version")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS boards(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS members(
            board INTEGER NOT NULL REFERENCES boards(id), actor TEXT NOT NULL,
            name TEXT NOT NULL, PRIMARY KEY(board,actor));
          CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY, board INTEGER NOT NULL REFERENCES boards(id),
            title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued'
              CHECK(status IN ('queued','doing','blocked','done','cancelled')),
            owner TEXT, priority INTEGER NOT NULL DEFAULT 5 CHECK(priority BETWEEN 0 AND 9),
            note TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL, updated INTEGER NOT NULL,
            FOREIGN KEY(board,owner) REFERENCES members(board,actor));
          CREATE TABLE IF NOT EXISTS dependencies(
            task INTEGER REFERENCES tasks(id), needs INTEGER REFERENCES tasks(id),
            PRIMARY KEY(task,needs), CHECK(task != needs));
          CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY, task INTEGER NOT NULL REFERENCES tasks(id),
            actor TEXT NOT NULL, action TEXT NOT NULL, body TEXT NOT NULL, at INTEGER NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS one_doing_per_owner
            ON tasks(board,owner) WHERE status='doing';
          CREATE TABLE IF NOT EXISTS spaces(
            session TEXT NOT NULL, workspace TEXT NOT NULL,
            board INTEGER NOT NULL UNIQUE REFERENCES boards(id),
            PRIMARY KEY(session,workspace));
          CREATE TABLE IF NOT EXISTS viewers(
            session TEXT NOT NULL, tab TEXT NOT NULL, pane TEXT NOT NULL,
            board INTEGER NOT NULL REFERENCES boards(id), PRIMARY KEY(session,tab));
          PRAGMA user_version=2;
        """)
        os.chmod(self.path, 0o600)

    def close(self):
        self.db.close()

    def transaction(self, fn):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            value = fn()
            self.db.execute("COMMIT")
            return value
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def boards(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM boards ORDER BY name")]

    def bind_space(self, board, session, workspace):
        def write():
            current = self.space_board(session, workspace)
            require(current in (None, board), "This space already has another queue; no binding was changed")
            other = self.db.execute("SELECT session,workspace FROM spaces WHERE board=?", (board,)).fetchone()
            require(other is None or tuple(other) == (session,workspace), "This queue is already linked to another space")
            self.db.execute("INSERT OR IGNORE INTO spaces VALUES(?,?,?)",(session,workspace,board))
            return {"board":board,"workspace":workspace}
        return self.transaction(write)

    def space_board(self, session, workspace):
        row = self.db.execute("SELECT board FROM spaces WHERE session=? AND workspace=?", (session,workspace)).fetchone()
        return row[0] if row else None

    def viewer(self, session, tab):
        row = self.db.execute("SELECT pane,board FROM viewers WHERE session=? AND tab=?", (session,tab)).fetchone()
        return dict(row) if row else None

    def remember_viewer(self, session, tab, pane, board):
        self.db.execute("INSERT INTO viewers VALUES(?,?,?,?) ON CONFLICT(session,tab) DO UPDATE SET pane=excluded.pane,board=excluded.board",(session,tab,pane,board))

    def join(self, name, actor):
        name = text(name, 80)
        def write():
            self.db.execute("INSERT OR IGNORE INTO boards(name,created) VALUES(?,?)", (name, int(time.time())))
            board = self.db.execute("SELECT id FROM boards WHERE name=?", (name,)).fetchone()[0]
            self.db.execute("INSERT INTO members VALUES(?,?,?) ON CONFLICT(board,actor) DO UPDATE SET name=excluded.name",
                            (board, actor["id"], actor["name"]))
            return {"board": board, "name": name, "member": actor}
        return self.transaction(write)

    def resolve(self, selector=None, actor=None):
        if selector is not None:
            row = self.db.execute("SELECT id FROM boards WHERE name=?", (str(selector),)).fetchone()
            if row is None and str(selector).isdigit():
                row = self.db.execute("SELECT id FROM boards WHERE id=?", (int(selector),)).fetchone()
            require(row is not None, "Unknown board")
            return row[0]
        require(actor is not None, "Choose a board with --board NAME")
        rows = self.db.execute("SELECT board FROM members WHERE actor=?", (actor["id"],)).fetchall()
        require(len(rows) == 1, "Join a board first, or use --board NAME if you belong to several")
        return rows[0][0]

    def member(self, board, actor):
        require(self.db.execute("SELECT 1 FROM members WHERE board=? AND actor=?", (board, actor["id"])).fetchone(),
                "This conversation has not joined that board")

    def owner(self, board, value):
        if value is None:
            return None
        rows = self.db.execute("SELECT actor FROM members WHERE board=? AND (actor=? OR name=?)",
                               (board, value, value)).fetchall()
        require(len(rows) == 1, "Owner must be an unambiguous board member name or conversation ID")
        return rows[0][0]

    def event(self, task, actor, action, body):
        self.db.execute("INSERT INTO events(task,actor,action,body,at) VALUES(?,?,?,?,?)",
                        (task, actor["id"], action, body, int(time.time())))

    def show(self, task):
        row = self.db.execute("SELECT t.*,m.name AS owner_name FROM tasks t LEFT JOIN members m ON m.board=t.board AND m.actor=t.owner WHERE t.id=?", (task,)).fetchone()
        require(row is not None, "Unknown task")
        result = dict(row)
        result["needs"] = [r[0] for r in self.db.execute("SELECT needs FROM dependencies WHERE task=? ORDER BY needs", (task,))]
        result["history"] = [dict(r) for r in self.db.execute("SELECT actor,action,body,at FROM events WHERE task=? ORDER BY id", (task,))]
        return result

    def snapshot(self, board):
        # One read transaction prevents a half-updated overview during agent writes.
        self.db.execute("BEGIN")
        try:
            result = {"board": dict(self.db.execute("SELECT * FROM boards WHERE id=?", (board,)).fetchone()),
                      "members": [dict(r) for r in self.db.execute("SELECT actor,name FROM members WHERE board=? ORDER BY name", (board,))],
                      "tasks": [dict(r) for r in self.db.execute("""SELECT t.*,m.name AS owner_name,
                        (SELECT count(*) FROM dependencies d JOIN tasks n ON n.id=d.needs WHERE d.task=t.id AND n.status!='done') AS waiting_on
                        FROM tasks t LEFT JOIN members m ON m.board=t.board AND m.actor=t.owner
                        WHERE t.board=? ORDER BY t.priority,t.id""", (board,))]}
            return result
        finally:
            self.db.execute("COMMIT")

    def add(self, board, actor, title, detail="", owner=None, priority=5, needs=()):
        title = text(title, 240)
        require(len(detail) <= 20000, "Detail is too long")
        require(0 <= priority <= 9, "Priority must be 0–9")
        def write():
            self.member(board, actor)
            assigned = self.owner(board, owner) if owner else actor["id"]
            for dep in set(needs):
                require(self.show(dep)["board"] == board, "Dependencies must be on the same board")
            now = int(time.time())
            task = self.db.execute("INSERT INTO tasks(board,title,detail,owner,priority,created,updated) VALUES(?,?,?,?,?,?,?)",
                                   (board, title, detail, assigned, priority, now, now)).lastrowid
            self.db.executemany("INSERT INTO dependencies VALUES(?,?)", [(task, d) for d in set(needs)])
            self.event(task, actor, "created", title)
            return self.show(task)
        return self.transaction(write)

    def ready(self, task):
        return not self.db.execute("SELECT 1 FROM dependencies d JOIN tasks t ON t.id=d.needs WHERE d.task=? AND t.status!='done'", (task,)).fetchone()

    def start(self, task, actor):
        def write():
            t = self.show(task)
            self.member(t["board"], actor)
            require(t["owner"] in (None, actor["id"]), "Task is assigned to another agent")
            require(t["status"] in ("queued", "doing"), "Only a queued task can start; explicitly requeue blocked work")
            require(self.ready(task), "Task has unfinished dependencies")
            other = self.db.execute("SELECT id FROM tasks WHERE board=? AND owner=? AND status='doing' AND id!=?",
                                    (t["board"], actor["id"], task)).fetchone()
            require(other is None, f"Finish or block your current task first: {other[0] if other else ''}")
            if t["status"] != "doing":
                self.db.execute("UPDATE tasks SET status='doing',owner=?,updated=? WHERE id=?", (actor["id"], int(time.time()), task))
                self.event(task, actor, "doing", "Claimed")
            return self.show(task)
        return self.transaction(write)

    def next(self, board, actor):
        def write():
            self.member(board, actor)
            row = self.db.execute("SELECT id FROM tasks WHERE board=? AND owner=? AND status='doing'", (board, actor["id"])).fetchone()
            if row:
                return self.show(row[0])
            row = self.db.execute("""SELECT id FROM tasks t WHERE board=? AND status='queued' AND (owner=? OR owner IS NULL)
                AND NOT EXISTS(SELECT 1 FROM dependencies d JOIN tasks n ON n.id=d.needs WHERE d.task=t.id AND n.status!='done')
                ORDER BY priority,id LIMIT 1""", (board, actor["id"])).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE tasks SET status='doing',owner=?,updated=? WHERE id=?", (actor["id"], int(time.time()), row[0]))
            self.event(row[0], actor, "doing", "Claimed next task")
            return self.show(row[0])
        return self.transaction(write)

    def update(self, task, actor, status=None, note=None, title=None, priority=None, owner=None, unassign=False):
        if status:
            require(status in STATUSES and status != "doing", "Use start or next to claim work")
        if title is not None:
            title = text(title, 240)
        if note is not None:
            note = text(note)
        if priority is not None:
            require(0 <= priority <= 9, "Priority must be 0–9")
        require(not (owner and unassign), "Choose an owner or --unassign, not both")
        def write():
            t = self.show(task)
            self.member(t["board"], actor)
            require(t["owner"] in (None, actor["id"]) or (t["status"] == "queued" and status is None),
                    "Only the owner can update active work or mark its outcome")
            if status == "done":
                require(t["status"] in ("doing", "blocked"), "Start work before completing it")
                require(self.ready(task), "Cannot finish with unfinished dependencies")
            if status in ("done", "blocked", "cancelled"):
                require(note is not None, "Include --note with the result, blocker, or cancellation reason")
            if t["status"] in ("done", "cancelled") and status:
                require(status == "queued" and note, "Reopening requires --status queued and --note explaining why")
            if owner or unassign:
                require(t["status"] == "queued", "Only queued work can be reassigned")
            updates = {k: v for k, v in {"status": status, "note": note, "title": title, "priority": priority}.items() if v is not None}
            if owner or unassign:
                updates["owner"] = None if unassign else self.owner(t["board"], owner)
            require(updates, "No changes supplied")
            updates["updated"] = int(time.time())
            self.db.execute("UPDATE tasks SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?", (*updates.values(), task))
            self.event(task, actor, status or "updated", json.dumps(updates, ensure_ascii=False))
            return self.show(task)
        return self.transaction(write)


def config_path():
    return Path(os.environ.get("HERDR_CONFIG_PATH", str(Path.home()/".config/herdr/config.toml")))


def setup(remove=False, key=None):
    require(os.environ.get("HERDR_ENV") == "1", "Run setup inside Herdr")
    dest = Path.home()/".local/bin/herdr-tasks"
    skill = Path.home()/".codex/skills/herdr-tasks"
    config = config_path()
    original = config.read_text() if config.exists() else ""
    require(original.count(MARK_START) == original.count(MARK_END) and original.count(MARK_START) <= 1,
            "Malformed managed config block; resolve it before setup")
    base = re.sub(r"(?m)^# herdr-tasks:begin\n.*?^# herdr-tasks:end\n?", "", original, flags=re.S)
    require(MARK_START not in base and MARK_END not in base, "Malformed managed config block")
    if remove:
        replacement = base
    else:
        for link, target in ((dest, ROOT/"herdr_tasks.py"), (skill, ROOT/"skill")):
            require(not link.exists() and not link.is_symlink() or link.is_symlink() and link.resolve() == target,
                    f"Refusing to replace an existing installation: {link}")
        binding = ""
        if key:
            require(re.fullmatch(r"[a-z0-9+_-]+",key), "Use a Herdr key name such as alt+t")
            require(key.lower() not in base.lower(), "That key is already configured; choose another or omit --key")
            binding = '\n[[keys.command]]\nkey = '+json.dumps(key)+'\ntype = "shell"\ncommand = "herdr plugin action invoke open --plugin herdr-tasks"\ndescription = "Open space task queue"\n'
        # Existing inline arrays cannot be extended with TOML array-of-table syntax.
        # Preserve them and explain the one manual entry instead of rewriting config.
        inline = re.search(r'(?m)^\s*(?:ui\.)?tab_bar_right\s*=',base)
        summary = ""
        # The server does not inherit a pane's login-shell PATH. Pin the
        # working interpreter used during setup, not /usr/bin/env python3.
        command = shlex.join([sys.executable, str(ROOT/"herdr_tasks.py"), "status"])
        if not inline:
            summary = '\n[[ui.tab_bar_right]]\ntype = "command"\ncommand = '+json.dumps(command)+'\ninterval_seconds = 2\ntimeout_seconds = 1\n'
        else:
            print('Existing inline tab_bar_right preserved. Add this entry to enable the summary: '
                  '{ type = "command", command = '+json.dumps(command)+
                  ', interval_seconds = 2, timeout_seconds = 1 }',file=sys.stderr)
        replacement = base.rstrip()+"\n\n"+MARK_START+binding+summary+"\n"+MARK_END+"\n"
    if replacement != original:
        config.parent.mkdir(parents=True, exist_ok=True)
        backup = config.with_name(config.name+".herdr-tasks-backup")
        if config.exists() and not backup.exists():
            shutil.copy2(config, backup)
        config.write_text(replacement)
        try:
            herdr("config", "check")
        except Exception:
            config.write_text(original)
            raise
        herdr("server", "reload-config")
    # Install/remove links only after config validation succeeds.
    for link, target in ((dest, ROOT/"herdr_tasks.py"), (skill, ROOT/"skill")):
        if remove:
            if link.is_symlink() and link.resolve() == target:
                link.unlink()
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target, target_is_directory=target.is_dir())
    if not remove:
        (ROOT/"herdr_tasks.py").chmod(0o755)
    return {"cli": str(dest), "skill": str(skill), "removed": remove, "data": str(db_path())}


def parent_split(root, pane, path=()):
    if root["type"] != "split":
        return None
    for second, child in ((False,root["first"]),(True,root["second"])):
        if child["type"] == "pane" and child.get("pane_id") == pane:
            return list(path),second
        found = parent_split(child,pane,path+(second,))
        if found:
            return found
    return None


def open_board(store, target=None, focus=True):
    session = session_key()
    if target:
        pane = api("pane","get",target)["pane"]
    else:
        snapshot = api("api","snapshot")["snapshot"]
        pane = next((p for p in snapshot["panes"] if p["pane_id"] == snapshot["focused_pane_id"]),None)
        require(pane is not None, "Focus a terminal in the space first")
    board = store.space_board(session,pane["workspace_id"])
    require(board is not None, "No queue linked to this space. Run herdr-tasks join NAME from its agent, or bind-space for an existing queue")
    existing = store.viewer(session,pane["tab_id"])
    if existing:
        try:
            live = api("pane","get",existing["pane"])["pane"]
        except ValueError:
            live = None
        if live and live["tab_id"] == pane["tab_id"] and existing["board"] == board:
            if focus:
                api("plugin","pane","focus",live["pane_id"])
            return {"pane":live,"reused":True}
    arguments = ["plugin","pane","open","--plugin","herdr-tasks","--entrypoint","board",
                 "--placement","split","--target-pane",pane["pane_id"],"--direction","down",
                 "--no-focus","--env",f"HERDR_TASKS_BOARD={board}"]
    if os.environ.get("HERDR_TASKS_DB"):
        arguments += ["--env",f"HERDR_TASKS_DB={store.path.resolve()}"]
    result = api(*arguments)
    created = result["plugin_pane"]["pane"]
    store.remember_viewer(session,created["tab_id"],created["pane_id"],board)
    # Never layout.apply: it replaces PTYs. Change only our new parent split.
    layout = rpc("layout.export",{"pane_id":created["pane_id"]})["layout"]
    split = parent_split(layout["root"],created["pane_id"])
    if split:
        path,second = split
        rpc("layout.set_split_ratio",{"tab_id":created["tab_id"],"path":path,"ratio":0.7 if second else 0.3})
    if focus:
        api("plugin","pane","focus",created["pane_id"])
    return {"pane":created,"reused":False}


def top_status(store, session, workspace):
    board = store.space_board(session,workspace)
    if board is None:
        return ""
    snapshot = store.snapshot(board)
    n = counts(snapshot)
    active = next((t for t in snapshot["tasks"] if t["status"] == "doing"),None)
    ready = next((t for t in snapshot["tasks"] if t["status"] == "queued" and not t["waiting_on"]),None)
    waiting = next((t for t in snapshot["tasks"] if t["status"] == "blocked" or t["status"] == "queued" and t["waiting_on"]),None)
    lead = next((label+clip(task["title"],28) for label,task in
                 (("Now: ",active),("Next: ",ready),("Waiting: ",waiting)) if task), "All clear")
    if n["now"] > 1:
        lead += f" (+{n['now']-1})"
    return f"Tasks · {lead} · {n['next']} next · {n['waiting']} waiting"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--board", help="Board name or ID; defaults to this conversation's board")
    p.add_argument("--agent", help="Explicit live Herdr agent to enroll or act as; defaults to caller")
    sub = p.add_subparsers(dest="command", required=True)
    j = sub.add_parser("join", help="Join/create a shared board using this conversation's identity")
    j.add_argument("name")
    sub.add_parser("boards")
    sub.add_parser("list", help="JSON snapshot of tasks, owners, and dependencies")
    s = sub.add_parser("show")
    s.add_argument("id", type=int)
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--detail", default="")
    a.add_argument("--owner", help="Board member name; defaults to yourself")
    a.add_argument("--priority", type=int, default=5, help="0 is highest, 9 lowest")
    a.add_argument("--after", type=int, nargs="*", default=[])
    s = sub.add_parser("start")
    s.add_argument("id", type=int)
    sub.add_parser("next", help="Atomically claim the next ready task, or return your current task")
    u = sub.add_parser("update")
    u.add_argument("id", type=int)
    u.add_argument("--status", choices=[s for s in STATUSES if s != "doing"])
    u.add_argument("--note")
    u.add_argument("--title")
    u.add_argument("--priority", type=int)
    group = u.add_mutually_exclusive_group()
    group.add_argument("--owner")
    group.add_argument("--unassign", action="store_true")
    sub.add_parser("view", help="Read-only, clickable inline task list")
    o = sub.add_parser("open", help="Open/reuse a compact task split in the focused space")
    o.add_argument("--pane",help="Explicit terminal to split; otherwise focused terminal")
    o.add_argument("--no-focus",action="store_true")
    b = sub.add_parser("bind-space", help="Link an existing queue to one Herdr workspace")
    b.add_argument("--workspace",required=True)
    sub.add_parser("status",help="Short read-only summary for Herdr's active workspace")
    s = sub.add_parser("setup", help="Install CLI, skill and top-bar summary; optional shortcut")
    s.add_argument("--key",help="Optional explicit Herdr binding, e.g. alt+t; no default")
    sub.add_parser("uninstall", help="Remove integration; keep data")
    sub.add_parser("skill", help="Print the agent workflow")
    return p


def main():
    args = parser().parse_args()
    if args.command == "skill":
        print((ROOT/"skill/SKILL.md").read_text())
        return
    if args.command == "status":
        # Status commands have active workspace context but no agent/pane identity.
        # Never initialize a database or query another session as a fallback.
        store = None
        try:
            session, workspace = status_context()
            store = Store(readonly=True)
            print(top_status(store,session,workspace))
        except ValueError:
            print("")
        except (sqlite3.Error,OSError):
            print("Tasks · unavailable")
        finally:
            if store:
                store.close()
        return
    if args.command in ("setup", "uninstall"):
        result = setup(remove=args.command == "uninstall",key=getattr(args,"key",None))
        print(json.dumps(result))
        return
    store = Store()
    try:
        if args.command == "boards":
            result = store.boards()
        elif args.command == "open":
            result = open_board(store,args.pane,not args.no_focus)
        elif args.command == "bind-space":
            require(args.board,"Use --board NAME before bind-space")
            workspace = api("workspace","get",args.workspace)["workspace"]
            result = store.bind_space(store.resolve(args.board),session_key(),workspace["workspace_id"])
        elif args.command == "view":
            selector = args.board or os.environ.get("HERDR_TASKS_BOARD")
            board = store.resolve(selector) if selector else store.space_board(session_key(),api("pane","current","--current")["pane"]["workspace_id"]) if os.environ.get("HERDR_ENV") == "1" else None
            curses.wrapper(ui, store, board)
            return
        elif args.command == "show":
            result = store.show(args.id)
        elif args.command == "list" and args.board:
            result = store.snapshot(store.resolve(args.board))
        else:
            actor = identity(args.agent)
            if args.command == "join":
                workspace = actor_workspace(args.agent)
                existing = store.space_board(session_key(),workspace)
                if existing is not None:
                    require(store.resolve(args.name) == existing,"This space already has a queue; join its existing name")
                result = store.join(args.name, actor)
                store.bind_space(result["board"],session_key(),workspace)
            elif args.command == "start":
                result = store.start(args.id, actor)
            elif args.command == "update":
                result = store.update(args.id, actor, **{k:getattr(args,k) for k in ("status","note","title","priority","owner","unassign")})
            else:
                bound = store.space_board(session_key(),actor_workspace(args.agent)) if not args.board else None
                board = bound if bound is not None else store.resolve(args.board, actor)
                if args.command == "list":
                    result = store.snapshot(board)
                elif args.command == "add":
                    result = store.add(board, actor, args.title, args.detail, args.owner, args.priority, args.after)
                elif args.command == "next":
                    result = store.next(board, actor)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, sqlite3.Error, OSError, subprocess.SubprocessError, curses.error) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
