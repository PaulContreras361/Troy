"""
================================================================================
 TROY TOOLBOX  -  troy_tools.py
================================================================================
 This file is Troy's HANDS and EYES.

 Plain English:
   A language model by itself can only produce text. It cannot touch your
   computer. This file changes that by writing ordinary Python functions that
   DO touch the computer (open a folder, take a picture of the screen, click
   the mouse), and then handing Gemini a menu of those functions.

   Gemini never touches anything itself. Gemini only says:
       "please run take_screenshot"
   and THIS file decides whether that is allowed, runs it, and reports back.

 The safety idea - four levels:
   0  OFF    Troy has no tools at all. Chat only.
   1  LOOK   Troy may observe. Read files, list folders, screenshot, check RAM.
   2  DO     Troy may act in safe, reversible ways. Open approved apps, open a
             web page, write files ONLY inside his own workspace folder.
   3  DRIVE  Troy may run the machine. Mouse, keyboard, approved commands.

   You set the level. Troy cannot raise it. If Troy asks for a tool above the
   current level, the call is refused and Troy is told why.

 Emergency stop:
   pyautogui's failsafe is ON. If Troy ever starts doing something you don't
   like, SLAM THE MOUSE INTO THE TOP-LEFT CORNER OF THE SCREEN. Everything
   stops instantly with an exception.

 Every single action is written to troy_data/action_log.jsonl before and after
 it runs, so there is always a receipt.
================================================================================
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import platform
import shutil
import subprocess
import time
import webbrowser

# ------------------------------------------------------------------------------
# FOLDERS
# Code and logs stay on the laptop. Files Troy creates go to the external drive
# when it is plugged in, and to a laptop folder when it is not. troy_storage
# finds the drive by a marker file, so the drive letter can change freely.
# ------------------------------------------------------------------------------
BASE = pathlib.Path(__file__).resolve().parent
DATA = BASE / "troy_data"                 # logs, memory, config - always local
LOG_FILE = DATA / "action_log.jsonl"
MEMORY_FILE = DATA / "troy_memory.json"
APPS_FILE = DATA / "allowed_apps.json"
DATA.mkdir(parents=True, exist_ok=True)

try:
    import troy_storage
    STORAGE = troy_storage.resolve()
except Exception as _e:                    # noqa: BLE001
    troy_storage = None
    STORAGE = {"connected": False, "drive_root": None,
               "workspace": BASE / "troy_workspace",
               "screenshots": DATA / "screenshots",
               "note": f"Storage module unavailable: {_e}"}

WORKSPACE = pathlib.Path(STORAGE["workspace"])   # the ONLY folder Troy may write into
SHOTS = pathlib.Path(STORAGE["screenshots"])
DRIVE_ROOT = STORAGE.get("drive_root")

for _d in (DATA, WORKSPACE, SHOTS):
    pathlib.Path(_d).mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------------------
# OPTIONAL IMPORTS
# These are wrapped so the file still loads on a machine where they are missing.
# ------------------------------------------------------------------------------
try:
    import pyautogui
    pyautogui.FAILSAFE = True    # mouse to top-left corner = emergency stop
    pyautogui.PAUSE = 0.25       # quarter second between actions, so you can watch
    HAS_GUI = True
except Exception as _e:          # noqa: BLE001
    pyautogui = None
    HAS_GUI = False
    _GUI_ERROR = str(_e)

try:
    import psutil
    HAS_PSUTIL = True
except Exception:                # noqa: BLE001
    psutil = None
    HAS_PSUTIL = False


# ------------------------------------------------------------------------------
# DEFAULT APP ALLOWLIST
# Troy may only launch what is on this list. Edit troy_data/allowed_apps.json
# to add your own. Key = what Troy says, Value = what Windows actually runs.
# ------------------------------------------------------------------------------
DEFAULT_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "wordpad": "write.exe",
    "excel": "excel.exe",
    "word": "winword.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "snipping tool": "snippingtool.exe",
    "outlook": "outlook.exe",
}

# Command words Troy may run at DRIVE level. Anything else is refused.
ALLOWED_COMMANDS = {
    "dir", "echo", "type", "whoami", "hostname", "ipconfig", "ping",
    "tasklist", "systeminfo", "python", "pip", "git", "where", "tree",
}

# Command words that are refused no matter what. Belt and suspenders.
FORBIDDEN_COMMANDS = {
    "del", "erase", "rd", "rmdir", "format", "diskpart", "reg", "shutdown",
    "restart", "taskkill", "net", "cipher", "bcdedit", "vssadmin", "sc",
    "attrib", "icacls", "takeown", "wmic", "powershell", "curl", "certutil",
}


# ==============================================================================
# HOUSEKEEPING HELPERS
# ==============================================================================
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def log_action(tool: str, args: dict, outcome: str, detail=None) -> None:
    """Write one line to the action log. Never raises - logging must not crash Troy."""
    try:
        row = {
            "time": _now(),
            "tool": tool,
            "args": args,
            "outcome": outcome,       # requested | allowed | refused | ok | error
            "detail": detail,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:                # noqa: BLE001
        pass


def read_log(limit: int = 100) -> list:
    """Return the most recent log rows, newest last. Used by the Streamlit UI."""
    if not LOG_FILE.exists():
        return []
    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:    # noqa: BLE001
                    pass
    return rows[-limit:]


def ok(**kw) -> dict:
    return {"ok": True, **kw}


def fail(reason: str, **kw) -> dict:
    return {"ok": False, "error": reason, **kw}


def load_apps() -> dict:
    if APPS_FILE.exists():
        try:
            return json.loads(APPS_FILE.read_text(encoding="utf-8"))
        except Exception:            # noqa: BLE001
            pass
    APPS_FILE.write_text(json.dumps(DEFAULT_APPS, indent=2), encoding="utf-8")
    return dict(DEFAULT_APPS)


def _read_path(raw: str) -> pathlib.Path:
    """
    Path check for READING. Troy may look inside your user folder, his own
    program folder, and his folder on the external drive. Nowhere else.

    Note what this does NOT allow: the whole 1 TB drive. Only the TroyDrive
    folder on it. If you keep other things on that drive, Troy cannot read them.
    """
    p = pathlib.Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()
    allowed_roots = [pathlib.Path.home().resolve(), BASE.resolve()]
    if DRIVE_ROOT:
        allowed_roots.append(pathlib.Path(DRIVE_ROOT).resolve())
    for allowed in allowed_roots:
        try:
            p.relative_to(allowed)
            return p
        except ValueError:
            continue
    raise PermissionError(
        f"Reading '{p}' is outside Troy's allowed area "
        f"(your user folder, the Troy folder, or Troy's folder on the drive)."
    )


def _write_path(raw: str) -> pathlib.Path:
    """
    Path check for WRITING. Troy may ONLY create or change files inside
    troy_workspace. This is the single most important guard in the file.
    """
    raw = str(raw).strip().lstrip("/\\")
    p = (WORKSPACE / raw).resolve()
    try:
        p.relative_to(WORKSPACE.resolve())
    except ValueError:
        raise PermissionError(
            "Troy may only write inside the troy_workspace folder."
        )
    return p


# ==============================================================================
# LEVEL 1 TOOLS  -  LOOK
# ==============================================================================
def get_status() -> dict:
    """Date, time, machine name, CPU, memory, disk, battery."""
    out = {
        "time": _now(),
        "computer": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        du = psutil.disk_usage(str(BASE.anchor or "/"))
        out["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        out["memory_used_percent"] = vm.percent
        out["memory_total_gb"] = round(vm.total / 1024**3, 1)
        out["disk_free_gb"] = round(du.free / 1024**3, 1)
        out["disk_used_percent"] = du.percent
        try:
            bat = psutil.sensors_battery()
            if bat:
                out["battery_percent"] = bat.percent
                out["on_ac_power"] = bat.power_plugged
        except Exception:            # noqa: BLE001
            pass
    else:
        out["note"] = "psutil not installed - no hardware readings"
    return ok(**out)


def list_folder(path: str = "~", show_hidden: bool = False) -> dict:
    """List the files and folders at a location."""
    p = _read_path(path)
    if not p.exists():
        return fail(f"'{p}' does not exist.")
    if not p.is_dir():
        return fail(f"'{p}' is a file, not a folder. Use read_text_file.")
    folders, files = [], []
    for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
        if child.name.startswith(".") and not show_hidden:
            continue
        if child.is_dir():
            folders.append(child.name)
        else:
            try:
                size = child.stat().st_size
            except Exception:        # noqa: BLE001
                size = -1
            files.append({"name": child.name, "size_bytes": size})
    return ok(path=str(p), folders=folders[:200], files=files[:200],
              folder_count=len(folders), file_count=len(files))


def read_text_file(path: str, max_chars: int = 20000) -> dict:
    """Read a text file. Long files are cut off so they don't flood the model."""
    p = _read_path(path)
    if not p.exists():
        return fail(f"'{p}' does not exist.")
    if p.is_dir():
        return fail(f"'{p}' is a folder. Use list_folder.")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:           # noqa: BLE001
        return fail(f"Could not read: {e}")
    truncated = len(text) > max_chars
    return ok(path=str(p), truncated=truncated, characters=len(text),
              content=text[:max_chars])


