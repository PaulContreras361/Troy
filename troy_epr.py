"""
================================================================================
 TROY EPR CHECKER  -  troy_epr.py
================================================================================
 Troy's first real job: checking the EPR Master Tracker workbook.

 READ THIS FIRST - what this file will and will not do
 -----------------------------------------------------
 It NEVER writes to your workbook. Not one cell, ever. There is no save call
 anywhere in this file, and openpyxl is always opened read-only.

 That is deliberate. The weekly reconciliation is the one job where a silent
 mistake is expensive - a permit that leaves the Master before the Folder
 confirms it is a compliance problem, not a spreadsheet problem. So Troy's
 first job is to CHECK and REPORT. You still make every change yourself.

 Once you have run this for a few weeks and trust what it says, adding the
 moves is a separate decision, made then and not now.

 WHAT IT CHECKS
   1. The reconciliation identity:
          Folder = Master + Completed + EXPIRING SOON
   2. Move candidates: Master rows with an Excavation End Date filled in
      (Col Y), which is what marks a permit complete
   3. Master numbering runs 1..N with no gaps or repeats
   4. DJ Summary COUNTA/COUNTIF ranges over the Folder start at row 5,
      not row 4 - row 4 is the header, and including it inflates every count
   5. Duplicate EPR codes within a tab, and codes sitting on two tabs at once

 EVERY NUMBER IT REPORTS IS ONE YOU CAN CHECK BY HAND. That is the point.
 The first time you run it, run it against a week you have already closed
 and know the right answer to.

 The tab names and column letters below come from how the workbook is built
 today. If a tab gets renamed, this file says so plainly instead of guessing.
================================================================================
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re

PROJECT = pathlib.Path(__file__).resolve().parent
DATA = PROJECT / "troy_data"
LOG_FILE = DATA / "action_log.jsonl"
DATA.mkdir(parents=True, exist_ok=True)

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    openpyxl = None
    HAS_OPENPYXL = False


# ------------------------------------------------------------------ the layout
# Tab names as they stand. Matching is loose (case and punctuation ignored) so
# a stray apostrophe or a capital letter does not break the whole run.
TABS = {
    "folder":    "2026 EPR's FOLDER",
    "master":    "EPR Master Tracker",
    "completed": "EPR's Completed",
    "summary":   "DJ Summary",
    "guide":     "Guide & Change Log",
}

HEADER_ROW_FOLDER = 4        # data starts at row 5
DATA_START_FOLDER = 5

# Master Tracker columns
MASTER_NUM = "A"             # sequential number
MASTER_CODE = "B"            # EPR code
MASTER_EXC_END = "Y"         # Excavation End Date - filled means complete

# Completed tab columns
COMPLETED_CODE = "B"

# Master -> Completed column mapping. The layouts diverge from column O
# onward, so a straight O:Y copy misfiles every field. Kept here so the
# checker can explain the mapping when you are doing a move by hand.
MOVE_MAPPING = [
    ("R", "O", "Date Issued"),
    ("X", "P", "Excavation Start"),
    ("Y", "Q", "Excavation End"),
    ("U", "R", "Extension Date"),
    ("V", "S", "Extension End"),
    (None, "T", 'Job Completed  (set to "Yes")'),
    ("Q", "U", "Progress %"),
    ("O", "V", "EPR Status"),
    ("P", "W", "EPR Completed"),
    ("AA", "X", "File Path"),
]


def _ok(**kw):
    return {"ok": True, **kw}


def _fail(reason, **kw):
    return {"ok": False, "error": reason, **kw}


def _log(tool, args, outcome, detail=None):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "tool": tool, "args": args, "outcome": outcome,
                "detail": detail}, default=str) + "\n")
    except Exception:                                    # noqa: BLE001
        pass


# ==============================================================================
# OPENING THE FILE  -  read-only, always
# ==============================================================================
def _normalise(name: str) -> str:
    """Squash case, apostrophes and spacing so tab matching is forgiving."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _find_tab(wb, wanted: str):
    """Find a sheet by loose name match. Returns the sheet or None."""
    target = _normalise(wanted)
    for name in wb.sheetnames:
        if _normalise(name) == target:
            return wb[name]
    for name in wb.sheetnames:                # then try 'contains'
        if target in _normalise(name) or _normalise(name) in target:
            return wb[name]
    return None


