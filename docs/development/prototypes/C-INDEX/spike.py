"""Isolated stdlib design experiment; not a production indexer or acceptance suite."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
import tracemalloc
from dataclasses import dataclass
from functools import partial
from pathlib import Path


@dataclass
class Node:
    digest: str
    children: dict[str, Node]
    path: str | None = None


def tree(files: dict[str, str]) -> Node:
    root: dict = {}
    for path, digest in files.items():
        parts = path.split("/")
        cursor = root
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = (path, digest)

    def freeze(value: dict | tuple) -> Node:
        if isinstance(value, tuple):
            path, digest = value
            return Node(digest, {}, path)
        children = {key: freeze(value[key]) for key in sorted(value)}
        # Encode names and types, so reordering has no effect and file/dir differ.
        payload = [(key, node.path is not None, node.digest) for key, node in children.items()]
        digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        return Node(digest, children)

    return freeze(root)


def flat_diff(old: dict[str, str], new: dict[str, str]) -> set[str]:
    return {path for path in old.keys() | new.keys() if old.get(path) != new.get(path)}


def merkle_diff(old: Node | None, new: Node | None) -> tuple[set[str], int]:
    result: set[str] = set()
    visited = 0

    def walk(left: Node | None, right: Node | None) -> None:
        nonlocal visited
        visited += 1
        if left is not None and right is not None:
            if left.digest == right.digest and (left.path is None) == (right.path is None):
                return
        if left is not None and left.path is not None:
            result.add(left.path)
        if right is not None and right.path is not None:
            result.add(right.path)
        lc = left.children if left is not None else {}
        rc = right.children if right is not None else {}
        for name in sorted(lc.keys() | rc.keys()):
            walk(lc.get(name), rc.get(name))

    walk(old, new)
    return result, visited


def median_ms(fn, repeats: int = 15) -> float:
    values = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        fn()
        values.append((time.perf_counter_ns() - start) / 1_000_000)
    return round(statistics.median(values), 4)


def main() -> None:
    old = {"pkg/a.py": "one", "pkg/b.py": "two", "other/c.ts": "three"}
    scenarios = {
        "unchanged": dict(old),
        "addition": {**old, "pkg/new.go": "four"},
        "deletion": {k: v for k, v in old.items() if k != "pkg/a.py"},
        "rename": {"pkg/renamed.py": "one", "pkg/b.py": "two", "other/c.ts": "three"},
        "reorder": dict(reversed(list(old.items()))),
        "edit": {**old, "pkg/b.py": "changed"},
        "empty": {},
        "file_to_directory": {"pkg/a.py/child.go": "one"},
    }
    correctness = []
    for name, new in scenarios.items():
        actual, visited = merkle_diff(tree(old), tree(new))
        expected = flat_diff(old, new)
        assert actual == expected, (name, actual, expected)
        applied = {k: v for k, v in old.items() if k not in actual}
        applied.update({k: new[k] for k in actual if k in new})
        assert applied == new
        correctness.append({"case": name, "changed": sorted(actual), "visited_nodes": visited})

    # Regression signal for the old pseudocode's old-children-only iteration.
    old_order = ["a", "b"]
    new_order = ["a", "b", "new"]
    legacy_visits = [new_order[i] for i in range(len(old_order))]
    assert "new" not in legacy_visits

    measurements = []
    for count in (1000, 10000):
        files = {
            f"d{i // 100:03d}/f{i:05d}.py": hashlib.sha256(str(i).encode()).hexdigest()
            for i in range(count)
        }
        changed = {**files, "d000/f00000.py": "changed"}
        before, after = tree(files), tree(changed)
        diff, visited = merkle_diff(before, after)
        assert diff == flat_diff(files, changed) == {"d000/f00000.py"}
        tracemalloc.start()
        tree(files)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append({
            "files": count,
            "changes": 1,
            "flat_diff_median_ms": median_ms(partial(flat_diff, files, changed)),
            "merkle_diff_median_ms": median_ms(partial(merkle_diff, before, after)),
            "full_tree_build_median_ms": median_ms(partial(tree, files)),
            "merkle_visited_nodes": visited,
            "tree_build_peak_python_bytes": peak,
        })
    report = {
        "scope": "Synthetic file-hash manifests only; excludes parsing, disk, DB and LSP",
        "python": platform.python_version(),
        "platform": platform.system(),
        "repeats": 15,
        "correctness": correctness,
        "legacy_new_sibling_omitted": True,
        "measurements": measurements,
        "limits": "Merkle timing assumes prebuilt trees; build cost is reported separately",
    }
    output = Path(__file__).with_name("results.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
