"""
troy_hands.py  —  Rev 2
Troy's hands: safe file actions on Paul's laptop.

Standalone. Imports nothing from Troy's other files.

HOW EVERY ACTION WORKS
    move("a.txt", "Documents/Archive")              -> returns a PLAN, does nothing
    move("a.txt", "Documents/Archive", confirm=True) -> actually does it

Every answer starts with one word so Troy (and you) can read it fast:
    PLAN:     what would happen, nothing done yet
    DONE:     it happened
    REFUSED:  blocked on purpose (fence, name clash, not allowed)
    ERROR:    something went wrong while trying

WHAT CHANGED FROM REV 1 (the five bugs, plus two upgrades)
    1. undo() no longer gets stuck behind open/run. Open and run go to the
       audit log only. The undo list holds only things that can be undone.
    2. Undoing a copy sends the copy to troy_trash. Nothing is erased.
    3. Trash can't collide. Every deleted item gets its own random folder.
    4. run() only runs tasks from an allowlist, with shell=False.
       Add your own tasks in troy_tasks.json (see bottom of this file).
    5. find() has limits: max results, max seconds, max folder depth.
    6. Two logs: audit.jsonl (everything, never edited) and
       undo_stack.json (only undoable actions).
    7. undo() re-checks the files before acting. If something changed
       since the action, it refuses instead of guessing.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent          # the Troy folder
TRASH = ROOT / "troy_trash"
LOGS = ROOT / "troy_logs"
AUDIT_LOG = LOGS / "audit.jsonl"
UNDO_FILE = LOGS / "undo_stack.json"
TASKS_FILE = ROOT / "troy_tasks.json"

UNDO_KEEP = 200            # how many undoable actions to remember
RUN_TIMEOUT = 60           # seconds before a task is stopped

# Folder names that are never allowed, anywhere in the path
BLOCKED_PARTS = {
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "$recycle.bin", "system volume information", "recovery",
}


# ---------------------------------------------------------------------------
# The fence
# ---------------------------------------------------------------------------
def fence_roots():
    """Every folder Troy is allowed to work inside."""
    home = Path.home()
    roots = [ROOT]
    onedrive = os.environ.get("OneDrive")
    for name in ("Desktop", "Documents", "Downloads", "Pictures"):
        roots.append(home / name)
        roots.append(home / "OneDrive" / name)       # Paul's Documents live here
        if onedrive:
            roots.append(Path(onedrive) / name)
    if os.name == "nt":
        for letter in "DEFGH":
            drive = Path(f"{letter}:/")
            if drive.exists():
                roots.append(drive)
    out = []
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if r not in out:
            out.append(r)
    return out


def _inside(path, folder):
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _protected():
    """Folders Troy may work INSIDE but must never move or delete themselves."""
    return set(fence_roots()) | {TRASH.resolve(), LOGS.resolve()}


def _check(raw, must_exist=True, allow_trash=False):
    """
    Turn a path into a safe, fully resolved Path, or explain why not.
    Returns (Path, None) when okay, (None, reason) when refused.
    """
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path.home() / p
        p = p.resolve()                 # follows shortcuts and ".." tricks
    except (OSError, RuntimeError) as e:
        return None, f"can't read that path ({e})"

    if any(part.lower() in BLOCKED_PARTS for part in p.parts):
        return None, f"{p} is a system folder — Troy never touches those"

    if not any(_inside(p, r) for r in fence_roots()):
        return None, f"{p} is outside Troy's fence"

    if not allow_trash and (_inside(p, TRASH.resolve()) or _inside(p, LOGS.resolve())):
        return None, f"{p} is Troy's own trash/log area — use undo() instead"

    if must_exist and not p.exists():
        return None, f"{p} doesn't exist"

    return p, None


def _is_protected(p):
    return p in _protected()


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
def _now():
    return datetime.now().isoformat(timespec="seconds")


def _audit(action, result, **details):
    """Append one line to the audit log. This file is never edited."""
    LOGS.mkdir(parents=True, exist_ok=True)
    entry = {"time": _now(), "action": action, "result": result, **details}
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _load_undo():
    if not UNDO_FILE.exists():
        return []
    try:
        return json.loads(UNDO_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_undo(stack):
    """Write safely: temp file first, then swap it in (no half-written file)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    tmp = UNDO_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(stack[-UNDO_KEEP:], indent=1), encoding="utf-8")
    os.replace(tmp, UNDO_FILE)