def _open(path: str, values: bool = True):
    """
    Open the workbook READ-ONLY.

    Two things worth knowing about openpyxl here:
      - data_only=True gives you the last values Excel calculated, with the
        formulas gone. That is what we want for counting.
      - data_only=False gives the formula text, which is what we need to
        check the COUNTA ranges.
    One pass cannot give you both, so the checks that need formulas open the
    file a second time.
    """
    if not HAS_OPENPYXL:
        raise RuntimeError(
            "openpyxl is not installed. Run:  pip install openpyxl")
    p = pathlib.Path(str(path).strip().strip('"')).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"No workbook at '{p}'")
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(f"'{p.name}' is not an Excel workbook.")
    return openpyxl.load_workbook(p, data_only=values, read_only=True), p


def _column_values(sheet, col: str, start_row: int) -> list[tuple[int, object]]:
    """Every non-empty cell in one column, with its row number."""
    out = []
    for row in range(start_row, (sheet.max_row or start_row) + 1):
        v = sheet[f"{col}{row}"].value
        if v is not None and str(v).strip() != "":
            out.append((row, v))
    return out


# ==============================================================================
# CHECK 1  -  the counts on each tab
# ==============================================================================
def epr_tab_counts(workbook_path: str) -> dict:
    """Count the real data rows on each tab."""
    try:
        wb, p = _open(workbook_path)
    except Exception as e:                               # noqa: BLE001
        return _fail(str(e))

    found, missing = {}, []
    for key, name in TABS.items():
        sheet = _find_tab(wb, name)
        if sheet is None:
            missing.append(name)
        else:
            found[key] = sheet

    counts = {}
    if "folder" in found:
        counts["folder"] = len(_column_values(
            found["folder"], MASTER_CODE, DATA_START_FOLDER))
    if "master" in found:
        counts["master"] = len(_column_values(found["master"], MASTER_CODE, 2))
    if "completed" in found:
        counts["completed"] = len(_column_values(
            found["completed"], COMPLETED_CODE, 2))

    wb.close()
    result = _ok(workbook=p.name, counts=counts,
                 tabs_found=[s.title for s in found.values()])
    if missing:
        result["tabs_not_found"] = missing
        result["note"] = ("Some tabs were not found by name. Check they have "
                          "not been renamed - every count below excludes them.")
    _log("epr_tab_counts", {"path": p.name}, "ok", str(counts))
    return result


# ==============================================================================
# CHECK 2  -  move candidates
# ==============================================================================
def epr_move_candidates(workbook_path: str) -> dict:
    """
    Master rows with an Excavation End Date filled in - the permits that look
    finished and are candidates to move to the Completed tab.

    'Candidates', not 'ready'. The governing rule is that nothing leaves the
    Master until the Folder confirms completion, and this function cannot see
    the Folder's confirmation - only the date. So this is a shortlist for you
    to check, never an instruction.
    """
    try:
        wb, p = _open(workbook_path)
    except Exception as e:                               # noqa: BLE001
        return _fail(str(e))

    master = _find_tab(wb, TABS["master"])
    if master is None:
        wb.close()
        return _fail(f"Could not find the '{TABS['master']}' tab.")

    candidates = []
    for row, code in _column_values(master, MASTER_CODE, 2):
        end = master[f"{MASTER_EXC_END}{row}"].value
        if end is not None and str(end).strip() != "":
            if isinstance(end, datetime.datetime):
                end = end.date().isoformat()
            candidates.append({"row": row, "epr_code": str(code).strip(),
                               "excavation_end": str(end)})
    wb.close()
    _log("epr_move_candidates", {"path": p.name}, "ok",
         f"{len(candidates)} candidates")
    return _ok(workbook=p.name, candidate_count=len(candidates),
               candidates=candidates,
               reminder="These have an end date only. Nothing leaves the "
                        "Master until the Folder confirms completion - check "
                        "each one against the Folder before moving it.")


