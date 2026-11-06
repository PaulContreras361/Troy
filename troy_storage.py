"""
================================================================================
 TROY STORAGE  -  troy_storage.py
================================================================================
 Where Troy keeps his stuff.

 THE PROBLEM WITH DRIVE LETTERS
 ------------------------------
 Windows assigns letters in plug-in order. Your drive is E: today. Plug in a
 phone or a camera card first tomorrow and the same drive becomes F:. Any code
 with "E:\\" written into it now points at nothing - or at the wrong device.

 THE FIX
 -------
 Troy does not look for a letter. He looks for a MARKER FILE:

     <drive>\\TroyDrive\\TROY_DRIVE.marker

 On startup he checks every drive letter from A to Z for that marker. Whichever
 drive has it IS the Troy drive, whatever letter Windows happened to give it.
 Unplug it, plug it into a different USB port, use a different computer - it
 still works, because the marker travels with the drive.

 WHAT GOES WHERE
 ---------------
   INTERNAL (your laptop)          EXTERNAL (the 1 TB drive)
   ------------------------        --------------------------------
   Troy's source code              workspace/     files Troy creates
   troy_data/ logs and memory      screenshots/   the screen history
   code_backups/ (the originals)   code_backups/  a second copy, off-machine
                                   projects/      big builds
                                   datasets/      large files

 Code stays internal ON PURPOSE. If the drive is unplugged, Troy still starts,
 still runs, and simply tells you the drive is missing. He never silently
 half-works.

 IF THE DRIVE IS ABSENT
 ----------------------
 Troy falls back to a folder on the laptop and says so loudly in the sidebar.
 He does not pretend the drive is there.
================================================================================
"""

from __future__ import annotations

import json
import pathlib
import shutil
import string

BASE = pathlib.Path(__file__).resolve().parent
DATA = BASE / "troy_data"
DATA.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA / "storage.json"
MARKER_NAME = "TROY_DRIVE.marker"
DRIVE_FOLDER = "TroyDrive"          # the folder created at the root of the drive

# The folders Troy expects to find on the drive
LAYOUT = ["workspace", "screenshots", "code_backups", "projects", "datasets"]

# Fallback location if the drive is not connected
INTERNAL_WORKSPACE = BASE / "troy_workspace"


# ------------------------------------------------------------------ config
def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:                            # noqa: BLE001
            pass
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ finding
def _has_marker(root: pathlib.Path) -> bool:
    try:
        return (root / MARKER_NAME).is_file()
    except Exception:                                # noqa: BLE001
        return False


def find_drive() -> pathlib.Path | None:
    """
    Locate the Troy drive. Tries the remembered path first (fast), then scans
    every drive letter for the marker file (reliable). Returns None if the
    drive is not connected.
    """
    cfg = _load_config()

    # 1. Did it stay where we last saw it?
    remembered = cfg.get("drive_root", "")
    if remembered:
        p = pathlib.Path(remembered)
        if _has_marker(p):
            return p

    # 2. Scan for the marker. This is what survives a letter change.
    for letter in string.ascii_uppercase:
        candidate = pathlib.Path(f"{letter}:/") / DRIVE_FOLDER
        if _has_marker(candidate):
            cfg["drive_root"] = str(candidate)
            _save_config(cfg)
            return candidate

    # 3. Also check Mac/Linux mount points, in case Troy ever moves house
    for base in ("/Volumes", "/media", "/mnt"):
        b = pathlib.Path(base)
        if not b.is_dir():
            continue
        try:
            for child in b.iterdir():
                candidate = child / DRIVE_FOLDER
                if _has_marker(candidate):
                    cfg["drive_root"] = str(candidate)
                    _save_config(cfg)
                    return candidate
        except Exception:                            # noqa: BLE001
            continue

    return None