def _push_undo(entry):
    stack = _load_undo()
    entry["time"] = _now()
    stack.append(entry)
    _save_undo(stack)


# ---------------------------------------------------------------------------
# Trash (bug 3 fix: every item gets its own random folder)
# ---------------------------------------------------------------------------
def _send_to_trash(p):
    slot = TRASH / f"{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:8]}"
    slot.mkdir(parents=True, exist_ok=False)
    dest = slot / p.name
    shutil.move(str(p), str(dest))
    return dest


def _kind(p):
    return "folder" if p.is_dir() else "file"


def _target(dst, src):
    """If dst is an existing folder, put src inside it. Otherwise dst is the new path."""
    d = Path(dst).expanduser()
    if not d.is_absolute():
        d = Path.home() / d
    if d.is_dir():
        d = d / src.name
    return d


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def move(src, dst, confirm=False):
    s, why = _check(src)
    if why:
        return f"REFUSED: {why}"
    if _is_protected(s):
        return f"REFUSED: {s} is a main folder — Troy won't move it"
    d, why = _check(_target(dst, s), must_exist=False)
    if why:
        return f"REFUSED: {why}"
    if d.exists():
        return f"REFUSED: {d} already exists — Troy won't overwrite"
    if _inside(d, s):
        return "REFUSED: can't move a folder inside itself"
    if not d.parent.exists():
        return f"REFUSED: destination folder {d.parent} doesn't exist"
    if not confirm:
        return f"PLAN: move {_kind(s)} {s}  →  {d}"
    try:
        shutil.move(str(s), str(d))
    except OSError as e:
        _audit("move", "error", src=str(s), dst=str(d), error=str(e))
        return f"ERROR: move failed ({e})"
    _push_undo({"action": "move", "src": str(s), "dst": str(d)})
    _audit("move", "done", src=str(s), dst=str(d))
    return f"DONE: moved {s.name} to {d}"


def rename(src, new_name, confirm=False):
    if not new_name or any(c in new_name for c in '\\/:*?"<>|'):
        return "REFUSED: new name can't be blank or contain \\ / : * ? \" < > |"
    s, why = _check(src)
    if why:
        return f"REFUSED: {why}"
    if _is_protected(s):
        return f"REFUSED: {s} is a main folder — Troy won't rename it"
    d = s.with_name(new_name)
    if d.exists():
        return f"REFUSED: {d} already exists"
    if not confirm:
        return f"PLAN: rename {s.name}  →  {new_name}  (in {s.parent})"
    try:
        s.rename(d)
    except OSError as e:
        _audit("rename", "error", src=str(s), dst=str(d), error=str(e))
        return f"ERROR: rename failed ({e})"
    _push_undo({"action": "rename", "src": str(s), "dst": str(d)})
    _audit("rename", "done", src=str(s), dst=str(d))
    return f"DONE: renamed to {new_name}"


def copy(src, dst, confirm=False):
    s, why = _check(src)
    if why:
        return f"REFUSED: {why}"
    d, why = _check(_target(dst, s), must_exist=False)
    if why:
        return f"REFUSED: {why}"
    if d.exists():
        return f"REFUSED: {d} already exists — Troy won't overwrite"
    if s.is_dir() and _inside(d, s):
        return "REFUSED: can't copy a folder inside itself"
    if not d.parent.exists():
        return f"REFUSED: destination folder {d.parent} doesn't exist"
    if not confirm:
        return f"PLAN: copy {_kind(s)} {s}  →  {d}"
    try:
        if s.is_dir():
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    except OSError as e:
        _audit("copy", "error", src=str(s), dst=str(d), error=str(e))
        return f"ERROR: copy failed ({e})"
    _push_undo({"action": "copy", "src": str(s), "dst": str(d)})
    _audit("copy", "done", src=str(s), dst=str(d))
    return f"DONE: copied {s.name} to {d}"


def delete(target, confirm=False):
    p, why = _check(target)
    if why:
        return f"REFUSED: {why}"
    if _is_protected(p):
        return f"REFUSED: {p} is a main folder — Troy won't delete it"
    if not confirm:
        return f"PLAN: send {_kind(p)} {p} to troy_trash (nothing is erased; undo() brings it back)"
    try:
        t = _send_to_trash(p)
    except OSError as e:
        _audit("delete", "error", src=str(p), error=str(e))
        return f"ERROR: delete failed ({e})"
    _push_undo({"action": "delete", "src": str(p), "trash": str(t)})
    _audit("delete", "done", src=str(p), trash=str(t))
    return f"DONE: {p.name} is in troy_trash"


