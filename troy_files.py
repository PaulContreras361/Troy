"""
troy_files.py - plugs troy_hands.py into Troy's toolbox.

Plain English:
  troy_hands.py does the real work (move, copy, rename, delete, new folder,
  open, find, undo). Every action there plans first and only acts when told
  confirm=True.

  Here, every action that changes a file is on ALWAYS_ASK. So Troy shows you
  the plan in an Allow / Deny box first, and only after you press Allow does
  this file call troy_hands with confirm=True.

  Deletes go to troy_trash (nothing is erased) and everything stays inside the
  fence: Desktop, Documents, Downloads, Pictures, the Troy folder and drives D-H.
"""

import troy_hands as hands


def _wrap(text):
    """troy_hands answers with one word first: PLAN / DONE / REFUSED / ERROR."""
    text = str(text)
    word = text.split(":", 1)[0].strip().upper()
    return {"ok": word in ("DONE", "PLAN"), "result": text}


# ------------------------------------------------------------------ LOOK
def find_files(pattern: str, where: str = "Documents", max_results: int = 50) -> dict:
    return _wrap(hands.find(pattern, where=where, max_results=max(1, min(int(max_results), 200))))


def file_history(n: int = 10) -> dict:
    return {"ok": True, "result": hands.history(max(1, min(int(n), 50)))}


# ------------------------------------------------------------------ DO (always ask)
def open_file(path: str) -> dict:
    return _wrap(hands.open_file(path, confirm=True))


def move_file(src: str, dst: str) -> dict:
    return _wrap(hands.move(src, dst, confirm=True))


def copy_file(src: str, dst: str) -> dict:
    return _wrap(hands.copy(src, dst, confirm=True))


def rename_file(src: str, new_name: str) -> dict:
    return _wrap(hands.rename(src, new_name, confirm=True))


def delete_file(target: str) -> dict:
    return _wrap(hands.delete(target, confirm=True))


def make_folder(path: str) -> dict:
    return _wrap(hands.make_folder(path, confirm=True))


def undo_last_file_action() -> dict:
    return _wrap(hands.undo(confirm=True))


REGISTRY = {
    "find_files":            (find_files, 1),
    "file_history":          (file_history, 1),
    "open_file":             (open_file, 2),
    "move_file":             (move_file, 2),
    "copy_file":             (copy_file, 2),
    "rename_file":           (rename_file, 2),
    "delete_file":           (delete_file, 2),
    "make_folder":           (make_folder, 2),
    "undo_last_file_action": (undo_last_file_action, 2),
}

# open_file is not undoable but harmless, so it runs at DO without a box.
ALWAYS_ASK = {"move_file", "copy_file", "rename_file", "delete_file",
              "make_folder", "undo_last_file_action"}

# What the Allow box shows: troy_hands' own plan, with nothing done yet.
PLANS = {
    "move_file":   lambda a: hands.move(a.get("src", ""), a.get("dst", "")),
    "copy_file":   lambda a: hands.copy(a.get("src", ""), a.get("dst", "")),
    "rename_file": lambda a: hands.rename(a.get("src", ""), a.get("new_name", "")),
    "delete_file": lambda a: hands.delete(a.get("target", "")),
    "make_folder": lambda a: hands.make_folder(a.get("path", "")),
    "undo_last_file_action": lambda a: hands.undo(),
}


def _o(props, required):
    return {"type": "object", "properties": props, "required": required}


_S = {"type": "string"}
DECLARATIONS = [
    {"name": "find_files",
     "description": "Find files or folders whose NAME contains some text. 'where' is a folder such "
                    "as Documents, Desktop, Downloads, or a full path like D:/Drawings.",
     "parameters": _o({"pattern": {**_S, "description": "Part of the file name, e.g. pipeline"},
                       "where": {**_S, "description": "Folder to search. Default Documents."},
                       "max_results": {"type": "integer"}}, ["pattern"])},
    {"name": "file_history",
     "description": "Show the last file actions Troy took (moves, copies, deletes, undos).",
     "parameters": _o({"n": {"type": "integer"}}, [])},
    {"name": "open_file",
     "description": "Open a document with its normal program (a PDF, a DWG in AutoCAD, an SKP in "
                    "SketchUp, an XLSX in Excel). Programs (.exe/.bat) are refused.",
     "parameters": _o({"path": {**_S, "description": "Full path to the file."}}, ["path"])},
    {"name": "move_file",
     "description": "Move a file or folder. Paul sees the plan and must press Allow first.",
     "parameters": _o({"src": _S, "dst": {**_S, "description": "Destination folder or full new path."}},
                      ["src", "dst"])},
    {"name": "copy_file",
     "description": "Copy a file or folder. Paul must press Allow first.",
     "parameters": _o({"src": _S, "dst": _S}, ["src", "dst"])},
    {"name": "rename_file",
     "description": "Rename a file or folder (new name only, no path). Paul must press Allow first.",
     "parameters": _o({"src": _S, "new_name": _S}, ["src", "new_name"])},
    {"name": "delete_file",
     "description": "Delete a file or folder. It goes to troy_trash, so undo can bring it back. "
                    "Paul must press Allow first.",
     "parameters": _o({"target": _S}, ["target"])},
    {"name": "make_folder",
     "description": "Make a new folder. Paul must press Allow first.",
     "parameters": _o({"path": _S}, ["path"])},
    {"name": "undo_last_file_action",
     "description": "Undo Troy's most recent move, copy, rename, delete or new folder.",
     "parameters": _o({}, [])},
]
