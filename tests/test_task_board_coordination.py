"""Behavior checks for shared-workspace task claims; uses isolated boards."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_board.py"


@pytest.fixture
def board(tmp_path):
    tasks = []
    for key, deps, ready in [("A", [], True), ("B", ["A"], True), ("C", [], False)]:
        tasks.append(
            {
                "id": key,
                "title": key,
                "requirements": ["REQ-TEST"],
                "interface": "input/output",
                "acceptance": "observable result",
                "write_scopes": [f"src/{key}"],
                "implementation_dependencies": deps,
                "implementation_ready": ready,
                "status": "待开发",
                "owner": None,
                "mode": None,
            }
        )
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"tasks": tasks, "history": []}), encoding="utf-8")
    return path


def run(board, *args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args, "--board", str(board)],
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=20,
    )


def test_concurrent_claim_has_exactly_one_winner(board):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda i: run(board, "claim", "A", "--owner", f"chat-{i}"), range(8))
        )
    assert sum(result.returncode == 0 for result in results) == 1
    data = json.loads(board.read_text(encoding="utf-8"))
    assert data["tasks"][0]["status"] == "开发中"
    assert len(data["history"]) == 1


def test_dependencies_and_approval_block_implementation_but_allow_design(board):
    assert run(board, "claim", "B", "--owner", "b", "--mode", "implementation").returncode
    assert run(board, "claim", "C", "--owner", "c", "--mode", "implementation").returncode
    assert run(board, "claim", "B", "--owner", "b", "--mode", "design").returncode == 0


def test_owner_release_handoff_and_acceptance_flow(board):
    assert run(board, "claim", "A", "--owner", "one", "--mode", "implementation").returncode == 0
    assert run(board, "release", "A", "--owner", "other", "--note", "steal").returncode
    assert run(board, "accept", "A", "--owner", "one", "--evidence", "user").returncode
    assert (
        run(board, "handoff", "A", "--owner", "one", "--to", "two", "--note", "handoff").returncode
        == 0
    )
    assert run(board, "submit", "A", "--owner", "one", "--evidence", "report").returncode
    assert run(board, "submit", "A", "--owner", "two").returncode
    assert run(board, "submit", "A", "--owner", "two", "--evidence", "report").returncode == 0
    assert run(board, "claim", "A", "--owner", "other").returncode
    assert (
        run(board, "accept", "A", "--owner", "two", "--evidence", "user-confirmation").returncode
        == 0
    )
    assert run(board, "claim", "B", "--owner", "b", "--mode", "implementation").returncode == 0


def test_design_review_then_implementation(board):
    assert run(board, "claim", "C", "--owner", "c").returncode == 0
    assert run(board, "submit", "C", "--owner", "c", "--evidence", "report").returncode
    assert run(board, "submit-design", "C", "--owner", "c", "--evidence", "design").returncode == 0
    assert run(board, "approve-design", "C", "--owner", "c").returncode
    assert (
        run(
            board, "approve-design", "C", "--owner", "c", "--evidence", "user-confirmation"
        ).returncode
        == 0
    )
    assert run(board, "claim", "C", "--owner", "new", "--mode", "implementation").returncode == 0


def test_overlap_and_existing_lock_refuse_claim(board):
    data = json.loads(board.read_text(encoding="utf-8"))
    data["tasks"][2].update(implementation_ready=True, write_scopes=["SRC/a/child"])
    board.write_text(json.dumps(data), encoding="utf-8")
    assert run(board, "claim", "A", "--owner", "a", "--mode", "implementation").returncode == 0
    assert run(board, "claim", "C", "--owner", "c", "--mode", "implementation").returncode
    lock = board.with_suffix(".lock")
    lock.write_text("existing writer", encoding="utf-8")
    assert run(board, "heartbeat", "A", "--owner", "a").returncode
    assert lock.read_text(encoding="utf-8") == "existing writer"


def test_cycle_is_rejected(board):
    data = json.loads(board.read_text(encoding="utf-8"))
    data["tasks"][0]["implementation_dependencies"] = ["B"]
    board.write_text(json.dumps(data), encoding="utf-8")
    assert run(board, "validate").returncode