def make_folder(path, confirm=False):
    p, why = _check(path, must_exist=False)
    if why:
        return f"REFUSED: {why}"
    if p.exists():
        return f"REFUSED: {p} already exists"
    if not p.parent.exists():
        return f"REFUSED: parent folder {p.parent} doesn't exist"
    if not confirm:
        return f"PLAN: make new folder {p}"
    try:
        p.mkdir()
    except OSError as e:
        _audit("make_folder", "error", path=str(p), error=str(e))
        return f"ERROR: couldn't make folder ({e})"
    _push_undo({"action": "make_folder", "path": str(p)})
    _audit("make_folder", "done", path=str(p))
    return f"DONE: made folder {p}"


def open_file(path, confirm=False):
    """Opens a file with its normal program. Can't be undone, so audit log only."""
    p, why = _check(path)
    if why:
        return f"REFUSED: {why}"
    if p.suffix.lower() in {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".lnk"}:
        return f"REFUSED: {p.name} is a program — use run() with an allowlisted task"
    if not confirm:
        return f"PLAN: open {p} with its normal program"
    try:
        if os.name == "nt":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError as e:
        _audit("open", "error", path=str(p), error=str(e))
        return f"ERROR: couldn't open ({e})"
    _audit("open", "done", path=str(p))
    return f"DONE: opened {p.name}"


# ---------------------------------------------------------------------------
# run()  —  bug 4 fix: allowlist only, shell=False
# ---------------------------------------------------------------------------
def _builtin_tasks():
    py = sys.executable
    return {
        "python_version": {"cmd": [py, "--version"], "about": "show Python version"},
        "pip_list":       {"cmd": [py, "-m", "pip", "list"], "about": "list installed Python packages"},
        "git_status":     {"cmd": ["git", "status"], "cwd": str(ROOT), "about": "Troy's git status"},
        "git_log":        {"cmd": ["git", "log", "--oneline", "-10"], "cwd": str(ROOT), "about": "last 10 Troy commits"},
        "ollama_list":    {"cmd": ["ollama", "list"], "about": "local models installed"},
        "brain_test":     {"cmd": [py, "brain.py"], "cwd": str(ROOT), "about": "local brain self-test"},
        "hands_test":     {"cmd": [py, "troy_hands.py"], "cwd": str(ROOT), "about": "this file's self-test"},
    }


def tasks():
    """All allowed tasks: built-ins plus anything Paul adds in troy_tasks.json."""
    all_tasks = _builtin_tasks()
    if TASKS_FILE.exists():
        try:
            extra = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
            for name, t in extra.items():
                if isinstance(t, dict) and isinstance(t.get("cmd"), list) \
                        and all(isinstance(x, str) for x in t["cmd"]):
                    all_tasks[name] = t
        except (OSError, json.JSONDecodeError):
            pass
    return all_tasks


def list_tasks():
    lines = [f"  {n:<16} {t.get('about', ' '.join(t['cmd']))}" for n, t in sorted(tasks().items())]
    return "Allowed tasks:\n" + "\n".join(lines)


def run(task_name, confirm=False):
    t = tasks().get(task_name)
    if t is None:
        return f"REFUSED: '{task_name}' isn't on the allowlist. {list_tasks()}"
    cmd = t["cmd"]
    cwd = t.get("cwd") or str(ROOT)
    if not confirm:
        return f"PLAN: run task '{task_name}': {' '.join(cmd)}  (in {cwd})"
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=False, capture_output=True,
                           text=True, timeout=RUN_TIMEOUT)
    except FileNotFoundError:
        _audit("run", "error", task=task_name, error="program not found")
        return f"ERROR: '{cmd[0]}' isn't installed or isn't on PATH"
    except subprocess.TimeoutExpired:
        _audit("run", "error", task=task_name, error="timeout")
        return f"ERROR: '{task_name}' took over {RUN_TIMEOUT}s and was stopped"
    out = (r.stdout + r.stderr).strip()
    if len(out) > 4000:
        out = out[:4000] + "\n...(cut off)"
    _audit("run", "done", task=task_name, exit_code=r.returncode)
    return f"DONE: '{task_name}' finished (exit code {r.returncode})\n{out}"


