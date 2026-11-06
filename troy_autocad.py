"""
troy_autocad.py - Troy draws in AutoCAD (full AutoCAD, not LT).

Plain English:
  Full AutoCAD lets other programs drive it through "COM" (the same doorway
  Excel macros use). Troy uses that doorway to:
    LOOK  - see which drawings are open, the layers, what's in model space
    DO    - start AutoCAD, open a drawing, draw lines / polylines / rectangles /
            circles / arcs / text / dimensions on a layer, make layers, zoom,
            undo his last drawing step
    ASK   - save the drawing, or type a raw command on AutoCAD's command line
            (these always stop for your Allow)

  Every autocad_draw call is wrapped in one undo mark, so ONE Ctrl+Z in AutoCAD
  (or autocad_undo) takes back everything Troy drew in that step.

  AutoCAD LT has no COM doorway, so none of this works in LT.

  Coordinates and sizes are in the drawing's own units (autocad_status tells
  you which: inches, feet, ...).
"""

from __future__ import annotations

import glob
import math
import os
import time

try:
    import pythoncom
    import win32com.client
    HAS_COM = True
except Exception as _e:          # noqa: BLE001  (not Windows, or pywin32 missing)
    HAS_COM = False
    _COM_ERROR = str(_e)

import troy_hands

INSUNITS = {0: "unitless", 1: "inches", 2: "feet", 3: "miles", 4: "millimeters",
            5: "centimeters", 6: "meters", 7: "kilometers", 8: "microinches",
            9: "mils", 10: "yards", 14: "decimeters"}


def ok(**kw):
    return {"ok": True, **kw}


def fail(reason, **kw):
    return {"ok": False, "error": reason, **kw}


# ---------------------------------------------------------------- COM helpers
def _retry(fn, tries=12):
    """AutoCAD says 'Call was rejected by callee' while it's busy. Wait and retry."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:   # noqa: BLE001
            last = e
            text = str(e)
            if "-2147418111" in text or "rejected" in text.lower() or "-2147417846" in text:
                time.sleep(0.5)
                continue
            raise
    raise last


def _app(start=False):
    if not HAS_COM:
        raise RuntimeError(f"AutoCAD tools need Windows with pywin32 installed ({_COM_ERROR}).")
    pythoncom.CoInitialize()               # Streamlit runs us on its own thread
    try:
        return win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:            # noqa: BLE001
        if not start:
            raise RuntimeError("AutoCAD isn't open. Ask Troy to start it (autocad_start).")
    app = win32com.client.Dispatch("AutoCAD.Application")
    _retry(lambda: setattr(app, "Visible", True))
    return app


def _doc(app):
    if _retry(lambda: app.Documents.Count) == 0:
        _retry(lambda: app.Documents.Add())
    return _retry(lambda: app.ActiveDocument)


def _pt(x, y, z=0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                   (float(x), float(y), float(z)))


def _flat2d(points):
    flat = []
    for p in points:
        flat += [float(p[0]), float(p[1])]
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)


def _xy(p, name="point"):
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        raise ValueError(f"{name} must be [x, y] or [x, y, z]")
    return [float(v) for v in p[:3]] + ([0.0] if len(p) == 2 else [])


def _layer(doc, name, color=None):
    layers = _retry(lambda: doc.Layers)
    try:
        lay = _retry(lambda: layers.Item(name))
    except Exception:            # noqa: BLE001
        lay = _retry(lambda: layers.Add(name))
    if color is not None:
        _retry(lambda: setattr(lay, "color", int(color)))
    return lay


# ---------------------------------------------------------------- LOOK
def autocad_status() -> dict:
    """Is AutoCAD open, which drawings, which units, how much is in model space."""
    try:
        app = _app()
    except RuntimeError as e:
        return fail(str(e), running=False)
    docs = []
    for i in range(_retry(lambda: app.Documents.Count)):
        d = _retry(lambda: app.Documents.Item(i))
        docs.append(_retry(lambda: d.FullName) or _retry(lambda: d.Name))
    doc = _retry(lambda: app.ActiveDocument)
    units = _retry(lambda: doc.GetVariable("INSUNITS"))
    return ok(running=True, version=_retry(lambda: app.Version), open_drawings=docs,
              active=_retry(lambda: doc.Name), units=INSUNITS.get(int(units), str(units)),
              entities_in_model_space=_retry(lambda: doc.ModelSpace.Count),
              active_layer=_retry(lambda: doc.ActiveLayer.Name))


def autocad_list_layers() -> dict:
    doc = _doc(_app())
    out = []
    layers = _retry(lambda: doc.Layers)
    for i in range(_retry(lambda: layers.Count)):
        lay = _retry(lambda: layers.Item(i))
        out.append({"name": lay.Name, "color": lay.color, "on": bool(lay.LayerOn),
                    "frozen": bool(lay.Freeze), "locked": bool(lay.Lock)})
    return ok(layers=out)


def autocad_list_entities(limit: int = 300) -> dict:
    """What's drawn: counts by type and layer, plus the first few items with points."""
    doc = _doc(_app())
    ms = _retry(lambda: doc.ModelSpace)
    n = _retry(lambda: ms.Count)
    by_type, by_layer, sample = {}, {}, []
    for i in range(min(n, 5000)):
        e = _retry(lambda: ms.Item(i))
        t = e.ObjectName.replace("AcDb", "")
        by_type[t] = by_type.get(t, 0) + 1
        by_layer[e.Layer] = by_layer.get(e.Layer, 0) + 1
        if len(sample) < min(int(limit), 300):
            item = {"type": t, "layer": e.Layer, "handle": e.Handle}
            try:
                lo, hi = e.GetBoundingBox()
                item["box"] = [[round(lo[0], 3), round(lo[1], 3)], [round(hi[0], 3), round(hi[1], 3)]]
            except Exception:    # noqa: BLE001
                pass
            if t == "Text" or t == "MText":
                item["text"] = str(e.TextString)[:120]
            sample.append(item)
    return ok(total=n, by_type=by_type, by_layer=by_layer, first_items=sample,
              note="Only the first 5000 items were counted." if n > 5000 else "")


