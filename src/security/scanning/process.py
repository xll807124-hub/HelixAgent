"""Run scanner processes without leaving them alive after cancellation."""
from __future__ import annotations

import asyncio
import subprocess


async def run_scanner_process(
    cmd: list[str], cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    process = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    returncode = await process.wait()
    return subprocess.CompletedProcess(
        cmd, returncode, stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