# ---------------------------------------------------------------------------
# find()  —  bug 5 fix: limits on results, time, and depth
# ---------------------------------------------------------------------------
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "troy_trash", "troy_logs"}


def find(pattern, where="Documents", max_results=50, max_seconds=5, max_depth=6):
    """Find files whose name contains `pattern` (not case sensitive)."""
    base, why = _check(where)
    if why:
        return f"REFUSED: {why}"
    if not base.is_dir():
        return f"REFUSED: {base} isn't a folder"
    needle = pattern.lower()
    start = time.monotonic()
    base_depth = len(base.parts)
    hits, stopped = [], None
    for folder, dirs, files in os.walk(base):
        depth = len(Path(folder).parts) - base_depth
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and not d.startswith(".")
                   and d.lower() not in BLOCKED_PARTS] if depth < max_depth else []
        for name in dirs + files:
            if needle in name.lower():
                hits.append(str(Path(folder) / name))
                if len(hits) >= max_results:
                    stopped = f"stopped at {max_results} results"
                    break
        if stopped:
            break
        if time.monotonic() - start > max_seconds:
            stopped = f"stopped after {max_seconds} seconds"
            break
    if not hits:
        return f"DONE: nothing matching '{pattern}' in {base}" + (f" ({stopped})" if stopped else "")
    note = f"\n({stopped} — narrow the search for more)" if stopped else ""
    return f"DONE: {len(hits)} found in {base}\n" + "\n".join(hits) + note


# ---------------------------------------------------------------------------
# undo()  —  bugs 1, 2, and 7 fixed
# ---------------------------------------------------------------------------
def _undo_plan(e):
    a = e["action"]
    if a in ("move", "rename"):
        return f"put {Path(e['dst']).name} back at {e['src']}"
    if a == "copy":
        return f"send the copy {e['dst']} to troy_trash"
    if a == "delete":
        return f"bring {Path(e['src']).name} back from troy_trash to {e['src']}"
    if a == "make_folder":
        return f"remove folder {e['path']} (to troy_trash if it has anything in it)"
    return f"unknown action {a}"


def _revalidate(e):
    """Check the files are still where the log says. Returns a reason if not."""
    a = e["action"]
    if a in ("move", "rename"):
        now, why = _check(e["dst"])
        if why:
            return f"{e['dst']} isn't there any more ({why})"
        back, why = _check(e["src"], must_exist=False)
        if why:
            return why
        if back.exists():
            return f"something new is already at {back}"
    elif a == "copy":
        _, why = _check(e["dst"])
        if why:
            return f"the copy {e['dst']} isn't there any more"
    elif a == "delete":
        t = Path(e["trash"])
        if not t.exists():
            return f"the trashed item {t} is gone"
        back, why = _check(e["src"], must_exist=False)
        if why:
            return why
        if back.exists():
            return f"something new is already at {back}"
        if not back.parent.exists():
            return f"its old folder {back.parent} no longer exists"
    elif a == "make_folder":
        _, why = _check(e["path"])
        if why:
            return f"folder {e['path']} isn't there any more"
    else:
        return f"don't know how to undo '{a}'"
    return None


def undo(confirm=False, drop=False):
    """
    Undo the last undoable action.
    If it can't be undone safely (files changed since), it refuses.
    undo(drop=True, confirm=True) forgets that stuck entry so older ones can be undone.
    """
    stack = _load_undo()
    if not stack:
        return "DONE: nothing to undo"
    e = stack[-1]

    if drop:
        if not confirm:
            return f"PLAN: forget the last undo entry ({e['action']} at {e['time']}) without undoing it"
        stack.pop()
        _save_undo(stack)
        _audit("undo_drop", "done", entry=e)
        return f"DONE: forgot the {e['action']} entry. {len(stack)} left to undo."

    problem = _revalidate(e)
    if problem:
        return (f"REFUSED: can't safely undo the last {e['action']} — {problem}. "
                f"Use undo(drop=True, confirm=True) to skip it.")
    if not confirm:
        return f"PLAN: undo {e['action']} from {e['time']}: {_undo_plan(e)}"

    a = e["action"]
    try:
        if a in ("move", "rename"):
            shutil.move(e["dst"], e["src"])
        elif a == "copy":
            _send_to_trash(Path(e["dst"]))                  # bug 2: trash, not erase
        elif a == "delete":
            shutil.move(e["trash"], e["src"])
            try:
                Path(e["trash"]).parent.rmdir()             # clean the empty trash slot
            except OSError:
                pass
        elif a == "make_folder":
            p = Path(e["path"])
            if any(p.iterdir()):
                _send_to_trash(p)
            else:
                p.rmdir()
    except OSError as err:
        _audit("undo", "error", entry=e, error=str(err))
        return f"ERROR: undo failed ({err}) — entry kept so you can try again"

    stack.pop()
    _save_undo(stack)
    _audit("undo", "done", entry=e)
    return f"DONE: undid {a} — {_undo_plan(e)}"