# ---------------------------------------------------------------- DO
def _find_acad_exe():
    pats = [r"C:\Program Files\Autodesk\AutoCAD *\acad.exe"]
    hits = []
    for p in pats:
        hits += glob.glob(p)
    hits = [h for h in hits if " LT " not in h and not h.lower().endswith("lt\\acad.exe")]
    return sorted(hits)[-1] if hits else None


def autocad_start() -> dict:
    """Start AutoCAD (or connect to the one already open)."""
    try:
        app = _app(start=True)
        return ok(started=True, version=_retry(lambda: app.Version))
    except Exception as e:       # noqa: BLE001
        exe = _find_acad_exe() if os.name == "nt" else None
        if exe:
            os.startfile(exe)    # noqa: S606
            return ok(started=True, note="Starting AutoCAD - give it about 30 seconds, "
                      "then call autocad_status.", exe=exe)
        return fail(f"Couldn't start AutoCAD: {e}")


def autocad_open(path: str = "", new_drawing: bool = False) -> dict:
    """Open a .dwg (inside the fence), or start a new blank drawing."""
    app = _app(start=True)
    if new_drawing or not path:
        d = _retry(lambda: app.Documents.Add())
        return ok(opened="new drawing", name=d.Name)
    p, why = troy_hands._check(path)
    if why:
        return fail(why)
    if p.suffix.lower() not in (".dwg", ".dxf", ".dwt"):
        return fail(f"{p.name} isn't a drawing (.dwg / .dxf / .dwt).")
    d = _retry(lambda: app.Documents.Open(str(p)))
    return ok(opened=str(p), name=d.Name)


SHAPES_HELP = (
    "List of shapes. Each is an object with 'type' and its fields:\n"
    "  line: start [x,y], end [x,y]\n"
    "  polyline: points [[x,y],...], closed true/false\n"
    "  rectangle: corner [x,y], width, height\n"
    "  circle: center [x,y], radius\n"
    "  arc: center [x,y], radius, start_angle, end_angle (degrees, counter-clockwise from east)\n"
    "  text: at [x,y], text, height, rotation (degrees, optional)\n"
    "  dimension: start [x,y], end [x,y], offset (distance of the dimension line, default 1)\n"
    "Any shape may also have 'layer' (made if missing) and 'color' (AutoCAD color number 1-255)."
)


