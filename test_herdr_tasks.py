import concurrent.futures
import os
import fcntl
from pathlib import Path
import select
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from unittest.mock import patch

import herdr_tasks as app


A = {"id": "codex:conversation-a", "name": "Dev"}
B = {"id": "codex:conversation-b", "name": "GTM"}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"tasks.db"
        self.s = app.Store(self.path)
        self.board = self.s.join("Product", A)["board"]
        self.s.join("Product", B)

    def tearDown(self):
        self.s.close()
        self.temp.cleanup()

    def add(self, title="Ship feature", **kwargs):
        return self.s.add(self.board, A, title, **kwargs)["id"]

    def test_resume_and_rename_keep_membership_and_ownership(self):
        task = self.add()
        renamed = dict(A, name="Engineering")
        self.s.join("Product", renamed)
        self.assertEqual(self.s.resolve(actor=renamed), self.board)
        self.assertEqual(self.s.show(task)["owner_name"], "Engineering")
        self.s.close()
        self.s = app.Store(self.path)
        self.assertEqual(self.s.next(self.board, renamed)["id"], task)

    def test_fork_does_not_inherit_membership(self):
        fork = dict(A, id="codex:fork")
        with self.assertRaises(ValueError):
            self.s.resolve(actor=fork)
        with self.assertRaises(ValueError):
            self.s.add(self.board, fork, "Unauthorized membership")

    def test_priority_and_one_active_task(self):
        low = self.add(priority=8)
        high = self.add(priority=1)
        self.assertEqual(self.s.next(self.board, A)["id"], high)
        self.assertEqual(self.s.next(self.board, A)["id"], high)
        with self.assertRaises(ValueError):
            self.s.start(low, A)
        self.s.update(high, A, status="done", note="Verified")
        self.assertEqual(self.s.next(self.board, A)["id"], low)

    def test_dependencies_and_cross_board_rejection(self):
        prerequisite = self.add(priority=8)
        child = self.add(needs=[prerequisite], priority=0)
        with self.assertRaises(ValueError):
            self.s.start(child, A)
        self.assertEqual(self.s.next(self.board, A)["id"], prerequisite)
        self.s.update(prerequisite, A, status="done", note="Verified")
        self.assertEqual(self.s.next(self.board, A)["id"], child)
        other = self.s.join("Other", A)["board"]
        with self.assertRaises(ValueError):
            self.s.add(other, A, "Cross board", needs=[child])
        with self.assertRaises(ValueError):
            self.add(needs=[99999])
        with self.assertRaises(ValueError):
            self.s.resolve(actor=A)

    def test_owner_claim_and_outcome_guards(self):
        task = self.add()
        with self.assertRaises(ValueError):
            self.s.start(task, B)
        with self.assertRaises(ValueError):
            self.s.update(task, A, status="done", note="Premature")
        self.s.start(task, A)
        for actor, note in ((B, "Not mine"), (A, None)):
            with self.assertRaises(ValueError):
                self.s.update(task, actor, status="done", note=note)
        with self.assertRaises(ValueError):
            self.s.update(task, A, owner=B["name"])
        self.s.update(task, A, status="blocked", note="Need clarification")
        self.assertIsNone(self.s.next(self.board, A))
        self.s.update(task, A, status="queued", note="Clarified")
        self.s.update(task, A, owner=B["name"])
        self.assertEqual(self.s.next(self.board, B)["id"], task)
        self.s.update(task, B, status="done", note="Verified")
        with self.assertRaises(ValueError):
            self.s.update(task, B, status="queued")
        self.s.update(task, B, status="queued", note="Regression found")

    def test_atomic_claim_between_two_agents(self):
        task = self.add()
        self.s.update(task, A, unassign=True)
        barrier = threading.Barrier(2)
        def claim(actor):
            store = app.Store(self.path)
            try:
                barrier.wait(timeout=5)
                return store.next(self.board, actor)
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, (A, B)))
        claimed = [r for r in results if r]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["id"], task)
        self.assertEqual(len(self.s.show(task)["history"]), 3)

    def test_snapshot_observes_other_connection(self):
        task = self.add()
        reader = app.Store(self.path)
        try:
            self.assertEqual(reader.snapshot(self.board)["tasks"][0]["status"], "queued")
            self.s.start(task, A)
            self.assertEqual(reader.snapshot(self.board)["tasks"][0]["status"], "doing")
        finally:
            reader.close()

    def test_sql_and_terminal_text_are_data(self):
        title = "Robert'); DROP TABLE tasks; --\x1b[2J"
        task = self.add(title=title)
        self.assertEqual(self.s.show(task)["title"], title)
        self.assertNotIn("\x1b", app.clean(title))
        self.assertEqual(len(self.s.snapshot(self.board)["tasks"]), 1)


