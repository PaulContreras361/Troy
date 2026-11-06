"""
================================================================================
 TROY DRIVE SETUP  -  troy_setup_drive.py
================================================================================
 Run this ONCE to prepare your external drive. After that Troy finds it on his
 own, every time, even if Windows gives it a different letter.

     python troy_setup_drive.py

 It creates a TroyDrive folder at the root of the drive with five subfolders
 and one small marker file. It never deletes anything and it never touches
 anything already on the drive.
================================================================================
"""

import shutil
import string
import sys
from pathlib import Path

import troy_storage as storage


def list_candidate_drives():
    """Every drive that currently exists, with free space."""
    found = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        try:
            if not root.exists():
                continue
            du = shutil.disk_usage(str(root))
            found.append({
                "path": root,
                "total_gb": round(du.total / 1024**3, 1),
                "free_gb": round(du.free / 1024**3, 1),
                "is_troy": (root / storage.DRIVE_FOLDER /
                            storage.MARKER_NAME).is_file(),
            })
        except Exception:                            # noqa: BLE001
            continue

    # Mac / Linux mount points, just in case
    for base in ("/Volumes", "/media", "/mnt"):
        b = Path(base)
        if not b.is_dir():
            continue
        try:
            for child in b.iterdir():
                if not child.is_dir():
                    continue
                du = shutil.disk_usage(str(child))
                found.append({
                    "path": child,
                    "total_gb": round(du.total / 1024**3, 1),
                    "free_gb": round(du.free / 1024**3, 1),
                    "is_troy": (child / storage.DRIVE_FOLDER /
                                storage.MARKER_NAME).is_file(),
                })
        except Exception:                            # noqa: BLE001
            continue
    return found


def main() -> int:
    print("=" * 70)
    print(" TROY DRIVE SETUP")
    print("=" * 70)

    drives = list_candidate_drives()
    if not drives:
        print("\nNo drives found. Is the external drive plugged in?")
        return 1

    print("\nDrives currently connected:\n")
    for i, d in enumerate(drives, 1):
        tag = "  <-- already set up for Troy" if d["is_troy"] else ""
        print(f"  [{i:2d}]  {str(d['path']):<22} "
              f"{d['total_gb']:>8.1f} GB total, "
              f"{d['free_gb']:>8.1f} GB free{tag}")

    print("\n  [ 0]  cancel")
    print("\nPick the 1 TB drive. Look at the size column to be sure -")
    print("choosing your C: drive by mistake would put Troy's files on the laptop.")

    try:
        choice = int(input("\nWhich number? ").strip())
    except (ValueError, EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 1

    if choice == 0:
        print("Cancelled.")
        return 0
    if not 1 <= choice <= len(drives):
        print("Not one of the numbers. Cancelled.")
        return 1

    chosen = drives[choice - 1]
    target = chosen["path"] / storage.DRIVE_FOLDER

    print(f"\n  Will create : {target}")
    print(f"  Subfolders  : {', '.join(storage.LAYOUT)}")
    print(f"  Free space  : {chosen['free_gb']} GB")
    print("\n  Nothing already on the drive will be changed or deleted.")

    if input("\nType YES to continue: ").strip() != "YES":
        print("Not confirmed. Nothing changed.")
        return 1

    result = storage.setup_drive(str(chosen["path"]))
    if not result["ok"]:
        print(f"\n  ❌ {result['error']}")
        return 1

    print(f"\n  ✅ Ready at {result['drive_root']}")
    print(f"     {result['free_gb']} GB free")
    print("\n  Troy now finds this drive by its marker file, so the drive")
    print("  letter can change and nothing breaks.")
    print("\n  Start Troy:  python -m streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
