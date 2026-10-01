"""
Bot süreç yönetimi — panelden başlat / durdur (Windows: boş terminal açmaz).
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from settings import BASE_DIR

logger = logging.getLogger(__name__)

PID_FILE = BASE_DIR / ".bot.pid"
LOG_FILE = BASE_DIR / "bot.log"

# Windows: yeni konsol penceresi açma
CREATE_NO_WINDOW = 0x08000000


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log_tail(max_chars: int = 600) -> str:
    if not LOG_FILE.exists():
        return ""
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:].strip()
    except OSError:
        return ""


def is_bot_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False
    if not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return False
    return True


def start_bot(interval: int, symbol: str = "") -> tuple[bool, str]:
    if is_bot_running():
        return False, "Bot zaten çalışıyor."

    main_py = BASE_DIR / "main.py"
    py = sys.executable
    cmd = [py, str(main_py), "--loop", str(interval)]

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(LOG_FILE, "a", encoding="utf-8")
        log_handle.write(
            f"\n{'=' * 50}\n"
            f"[{datetime.now(timezone.utc).isoformat()}] Bot baslatiliyor\n"
            f"Komut: {' '.join(cmd)}\n"
        )
        log_handle.flush()

        popen_kw: dict = {
            "cwd": str(BASE_DIR),
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kw["creationflags"] = CREATE_NO_WINDOW
        else:
            popen_kw["start_new_session"] = True

        proc = subprocess.Popen(cmd, **popen_kw)
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")

        time.sleep(1.5)
        if not _pid_alive(proc.pid):
            PID_FILE.unlink(missing_ok=True)
            tail = _log_tail()
            hint = tail.splitlines()[-3:] if tail else ["bot.log bos"]
            return False, "Bot hemen kapandi: " + " | ".join(hint)

        return True, f"Bot arka planda calisiyor (PID {proc.pid}). Log: bot.log"
    except Exception as exc:
        logger.error("Bot baslatilamadi: %s", exc)
        PID_FILE.unlink(missing_ok=True)
        return False, f"Baslatilamadi: {exc}"


def stop_bot() -> tuple[bool, str]:
    if not PID_FILE.exists():
        return False, "Bot calismiyor."

    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False, "Bot calismiyor."

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            import os

            os.killpg(os.getpgid(pid), 15)
    except Exception as exc:
        return False, f"Durdurulamadi: {exc}"
    finally:
        PID_FILE.unlink(missing_ok=True)

    return True, "Bot durduruldu."


def read_bot_log(lines: int = 20) -> str:
    if not LOG_FILE.exists():
        return ""
    try:
        all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(all_lines[-lines:])
    except OSError:
        return ""