class IntegrationTests(unittest.TestCase):
    def test_open_selects_focused_agents_board_without_prompting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.Store(Path(tmp)/"tasks.db")
            board = store.join("Demo", A)["board"]
            try:
                with patch.object(app, "identity", return_value=A), patch.object(app, "api", side_effect=[
                    {"agents":[{"pane_id":"w1:p2","focused":True}]}, {"opened":True}
                ]) as api:
                    self.assertEqual(app.open_board(store), {"opened":True})
                    self.assertEqual(api.call_args_list[1].args, (
                        "plugin", "pane", "open", "--plugin", "herdr-tasks", "--entrypoint", "board",
                        "--placement", "overlay", "--focus", "--env", f"HERDR_TASKS_BOARD={board}"
                    ))
            finally:
                store.close()

    def test_identity_targets_calling_pane_not_focus(self):
        with patch.object(app, "api", side_effect=[
            {"pane": {"pane_id": "w1:p2"}},
            {"agent": {"pane_id": "w1:p2", "name": "Dev", "agent": "codex",
                       "agent_session": {"kind": "id", "value": "durable-id", "agent": "codex"}}}
        ]) as api:
            self.assertEqual(app.identity(), {"id": "codex:durable-id", "name": "Dev"})
            self.assertEqual(api.call_args_list[0].args, ("pane", "current", "--current"))
            self.assertEqual(api.call_args_list[1].args, ("agent", "get", "w1:p2"))

    def test_setup_idempotent_preserves_config_and_uninstall_keeps_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root/"herdr.toml"
            original = '[keys]\nnext_agent = "shift+tab"\n'
            config.write_text(original)
            data = root/"tasks.db"
            data.write_bytes(b"preserve me")
            with patch.object(Path, "home", return_value=root), patch.dict(os.environ, {
                "HERDR_ENV": "1", "HERDR_CONFIG_PATH": str(config), "HERDR_TASKS_DB": str(data)
            }), patch.object(app, "herdr", return_value="ok"):
                app.setup()
                once = config.read_text()
                app.setup()
                self.assertEqual(once, config.read_text())
                self.assertIn(original, once)
                self.assertEqual(once.count('key = "prefix+shift+t"'), 1)
                self.assertTrue((root/".local/bin/herdr-tasks").is_symlink())
                app.setup(remove=True)
                self.assertEqual(config.read_text().strip(), original.strip())
                self.assertFalse((root/".local/bin/herdr-tasks").exists())
                self.assertEqual(data.read_bytes(), b"preserve me")

    def test_setup_skips_conflicting_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root/"herdr.toml"
            original = '[[keys.command]]\nkey="prefix+shift+t"\ncommand="existing"\n'
            config.write_text(original)
            with patch.object(Path, "home", return_value=root), patch.dict(os.environ, {
                "HERDR_ENV": "1", "HERDR_CONFIG_PATH": str(config)
            }), patch.object(app, "herdr", return_value="ok"):
                app.setup()
                self.assertIn(original, config.read_text())
                self.assertEqual(config.read_text().count("prefix+shift+t"), 1)

    def test_setup_restores_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root/"herdr.toml"
            original = '[keys]\nnext_agent="shift+tab"\n'
            config.write_text(original)
            with patch.object(Path, "home", return_value=root), patch.dict(os.environ, {
                "HERDR_ENV": "1", "HERDR_CONFIG_PATH": str(config)
            }), patch.object(app, "herdr", side_effect=ValueError("Invalid")):
                with self.assertRaises(ValueError):
                    app.setup()
                self.assertEqual(config.read_text(), original)
                self.assertFalse((root/".local/bin/herdr-tasks").is_symlink())

    def test_setup_wont_replace_existing_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root/".local/bin/herdr-tasks"
            existing.parent.mkdir(parents=True)
            existing.write_text("unrelated executable")
            with patch.object(Path, "home", return_value=root), patch.dict(os.environ, {
                "HERDR_ENV": "1", "HERDR_CONFIG_PATH": str(root/"config.toml")
            }), patch.object(app, "herdr", return_value="ok"):
                with self.assertRaises(ValueError):
                    app.setup()
                self.assertEqual(existing.read_text(), "unrelated executable")
                self.assertFalse((root/"config.toml").exists())


class TerminalTests(unittest.TestCase):
    def test_real_viewer_wide_narrow_details_and_exit(self):
        for width in (80, 160):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"tasks.db"
                store = app.Store(path)
                board = store.join("Demo", A)["board"]
                task = store.add(board, A, "Ship the demo", detail="Acceptance criteria")["id"]
                store.start(task, A)
                store.close()
                master, slave = os.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32,width,0,0))
                process = subprocess.Popen([sys.executable, str(app.ROOT/"herdr_tasks.py"), "--board", "Demo", "view"],
                    stdin=slave, stdout=slave, stderr=slave,
                    env={**os.environ, "TERM":"xterm-256color", "HERDR_TASKS_DB":str(path)})
                os.close(slave)
                output = b""
                def expect(needle):
                    nonlocal output
                    deadline = time.monotonic()+5
                    while needle not in output and time.monotonic()<deadline:
                        if select.select([master],[],[],0.1)[0]:
                            try:
                                output += os.read(master,65536)
                            except OSError:
                                break
                    self.assertIn(needle, output, output.decode(errors="replace"))
                try:
                    expect(b"Ship the demo")
                    expect(b"DOING")
                    os.write(master, f"#{task}\n".encode())
                    expect(b"Acceptance criteria")
                    os.write(master,b"q")
                    deadline = time.monotonic()+5
                    while process.poll() is None and time.monotonic()<deadline:
                        if select.select([master],[],[],0.1)[0]:
                            try:
                                os.read(master,65536)
                            except OSError:
                                break
                    self.assertEqual(process.wait(timeout=5),0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
