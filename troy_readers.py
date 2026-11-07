"""
troy_readers.py - turns Excel and CAD files into plain text Troy's brain can read.

Plain English:
  Claude reads PDFs, photos and text. It can't open an Excel workbook or an
  AutoCAD drawing by itself, so Troy converts them first:

    .xlsx / .xlsm  -> every sheet, row by row (values, not formulas), up to a limit
    .xls (old)     -> a note asking for .xlsx (the old format needs another library)
    .dxf           -> the drawing's units, size, layers, object counts, all the
                      text on it, and the points of the first lines/polylines
    .dwg           -> AutoCAD's locked format can't be read here. Troy says how to
                      get it in (Save As DXF or PDF), and on Paul's laptop he can
                      open it in AutoCAD with the laptop powers instead.

  Nothing here changes the original file.
"""

from __future__ import annotations

import io

MAX_CHARS = 60_000          # about 15,000 words: plenty for a tracker, safe for the brain
MAX_ROWS_PER_SHEET = 2_000

CONVERTED = {"xlsx", "xlsm", "xls", "dxf", "dwg"}


def to_text(name: str, data: bytes, laptop_path: str | None = None) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if ext in ("xlsx", "xlsm"):
            return excel_text(name, data)
        if ext == "xls":
            return (f"[{name} is an old .xls workbook. Troy can't read that format. In Excel: "
                    "File > Save As > Excel Workbook (.xlsx), then add it again.]")
        if ext == "dxf":
            return dxf_text(name, data)
        if ext == "dwg":
            return dwg_note(name, laptop_path)
    except Exception as e:      # noqa: BLE001
        return f"[Troy couldn't read {name}: {type(e).__name__}: {e}]"
    return data.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ Excel
def _cell(v):
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d") if not getattr(v, "hour", 0) else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("\t", " ").replace("\n", " ").strip()


def excel_text(name: str, data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = [f"Excel workbook {name} — {len(wb.sheetnames)} sheet(s): {', '.join(wb.sheetnames)}",
           "(Values shown, not formulas. Columns are separated by | .)"]
    used = sum(len(x) for x in out)
    cut = False
    for ws in wb.worksheets:
        head = f"\n=== Sheet: {ws.title} ==="
        out.append(head)
        used += len(head)
        rows = 0
        for r_i, row in enumerate(ws.iter_rows(values_only=True), 1):
            cells = [_cell(v) for v in row]
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                continue
            line = f"row {r_i}: " + " | ".join(cells)
            if used + len(line) > MAX_CHARS or rows >= MAX_ROWS_PER_SHEET:
                out.append(f"... (more rows in {ws.title} not shown)")
                cut = True
                break
            out.append(line)
            used += len(line) + 1
            rows += 1
        if rows == 0:
            out.append("(empty)")
        if used > MAX_CHARS:
            cut = True
            break
    wb.close()
    if cut:
        out.append("\n[The workbook was too big to show all of it. Ask Troy about a sheet by name.]")
    return "\n".join(out)


# ------------------------------------------------------------------ CAD
INSUNITS = {0: "unitless", 1: "inches", 2: "feet", 4: "millimeters", 5: "centimeters",
            6: "meters", 10: "yards"}


def dxf_text(name: str, data: bytes) -> str:
    from ezdxf import recover

    doc, auditor = recover.read(io.BytesIO(data))
    msp = doc.modelspace()
    hdr = doc.header
    units = INSUNITS.get(int(hdr.get("$INSUNITS", 0)), str(hdr.get("$INSUNITS")))
    lo, hi = hdr.get("$EXTMIN"), hdr.get("$EXTMAX")
    by_type, by_layer, texts, geom = {}, {}, [], []
    for e in msp:
        t = e.dxftype()
        by_type[t] = by_type.get(t, 0) + 1
        lay = e.dxf.get("layer", "0")
        by_layer[lay] = by_layer.get(lay, 0) + 1
        if t in ("TEXT", "MTEXT") and len(texts) < 400:
            s = e.plain_text() if t == "MTEXT" else e.dxf.get("text", "")
            p = e.dxf.get("insert")
            where = f" at ({p.x:.2f}, {p.y:.2f})" if p is not None else ""
            texts.append(f"  [{lay}] {s.strip()[:200]}{where}")
        elif len(geom) < 150:
            if t == "LINE":
                a, b = e.dxf.start, e.dxf.end
                geom.append(f"  LINE [{lay}] ({a.x:.2f}, {a.y:.2f}) -> ({b.x:.2f}, {b.y:.2f})")
            elif t == "LWPOLYLINE":
                pts = [(round(float(p[0]), 2), round(float(p[1]), 2)) for p in e.get_points("xy")][:12]
                geom.append(f"  POLYLINE [{lay}] {'closed ' if e.closed else ''}{pts}"
                            + (" ..." if len(e) > 12 else ""))
            elif t == "CIRCLE":
                c = e.dxf.center
                geom.append(f"  CIRCLE [{lay}] center ({c.x:.2f}, {c.y:.2f}) r={e.dxf.radius:.2f}")
            elif t == "INSERT":
                p = e.dxf.insert
                geom.append(f"  BLOCK '{e.dxf.name}' [{lay}] at ({p.x:.2f}, {p.y:.2f})")
    lines = [f"AutoCAD drawing {name} (DXF {doc.dxfversion}), units: {units}"]
    try:
        from ezdxf import bbox
        box = bbox.extents(msp, fast=True)
        if box.has_data:
            lo, hi = box.extmin, box.extmax
    except Exception:           # noqa: BLE001
        pass
    if lo is not None and hi is not None and lo[0] <= hi[0] and lo[1] <= hi[1]:
        lines.append(f"Drawing extents: ({lo[0]:.2f}, {lo[1]:.2f}) to ({hi[0]:.2f}, {hi[1]:.2f})")
    lines.append(f"Layers ({len(doc.layers)}): " + ", ".join(sorted(l.dxf.name for l in doc.layers)))
    lines.append("Objects by type: " + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items())))
    lines.append("Objects by layer: " + ", ".join(f"{k} {v}" for k, v in sorted(by_layer.items())))
    if texts:
        lines.append(f"\nText on the drawing ({len(texts)} shown):")
        lines += texts
    if geom:
        lines.append(f"\nFirst {len(geom)} shapes with coordinates:")
        lines += geom
    if auditor.has_errors:
        lines.append(f"\n(The file had {len(auditor.errors)} small errors; Troy read around them.)")
    text = "\n".join(lines)
    return text[:MAX_CHARS]


def dwg_note(name: str, laptop_path: str | None) -> str:
    note = (f"[{name} is an AutoCAD .dwg drawing. Troy can't read inside a .dwg directly "
            "(it's Autodesk's locked format). To let Troy read it, open it in AutoCAD and "
            "use Save As > AutoCAD DXF (.dxf), or Plot / Export to PDF, then add that file.")
    if laptop_path:
        note += (f" Paul is on his laptop, and a copy is saved at {laptop_path}. With Laptop "
                 "powers at DO or higher, use autocad_open on that path and then "
                 "autocad_list_entities to read the drawing.")
    return note + "]"
