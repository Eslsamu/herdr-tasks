#!/usr/bin/env python3
"""Build the fully synthetic, deterministic data used by the demo capture."""

import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import herdr_tasks as tasks  # noqa: E402


FIXED_TIME = 1_788_753_600
SESSION_NAME = "demo-session.sock"
WORKSPACE = "demo-workspace"
WORKSPACE_LABEL = "Demo workspace"
BOARD_NAME = "Launch readiness"
AGENT_ONE = {"id": "codex:synthetic-agent-one", "name": "Agent One"}
QA_AGENT = {"id": "codex:synthetic-qa", "name": "QA"}


def display_payload(store, session, board):
    return copy.deepcopy(tasks.browser_payload(
        store,
        session,
        WORKSPACE,
        board,
        live={
            "focused_workspace_id": WORKSPACE,
            "workspaces": [{"workspace_id": WORKSPACE, "label": WORKSPACE_LABEL}],
        },
    ))


def build_fixture():
    with tempfile.TemporaryDirectory(prefix="herdr-tasks-demo-fixture-") as temporary:
        database = Path(temporary) / "tasks.db"
        session = str(Path(temporary) / SESSION_NAME)

        with patch.object(tasks.time, "time", return_value=FIXED_TIME):
            store = tasks.Store(database)
            try:
                board = store.join(BOARD_NAME, AGENT_ONE)["board"]
                store.join(BOARD_NAME, QA_AGENT)
                store.bind_space(board, session, WORKSPACE)

                current = store.add(
                    board,
                    AGENT_ONE,
                    "Draft release notes",
                    detail="Prepare a concise release summary.",
                    priority=4,
                )["id"]
                store.start(current, AGENT_ONE)
                working_preview = tasks.top_status(store, session, WORKSPACE)

                follow_up = store.add(
                    board,
                    AGENT_ONE,
                    "Run pre-release regression",
                    detail="Retest install, queue claims, and the read-only viewer.",
                    priority=1,
                )["id"]
                store.update(follow_up, AGENT_ONE, unassign=True)
                store.update(
                    current,
                    AGENT_ONE,
                    status="done",
                    note="Release notes reviewed.",
                )

                queued = {
                    "preview": tasks.top_status(store, session, WORKSPACE),
                    "payload": display_payload(store, session, board),
                }

                claimed = store.next(board, QA_AGENT)
                doing = {
                    "preview": tasks.top_status(store, session, WORKSPACE),
                    "payload": display_payload(store, session, board),
                }
            finally:
                store.close()

    assert current == 1 and follow_up == 2
    assert working_preview == "Tasks · Now: Draft release notes · 0 next · 0 waiting"
    assert queued["preview"] == (
        "Tasks · Next: Run pre-release regression · 1 next · 0 waiting"
    )
    assert doing["preview"] == (
        "Tasks · Now: Run pre-release regression · 0 next · 0 waiting"
    )
    assert claimed["id"] == follow_up
    assert claimed["status"] == "doing"
    assert claimed["owner_name"] == "QA"

    fixture = {
        "schema": "herdr-tasks-demo-v1",
        "synthetic": True,
        "duration_ms": 24_000,
        "fps": 30,
        "workspace_label": WORKSPACE_LABEL,
        "board_name": BOARD_NAME,
        "working_preview": working_preview,
        "queued": queued,
        "claim": {
            "agent": "QA",
            "command": "herdr-tasks next",
            "task": {
                "id": claimed["id"],
                "title": claimed["title"],
                "status": claimed["status"],
                "owner_name": claimed["owner_name"],
            },
        },
        "doing": doing,
    }

    serialized = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    forbidden = (
        AGENT_ONE["id"],
        QA_AGENT["id"],
        tempfile.gettempdir() + "/",
        '"members"',
        '"history"',
        '"owner":',
        '"token"',
    )
    assert all(value not in serialized for value in forbidden)
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    fixture = build_fixture()
    args.output.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