# ------------------------------------------------------------------ setup
def setup_drive(drive_letter_or_path: str) -> dict:
    """
    One-time preparation of a drive. Creates TroyDrive\\ with the marker file
    and the folder layout. Safe to run again - it never deletes anything.
    """
    raw = str(drive_letter_or_path).strip()
    if len(raw) == 1 and raw.isalpha():
        raw = f"{raw.upper()}:/"

    root = pathlib.Path(raw)
    if not root.exists():
        return {"ok": False,
                "error": f"'{root}' does not exist. Is the drive plugged in?"}

    target = root if root.name == DRIVE_FOLDER else root / DRIVE_FOLDER
    try:
        target.mkdir(parents=True, exist_ok=True)
        for folder in LAYOUT:
            (target / folder).mkdir(parents=True, exist_ok=True)
        (target / MARKER_NAME).write_text(
            "This file tells Troy which drive is his.\n"
            "Do not delete or rename it. Troy finds this drive by looking for\n"
            "this file, which is why the drive letter can change freely.\n",
            encoding="utf-8")
    except PermissionError:
        return {"ok": False,
                "error": f"No permission to write to '{target}'. "
                         f"Is the drive read-only?"}
    except Exception as e:                           # noqa: BLE001
        return {"ok": False, "error": f"Could not set up '{target}': {e}"}

    cfg = _load_config()
    cfg["drive_root"] = str(target)
    _save_config(cfg)

    free = shutil.disk_usage(str(target)).free
    return {"ok": True, "drive_root": str(target),
            "folders_created": LAYOUT,
            "free_gb": round(free / 1024**3, 1)}


# ------------------------------------------------------------------ resolve
def resolve() -> dict:
    """
    Work out where everything lives right now. Called once when Troy starts.
    Always returns usable paths, connected drive or not.
    """
    drive = find_drive()

    if drive is None:
        INTERNAL_WORKSPACE.mkdir(parents=True, exist_ok=True)
        (DATA / "screenshots").mkdir(parents=True, exist_ok=True)
        return {
            "connected": False,
            "drive_root": None,
            "workspace": INTERNAL_WORKSPACE,
            "screenshots": DATA / "screenshots",
            "mirror_backups_to": None,
            "projects": INTERNAL_WORKSPACE / "projects",
            "datasets": INTERNAL_WORKSPACE / "datasets",
            "note": "External drive not found - using the laptop instead.",
        }

    for folder in LAYOUT:
        (drive / folder).mkdir(parents=True, exist_ok=True)

    return {
        "connected": True,
        "drive_root": drive,
        "workspace": drive / "workspace",
        "screenshots": drive / "screenshots",
        "mirror_backups_to": drive / "code_backups",
        "projects": drive / "projects",
        "datasets": drive / "datasets",
        "note": f"Using external drive at {drive}",
    }


def status() -> dict:
    """Human-readable report. Powers the sidebar and the storage_status tool."""
    info = resolve()
    out = {
        "connected": info["connected"],
        "location": str(info["drive_root"] or info["workspace"]),
        "workspace": str(info["workspace"]),
        "note": info["note"],
    }
    try:
        du = shutil.disk_usage(str(info["workspace"]))
        out["free_gb"] = round(du.free / 1024**3, 1)
        out["total_gb"] = round(du.total / 1024**3, 1)
        out["used_percent"] = round(du.used / du.total * 100, 1)
    except Exception:                                # noqa: BLE001
        pass

    if info["connected"]:
        counts = {}
        for folder in LAYOUT:
            p = info["drive_root"] / folder
            try:
                counts[folder] = sum(1 for _ in p.rglob("*") if _.is_file())
            except Exception:                        # noqa: BLE001
                counts[folder] = -1
        out["file_counts"] = counts
    return out


# ------------------------------------------------------------- housekeeping
def archive_screenshots(keep_recent: int = 50) -> dict:
    """
    Screenshots pile up fast - one per look. Keep the recent ones handy and
    move the rest into dated folders on the big drive, where 1 TB means you
    never have to think about it again.
    """
    info = resolve()
    shots = info["screenshots"]
    if not shots.exists():
        return {"ok": True, "moved": 0, "note": "No screenshots yet."}

    files = sorted(shots.glob("shot_*.png"), key=lambda f: f.stat().st_mtime,
                   reverse=True)
    old = files[keep_recent:]
    if not old:
        return {"ok": True, "moved": 0, "note": "Nothing old enough to archive."}

    if not info["connected"]:
        return {"ok": False,
                "error": "Drive not connected - nowhere to archive to."}

    moved = 0
    for f in old:
        day = f.stem.split("_")[1] if "_" in f.stem else "undated"
        dest_dir = info["drive_root"] / "screenshots" / "archive" / day
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(f), str(dest_dir / f.name))
            moved += 1
        except Exception:                            # noqa: BLE001
            continue
    return {"ok": True, "moved": moved,
            "kept_recent": min(len(files), keep_recent)}


if __name__ == "__main__":
    print("Troy storage check")
    for k, v in status().items():
        print(f"  {k:15s}: {v}")
