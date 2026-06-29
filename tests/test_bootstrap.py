import sys
import pytest
from unittest.mock import patch, MagicMock
from scripts.bootstrap import check_tool, get_install_command, Platform


def test_check_tool_found(tmp_path):
    fake_bin = tmp_path / "yt-dlp"
    fake_bin.write_text("#!/bin/sh\necho ok")
    fake_bin.chmod(0o755)
    import shutil
    with patch("shutil.which", return_value=str(fake_bin)):
        assert check_tool("yt-dlp") is True


def test_check_tool_not_found():
    import shutil
    with patch("shutil.which", return_value=None):
        assert check_tool("yt-dlp") is False


def test_get_install_command_linux():
    cmd = get_install_command("ffmpeg", Platform.LINUX)
    assert "apt-get" in cmd or "apt" in cmd


def test_get_install_command_mac():
    cmd = get_install_command("ffmpeg", Platform.MACOS)
    assert "brew" in cmd


def test_get_install_command_windows():
    cmd = get_install_command("ffmpeg", Platform.WINDOWS)
    assert "winget" in cmd or "choco" in cmd