# ==============================================================================
# CHECK 3  -  Master numbering
# ==============================================================================
def epr_check_numbering(workbook_path: str) -> dict:
    """The Master's sequential numbers should run 1..N with no gaps or repeats."""
    try:
        wb, p = _open(workbook_path)
    except Exception as e:                               # noqa: BLE001
        return _fail(str(e))

    master = _find_tab(wb, TABS["master"])
    if master is None:
        wb.close()
        return _fail(f"Could not find the '{TABS['master']}' tab.")

    numbers, bad = [], []
    for row, raw in _column_values(master, MASTER_NUM, 2):
        try:
            numbers.append(int(float(str(raw).strip())))
        except (TypeError, ValueError):
            bad.append({"row": row, "value": str(raw)})
    wb.close()

    expected = list(range(1, len(numbers) + 1))
    gaps = sorted(set(expected) - set(numbers))
    repeats = sorted({n for n in numbers if numbers.count(n) > 1})
    tidy = not gaps and not repeats and not bad and numbers == expected

    return _ok(workbook=p.name, rows_numbered=len(numbers),
               sequential=tidy,
               missing_numbers=gaps[:20], repeated_numbers=repeats[:20],
               unreadable=bad[:20],
               note=("Numbering is clean." if tidy else
                     "Renumber the Master sequentially after this week's moves."))


# ==============================================================================
# CHECK 4  -  the row-4 trap in the DJ Summary
# ==============================================================================
def epr_check_summary_ranges(workbook_path: str) -> dict:
    """
    Look for COUNTA/COUNTIF formulas over the Folder that start at row 4.

    Row 4 is the Folder's header row. A range that begins there counts the
    header as a record and inflates the total by exactly one - which is small
    enough to look like an ordinary off-by-one in the reconciliation and send
    you hunting through the data for a permit that was never missing.
    """
    try:
        wb, p = _open(workbook_path, values=False)       # formulas, not values
    except Exception as e:                               # noqa: BLE001
        return _fail(str(e))

    summary = _find_tab(wb, TABS["summary"])
    if summary is None:
        wb.close()
        return _fail(f"Could not find the '{TABS['summary']}' tab.")

    folder_hint = _normalise(TABS["folder"])
    suspect, counted = [], 0
    pattern = re.compile(r"([A-Z]{1,3})(\d+)\s*:\s*([A-Z]{1,3})(\d+)")

    for row in summary.iter_rows():
        for cell in row:
            f = cell.value
            if not isinstance(f, str) or not f.startswith("="):
                continue
            upper = f.upper()
            if "COUNT" not in upper:
                continue
            counted += 1
            if folder_hint not in _normalise(f):
                continue
            for m in pattern.finditer(f):
                if int(m.group(2)) < DATA_START_FOLDER:
                    suspect.append({
                        "cell": cell.coordinate,
                        "starts_at_row": int(m.group(2)),
                        "formula": f[:180],
                    })
                    break
    wb.close()

    return _ok(workbook=p.name, count_formulas_examined=counted,
               problems=suspect, problem_count=len(suspect),
               note=("No range starts above row 5." if not suspect else
                     f"{len(suspect)} formula(s) start above row 5 and will "
                     f"count the header row. Each inflates its total by 1."))


# ==============================================================================
# CHECK 5  -  duplicates and overlaps
# ==============================================================================
def epr_check_duplicates(workbook_path: str) -> dict:
    """Repeated codes on one tab, and codes sitting on Master and Completed at once."""
    try:
        wb, p = _open(workbook_path)
    except Exception as e:                               # noqa: BLE001
        return _fail(str(e))

    def codes(sheet, col, start):
        out = {}
        if sheet is None:
            return out
        for row, v in _column_values(sheet, col, start):
            key = str(v).strip().upper()
            out.setdefault(key, []).append(row)
        return out

    folder = codes(_find_tab(wb, TABS["folder"]), MASTER_CODE, DATA_START_FOLDER)
    master = codes(_find_tab(wb, TABS["master"]), MASTER_CODE, 2)
    completed = codes(_find_tab(wb, TABS["completed"]), COMPLETED_CODE, 2)
    wb.close()

    def dupes(d):
        return {k: v for k, v in d.items() if len(v) > 1}

    on_both = sorted(set(master) & set(completed))
    return _ok(workbook=p.name,
               duplicates_in_folder=dupes(folder),
               duplicates_in_master=dupes(master),
               duplicates_in_completed=dupes(completed),
               on_master_and_completed=on_both,
               note=("Nothing repeated." if not (dupes(folder) or dupes(master)
                     or dupes(completed) or on_both) else
                     "A code on both Master and Completed means a move was "
                     "copied rather than moved. Check each one."))


