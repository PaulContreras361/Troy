"""
install_laptop.py - sets up Troy's laptop powers. Safe to run as many times as you like.

Double-click "Install Troy.bat" (or run:  python install_laptop.py)

What it does, in order:
  1. Checks your Python version.
  2. Installs the parts Troy needs (requirements.txt + requirements-laptop.txt).
  3. Puts the Troy Bridge plugin into SketchUp's Plugins folder (every SketchUp year found).
  4. Makes a "Start Troy" icon on your Desktop.
  5. Checks AutoCAD, SketchUp, Outlook, Claude Code and the toolbox, and prints
     OK / NOTE / FAIL for each.

It never deletes anything and never overwrites one of your own files.
"""

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = []


def say(status, what, detail=""):
    rows.append((status, what, detail))
    print(f"  {status:<5} {what:<22} {detail}")


def step(title):
    print(f"\n== {title}")


def python_ok():
    step("1. Python")
    v = sys.version_info
    if v < (3, 10):
        say("FAIL", "Python", f"{v.major}.{v.minor} is too old - install Python 3.12 from python.org")
        return False
    say("OK", "Python", f"{v.major}.{v.minor}.{v.micro}")
    return True


def install_parts():
    step("2. Installing Troy's parts (takes a few minutes the first time)")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade",
           "-r", str(HERE / "requirements.txt"), "-r", str(HERE / "requirements-laptop.txt")]
    r = subprocess.run(cmd)
    say("OK" if r.returncode == 0 else "FAIL", "pip install",
        "" if r.returncode == 0 else "scroll up for the red error and send it to Claude")


def sketchup_plugin():
    step("3. SketchUp plugin (Troy Bridge)")
    src = HERE / "sketchup" / "troy_bridge.rb"
    appdata = os.environ.get("APPDATA", "")
    years = sorted(glob.glob(os.path.join(appdata, "SketchUp", "SketchUp 20*", "SketchUp")))
    if not years:
        say("NOTE", "SketchUp", "no SketchUp settings folder yet - open SketchUp Pro once, "
            "close it, then run this installer again")
        return
    for folder in years:
        plugins = Path(folder) / "Plugins"
        plugins.mkdir(exist_ok=True)
        dst = plugins / "troy_bridge.rb"
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            say("OK", "SketchUp plugin", f"already in {plugins}")
        else:
            shutil.copy2(src, dst)          # our own file; updating it is safe
            say("OK", "SketchUp plugin", f"copied to {plugins}")
    say("NOTE", "SketchUp", "restart SketchUp so it loads the plugin (Extensions > Troy Bridge)")


def desktop_icon():
    step("4. Desktop icon")
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = Path(shell.SpecialFolders("Desktop"))
        lnk = desktop / "Start Troy.lnk"
        sc = shell.CreateShortCut(str(lnk))
        sc.TargetPath = str(HERE / "Start Troy.bat")
        sc.WorkingDirectory = str(HERE)
        icon = HERE / "troy_icon.ico"
        if icon.exists():
            sc.IconLocation = str(icon)
        sc.Description = "Start Troy on this laptop"
        sc.Save()
        say("OK", "Desktop icon", f"'Start Troy' on {desktop}")
    except Exception as e:                  # noqa: BLE001
        say("NOTE", "Desktop icon", f"couldn't make it ({e}) - double-click Start Troy.bat instead")


def com_registered(progid):
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid))
        return True
    except Exception:                       # noqa: BLE001
        return False


def checks():
    step("5. Checks")
    sys.path.insert(0, str(HERE))
    try:
        import troy_tools
        bad = getattr(troy_tools, "LOAD_PROBLEMS", {})
        say("OK" if not bad else "FAIL", "Toolbox", f"{len(troy_tools.REGISTRY)} tools" +
            (f" - problems: {bad}" if bad else ""))
        say("OK" if troy_tools.HAS_GUI else "FAIL", "Mouse/keyboard/screen",
            "" if troy_tools.HAS_GUI else "pyautogui didn't load")
    except Exception as e:                  # noqa: BLE001
        say("FAIL", "Toolbox", str(e))
    say("OK" if com_registered("AutoCAD.Application") else "NOTE", "AutoCAD",
        "full AutoCAD found" if com_registered("AutoCAD.Application")
        else "not found (AutoCAD LT can't be driven by Troy)")
    exe = sorted(glob.glob(r"C:\Program Files\SketchUp\SketchUp 20*\SketchUp.exe"))
    say("OK" if exe else "NOTE", "SketchUp Pro", exe[-1] if exe else "SketchUp.exe not found")
    say("OK" if com_registered("Outlook.Application") else "NOTE", "Outlook",
        "classic Outlook found" if com_registered("Outlook.Application")
        else "classic Outlook not found - email tools won't work")
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    say("OK" if claude else "NOTE", "Claude Code (Hotkey)",
        claude or "not found - Troy Hotkey's brain needs it (or set BRAIN = 'api')")
    node = shutil.which("node")
    say("OK" if node else "NOTE", "Node.js (Hey Troy)", node or "install Node LTS from nodejs.org")


def main():
    print("TROY LAPTOP INSTALLER\n" + "=" * 60)
    if os.name != "nt":
        print("This installer is for your Windows laptop.")
        return
    if not python_ok():
        return
    install_parts()
    sketchup_plugin()
    desktop_icon()
    checks()
    fails = [r for r in rows if r[0] == "FAIL"]
    print("\n" + "=" * 60)
    if fails:
        print(f"{len(fails)} thing(s) need fixing (FAIL above). Send Claude a photo of this window.")
    else:
        print("All set. Double-click 'Start Troy' on your Desktop.")
        print("NOTE lines are fine - they only matter for the program they name.")


if __name__ == "__main__":
    main()
