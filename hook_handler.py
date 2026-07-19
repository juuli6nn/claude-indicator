"""Hook handler for claude-indicator.

Invoked by Claude Code hooks (SessionStart, UserPromptSubmit, PreToolUse,
Notification, Stop, SessionEnd). Reads the hook payload from stdin, writes
this session's status to runtime/sessions/<session_id>.json, and makes sure
the indicator app is running. Must exit fast and never block Claude Code.

One file per session: writes are atomic (tmp + replace) and never contend,
so no locking is needed. The indicator aggregates: waiting > working > done.
"""

import json
import os
import subprocess
import sys
import time

# Runtime files live next to the scripts, NOT in %LOCALAPPDATA%: Microsoft
# Store Python virtualizes AppData writes per package context, so the hook
# and the indicator can otherwise end up reading two different files.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "runtime")
SESSIONS_DIR = os.path.join(APP_DIR, "sessions")
HOOKS_LOG = os.path.join(APP_DIR, "hooks.log")

EVENT_STATUS = {
    "SessionStart": "done",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "Notification": "waiting",
    "Stop": "done",
    "SessionEnd": "ended",
}


def safe_name(session_id: str) -> str:
    return "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"


def log_event(event: str, session_id: str, extra: str = "") -> None:
    try:
        with open(HOOKS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {event} [{session_id[:8]}] {extra}\n")
    except OSError:
        pass


def resolve_status(event: str, payload: dict) -> str | None:
    """Map a hook event to a pill status.

    Notification fires for two unrelated things: permission requests and a
    "Claude is waiting for your input" idle reminder (~60s after Stop). Only
    the former is a real "needs you"; the idle reminder means ready.
    """
    if event == "Notification":
        message = (payload.get("message") or "").lower()
        if "waiting for your input" in message or "idle" in message:
            return "done"
        return "waiting"
    return EVENT_STATUS.get(event)


def owner_claude_pid() -> int:
    """Walk up the process tree to the claude.exe this hook belongs to.

    Lets the indicator drop sessions whose Claude process has exited, even
    when no SessionEnd hook ever fired (killed terminal, resumed session id
    change, etc.). Returns 0 if not found.
    """
    try:
        import psutil

        p = psutil.Process(os.getpid())
        for _ in range(10):
            p = p.parent()
            if p is None:
                return 0
            if p.name().lower() in ("claude.exe", "claude"):
                return p.pid
    except Exception:
        pass
    return 0


def write_session(status: str, payload: dict) -> None:
    session_id = safe_name(payload.get("session_id", "unknown"))
    path = os.path.join(SESSIONS_DIR, session_id + ".json")

    if status == "ended":
        try:
            os.remove(path)
        except OSError:
            pass
        return

    # The psutil parent-walk costs ~300ms; do it once per session and reuse
    # the cached pid on subsequent events so hooks stay fast. Also keep
    # "since" (when the current status began) for the elapsed-time display.
    pid = 0
    prev_status, prev_since = None, 0.0
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        pid = prev.get("pid", 0)
        prev_status = prev.get("status")
        prev_since = prev.get("since", 0.0)
    except (OSError, json.JSONDecodeError):
        pass
    if not pid:
        pid = owner_claude_pid()

    now = time.time()
    data = {
        "status": status,
        "cwd": payload.get("cwd", ""),
        "ts": now,
        "since": prev_since if status == prev_status and prev_since else now,
        "pid": pid,
    }
    tmp = path + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def indicator_running() -> bool:
    """Check for the named mutex the indicator holds while alive."""
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenMutexW(
            SYNCHRONIZE, False, "claude_indicator_singleton"
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except OSError:
        return False


def launch_indicator() -> None:
    script = os.path.join(BASE_DIR, "indicator.py")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [exe, script],
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    event = payload.get("hook_event_name", "")
    status = resolve_status(event, payload)
    if status is None:
        return

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    log_event(event, payload.get("session_id", "unknown"),
              payload.get("message", "") if event == "Notification" else "")
    write_session(status, payload)

    if status != "ended" and not indicator_running():
        try:
            launch_indicator()
        except OSError:
            pass


if __name__ == "__main__":
    main()