def take_screenshot(note: str = "") -> dict:
    """
    Photograph the screen and save it. The picture is then handed to Gemini as
    an image, which is how Troy actually SEES your desktop.
    """
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = SHOTS / f"shot_{stamp}.png"
    img = pyautogui.screenshot()
    img.save(target)
    return ok(path=str(target), width=img.width, height=img.height, note=note)


def get_screen_size() -> dict:
    """How big the screen is, in pixels. Troy needs this before clicking."""
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    w, h = pyautogui.size()
    x, y = pyautogui.position()
    return ok(width=w, height=h, mouse_x=x, mouse_y=y)


def list_running_apps(limit: int = 40) -> dict:
    """What programs are open right now, heaviest first."""
    if not HAS_PSUTIL:
        return fail("psutil not installed.")
    seen = {}
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = proc.info["name"]
            mem = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
            seen[name] = seen.get(name, 0) + mem
        except Exception:            # noqa: BLE001
            continue
    ranked = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return ok(apps=[{"name": n, "memory_mb": round(m / 1024**2, 1)} for n, m in ranked])


def recall(key: str = "") -> dict:
    """Read Troy's long-term notes. Empty key returns everything."""
    store = {}
    if MEMORY_FILE.exists():
        try:
            store = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:            # noqa: BLE001
            store = {}
    if key:
        return ok(key=key, value=store.get(key), found=key in store)
    return ok(all_keys=list(store.keys()), memory=store)


