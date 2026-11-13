"""Troy's drive — Paul's external drive (E:) on his laptop, free storage for Troy.

What Troy keeps there on his own (his folder, E:\\Troy — no asking needed):
    History\\problems.jsonl   every problem Troy ever logged (never resets)
    Chats\\                   a copy of every chat
    Memory\\                  backups of what Troy has learned about Paul
    Files\\                   files Troy makes for Paul

Anywhere else on E:, Troy can LOOK (list folders, find and read files) but he
asks Paul first — Allow once / Allow this folder / Deny — like Claude does.
He never writes, moves or deletes anything outside E:\\Troy, and never touches
other drives (C: etc.).

Only the laptop Troy can reach the drive. The phone Troy runs on Streamlit's
servers; when Paul asks it for drive files it says to open Troy on the laptop.
If the drive is unplugged, Troy says "plug in your drive" and carries on.
"""

import base64
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("TROY_DRIVE") or "E:\\")
FOLDER_NAME = "Troy"
SUBFOLDERS = ("History", "Chats", "Memory", "Files")
MAX_READ_CHARS = 150_000
MAX_LIST = 200
MAX_FIND = 100
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", "$Recycle.Bin", ".Trashes",
             ".Spotlight-V100", ".fseventsd"}


def _root_path(root):
    root = str(root).strip().strip('"')
    if re.fullmatch(r"[A-Za-z]:", root):   # "E:" alone means "current folder on E:" to Windows
        root += "\\"
    return Path(root)


def configure(root):
    global ROOT
    if root:
        ROOT = _root_path(root)


def home():
    return ROOT / FOLDER_NAME


def on_laptop():
    """True on Paul's laptop (or any computer told where the drive is)."""
    return sys.platform == "win32" or bool(os.environ.get("TROY_DRIVE"))


def status():
    """'ready', 'unplugged' (laptop, drive not there) or 'cloud' (phone Troy)."""
    if not on_laptop():
        return "cloud"
    try:
        if ROOT.exists() and ROOT.is_dir():
            for sub in SUBFOLDERS:
                (home() / sub).mkdir(parents=True, exist_ok=True)
            return "ready"
    except OSError:
        pass
    return "unplugged"


def status_line(s=None):
    s = s or status()
    return {"ready": f"🟢 Drive {_label()} connected — Troy's folder is {home()}",
            "unplugged": f"🔌 Drive {_label()} isn't plugged in. Plug it in and Troy will use it again.",
            "cloud": f"☁️ This is the phone/cloud Troy — drive {_label()} is only on the laptop Troy."}[s]


def _label():
    return str(ROOT).rstrip("\\/") or str(ROOT)


# ---- Fence and permission -----------------------------------------------------
def resolve(path):
    """Turn what Troy asked for into a real path ON THE DRIVE, or explain why not."""
    p = str(path or "").strip().strip('"')
    if not p or p in (".", "\\", "/"):
        p = str(ROOT)
    cand = Path(p)
    if not cand.is_absolute() and not re.match(r"^[A-Za-z]:", p):
        cand = ROOT / p
    try:
        real = cand.resolve()
        root = ROOT.resolve()
    except OSError as e:
        return None, f"can't open that path ({e})"
    if real != root and root not in real.parents:
        return None, f"that's outside drive {_label()} — Troy only looks on Paul's drive"
    if any(part in SKIP_DIRS for part in real.parts):
        return None, "that's a system folder — Troy leaves it alone"
    return real, None


def in_troy_folder(real):
    h = home().resolve()
    return real == h or h in real.parents


def needs_permission(real, allowed):
    """Inside E:\\Troy: never. Elsewhere: unless Paul allowed that folder this visit."""
    if in_troy_folder(real):
        return False
    for a in allowed:
        a = Path(a)
        if real == a or a in real.parents:
            return False
    return True


def folder_for_permission(real):
    return real if real.is_dir() else real.parent


