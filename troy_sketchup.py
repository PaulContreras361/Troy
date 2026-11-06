"""
troy_sketchup.py - Troy draws in SketchUp Pro.

Plain English:
  SketchUp Pro runs Ruby plugins. install_laptop.py puts our small plugin,
  sketchup/troy_bridge.rb, into SketchUp's Plugins folder. While SketchUp is
  open, that plugin watches a folder for requests.

  This file is Troy's side: it writes a request ("box 12 x 16, 8 ft tall"),
  waits for the plugin's answer, and hands it back to Troy.

  Every request is one undo step in SketchUp, so Ctrl+Z takes it back.
  Sizes are in feet unless you say otherwise (unit: in, m, cm, mm).
  The free web SketchUp can't run plugins, so this is SketchUp Pro only.
"""

from __future__ import annotations

import glob
import json
import os
import time
import uuid
from pathlib import Path

import troy_hands

BOX = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TroyBridge" / "sketchup"
INBOX, OUTBOX = BOX / "inbox", BOX / "outbox"
WAIT_SECONDS = 20


def ok(**kw):
    return {"ok": True, **kw}


def fail(reason, **kw):
    return {"ok": False, "error": reason, **kw}


def _send(op: str, **args) -> dict:
    """Drop a request in the inbox and wait for SketchUp's answer."""
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex[:12]
    req = {"id": rid, "op": op, **{k: v for k, v in args.items() if v is not None}}
    tmp = INBOX / f"{rid}.tmp"
    tmp.write_text(json.dumps(req), encoding="utf-8")
    tmp.replace(INBOX / f"{rid}.json")          # appears all at once, never half-written
    answer = OUTBOX / f"{rid}.json"
    end = time.time() + WAIT_SECONDS
    while time.time() < end:
        if answer.exists():
            try:
                out = json.loads(answer.read_text(encoding="utf-8"))
            finally:
                answer.unlink(missing_ok=True)
            return out
        time.sleep(0.25)
    (INBOX / f"{rid}.json").unlink(missing_ok=True)   # don't let it run later by surprise
    return fail("SketchUp didn't answer. Is SketchUp Pro open with a model? If it is, the "
                "Troy Bridge plugin isn't loaded: run install_laptop.py again, then restart "
                "SketchUp (Extensions menu should show 'Troy Bridge').")


# ---------------------------------------------------------------- LOOK
def sketchup_status() -> dict:
    return _send("status")


# ---------------------------------------------------------------- DO
def _find_exe():
    hits = sorted(glob.glob(r"C:\Program Files\SketchUp\SketchUp 20*\SketchUp.exe"))
    return hits[-1] if hits else None


def sketchup_start(path: str = "") -> dict:
    """Start SketchUp Pro, optionally opening a .skp file."""
    if os.name != "nt":
        return fail("SketchUp tools only work on Paul's Windows laptop.")
    if path:
        p, why = troy_hands._check(path)
        if why:
            return fail(why)
        if p.suffix.lower() != ".skp":
            return fail(f"{p.name} isn't a SketchUp file (.skp).")
        os.startfile(str(p))                     # noqa: S606
        return ok(opening=str(p), note="Give SketchUp about 20 seconds, then call sketchup_status.")
    exe = _find_exe()
    if not exe:
        return fail("Couldn't find SketchUp.exe under C:\\Program Files\\SketchUp.")
    os.startfile(exe)                            # noqa: S606
    return ok(started=exe, note="Give SketchUp about 20 seconds (pick a template if it asks), "
              "then call sketchup_status.")


def sketchup_draw(shape: str, unit: str = "ft", name: str = "", color: str = "",
                  origin: list | None = None, width: float | None = None,
                  depth: float | None = None, height: float | None = None,
                  points: list | None = None, start: list | None = None, end: list | None = None,
                  thickness: float | None = None, center: list | None = None,
                  radius: float | None = None, z: float | None = None) -> dict:
    shape = shape.lower().strip()
    if shape not in ("box", "rectangle", "shape", "wall", "cylinder", "lines"):
        return fail("shape must be box, rectangle, shape, wall, cylinder or lines.")
    return _send(shape, unit=unit, name=name or None, color=color or None, origin=origin,
                 width=width, depth=depth, height=height, points=points, start=start, end=end,
                 thickness=thickness, center=center, radius=radius, z=z)


def sketchup_move(name: str, by: list, unit: str = "ft") -> dict:
    return _send("move", name=name, by=by, unit=unit)


def sketchup_delete(name: str) -> dict:
    return _send("delete", name=name)


def sketchup_zoom_extents() -> dict:
    return _send("zoom_extents")


def sketchup_undo() -> dict:
    return _send("undo")


# ---------------------------------------------------------------- ALWAYS ASK
def sketchup_save(path: str = "") -> dict:
    if path:
        p, why = troy_hands._check(path, must_exist=False)
        if why:
            return fail(why)
        path = str(p)
    return _send("save", path=path or None)


REGISTRY = {
    "sketchup_status":       (sketchup_status, 1),
    "sketchup_start":        (sketchup_start, 2),
    "sketchup_draw":         (sketchup_draw, 2),
    "sketchup_move":         (sketchup_move, 2),
    "sketchup_delete":       (sketchup_delete, 2),
    "sketchup_zoom_extents": (sketchup_zoom_extents, 2),
    "sketchup_undo":         (sketchup_undo, 2),
    "sketchup_save":         (sketchup_save, 2),
}
ALWAYS_ASK = {"sketchup_save"}

_P = {"type": "array", "items": {"type": "number"}}
DECLARATIONS = [
    {"name": "sketchup_status",
     "description": "Check SketchUp: is it open with the Troy Bridge plugin, the model name, "
                    "and the groups in it. Call this before drawing.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "sketchup_start",
     "description": "Start SketchUp Pro, or open a .skp file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}},
    {"name": "sketchup_draw",
     "description": (
         "Draw one thing in SketchUp as its own group (one undo step). Sizes in feet unless unit "
         "says in/m/cm/mm. Shapes:\n"
         "  box: origin [x,y,z], width (x), depth (y), height (z)\n"
         "  rectangle: origin, width, depth (flat)\n"
         "  shape: points [[x,y],...] outline, optional height to pull it up, optional z\n"
         "  wall: start [x,y], end [x,y], thickness, height (default 8)\n"
         "  cylinder: center [x,y], radius, height\n"
         "  lines: points [[x,y,z],...] (edges only)\n"
         "Give it a clear name (e.g. 'Shed floor') so it can be moved or deleted later. "
         "color is a SketchUp color name like 'Tan' or 'LightGray'."),
     "parameters": {"type": "object", "properties": {
         "shape": {"type": "string"}, "unit": {"type": "string"}, "name": {"type": "string"},
         "color": {"type": "string"}, "origin": _P, "width": {"type": "number"},
         "depth": {"type": "number"}, "height": {"type": "number"},
         "points": {"type": "array", "items": _P}, "start": _P, "end": _P,
         "thickness": {"type": "number"}, "center": _P, "radius": {"type": "number"},
         "z": {"type": "number"}}, "required": ["shape"]}},
    {"name": "sketchup_move",
     "description": "Move a named group by [dx, dy, dz].",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "by": _P, "unit": {"type": "string"}},
         "required": ["name", "by"]}},
    {"name": "sketchup_delete", "description": "Delete a named group (Ctrl+Z brings it back).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "sketchup_zoom_extents", "description": "Zoom so the whole model fits the view.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "sketchup_undo", "description": "Undo the last step in SketchUp.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "sketchup_save",
     "description": "Save the model, or save to a NEW .skp path. Paul must Allow it.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}},
]