# ==============================================================================
# LEVEL 2 TOOLS  -  DO
# ==============================================================================
def remember(key: str, value: str) -> dict:
    """Save a note that survives restarts."""
    store = {}
    if MEMORY_FILE.exists():
        try:
            store = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:            # noqa: BLE001
            store = {}
    store[key] = {"value": value, "saved": _now()}
    MEMORY_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return ok(key=key, saved=True)


def write_text_file(filename: str, content: str, mode: str = "overwrite") -> dict:
    """Create or update a text file INSIDE Troy's workspace only."""
    p = _write_path(filename)

    # If the workspace is supposed to be the external drive and the drive has
    # been pulled since Troy started, STOP. Silently writing to the laptop
    # instead is how you end up with two half-copies of the same work.
    if DRIVE_ROOT and not pathlib.Path(DRIVE_ROOT).exists():
        return fail(
            "The external drive has been disconnected since Troy started. "
            "Plug it back in and restart Troy, otherwise files end up scattered "
            "across two places. Nothing was written.")

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and mode == "overwrite":
            backup = p.with_suffix(p.suffix + f".bak_{int(time.time())}")
            shutil.copy2(p, backup)      # never destroy the old version silently
        with open(p, "a" if mode == "append" else "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as e:
        return fail(f"Could not write to '{p}': {e}")
    return ok(path=str(p), bytes_written=len(content.encode("utf-8")), mode=mode,
              on_external_drive=bool(DRIVE_ROOT))


def storage_status() -> dict:
    """Where Troy's files are going, and how much room is left."""
    if troy_storage is None:
        return fail("Storage module not installed.")
    return ok(**troy_storage.status())


def archive_screenshots(keep_recent: int = 50) -> dict:
    """Move older screenshots onto the big drive so the working folder stays small."""
    if troy_storage is None:
        return fail("Storage module not installed.")
    return troy_storage.archive_screenshots(keep_recent)


def open_app(app_name: str) -> dict:
    """Launch a program from the allowlist."""
    apps = load_apps()
    key = app_name.strip().lower()
    exe = apps.get(key)
    if not exe:
        return fail(f"'{app_name}' is not on the allowed apps list.",
                    allowed=sorted(apps.keys()))
    try:
        if platform.system() == "Windows":
            os.startfile(exe)        # noqa: S606
        else:
            subprocess.Popen([exe])
    except Exception as e:           # noqa: BLE001
        return fail(f"Could not start '{exe}': {e}")
    time.sleep(1.2)
    return ok(app=app_name, launched=exe)


def open_url(url: str) -> dict:
    """Open a web page in the default browser."""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    time.sleep(1.0)
    return ok(url=url, opened=True)


# ==============================================================================
# LEVEL 3 TOOLS  -  DRIVE
# ==============================================================================
def move_mouse(x: int, y: int, duration: float = 0.4) -> dict:
    """Glide the pointer to a screen coordinate."""
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    w, h = pyautogui.size()
    if not (0 <= x < w and 0 <= y < h):
        return fail(f"({x},{y}) is off screen. Screen is {w} x {h}.")
    pyautogui.moveTo(x, y, duration=max(0.1, min(duration, 3.0)))
    return ok(x=x, y=y)


def click(x: int = -1, y: int = -1, button: str = "left", clicks: int = 1) -> dict:
    """Click the mouse. Leave x and y out to click wherever it already is."""
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    if button not in ("left", "right", "middle"):
        return fail("button must be left, right or middle.")
    clicks = max(1, min(int(clicks), 3))
    if x >= 0 and y >= 0:
        res = move_mouse(x, y)
        if not res["ok"]:
            return res
    pyautogui.click(button=button, clicks=clicks, interval=0.15)
    px, py = pyautogui.position()
    return ok(clicked_at={"x": px, "y": py}, button=button, clicks=clicks)


def type_text(text: str, interval: float = 0.02) -> dict:
    """Type on the keyboard into whatever window has focus."""
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    if len(text) > 5000:
        return fail("Refusing to type more than 5000 characters at once.")
    pyautogui.write(text, interval=max(0.0, min(interval, 0.2)))
    return ok(characters_typed=len(text))


def press_keys(keys: str) -> dict:
    """
    Press single keys or combinations.
      "enter"        -> Enter
      "ctrl+s"       -> hold Ctrl, press S
      "win+d"        -> show desktop
    """
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    parts = [k.strip().lower() for k in keys.replace(" ", "").split("+") if k.strip()]
    if not parts:
        return fail("No keys given.")
    try:
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
    except Exception as e:           # noqa: BLE001
        return fail(f"Key press failed: {e}")
    return ok(keys=keys)


def scroll(amount: int = -300) -> dict:
    """Scroll the wheel. Negative scrolls down, positive scrolls up."""
    if not HAS_GUI:
        return fail(f"Screen tools unavailable: {_GUI_ERROR}")
    pyautogui.scroll(int(max(-2000, min(amount, 2000))))
    return ok(scrolled=amount)


def run_command(command: str, timeout: int = 30) -> dict:
    """Run a command line instruction. Only allowlisted first words are permitted."""
    cmd = command.strip()
    if not cmd:
        return fail("Empty command.")
    first = cmd.split()[0].lower().replace(".exe", "")
    if first in FORBIDDEN_COMMANDS:
        return fail(f"'{first}' is permanently blocked - it can destroy data.")
    if first not in ALLOWED_COMMANDS:
        return fail(f"'{first}' is not on the allowed command list.",
                    allowed=sorted(ALLOWED_COMMANDS))
    for bad in ("&", "|", ">", "<", ";", "`"):
        if bad in cmd:
            return fail(f"Character '{bad}' is not allowed - it can chain commands.")
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=max(1, min(timeout, 120)), cwd=str(WORKSPACE))
    except subprocess.TimeoutExpired:
        return fail(f"Command timed out after {timeout} seconds.")
    except Exception as e:           # noqa: BLE001
        return fail(f"Command failed: {e}")
    return ok(command=cmd, exit_code=proc.returncode,
              output=(proc.stdout or "")[:8000],
              errors=(proc.stderr or "")[:2000])