# ---- Tools Claude can use ------------------------------------------------------
TOOLS = [
    {"name": "drive_list",
     "description": "List what's in a folder on Paul's external drive. Use '' for the top of the drive.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Folder path on the drive, e.g. 'Projects' or 'E:\\\\EPR'"}},
         "required": ["path"]}},
    {"name": "drive_find",
     "description": "Find files on Paul's drive whose names contain some text (searches inside a folder and its subfolders).",
     "input_schema": {"type": "object", "properties": {
         "name_contains": {"type": "string"},
         "folder": {"type": "string", "description": "Folder to search in; '' = whole drive"}},
         "required": ["name_contains"]}},
    {"name": "drive_read",
     "description": "Read a file from Paul's drive: text, CSV, code/HTML, Excel (.xlsx), PDF text, or a photo.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
    {"name": "drive_save",
     "description": "Save a text file Troy made for Paul into Troy's own Files folder on the drive "
                    "(never overwrites; never saves anywhere else).",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "File name, e.g. 'EPR summary 11-13.md'"},
         "content": {"type": "string"}}, "required": ["name", "content"]}},
]

SYSTEM_NOTE = {
    "ready": "\nPAUL'S EXTERNAL DRIVE ({drive}) is connected. Use the drive tools when Paul asks about "
             "files or folders on it, or when a file there would answer his question. Your own folder "
             "is {home} (History, Chats, Memory, Files). Looking outside your folder pauses for Paul's "
             "OK — that's normal, just ask for what you need.",
    "unplugged": "\nPaul's external drive ({drive}) is NOT plugged in right now. If he asks for something "
                 "on it, tell him to plug in his drive.",
    "cloud": "\nPaul's external drive ({drive}) is only connected to the laptop Troy. If he asks for "
             "files on it, tell him to open Troy on his laptop.",
}


def system_note(s=None):
    s = s or status()
    return SYSTEM_NOTE[s].format(drive=_label(), home=home())


def tool_target(name, args):
    """The path a tool call touches (for the permission check)."""
    if name == "drive_list":
        return args.get("path", "")
    if name == "drive_find":
        return args.get("folder", "")
    if name == "drive_read":
        return args.get("path", "")
    return str(home() / "Files")


def describe(name, args, real):
    what = {"drive_list": "look in the folder", "drive_find": f"search for “{args.get('name_contains', '')}” in",
            "drive_read": "open the file", "drive_save": "save a file to"}.get(name, "use")
    return f"{what} {real}"