# ==============================================================================
# THE MAIN EVENT  -  the reconciliation identity
# ==============================================================================
def epr_reconcile(workbook_path: str, expiring_soon: int = 0) -> dict:
    """
    Check the identity that governs the whole workbook:

        Folder total  =  Master + Completed + extended projects

    The extended projects are the ones tracked in the DJ Summary EXPIRING SOON
    block. They have left the Master but are not complete, so they belong to
    neither of the first two numbers. Pass how many there are as
    expiring_soon; this function will not guess at that.
    """
    counts = epr_tab_counts(workbook_path)
    if not counts.get("ok"):
        return counts

    c = counts["counts"]
    for needed in ("folder", "master", "completed"):
        if needed not in c:
            return _fail(f"Could not read the '{needed}' tab, so the "
                         f"reconciliation cannot be done.",
                         counts=c, detail=counts.get("tabs_not_found"))

    expiring = max(0, int(expiring_soon))
    accounted = c["master"] + c["completed"] + expiring
    diff = c["folder"] - accounted

    if diff == 0:
        verdict = "BALANCED"
        advice = "Folder matches Master + Completed + extended projects."
    elif diff > 0:
        verdict = "SHORT"
        advice = (f"The Folder has {diff} more record(s) than are accounted "
                  f"for. Something on the Folder is on neither the Master nor "
                  f"the Completed tab, or an extended project is not counted.")
    else:
        verdict = "OVER"
        advice = (f"{abs(diff)} more record(s) are accounted for than exist on "
                  f"the Folder. Usually a move that was copied instead of "
                  f"moved - run the duplicates check.")

    out = _ok(workbook=counts["workbook"],
              folder=c["folder"], master=c["master"], completed=c["completed"],
              expiring_soon=expiring, accounted_for=accounted,
              difference=diff, verdict=verdict, advice=advice,
              arithmetic=(f"{c['folder']} folder  vs  {c['master']} master + "
                          f"{c['completed']} completed + {expiring} extended "
                          f"= {accounted}"))
    if expiring == 0:
        out["reminder"] = ("expiring_soon was 0. If the DJ Summary EXPIRING "
                           "SOON block has entries, pass that number or this "
                           "will read SHORT by exactly that many.")
    _log("epr_reconcile", {"path": counts["workbook"]}, "ok", verdict)
    return out


def epr_move_mapping() -> dict:
    """
    The Master-to-Completed column mapping, for when you are doing a move.

    The two layouts agree up to column N and diverge from O onward, so copying
    O:Y straight across misfiles every field from Date Issued rightward - and
    it misfiles them into columns that already hold plausible-looking dates,
    so nothing looks obviously wrong afterwards.
    """
    return _ok(
        mapping=[{"master_column": src or "(none)",
                  "completed_column": dst, "field": label}
                 for src, dst, label in MOVE_MAPPING],
        warning="Columns A through N line up. From O onward they do not. "
                "A straight O:Y copy misfiles every field to the right of it.",
        placement="Insert into the Completed tab in Date Received order, not "
                  "appended to the bottom.")


def epr_full_check(workbook_path: str, expiring_soon: int = 0) -> dict:
    """Run every check and return one report."""
    return _ok(
        reconciliation=epr_reconcile(workbook_path, expiring_soon),
        move_candidates=epr_move_candidates(workbook_path),
        numbering=epr_check_numbering(workbook_path),
        summary_ranges=epr_check_summary_ranges(workbook_path),
        duplicates=epr_check_duplicates(workbook_path),
        reminder="Every number here is one you can check by hand. On a tab "
                 "that matters, do check it.")