def _draw_one(doc, ms, s):
    t = str(s.get("type", "")).lower()
    if t == "line":
        a, b = _xy(s["start"], "start"), _xy(s["end"], "end")
        ent = _retry(lambda: ms.AddLine(_pt(*a), _pt(*b)))
    elif t in ("polyline", "rectangle"):
        if t == "rectangle":
            x, y = _xy(s["corner"], "corner")[:2]
            w, h = float(s["width"]), float(s["height"])
            pts, closed = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], True
        else:
            pts = [_xy(p)[:2] for p in s["points"]]
            closed = bool(s.get("closed", False))
            if len(pts) < 2:
                raise ValueError("a polyline needs at least 2 points")
        ent = _retry(lambda: ms.AddLightWeightPolyline(_flat2d(pts)))
        if closed:
            _retry(lambda: setattr(ent, "Closed", True))
    elif t == "circle":
        c = _xy(s["center"], "center")
        ent = _retry(lambda: ms.AddCircle(_pt(*c), float(s["radius"])))
    elif t == "arc":
        c = _xy(s["center"], "center")
        ent = _retry(lambda: ms.AddArc(_pt(*c), float(s["radius"]),
                                       math.radians(float(s["start_angle"])),
                                       math.radians(float(s["end_angle"]))))
    elif t == "text":
        at = _xy(s["at"], "at")
        ent = _retry(lambda: ms.AddText(str(s["text"]), _pt(*at), float(s.get("height", 1))))
        if s.get("rotation"):
            _retry(lambda: setattr(ent, "Rotation", math.radians(float(s["rotation"]))))
    elif t == "dimension":
        a, b = _xy(s["start"], "start"), _xy(s["end"], "end")
        off = float(s.get("offset", 1))
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1.0
        mid = [(a[0] + b[0]) / 2 - dy / ln * off, (a[1] + b[1]) / 2 + dx / ln * off, 0]
        ent = _retry(lambda: ms.AddDimAligned(_pt(*a), _pt(*b), _pt(*mid)))
    else:
        raise ValueError(f"unknown shape type '{t}'")
    if s.get("layer"):
        _layer(doc, str(s["layer"]))
        _retry(lambda: setattr(ent, "Layer", str(s["layer"])))
    if s.get("color") is not None:
        _retry(lambda: setattr(ent, "color", int(s["color"])))
    return {"type": t, "handle": ent.Handle}


def autocad_draw(shapes: list, zoom: bool = True) -> dict:
    """Draw several shapes in one step (one undo takes them all back)."""
    if not isinstance(shapes, list) or not shapes:
        return fail("shapes must be a non-empty list. " + SHAPES_HELP)
    if len(shapes) > 500:
        return fail("More than 500 shapes in one step - split it up.")
    app = _app(start=True)
    doc = _doc(app)
    ms = _retry(lambda: doc.ModelSpace)
    drawn, errors = [], []
    _retry(lambda: doc.StartUndoMark())
    try:
        for i, s in enumerate(shapes):
            try:
                drawn.append(_draw_one(doc, ms, s))
            except Exception as e:   # noqa: BLE001
                errors.append(f"shape {i + 1} ({s.get('type')}): {e}")
    finally:
        _retry(lambda: doc.EndUndoMark())
    if zoom and drawn:
        _retry(lambda: app.ZoomExtents())
    return {"ok": bool(drawn), "drawn": len(drawn), "items": drawn[:50], "errors": errors,
            "drawing": doc.Name, "undo": "autocad_undo (or Ctrl+Z once) removes this whole step"}


def autocad_make_layer(name: str, color: int = 7, make_current: bool = False) -> dict:
    doc = _doc(_app())
    lay = _layer(doc, name, color)
    if make_current:
        _retry(lambda: setattr(doc, "ActiveLayer", lay))
    return ok(layer=name, color=color, current=make_current)


def autocad_zoom_extents() -> dict:
    _retry(lambda: _app().ZoomExtents())
    return ok(zoomed=True)


def autocad_undo(steps: int = 1) -> dict:
    """Undo Troy's last drawing step(s) in the active drawing."""
    doc = _doc(_app())
    steps = max(1, min(int(steps), 10))
    _retry(lambda: doc.SendCommand(f"_.UNDO {steps} "))
    return ok(undone_steps=steps)