# ---------------------------------------------------------------------------
# history()
# ---------------------------------------------------------------------------
def history(n=10):
    """Last n lines of the audit log, in plain English."""
    if not AUDIT_LOG.exists():
        return "No actions yet."
    lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        what = e.get("src") or e.get("path") or e.get("task") or \
            (e.get("entry") or {}).get("action", "")
        out.append(f"  {e['time']}  {e['action']:<11} {e['result']:<5}  {what}")
    return "Recent actions:\n" + "\n".join(out)


# ---------------------------------------------------------------------------
# Self-test: proves each of the five fixes
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    passed = failed = 0

    def check(label, ok):
        global passed, failed
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if ok:
            passed += 1
        else:
            failed += 1

    docs = Path.home() / "Documents"
    docs.mkdir(exist_ok=True)
    box = docs / f"troy_hands_test_{uuid.uuid4().hex[:6]}"
    box.mkdir()
    a = box / "report.txt"
    a.write_text("hello")
    print(f"Test folder: {box}\n")

    print("Plan first, then do:")
    check("plan does nothing", delete(a).startswith("PLAN") and a.exists())
    check("fence blocks System32", delete("C:/Windows/System32").startswith("REFUSED"))
    check("won't delete a main folder", delete(docs).startswith("REFUSED"))

    print("\nBug 1 — undo not blocked by run/open:")
    delete(a, confirm=True)
    run("python_version", confirm=True)            # audit only, not undo stack
    r = undo(confirm=True)
    check("undo reached the delete past the run", r.startswith("DONE") and a.exists())

    print("\nBug 2 — undoing a copy trashes it, doesn't erase it:")
    copy(a, box / "report_copy.txt", confirm=True)
    undo(confirm=True)
    in_trash = list(TRASH.rglob("report_copy.txt"))
    check("copy gone from folder", not (box / "report_copy.txt").exists())
    check("copy is in troy_trash", len(in_trash) > 0)

    print("\nBug 3 — same name deleted twice in one second:")
    b = box / "sub"
    b.mkdir()
    (b / "report.txt").write_text("second")
    delete(a, confirm=True)
    delete(b / "report.txt", confirm=True)
    undo(confirm=True)
    undo(confirm=True)
    check("both came back", a.read_text() == "hello" and (b / "report.txt").read_text() == "second")

    print("\nBug 4 — run() allowlist, shell=False:")
    check("unknown task refused", run("del /s C:\\").startswith("REFUSED"))
    check("allowed task runs", run("python_version", confirm=True).startswith("DONE"))

    print("\nBug 5 — find() has limits:")
    for i in range(30):
        (box / f"note_{i}.txt").write_text("x")
    r = find("note_", where=str(box), max_results=10)
    check("stops at max results", "stopped at 10" in r)

    print("\nUpgrade — undo re-checks before acting:")
    move(a, b / "moved.txt", confirm=True)
    (b / "moved.txt").unlink()                     # someone removes it behind Troy's back
    check("undo refuses stale entry", undo(confirm=True).startswith("REFUSED"))
    check("drop clears it", undo(drop=True, confirm=True).startswith("DONE"))

    shutil.rmtree(box)
    for p in TRASH.rglob("report_copy.txt"):
        shutil.rmtree(p.parent, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    print(history(5))
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------
# troy_tasks.json  —  how to add your own run() tasks (optional file)
# Put it in the Troy folder. Each command is a LIST of words, no shell tricks.
# {
#   "open_epr": {"cmd": ["C:/Program Files/Microsoft Office/root/Office16/EXCEL.EXE",
#                        "C:/Users/paulc/OneDrive/Documents/EPR Master Tracker.xlsx"],
#                "about": "open the EPR tracker in Excel"}
# }
# ---------------------------------------------------------------------------
