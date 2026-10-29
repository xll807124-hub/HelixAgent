"""Shared-workspace task claims. Uses only the Python standard library."""

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "docs" / "development" / "task-board.json"


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def locked(board):
    lock = board.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(f"台账正在更新；稍后重试。禁止直接删除锁：{lock}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": now()}, handle)
        yield
    finally:
        lock.unlink()


def read(board):
    return json.loads(board.read_text(encoding="utf-8"))


def write(board, data):
    fd, name = tempfile.mkstemp(prefix="task-board-", suffix=".tmp", dir=board.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, board)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def blockers(task, tasks):
    return [key for key in task["implementation_dependencies"] if tasks[key]["status"] != "已完成"]


def validate(data):
    tasks = data["tasks"]
    indexed = {t["id"]: t for t in tasks}
    if len(indexed) != len(tasks):
        raise ValueError("任务 ID 重复")
    allowed = {"待开发", "开发中", "待确认", "阻塞", "待验收", "已完成"}
    for task in tasks:
        if task["status"] not in allowed:
            raise ValueError(f"非法状态：{task['id']}")
        for field in ("interface", "acceptance", "write_scopes", "requirements"):
            if not task.get(field):
                raise ValueError(f"缺少 {field}：{task['id']}")
        for key in task["implementation_dependencies"]:
            if key not in indexed:
                raise ValueError(f"未知依赖：{key}")
        if task["status"] in {"开发中", "待确认", "阻塞", "待验收"} and not task["owner"]:
            raise ValueError(f"已领取任务缺少负责人：{task['id']}")
        if task["status"] == "已完成" and not task.get("completion_evidence"):
            raise ValueError(f"完成任务缺少证据：{task['id']}")
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError(f"循环依赖：{key}")
        if key in visited:
            return
        visiting.add(key)
        for dep in indexed[key]["implementation_dependencies"]:
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in indexed:
        visit(key)
    return indexed


def overlap(left, right):
    a, b = left.replace("\\", "/").rstrip("/"), right.replace("\\", "/").rstrip("/")
    a, b = a.casefold(), b.casefold()
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "list",
            "show",
            "validate",
            "claim",
            "heartbeat",
            "block",
            "release",
            "submit-design",
            "approve-design",
            "submit",
            "accept",
            "handoff",
        ],
    )
    parser.add_argument("task", nargs="?")
    parser.add_argument("--owner", help="唯一会话/AI 标识；写操作必须提供")
    parser.add_argument("--mode", choices=["design", "implementation"], default="design")
    parser.add_argument("--note", default="")
    parser.add_argument("--evidence", default="", help="评审、测试或用户确认记录的路径与定位")
    parser.add_argument("--to", dest="new_owner")
    parser.add_argument("--board", type=Path, default=BOARD, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action in {"list", "show", "validate"}:
        data = read(args.board)
        tasks = validate(data)
        if args.action == "validate":
            print(f"台账有效：{len(tasks)} 项，依赖无环")
        elif args.action == "show":
            print(json.dumps(tasks[args.task], ensure_ascii=False, indent=2))
        else:
            for task in tasks.values():
                pending = blockers(task, tasks)
                ready = task["implementation_ready"] and not pending
                print(
                    f"{task['id']} | {task['status']} | {task['owner'] or '无人领取'} | "
                    f"实现可领取={ready} | {task['title']}"
                )
        return
    if not args.owner or not args.task:
        raise ValueError("写操作必须提供任务 ID 和 --owner")
    with locked(args.board):
        data = read(args.board)
        tasks = validate(data)
        task = tasks[args.task]
        previous = task["status"]
        if args.action == "claim":
            if task["owner"] or task["status"] != "待开发":
                raise ValueError("任务已被领取或当前不可领取；禁止抢占")
            if args.mode == "implementation":
                if not task["implementation_ready"] or blockers(task, tasks):
                    raise ValueError("实施基线未批准或实现依赖未完成；可先领取 design")
                for other in tasks.values():
                    if (
                        other["owner"]
                        and other.get("mode") == "implementation"
                        and other["status"] != "已完成"
                    ):
                        if any(
                            overlap(a, b)
                            for a in task["write_scopes"]
                            for b in other["write_scopes"]
                        ):
                            raise ValueError(f"写入范围与 {other['id']} 重叠；先明确文件边界再领取")
            task.update(owner=args.owner, mode=args.mode, status="开发中")
            task["claimed_at"] = now()
        else:
            if task["owner"] != args.owner:
                raise ValueError("仅当前负责人可更新；接手须由原负责人 handoff")
            if (
                args.action in {"approve-design", "accept", "submit", "submit-design"}
                and not args.evidence
            ):
                raise ValueError("必须提供 --evidence；批准/验收必须引用真实用户确认")
            if args.action == "heartbeat":
                pass
            elif args.action == "block":
                if task["status"] != "开发中" or not args.note:
                    raise ValueError("仅开发中任务可阻塞，必须说明原因")
                task["status"] = "阻塞"
            elif args.action == "release":
                if task["status"] not in {"开发中", "阻塞"} or not args.note:
                    raise ValueError("仅开发中/阻塞任务可释放，须记录成果和恢复方法")
                task.update(status="待开发", owner=None, mode=None)
            elif args.action == "handoff":
                if task["status"] == "已完成" or not args.new_owner or not args.note:
                    raise ValueError("交接须提供 --to 和 --note，已完成任务不可交接")
                task["owner"] = args.new_owner
            elif args.action == "submit-design":
                if task["status"] != "开发中" or task["mode"] != "design":
                    raise ValueError("需要处于设计开发中")
                task["status"] = "待确认"
                task["design_evidence"] = args.evidence
            elif args.action == "approve-design":
                if task["status"] != "待确认":
                    raise ValueError("需要处于待确认")
                task.update(status="待开发", implementation_ready=True, owner=None, mode=None)
                task["approval_evidence"] = args.evidence
            elif args.action == "submit":
                if task["status"] != "开发中" or task["mode"] != "implementation":
                    raise ValueError("需要处于实现开发中")
                if blockers(task, tasks):
                    raise ValueError("依赖尚未完成")
                task["status"] = "待验收"
                task["delivery_evidence"] = args.evidence
            elif args.action == "accept":
                if task["status"] != "待验收":
                    raise ValueError("需要处于待验收")
                task.update(status="已完成", completed_at=now(), completion_evidence=args.evidence)
        task["updated_at"] = now()
        task["last_note"] = args.note
        data["history"].append(
            {
                "at": now(),
                "task": args.task,
                "action": args.action,
                "actor": args.owner,
                "previous_status": previous,
                "status": task["status"],
                "note": args.note,
                "evidence": args.evidence,
            }
        )
        validate(data)
        write(args.board, data)
        print(f"{args.task}：{previous} → {task['status']}；负责人={task['owner'] or '无人领取'}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        sys.exit(1)
