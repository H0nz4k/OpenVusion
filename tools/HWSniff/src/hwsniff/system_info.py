from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def is_linux() -> bool:
    return os.name == "posix"


def can_shutdown() -> bool:
    return bool(shutil.which("systemctl")) or bool(shutil.which("shutdown"))


def request_shutdown() -> None:
    """Best-effort privileged shutdown without requiring whole app as root."""
    helpers = [
        ["systemctl", "poweroff"],
        ["shutdown", "-h", "now"],
        ["/sbin/shutdown", "-h", "now"],
    ]
    for cmd in helpers:
        if shutil.which(cmd[0]) or Path(cmd[0]).exists():
            subprocess.Popen(cmd)  # noqa: S603 - fixed command list
            return
    raise RuntimeError("No shutdown helper available")