# ==============================================================================
# REGISTRY  -  all level 1. Nothing here can change anything.
# ==============================================================================
REGISTRY = {
    "epr_reconcile":            (epr_reconcile, 1),
    "epr_tab_counts":           (epr_tab_counts, 1),
    "epr_move_candidates":      (epr_move_candidates, 1),
    "epr_check_numbering":      (epr_check_numbering, 1),
    "epr_check_summary_ranges": (epr_check_summary_ranges, 1),
    "epr_check_duplicates":     (epr_check_duplicates, 1),
    "epr_move_mapping":         (epr_move_mapping, 1),
    "epr_full_check":           (epr_full_check, 1),
}

ALWAYS_ASK: set = set()      # nothing here writes, so nothing needs a gate


def _obj(props, required):
    return {"type": "OBJECT", "properties": props, "required": required}


_PATH = {"type": "STRING",
         "description": "Full path to the EPR workbook (.xlsx)."}
_EXPIRING = {"type": "INTEGER",
             "description": "How many extended projects are in the DJ Summary "
                            "EXPIRING SOON block. Ask Paul if you do not know "
                            "- do not guess."}

DECLARATIONS = [
    {"name": "epr_reconcile",
     "description": "Check the EPR workbook balances: the Folder total should equal "
                    "Master plus Completed plus the extended projects in the DJ "
                    "Summary EXPIRING SOON block. Reports BALANCED, SHORT or OVER.",
     "parameters": _obj({"workbook_path": _PATH, "expiring_soon": _EXPIRING},
                        ["workbook_path"])},

    {"name": "epr_tab_counts",
     "description": "Count the data rows on the Folder, Master Tracker and Completed tabs.",
     "parameters": _obj({"workbook_path": _PATH}, ["workbook_path"])},

    {"name": "epr_move_candidates",
     "description": "List Master Tracker rows that have an Excavation End Date filled in, "
                    "which marks a permit as finished. These are candidates to move to the "
                    "Completed tab, but nothing moves until the Folder confirms completion.",
     "parameters": _obj({"workbook_path": _PATH}, ["workbook_path"])},

    {"name": "epr_check_numbering",
     "description": "Check the Master Tracker's sequential numbers run 1 to N with no gaps "
                    "or repeats.",
     "parameters": _obj({"workbook_path": _PATH}, ["workbook_path"])},

    {"name": "epr_check_summary_ranges",
     "description": "Check the DJ Summary's COUNT formulas over the Folder start at row 5. "
                    "A range starting at row 4 counts the header and inflates the total by one.",
     "parameters": _obj({"workbook_path": _PATH}, ["workbook_path"])},

    {"name": "epr_check_duplicates",
     "description": "Find EPR codes repeated on a tab, or sitting on both the Master and the "
                    "Completed tab at the same time.",
     "parameters": _obj({"workbook_path": _PATH}, ["workbook_path"])},

    {"name": "epr_move_mapping",
     "description": "Show which Master Tracker column goes to which Completed tab column when "
                    "moving a finished permit. The layouts differ from column O onward.",
     "parameters": _obj({}, [])},

    {"name": "epr_full_check",
     "description": "Run every EPR workbook check at once and return a single report.",
     "parameters": _obj({"workbook_path": _PATH, "expiring_soon": _EXPIRING},
                        ["workbook_path"])},
]


if __name__ == "__main__":
    import sys
    print("Troy EPR checker")
    print("  openpyxl available:", HAS_OPENPYXL)
    print("  checks registered :", len(REGISTRY))
    if len(sys.argv) > 1:
        expiring = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        print(json.dumps(epr_full_check(sys.argv[1], expiring),
                         indent=2, default=str))
    else:
        print("\nTo check a workbook:")
        print('  python troy_epr.py "C:\\path\\to\\EPR Master Tracker.xlsx" 6')
        print("  (the 6 is how many extended projects are in EXPIRING SOON)")
