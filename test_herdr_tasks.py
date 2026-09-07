import concurrent.futures
import http.client
import json
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
from queue_view import QueueView, cells, clip, wrap, counts


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

    def test_space_binding_is_unique_and_session_scoped(self):
        self.s.bind_space(self.board,"one.sock","w1")
        self.s.bind_space(self.board,"one.sock","w1")
        self.assertEqual(self.s.space_board("one.sock","w1"),self.board)
        self.assertIsNone(self.s.space_board("two.sock","w1"))
        with self.assertRaises(ValueError):
            self.s.bind_space(self.board,"one.sock","w2")
        other = self.s.join("Different",A)["board"]
        with self.assertRaises(ValueError):
            self.s.bind_space(other,"one.sock","w1")
        self.assertEqual(self.s.space_board("one.sock","w1"),self.board)

    def test_status_is_read_only_and_scoped(self):
        self.s.bind_space(self.board,"one.sock","w1")
        task = self.add()
        self.s.start(task,A)
        reader = app.Store(self.path,readonly=True)
        try:
            self.assertIn("Now: Ship feature",app.top_status(reader,"one.sock","w1"))
            self.assertEqual(app.top_status(reader,"two.sock","w1"),"")
            with self.assertRaises(app.sqlite3.OperationalError):
                reader.add(self.board,A,"Cannot write")
        finally:
            reader.close()

    def test_v1_data_migrates_without_changing_tasks(self):
        task = self.add()
        self.s.db.execute("DROP TABLE spaces")
        self.s.db.execute("DROP TABLE viewers")
        self.s.db.execute("PRAGMA user_version=1")
        self.s.close()
        self.s = app.Store(self.path)
        self.assertEqual(self.s.show(task)["title"],"Ship feature")
        self.s.bind_space(self.board,"one.sock","w1")

    def test_preview_shows_next_or_waiting_work_when_nothing_is_active(self):
        self.s.bind_space(self.board,"one.sock","w1")
        self.assertIn("All clear",app.top_status(self.s,"one.sock","w1"))
        task = self.add()
        self.assertIn("Next: Ship feature",app.top_status(self.s,"one.sock","w1"))
        self.s.update(task,A,status="blocked",note="Waiting for input")
        self.assertIn("Waiting: Ship feature",app.top_status(self.s,"one.sock","w1"))


