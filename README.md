# Claude Indicator

A beautiful always-on-top status pill for **Claude Code** that shows you what Claude is doing — even when you've alt-tabbed away.

<p align="center">
  <img src="assets/state_ready.png" width="30%" alt="Ready state" />
  <img src="assets/state_working.png" width="30%" alt="Working state" />
  <img src="assets/state_needs_you.png" width="30%" alt="Needs you state" />
</p>

## What it does

- **Ready** — green spark, idle and waiting for your next prompt
- **Working** — terracotta spark twinkles with whimsical labels ("Ruminating…", "Pondering…", "Caramelizing…") and a live elapsed timer
- **Needs you** — amber spark, permission prompt or input needed (+ attention pulse + system chime)

The pill **auto-hides when you're in your IDE/terminal** (you can already see Claude there) and **fades back in when you alt-tab away**. Perfect for when you're browsing, in Discord, watching a video — you never lose track of Claude's status.

### Multi-session support

Running Claude Code in multiple projects? The pill stacks one row per active session, most urgent on top. Click a row to jump straight to that session's window.

## Requirements

- **Windows 10/11**
- **Python 3.10+** (Microsoft Store Python or standard python.org install both work)
- **Claude Code** with hooks enabled (the pill reads hook events to track status)

## Installation

### 1. Install Python dependencies

```bash
pip install PySide6 psutil pywin32 pillow pypresence
```

### 2. Clone or download this repo

```bash
git clone https://github.com/yourusername/claude-indicator.git
cd claude-indicator
```

(Or download the ZIP and extract it anywhere.)

### 3. Install the Claude Code hooks

The indicator works by reading events from Claude Code's hook system. Run the installer:

```bash
python install.py
```

This adds hooks to your `~/.claude/settings.json` for:
- `SessionStart`, `SessionEnd` — track when conversations begin/end
- `UserPromptSubmit`, `Stop` — detect working vs idle
- `Notification` — catch permission prompts
- `PreToolUse`, `PostToolUse` — fine-grained status updates

**Note:** You only need to run `install.py` once. The hooks survive across Claude Code updates.

### 4. Launch the indicator

```bash
python indicator.py
```

Or for a background launch (no console window):

```bash
pythonw indicator.py
```

The pill appears in the top-right corner of your screen. **Restart any already-open Claude Code sessions** so they pick up the new hooks — sessions started before the hooks were installed won't send events.

## Configuration

Edit `config.json` to customize:

```json
{
  "hide_on_processes": [
    "Code.exe",
    "cursor.exe", 
    "Kiro.exe",
    "WindowsTerminal.exe",
    "wt.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe"
  ],
  "position": [1792, 48],
  "margin": 16,
  "sound_on_needs_you": true
}
```

- **`hide_on_processes`** — list of exe names where the pill auto-hides (your IDE/terminal apps)
- **`position`** — `[x, y]` screen coords; set automatically when you drag the pill, or `null` to reset to top-right
- **`margin`** — distance in pixels from screen edge when auto-positioned
- **`sound_on_needs_you`** — play a chime when Claude needs permission (`true` or `false`)

The pill auto-reloads `config.json` on every status check (10 times/second), so changes apply immediately.

## Usage

### Normal workflow

1. Launch `indicator.py` (once per Windows session, or add it to your startup apps)
2. Start Claude Code and work normally
3. Alt-tab away — the pill shows Claude's status live
4. When it turns amber "Needs you", jump back to approve/respond
5. Click a row to focus that session's window instantly

### Drag to reposition

Click and drag the pill anywhere on screen. Your position is saved to `config.json` automatically.

### Multiple Claude sessions

Open Claude Code in different projects (different terminals/windows). The pill shows one row per session, most urgent on top. Each row displays:
- Status spark (color + animation)
- Label + elapsed time
- Project folder name (when idle)

Click a row to bring that session's IDE/terminal to the front.

## Autostart on Windows login

To launch the indicator automatically when you log in:

1. Press `Win+R`, type `shell:startup`, press Enter
2. Create a shortcut in that folder pointing to:
   ```
   C:\Path\To\Python\pythonw.exe C:\Path\To\claude-indicator\indicator.py
   ```
   (Replace paths with your actual Python and repo locations)

Or use Task Scheduler for more control (run minimized, delay start, etc.).

## Troubleshooting

### The pill stays green even when Claude is working

**Cause:** Your Claude Code session was started *before* you ran `install.py`, so it's not firing hooks.

**Fix:** Close Claude Code completely (all terminal windows running `claude` or `claude-code`) and restart. New sessions will pick up the hooks.

### The pill never appears

1. Check that `indicator.py` is running (look for `python.exe` or `pythonw.exe` with `indicator.py` in Task Manager)
2. Run `python indicator.py` (not `pythonw`) to see error output in the console
3. Make sure dependencies are installed: `pip list | findstr "PySide6 psutil pywin32"`

### "Needs you" shows up after I already answered

**Cause:** You're looking at a *different* Claude Code session that legitimately needs permission, or the session that just finished has a stale status file.

**Fix:** Check which project name is shown in that row — it tells you which session is waiting. Click the row to jump to it. Stale sessions auto-expire after 10 minutes of silence.

### Multi-session: one row is stuck on "Working"

**Cause:** The terminal running that Claude Code was killed without a clean exit, so the `SessionEnd` hook never fired.

**Fix:** The pill auto-detects this after 10 minutes of silence and treats it as idle. Or restart the indicator to force a fresh scan: close `indicator.py` and relaunch.

## How it works

1. **Hooks** — `hook_handler.py` is registered in Claude Code's `settings.json` and runs on every hook event (prompt submitted, tool started, notification shown, etc.). Each event writes a tiny status file to `runtime/sessions/<session-id>.json`.

2. **Indicator** — `indicator.py` polls `runtime/sessions/` 10 times per second, aggregates status across all active sessions, and renders the pill with Qt. It hides when your IDE/terminal is focused (checks the foreground window process name) and shows when you're elsewhere.

3. **No network, no cloud** — everything is local. The indicator reads session files written by hooks on your machine. No telemetry, no external dependencies.

## Customization

Want to tweak the look or behavior? Everything is in `indicator.py`:

- **Colors** — lines 38-46: `CREAM`, `TERRACOTTA`, `GREEN`, `AMBER`
- **Whimsical words** — lines 51-56: `WORKING_WORDS` list
- **Twinkle speed** — line 334: `self._phase += 0.35` (higher = faster morph)
- **Rotation speed** — line 333: `self._spin = (self._spin + 1.2) % 360` (higher = faster spin)
- **Row height / pill width** — lines 48-50: `ROW_H`, `PILL_W`
- **Poll rate** — line 59: `POLL_MS = 100` (100ms = 10Hz)

All painting is custom Qt code, so colors, shapes, animations, and layout are fully under your control.

## Uninstall

To remove the hooks from Claude Code:

1. Open `~/.claude/settings.json` (or `%USERPROFILE%\.claude\settings.json` on Windows)
2. Delete the `"hooks"` section (or just the `claude_indicator` entries)
3. Delete the `claude-indicator` folder

Claude Code continues working normally — hooks are purely observational, they don't change Claude's behavior.

## Credits

Built with love for the Claude Code community. Designed to match Anthropic's warm aesthetic and Claude's whimsical personality.

## License

MIT — do whatever you want with it. If you improve it, PRs are welcome!
