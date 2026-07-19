"""Installer for claude-indicator hooks.

Merges hook entries into ~/.claude/settings.json so Claude Code notifies the
indicator on lifecycle events. Run `python install.py` to install,
`python install.py --uninstall` to remove.
"""

import argparse
import json
import os
import shutil
import sys

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
HANDLER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_handler.py")
MARKER = "claude-indicator"

EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SessionEnd",
]


def hook_command() -> str:
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{exe}" "{HANDLER}"'


def is_ours(entry: dict) -> bool:
    for hook in entry.get("hooks", []):
        if MARKER in hook.get("command", "") or HANDLER in hook.get("command", ""):
            return True
    return False


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print(f"ERROR: {SETTINGS_FILE} contains invalid JSON; fix it first.")
        sys.exit(1)


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    if os.path.exists(SETTINGS_FILE):
        shutil.copy2(SETTINGS_FILE, SETTINGS_FILE + ".bak")
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def install() -> None:
    try:
        import PySide6  # noqa: F401
        import win32gui  # noqa: F401
        import psutil  # noqa: F401
    except ImportError as exc:
        print(f"Missing dependency: {exc.name}. Run: pip install -r requirements.txt")
        sys.exit(1)

    settings = load_settings()
    hooks = settings.setdefault("hooks", {})
    command = hook_command()
    changed = []

    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if any(is_ours(e) for e in entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": command}]})
        changed.append(event)

    if changed:
        save_settings(settings)
        print(f"Installed hooks for: {', '.join(changed)}")
        print(f"(backup written to {SETTINGS_FILE}.bak)")
    else:
        print("Hooks already installed; nothing to do.")
    print("Start a new Claude Code session to see the indicator.")


def uninstall() -> None:
    settings = load_settings()
    hooks = settings.get("hooks", {})
    removed = []

    for event in list(hooks.keys()):
        before = len(hooks[event])
        hooks[event] = [e for e in hooks[event] if not is_ours(e)]
        if len(hooks[event]) != before:
            removed.append(event)
        if not hooks[event]:
            del hooks[event]

    if removed:
        save_settings(settings)
        print(f"Removed hooks for: {', '.join(removed)}")
    else:
        print("No claude-indicator hooks found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install/uninstall claude-indicator hooks")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    uninstall() if args.uninstall else install()


if __name__ == "__main__":
    main()
