#!/usr/bin/env python3
"""Bootstrap: verify required tools are installed, install if missing."""
from __future__ import annotations
import shutil
import subprocess
import sys
from enum import Enum


class Platform(Enum):
    LINUX = "linux"
    MACOS = "darwin"
    WINDOWS = "win32"


def detect_platform() -> Platform:
    if sys.platform.startswith("linux"):
        return Platform.LINUX
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform == "win32":
        return Platform.WINDOWS
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def check_tool(name: str) -> bool:
    return shutil.which(name) is not None


INSTALL_COMMANDS: dict[str, dict[Platform, str]] = {
    "ffmpeg": {
        Platform.LINUX: "sudo apt-get install -y ffmpeg",
        Platform.MACOS: "brew install ffmpeg",
        Platform.WINDOWS: "winget install ffmpeg",
    },
    "yt-dlp": {
        Platform.LINUX: "pip install yt-dlp",
        Platform.MACOS: "pip install yt-dlp",
        Platform.WINDOWS: "pip install yt-dlp",
    },
}


def get_install_command(tool: str, platform: Platform) -> str:
    return INSTALL_COMMANDS[tool][platform]


def ensure_tool(name: str, platform: Platform) -> None:
    if check_tool(name):
        return
    cmd = get_install_command(name, platform)
    print(f"Installing {name}: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"\nFailed to auto-install {name}. Install manually:\n  {cmd}")
        sys.exit(1)


def run() -> None:
    platform = detect_platform()
    print(f"Platform: {platform.value}")
    for tool in ["yt-dlp", "ffmpeg"]:
        ensure_tool(tool, platform)
    print("Bootstrap complete.")


if __name__ == "__main__":
    run()