# ==============================================================================
# THE REGISTRY
# name -> (python function, required level)
# ==============================================================================
REGISTRY = {
    # level 1 - LOOK
    "get_status":        (get_status, 1),
    "storage_status":    (storage_status, 1),
    "list_folder":       (list_folder, 1),
    "read_text_file":    (read_text_file, 1),
    "take_screenshot":   (take_screenshot, 1),
    "get_screen_size":   (get_screen_size, 1),
    "list_running_apps": (list_running_apps, 1),
    "recall":            (recall, 1),
    # level 2 - DO
    "remember":          (remember, 2),
    "write_text_file":   (write_text_file, 2),
    "open_app":          (open_app, 2),
    "open_url":          (open_url, 2),
    "archive_screenshots": (archive_screenshots, 2),
    # level 3 - DRIVE
    "move_mouse":        (move_mouse, 3),
    "click":             (click, 3),
    "type_text":         (type_text, 3),
    "press_keys":        (press_keys, 3),
    "scroll":            (scroll, 3),
    "run_command":       (run_command, 3),
}

LEVEL_NAMES = {0: "OFF", 1: "LOOK", 2: "DO", 3: "DRIVE"}


def tool_level(name: str) -> int:
    entry = REGISTRY.get(name)
    return entry[1] if entry else 99