def run(name, args):
    """Do one tool call (permission already settled). Returns tool_result content."""
    s = status()
    if s != "ready":
        return "The drive isn't available: " + status_line(s)
    try:
        if name == "drive_save":
            return _save(args.get("name", ""), args.get("content", ""))
        real, why = resolve(tool_target(name, args))
        if why:
            return "Not allowed: " + why
        if name == "drive_list":
            return _list(real)
        if name == "drive_find":
            return _find(real, args.get("name_contains", ""))
        if name == "drive_read":
            return _read(real)
        return f"Unknown tool {name}"
    except Exception as e:
        return f"Couldn't do that: {type(e).__name__}: {str(e)[:200]}"


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _list(real):
    if not real.exists():
        return f"{real} doesn't exist."
    if real.is_file():
        return f"{real} is a file ({_size(real.stat().st_size)}). Use drive_read to open it."
    rows, n = [], 0
    for e in sorted(real.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if e.name in SKIP_DIRS or e.name.startswith("."):
            continue
        n += 1
        if len(rows) < MAX_LIST:
            try:
                st_ = e.stat()
                when = datetime.fromtimestamp(st_.st_mtime).strftime("%m/%d/%Y")
                rows.append(f"📁 {e.name}\\" if e.is_dir() else f"📄 {e.name} — {_size(st_.st_size)}, {when}")
            except OSError:
                rows.append(e.name)
    more = f"\n… and {n - len(rows)} more" if n > len(rows) else ""
    return f"{real} ({n} items):\n" + ("\n".join(rows) or "(empty)") + more


def _find(real, needle):
    needle = (needle or "").lower().strip()
    if not needle:
        return "Tell me part of the file name to look for."
    hits, looked = [], 0
    for dirpath, dirnames, filenames in os.walk(real):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            looked += 1
            if needle in f.lower():
                hits.append(str(Path(dirpath) / f))
                if len(hits) >= MAX_FIND:
                    return "\n".join(hits) + f"\n… stopped at {MAX_FIND} matches"
        if looked > 200_000:
            break
    return "\n".join(hits) if hits else f"No file names containing “{needle}” under {real}."


def _read(real):
    if not real.exists():
        return f"{real} doesn't exist."
    if real.is_dir():
        return _list(real)
    ext = real.suffix.lower()
    size = real.stat().st_size
    if size > 25 * 1024 * 1024:
        return f"{real.name} is {_size(size)} — too big to read in one go."
    data = real.read_bytes()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=85)
        return [{"type": "text", "text": f"Photo {real.name}:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(out.getvalue()).decode()}}]
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        lines = [f"Excel {real.name} — tabs: " + ", ".join(wb.sheetnames)]
        for ws in wb.worksheets:
            lines.append(f"=== Tab: {ws.title} ===")
            for r, row in enumerate(ws.iter_rows(values_only=True), 1):
                cells = [f"{chr(64 + c) if c <= 26 else c}={v.strftime('%m/%d/%Y') if isinstance(v, datetime) else v}"
                         for c, v in enumerate(row, 1) if v not in (None, "")]
                if cells:
                    lines.append(f"Row {r}: " + " | ".join(cells))
        wb.close()
        return _cap("\n".join(lines))
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(data)).pages
        text = "\n\n".join(f"--- page {i} ---\n{p.extract_text() or ''}" for i, p in enumerate(pages, 1))
        if len(re.sub(r"\s|-|page \d+", "", text)) < 40:
            return (f"{real.name} has {len(pages)} pages but no readable text (probably scanned). "
                    "Paul can attach it in the chat so Troy can read the pictures.")
        return _cap(text)
    if ext == ".docx":
        import zipfile
        import xml.etree.ElementTree as ET
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
        paras = ["".join(t.text or "" for t in p.iter(w + "t")) for p in root.iter(w + "p")]
        return _cap(f"Word {real.name}:\n" + "\n".join(x for x in paras if x.strip()))
    if ext in (".doc", ".xls", ".ppt", ".pptx", ".dwg", ".zip", ".exe", ".msi", ".mp4", ".mov", ".mp3"):
        return f"{real.name} is a {ext} file ({_size(size)}). Troy can't read inside this kind from the drive."
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"data:[\w/+.\-]+;base64,[A-Za-z0-9+/=]{300,}", "[embedded data cut]", text)
    return _cap(text)


def _cap(text):
    if len(text) <= MAX_READ_CHARS:
        return text
    return text[:MAX_READ_CHARS] + f"\n…[cut — {len(text) - MAX_READ_CHARS:,} more characters]"


def _safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name or "").strip())[:120].strip(". ")
    return name or f"Troy file {datetime.now():%m-%d-%Y %H%M}.txt"


def _save(name, content):
    folder = home() / "Files"
    target = folder / _safe_name(name)
    if "." not in target.name:
        target = target.with_suffix(".txt")
    n = 2
    while target.exists():                       # never overwrite
        target = folder / f"{target.stem.rsplit(' (', 1)[0]} ({n}){target.suffix}"
        n += 1
    target.write_text(str(content), encoding="utf-8")
    return f"Saved {target} ({_size(target.stat().st_size)})."


# ---- Troy's own records on the drive (no asking: his folder) ------------------
def history_file():
    return home() / "History" / "problems.jsonl"


def save_chat(chat):
    if status() != "ready":
        return
    try:
        (home() / "Chats" / f"{chat['id']}.json").write_text(
            json.dumps(chat, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def backup_memory(mem):
    if status() != "ready":
        return
    try:
        d = home() / "Memory"
        text = json.dumps(mem, indent=1, ensure_ascii=False)
        (d / "memory.json").write_text(text, encoding="utf-8")
        (d / f"memory {datetime.now():%Y-%m-%d}.json").write_text(text, encoding="utf-8")
    except Exception:
        pass


def open_troy_folder():
    if status() == "ready" and hasattr(os, "startfile"):
        os.startfile(str(home()))   # opens File Explorer on the laptop
        return True
    return False