class QueueTests(unittest.TestCase):
    def snapshot(self):
        def task(id,status,waiting=0):
            return {"id":id,"title":"Task "+str(id),"status":status,"owner_name":"Demo-dev",
                    "waiting_on":waiting,"detail":"First paragraph\n\nSecond paragraph","note":"Reason",
                    "updated":id}
        return {"board":{"name":"Demo"},"tasks":[task(1,"queued"),task(2,"doing"),task(3,"blocked"),task(4,"queued",1),task(5,"done"),task(6,"cancelled")]}

    def test_current_waiting_next_history_reading_order(self):
        view = QueueView()
        rows = view.rows(self.snapshot(),60)
        self.assertEqual([r["target"] for r in rows if r["target"] is not None],[2,3,4,1,"history"])
        self.assertEqual(counts(self.snapshot()),{"now":1,"next":1,"waiting":2,"finished":2})

    def test_expansion_is_inline_and_history_includes_cancellation(self):
        view = QueueView()
        view.toggle(2)
        rows = view.rows(self.snapshot(),60)
        self.assertIn("   First paragraph",[r["text"] for r in rows])
        self.assertIn("   ",[r["text"] for r in rows])
        view.toggle(2)
        self.assertNotIn("   First paragraph",[r["text"] for r in view.rows(self.snapshot(),60)])
        view.toggle("history")
        self.assertEqual([r["target"] for r in view.rows(self.snapshot(),60) if r["target"] in (5,6)],[6,5])

    def test_selection_survives_refresh_and_changes_in_order(self):
        view = QueueView()
        view.rows(self.snapshot(),40)
        view.toggle(3)
        snap = self.snapshot()
        snap["tasks"].reverse()
        view.rows(snap,80)
        self.assertEqual(view.selected,3)
        self.assertEqual(view.expanded,{3})

    def test_click_targets_do_not_leak_into_wrapped_details(self):
        view = QueueView()
        view.toggle(2)
        rows = view.rows(self.snapshot(),20)
        task_row = next(i for i,r in enumerate(rows) if r["target"] == 2)
        self.assertIsNone(rows[task_row+1]["target"])
        for row in rows:
            if row["target"] is not None:
                self.assertLessEqual(cells(row["text"]),20)

    def test_unicode_clipping_and_paragraphs(self):
        self.assertLessEqual(cells(clip("界界界 abc",5)),5)
        self.assertEqual(cells("e\u0301"),1)
        self.assertEqual(wrap("first\n\nsecond",20),["first","","second"])
        self.assertTrue(all(cells(line)<=8 for line in wrap("界界界界界界界界界",8)))
        self.assertNotIn("\x1b",clip("unsafe\x1b[2J",30))

    def test_keyboard_selection_scrolls_to_selected_task(self):
        view = QueueView()
        rows = view.rows(self.snapshot(),40)
        view.move(rows,1,3)
        self.assertEqual(view.selected,3)
        self.assertGreater(view.scroll,0)

    def many_tasks(self):
        snap = self.snapshot()
        snap["tasks"] = [dict(snap["tasks"][0],id=i,title=f"Task {i}") for i in range(1,31)]
        return snap

    def test_refresh_anchors_selection_when_task_changes_group(self):
        view = QueueView()
        snap = self.many_tasks()
        view.selected = 20
        rows = view.rows(snap,40)
        view.reconcile(rows,6)
        self.assertEqual(view.scroll,15)
        snap["tasks"][19]["status"] = "doing"
        rows = view.rows(snap,40)
        view.reconcile(rows,6)
        self.assertEqual(view.selected,20)
        self.assertIn(20,[r["target"] for r in rows[view.scroll:view.scroll+6]])

    def test_description_scroll_survives_refresh_and_collapse_reveals_header(self):
        view = QueueView()
        snap = self.many_tasks()
        snap["tasks"][0]["detail"] = "A long description. "*200
        view.toggle(1)
        rows = view.rows(snap,40)
        view.reconcile(rows,6)
        view.scroll = 25
        view.reconcile(view.rows(snap,40),6)
        self.assertEqual(view.scroll,25)
        view.toggle(1)
        rows = view.rows(snap,40)
        view.reconcile(rows,6)
        self.assertIn(1,[r["target"] for r in rows[view.scroll:view.scroll+6]])

    def test_compact_rows_keep_tasks_beside_section_headings(self):
        rows = QueueView().rows(self.snapshot(),37,compact=True)
        self.assertEqual(rows[1]["target"],2)
        self.assertFalse(any(not r["text"] for r in rows))

    def test_long_paragraph_wrapping_is_linear(self):
        paragraph = "word 界 e\u0301 "*2000
        measured = 0
        def measure(value):
            nonlocal measured
            measured += len(value)
            return cells(value)
        with patch("queue_view.cells",new=measure):
            lines = wrap(paragraph,37)
        self.assertTrue(all(cells(line)<=37 for line in lines))
        self.assertLess(measured,len(paragraph)*3)