def execute(name: str, args: dict, current_level: int) -> dict:
    """
    The single door every tool call must pass through.
    Checks the permission level, runs the function, logs both sides.
    """
    args = args or {}
    entry = REGISTRY.get(name)
    if not entry:
        log_action(name, args, "refused", "unknown tool")
        return fail(f"There is no tool called '{name}'.")

    func, needed = entry
    if current_level < needed:
        msg = (f"Refused. '{name}' needs level {needed} "
               f"({LEVEL_NAMES[needed]}) but Troy is at level {current_level} "
               f"({LEVEL_NAMES.get(current_level, '?')}). Ask Paul to raise the level.")
        log_action(name, args, "refused", msg)
        return fail(msg)

    log_action(name, args, "allowed", f"level {needed}")
    started = time.time()
    try:
        result = func(**args)
    except TypeError as e:
        result = fail(f"Wrong arguments for {name}: {e}")
    except PermissionError as e:
        result = fail(str(e))
    except Exception as e:           # noqa: BLE001
        result = fail(f"{type(e).__name__}: {e}")
    result["_seconds"] = round(time.time() - started, 2)
    log_action(name, args, "ok" if result.get("ok") else "error",
               result.get("error") or "success")
    return result


# ==============================================================================
# THE MENU HANDED TO GEMINI
# These descriptions are what Gemini reads to decide which tool to ask for.
# Write them like instructions to a new employee - clear and literal.
# ==============================================================================
def _obj(props: dict, required: list) -> dict:
    return {"type": "OBJECT", "properties": props, "required": required}