# ---------------------------------------------------------------- ALWAYS ASK
def autocad_save(save_as: str = "") -> dict:
    """Save the active drawing (or Save As a new .dwg inside the fence)."""
    doc = _doc(_app())
    if save_as:
        p, why = troy_hands._check(save_as, must_exist=False)
        if why:
            return fail(why)
        if p.suffix.lower() != ".dwg":
            return fail("Save As name must end in .dwg")
        if p.exists():
            return fail(f"{p} already exists - Troy won't overwrite it. Pick a new name.")
        _retry(lambda: doc.SaveAs(str(p)))
        return ok(saved_as=str(p))
    if not _retry(lambda: doc.FullName):
        return fail("This drawing has never been saved. Give a save_as path like "
                    "C:/Users/paulc/Documents/Drawings/new.dwg")
    _retry(lambda: doc.Save())
    return ok(saved=doc.FullName)


def autocad_command(command: str) -> dict:
    """Type a command on AutoCAD's command line, e.g. '_.OFFSET 2 ' (spaces = Enter)."""
    command = str(command)
    if len(command) > 500:
        return fail("Command too long.")
    blocked = ("_.QUIT", "QUIT", "_.CLOSE", "CLOSEALL", "SHELL", "_.SHELL", "(STARTAPP", "(COMMAND \"SHELL")
    if any(b in command.upper() for b in blocked):
        return fail("That command is blocked (quits AutoCAD or runs programs).")
    doc = _doc(_app())
    if not command.endswith((" ", "\n")):
        command += " "
    _retry(lambda: doc.SendCommand(command))
    return ok(sent=command)


REGISTRY = {
    "autocad_status":        (autocad_status, 1),
    "autocad_list_layers":   (autocad_list_layers, 1),
    "autocad_list_entities": (autocad_list_entities, 1),
    "autocad_start":         (autocad_start, 2),
    "autocad_open":          (autocad_open, 2),
    "autocad_draw":          (autocad_draw, 2),
    "autocad_make_layer":    (autocad_make_layer, 2),
    "autocad_zoom_extents":  (autocad_zoom_extents, 2),
    "autocad_undo":          (autocad_undo, 2),
    "autocad_save":          (autocad_save, 2),
    "autocad_command":       (autocad_command, 3),
}
ALWAYS_ASK = {"autocad_save", "autocad_command"}

_P = {"type": "array", "items": {"type": "number"}, "description": "[x, y]"}
DECLARATIONS = [
    {"name": "autocad_status",
     "description": "Check whether AutoCAD is open, which drawings are open, the drawing units "
                    "and how many objects are in model space. Call this before drawing.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "autocad_list_layers", "description": "List the layers in the active drawing.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "autocad_list_entities",
     "description": "See what is drawn in model space: counts by type and layer, and the first "
                    "items with their bounding boxes and any text.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}},
    {"name": "autocad_start", "description": "Start AutoCAD, or connect to the one already open.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "autocad_open",
     "description": "Open a .dwg file, or set new_drawing true for a blank drawing.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "new_drawing": {"type": "boolean"}}, "required": []}},
    {"name": "autocad_draw",
     "description": "Draw shapes in the active AutoCAD drawing, all in one undo step. Work out "
                    "the coordinates first. " + SHAPES_HELP,
     "parameters": {"type": "object", "properties": {
         "shapes": {"type": "array", "items": {"type": "object"}, "description": SHAPES_HELP},
         "zoom": {"type": "boolean", "description": "Zoom to show everything after (default true)."}},
         "required": ["shapes"]}},
    {"name": "autocad_make_layer",
     "description": "Make a layer (or change its color). AutoCAD colors: 1 red, 2 yellow, 3 green, "
                    "4 cyan, 5 blue, 6 magenta, 7 white/black.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "color": {"type": "integer"},
         "make_current": {"type": "boolean"}}, "required": ["name"]}},
    {"name": "autocad_zoom_extents", "description": "Zoom so the whole drawing fits the screen.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "autocad_undo", "description": "Undo the last drawing step(s) in AutoCAD.",
     "parameters": {"type": "object", "properties": {"steps": {"type": "integer"}}, "required": []}},
    {"name": "autocad_save",
     "description": "Save the active drawing, or save_as a NEW .dwg path. Paul must Allow it.",
     "parameters": {"type": "object", "properties": {"save_as": {"type": "string"}}, "required": []}},
    {"name": "autocad_command",
     "description": "Type a command on AutoCAD's command line for anything autocad_draw can't do "
                    "(OFFSET, TRIM, FILLET, HATCH, MOVE...). Spaces act as Enter. Paul must Allow it.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                    "required": ["command"]}},
]