class BrowserTests(unittest.TestCase):
    TOKEN = "browser-contract-token-0123456789"
    SAFE_TASK_FIELDS = {
        "id", "title", "detail", "status", "owner_name", "priority",
        "note", "created", "updated", "waiting_on",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.servers = []
        self.path = Path(self.temp.name)/"tasks.db"
        self.session = str(Path(self.temp.name).resolve()/"herdr.sock")
        self.store = app.Store(self.path)
        self.board = self.store.join("ProjectName", A)["board"]
        self.store.join("ProjectName", B)
        self.store.bind_space(self.board, self.session, "w1")
        self.task = self.store.add(
            self.board, A, "Ship </script><img src=x onerror=alert(1)>",
            detail="Keep this as browser text.",
        )["id"]

        self.other = self.store.join("OtherProjectName", A)["board"]
        self.store.bind_space(self.other, self.session, "w2")
        self.store.add(self.other, A, "Other-space task")
        self.live = {
            "focused_workspace_id": "w2",
            "workspaces": [
                {"workspace_id": "w1", "label": "SpaceName"},
                {"workspace_id": "w2", "label": "OtherSpaceName"},
            ],
        }

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.store.close()
        self.temp.cleanup()

    def payload(self):
        return app.browser_payload(
            store=self.store,
            session=self.session,
            workspace="w1",
            board=self.board,
            live=self.live,
        )

    def start_server(self):
        handler = app.make_web_handler(
            session=self.session,
            database=self.path,
            workspace="w1",
            board=self.board,
            token=self.TOKEN,
            snapshot_reader=lambda _session: self.live,
        )
        server = app.LocalWebServer((app.WEB_HOST, 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return server

    def request(self, server, method, path, host=None, body=None):
        port = server.server_address[1]
        connection = http.client.HTTPConnection(app.WEB_HOST, port, timeout=2)
        headers = {"Host": host or f"{app.WEB_HOST}:{port}"}
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            content = response.read()
            return response.status, {key.lower(): value for key, value in response.getheaders()}, content
        finally:
            connection.close()

    def api_path(self, suffix="/api/state"):
        return f"/v/{self.TOKEN}{suffix}"

    def test_browser_payload_is_a_sanitized_display_dto(self):
        payload = self.payload()
        self.assertEqual(set(payload), {
            "workspace", "workspace_label", "snapshot", "counts", "served_at", "revision",
        })
        self.assertEqual(payload["workspace"], "w1")
        self.assertEqual(payload["snapshot"]["board"], {"name": "ProjectName"})
        self.assertEqual(set(payload["snapshot"]), {"board", "tasks"})
        self.assertEqual(set(payload["snapshot"]["tasks"][0]), self.SAFE_TASK_FIELDS)
        self.assertEqual(payload["snapshot"]["tasks"][0]["title"],
                         "Ship </script><img src=x onerror=alert(1)>")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(A["id"], serialized)
        self.assertNotIn(B["id"], serialized)
        self.assertNotIn("Other-space task", serialized)
        self.assertNotIn('"members"', serialized)
        self.assertNotIn('"actor"', serialized)
        self.assertNotIn('"owner"', serialized)

    def test_handler_pins_board_and_ignores_query_workspace_switches(self):
        server = self.start_server()
        status, _, content = self.request(
            server, "GET", self.api_path("/api/state?workspace=w2&board="+str(self.other)),
        )
        self.assertEqual(status, 200)
        payload = json.loads(content)
        self.assertEqual(payload["workspace"], "w1")
        self.assertEqual(payload["snapshot"]["board"]["name"], "ProjectName")
        self.assertNotIn("Other-space task", content.decode())

        # Administrative rebinding after launch must not change this URL's scope.
        self.store.db.execute("DELETE FROM spaces WHERE session=? AND workspace=?", (self.session, "w2"))
        self.store.db.execute("UPDATE spaces SET board=? WHERE session=? AND workspace=?",
                              (self.other, self.session, "w1"))
        status, _, content = self.request(server, "GET", self.api_path())
        self.assertEqual(status, 503)
        payload = json.loads(content)
        self.assertIn("reopen", payload["error"].lower())
        self.assertNotIn("Other-space task", content.decode())

    def test_http_rejects_wrong_token_host_and_mutation(self):
        server = self.start_server()
        port = server.server_address[1]

        status, _, content = self.request(server, "GET", "/v/wrong-token/api/state")
        self.assertEqual(status, 404)
        self.assertNotIn(b"Ship", content)

        status, _, content = self.request(
            server, "GET", self.api_path(), host=f"queue.example:{port}",
        )
        self.assertEqual(status, 421)
        self.assertNotIn(b"Ship", content)

        before = self.store.show(self.task)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, content = self.request(
                    server, method, self.api_path(), body=b'{"status":"done"}',
                )
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("connection"), "close")
                self.assertNotIn("access-control-allow-origin", headers)
                self.assertIn(b"Read-only", content)
        self.assertEqual(self.store.show(self.task), before)

    def test_revision_is_stable_until_queue_content_changes(self):
        with patch.object(app.time, "time", return_value=100):
            first = self.payload()
        with patch.object(app.time, "time", return_value=200):
            second = self.payload()
        self.assertNotEqual(first["served_at"], second["served_at"])
        self.assertEqual(first["revision"], second["revision"])
        self.assertRegex(first["revision"], r"^[0-9a-f]{16}$")

        self.store.update(self.task, A, note="Changed after the first poll")
        with patch.object(app.time, "time", return_value=300):
            changed = self.payload()
        self.assertNotEqual(first["revision"], changed["revision"])


class IntegrationTests(unittest.TestCase):
    def test_local_server_skips_reverse_dns(self):
        with patch.object(app.socket, "getfqdn",
                          side_effect=AssertionError("unexpected lookup")) as lookup:
            server = app.LocalWebServer((app.WEB_HOST, 0), app.BaseHTTPRequestHandler)
            try:
                self.assertEqual(server.server_name, app.WEB_HOST)
                self.assertGreater(server.server_port, 0)
            finally:
                server.server_close()
        lookup.assert_not_called()

    def test_local_server_binds_reuses_and_stops_for_one_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/"tasks.db"
            session = str(root.resolve()/"herdr.sock")
            store = app.Store(path)
            board = store.join("Browser", A)["board"]
            store.bind_space(board, session, "w1")
            store.add(board, A, "Visible only here")
            store.close()
            env = {"HERDR_TASKS_WEB_STATE_DIR":str(root/"web-state")}
            first = None
            state = None
            with patch.dict(os.environ, env, clear=False):
                try:
                    first = app.ensure_web_server(session, "w1", path)
                    second = app.ensure_web_server(session, "w1", path)
                    self.assertFalse(first["reused"])
                    self.assertTrue(second["reused"])
                    self.assertEqual(first["url"], second["url"])
                    state_path, _, _ = app.web_state_paths(session, "w1")
                    self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                    state = app.read_web_state(state_path)
                    self.assertEqual(app.web_health(first["port"], session, "w1", board,
                                                    path, state["token"])["pid"], first["pid"])
                    stale = dict(state, build_id="stale-build")
                    app.atomic_json(state_path, stale)
                    restarted = app.ensure_web_server(session, "w1", path)
                    self.assertFalse(restarted["reused"])
                    self.assertEqual(restarted["url"], first["url"])
                    self.assertNotEqual(restarted["pid"], first["pid"])
                    state = app.read_web_state(state_path)
                finally:
                    if first and state:
                        self.assertTrue(app.stop_web_server(session, "w1"))
                        deadline = time.monotonic()+2
                        while time.monotonic() < deadline and app.web_health(
                                first["port"], session, "w1", board, path, state["token"]):
                            time.sleep(0.05)
                        self.assertIsNone(app.web_health(first["port"], session, "w1", board,
                                                        path, state["token"]))

    def test_status_runs_in_server_environment_without_a_pane_or_login_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"tasks.db"
            session = str(Path(tmp).resolve()/"herdr.sock")
            store = app.Store(path)
            board = store.join("Preview",A)["board"]
            store.bind_space(board,session,"w1")
            task = store.add(board,A,"Preview without a prompt")["id"]
            store.start(task,A)
            store.close()
            env = {"PATH":"/usr/bin:/bin", "HERDR_TASKS_DB":str(path),
                   "HERDR_SOCKET_PATH":session,"HERDR_ACTIVE_WORKSPACE_ID":"w1"}
            def status(values):
                return subprocess.check_output([sys.executable,str(app.ROOT/"herdr_tasks.py"),"status"],
                                               env=values,text=True,timeout=2).strip()
            self.assertIn("Now: Preview without a prompt",status(env))
            self.assertEqual(status({**env,"HERDR_SOCKET_PATH":str(Path(tmp)/"other.sock")}),"")
            self.assertEqual(status({**env,"HERDR_ACTIVE_WORKSPACE_ID":"w2"}),"")
            self.assertEqual(status({**env,"HERDR_ACTIVE_WORKSPACE_ID":""}),"")
            absent = Path(tmp)/"absent.db"
            self.assertEqual(status({**env,"HERDR_TASKS_DB":str(absent)}),"Tasks · unavailable")
            self.assertFalse(absent.exists())
            with patch.dict(os.environ,env,clear=True), self.assertRaises(ValueError):
                app.session_key()  # Mutating commands still require a managed pane.

    def test_open_splits_and_reuses_without_replacing_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.Store(Path(tmp)/"tasks.db")
            board = store.join("Demo", A)["board"]
            store.bind_space(board,"test-session","w1")
            source = {"pane_id":"w1:p2","workspace_id":"w1","tab_id":"w1:t1"}
            viewer = dict(source,pane_id="w1:p3")
            try:
                with patch.object(app,"session_key",return_value="test-session"), patch.object(app, "api", side_effect=[
                    {"snapshot":{"panes":[source],"focused_pane_id":"w1:p2"}}, {"plugin_pane":{"pane":viewer}}, {}
                ]) as api, patch.object(app,"rpc",side_effect=[
                    {"layout":{"root":{"type":"split","direction":"down","ratio":0.5,
                        "first":{"type":"pane","pane_id":"w1:p2"},"second":{"type":"pane","pane_id":"w1:p3"}}}}, {}
                ]) as rpc:
                    self.assertEqual(app.open_board(store), {"pane":viewer,"reused":False})
                    self.assertEqual(api.call_args_list[1].args, (
                        "plugin", "pane", "open", "--plugin", "herdr-tasks", "--entrypoint", "board",
                        "--placement", "split", "--target-pane","w1:p2","--direction","down","--no-focus",
                        "--env", f"HERDR_TASKS_BOARD={board}"
                    ))
                    self.assertEqual([c.args[0] for c in rpc.call_args_list],["layout.export","layout.set_split_ratio"])
                with patch.object(app,"session_key",return_value="test-session"), patch.object(app,"api",side_effect=[{"pane":source},{"pane":viewer}]) as api:
                    self.assertEqual(app.open_board(store,"w1:p2",False), {"pane":viewer,"reused":True})
                    self.assertEqual(api.call_count,2)
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
            legacy_cli = root/".local/bin/herdr-tasks"
            legacy_cli.parent.mkdir(parents=True)
            legacy_cli.symlink_to(app.ROOT/"herdr_tasks.py")
            with patch.object(Path, "home", return_value=root), patch.dict(os.environ, {
                "HERDR_ENV": "1", "HERDR_CONFIG_PATH": str(config), "HERDR_TASKS_DB": str(data)
            }), patch.object(app, "herdr", return_value="ok"):
                app.setup()
                once = config.read_text()
                app.setup()
                self.assertEqual(once, config.read_text())
                self.assertIn(original, once)
                self.assertNotIn("prefix+shift+t",once)
                self.assertEqual(once.count('[[ui.tab_bar_right]]'), 1)
                self.assertIn(app.shlex.join([sys.executable,str(app.ROOT/"herdr_tasks.py"),"status"]),once)
                self.assertTrue((root/".local/bin/herdr-tasks").is_symlink())
                self.assertEqual((root/".local/bin/herdr-tasks").resolve(), app.ROOT/"run.sh")
                self.assertEqual(subprocess.check_output(
                    [str(root/".local/bin/herdr-tasks"), "--version"], text=True).strip(), app.VERSION)
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
        for width,height in ((80,32),(160,32),(40,8),(50,5)):
            with self.subTest(width=width,height=height), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"tasks.db"
                store = app.Store(path)
                board = store.join("Demo", A)["board"]
                task = store.add(board, A, "Ship the demo", detail="Acceptance criteria")["id"]
                store.start(task, A)
                store.close()
                master, slave = os.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", height,width,0,0))
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
                    expect(b"Now")
                    # Use the viewer's documented keyboard path here. Synthetic
                    # xterm mouse reports are interpreted differently by the
                    # ncurses builds on macOS and Ubuntu, while Enter exercises
                    # the same selected-task toggle deterministically.
                    os.write(master,b"\r")
                    if height == 5:
                        # The description is below the two-row viewport; page to it.
                        expect(b"1-2/3")
                        os.write(master,b"\x1b[6~")
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