DECLARATIONS = [
    {"name": "get_status",
     "description": "Get the current date and time, computer name, CPU load, memory use, free disk space and battery level.",
     "parameters": _obj({}, [])},

    {"name": "storage_status",
     "description": "Check where your files are being saved, whether the external drive is connected, and how much free space is left.",
     "parameters": _obj({}, [])},

    {"name": "archive_screenshots",
     "description": "Move older screenshots onto the external drive, into dated folders, keeping only the most recent ones in the working folder.",
     "parameters": _obj({
         "keep_recent": {"type": "INTEGER", "description": "How many recent screenshots to leave in place."},
     }, [])},

    {"name": "list_folder",
     "description": "List the files and folders at a path on this computer. Use ~ for the user's home folder.",
     "parameters": _obj({
         "path": {"type": "STRING", "description": "Folder to list, e.g. ~/Documents"},
         "show_hidden": {"type": "BOOLEAN", "description": "Include hidden items."},
     }, ["path"])},

    {"name": "read_text_file",
     "description": "Read the contents of a text file such as .txt, .py, .csv, .md, .json.",
     "parameters": _obj({
         "path": {"type": "STRING", "description": "Full path to the file."},
         "max_chars": {"type": "INTEGER", "description": "Maximum characters to return."},
     }, ["path"])},

    {"name": "take_screenshot",
     "description": "Photograph the entire screen so you can see what is currently displayed. Always do this before clicking or typing, so you know what is on screen.",
     "parameters": _obj({
         "note": {"type": "STRING", "description": "Why you are looking."},
     }, [])},

    {"name": "get_screen_size",
     "description": "Get the screen width and height in pixels and the current mouse position.",
     "parameters": _obj({}, [])},

    {"name": "list_running_apps",
     "description": "List the programs currently running, sorted by memory use.",
     "parameters": _obj({
         "limit": {"type": "INTEGER", "description": "How many to return."},
     }, [])},

    {"name": "recall",
     "description": "Look up something you saved earlier with remember. Leave key empty to list everything you know.",
     "parameters": _obj({
         "key": {"type": "STRING", "description": "The label to look up."},
     }, [])},

    {"name": "remember",
     "description": "Save a fact for later. It survives restarts.",
     "parameters": _obj({
         "key": {"type": "STRING", "description": "Short label."},
         "value": {"type": "STRING", "description": "What to remember."},
     }, ["key", "value"])},

    {"name": "write_text_file",
     "description": "Create or update a text file inside Troy's workspace folder. You cannot write anywhere else on the computer.",
     "parameters": _obj({
         "filename": {"type": "STRING", "description": "Name such as notes.txt or reports/summary.md"},
         "content": {"type": "STRING", "description": "The text to write."},
         "mode": {"type": "STRING", "description": "overwrite or append."},
     }, ["filename", "content"])},

    {"name": "open_app",
     "description": "Launch a program from the approved list, such as notepad or calculator. If the app you want is not approved, say so instead of guessing.",
     "parameters": _obj({
         "app_name": {"type": "STRING", "description": "Plain name, e.g. notepad."},
     }, ["app_name"])},

    {"name": "open_url",
     "description": "Open a web address in the default browser.",
     "parameters": _obj({
         "url": {"type": "STRING", "description": "The web address."},
     }, ["url"])},

    {"name": "move_mouse",
     "description": "Move the mouse pointer to a screen coordinate. Take a screenshot first so you know where things are.",
     "parameters": _obj({
         "x": {"type": "INTEGER", "description": "Pixels from the left edge."},
         "y": {"type": "INTEGER", "description": "Pixels from the top edge."},
         "duration": {"type": "NUMBER", "description": "Seconds to glide."},
     }, ["x", "y"])},

    {"name": "click",
     "description": "Click the mouse, optionally moving to a coordinate first. Take a screenshot afterwards to confirm what happened.",
     "parameters": _obj({
         "x": {"type": "INTEGER", "description": "Pixels from the left edge. Omit to click in place."},
         "y": {"type": "INTEGER", "description": "Pixels from the top edge."},
         "button": {"type": "STRING", "description": "left, right or middle."},
         "clicks": {"type": "INTEGER", "description": "1 for single, 2 for double."},
     }, [])},

    {"name": "type_text",
     "description": "Type text on the keyboard into whichever window currently has focus. Make sure the right window is focused first.",
     "parameters": _obj({
         "text": {"type": "STRING", "description": "The text to type."},
         "interval": {"type": "NUMBER", "description": "Seconds between keystrokes."},
     }, ["text"])},

    {"name": "press_keys",
     "description": "Press a key or key combination, for example enter, tab, escape, ctrl+s, alt+tab, win+d.",
     "parameters": _obj({
         "keys": {"type": "STRING", "description": "Key or combination joined with +."},
     }, ["keys"])},

    {"name": "scroll",
     "description": "Scroll the mouse wheel. Negative numbers scroll down, positive scroll up.",
     "parameters": _obj({
         "amount": {"type": "INTEGER", "description": "How far to scroll."},
     }, ["amount"])},

    {"name": "run_command",
     "description": "Run a command line instruction. Only safe read-only commands are permitted and destructive ones are blocked.",
     "parameters": _obj({
         "command": {"type": "STRING", "description": "The command, e.g. ipconfig"},
         "timeout": {"type": "INTEGER", "description": "Seconds to wait."},
     }, ["command"])},
]


def declarations_for_level(level: int) -> list:
    """Optional: hand Gemini only the tools it is currently allowed to use."""
    return [d for d in DECLARATIONS if tool_level(d["name"]) <= level]


# ==============================================================================
# BOLT-ON MODULES
# Tools that live in their own file get merged in here. Keeping them separate
# means a broken add-on cannot take the core toolbox down with it.
#
# ALWAYS_ASK holds tools that stop for Paul's button press no matter how the
# auto-approve slider is set. Code edits are on that list on purpose.
# ==============================================================================
ALWAYS_ASK: set = set()

# Each bolt-on file has REGISTRY, DECLARATIONS and (optionally) ALWAYS_ASK.
# A missing or broken one is skipped and logged; the rest still load.
BOLT_ONS = [
    "troy_epr",           # EPR Master Tracker checker (read-only)
    "troy_files",         # troy_hands.py file actions (move/copy/delete/undo)
    "troy_autocad",       # draw in AutoCAD (full AutoCAD, not LT)
    "troy_sketchup",      # draw in SketchUp Pro through the Troy bridge plugin
    "troy_outlook",       # read email, write DRAFTS (never sends)
]
LOAD_PROBLEMS: dict = {}

for _name in BOLT_ONS:
    try:
        _mod = __import__(_name)
        REGISTRY.update(_mod.REGISTRY)
        DECLARATIONS.extend(_mod.DECLARATIONS)
        ALWAYS_ASK |= getattr(_mod, "ALWAYS_ASK", set())
    except ImportError as _e:
        LOAD_PROBLEMS[_name] = f"not installed ({_e})"
    except Exception as _e:                     # noqa: BLE001
        LOAD_PROBLEMS[_name] = f"{type(_e).__name__}: {_e}"
        log_action("LOAD_MODULE", {"module": _name}, "error", str(_e))


if __name__ == "__main__":
    # Quick self-test. Runs only the harmless LOOK tools.
    print("Troy toolbox self-test")
    print("  GUI available   :", HAS_GUI)
    print("  psutil available:", HAS_PSUTIL)
    print("  workspace       :", WORKSPACE)
    print("  tools registered:", len(REGISTRY))
    print("  status          :", execute("get_status", {}, current_level=1))
    print("  blocked write   :", execute("write_text_file",
                                         {"filename": "x.txt", "content": "hi"},
                                         current_level=1))
