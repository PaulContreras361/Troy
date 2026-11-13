"""Troy's doctor — keeps Troy healthy so Paul doesn't have to.

Four jobs, all in plain English for Paul:

1. CHECKUP     Tests every part of Troy with built-in sample files (PDF, photo,
               Excel, HTML, zip, CSV), checks the keys and AI models still work,
               and checks his own code compiles. A quick offline checkup runs by
               itself whenever Troy starts; the full one runs from Settings.
2. ERROR LOG   Every real problem Troy hits while Paul uses him (Python side and
               the phone/browser side) is written down with the time.
3. DOUBLE-CHECK  After Troy answers from a file, a second pass checks the facts in
               the answer against the file, fixes them, and checks once more.
4. SELF-REPAIR  Troy reads his error log and his own code from GitHub, writes a
               fix, tests it with the same checkup, and sends it to Paul as a
               proposal. Paul taps Approve (or Reject). One tap undoes a fix.
               Troy never changes his live code on his own, and he never rewrites
               this file — so a bad fix can't break the thing that undoes it.
"""

import ast
import base64
import io
import json
import os
import re
import sys
import time
import traceback
import types
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_dir = Path(os.environ.get("TROY_DOCTOR_DIR", "/tmp/troy_doctor"))
try:
    _dir.mkdir(parents=True, exist_ok=True)
except OSError:
    _dir = HERE / ".troy_doctor"
    _dir.mkdir(parents=True, exist_ok=True)
LOG_FILE = _dir / "errors.jsonl"
MAX_LOG = 200

# Files the repair job may change. Not this file: the doctor stays fixed so a bad
# repair can never break the Approve / Undo buttons.
REPAIRABLE = ["app.py", "troy_study.py", "troy_memory.py", "requirements.txt"]
REPAIR_MODEL = "claude-sonnet-5-5"
FIX_BRANCH_PREFIX = "troy-fix-"

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    CENTRAL = timezone.utc


def when(ts):
    """'Fri 1:43 PM' in Paul's time."""
    return datetime.fromtimestamp(ts, CENTRAL).strftime("%a %-I:%M %p")


# =====================================================================
# 2. ERROR LOG
# =====================================================================
_SECRET = re.compile(r"(sk-ant-[\w-]{6})[\w-]+|(AIza[\w-]{4})[\w-]+|(gh[pousr]_\w{4})\w+|(github_pat_\w{4})\w+")


def _scrub(text):
    """Never write a key into the log."""
    return _SECRET.sub(lambda m: next(g for g in m.groups() if g) + "…", str(text or ""))


def log_error(where, err=None, detail="", source="troy"):
    """Write one problem down. Never raises — logging must not break Troy."""
    try:
        trace = ""
        if err is not None:
            trace = "".join(traceback.format_exception(type(err), err, err.__traceback__))[-2500:]
        entry = {
            "t": time.time(), "where": where, "source": source,
            "kind": type(err).__name__ if err is not None else "",
            "msg": _scrub(err)[:400] if err is not None else "",
            "detail": _scrub(detail)[:600], "trace": _scrub(trace),
        }
        # Same problem again within 10 minutes: count it instead of a new line.
        log = read_log(MAX_LOG)
        if log:
            last = log[0]
            if (last["where"], last["kind"], last["msg"], last["detail"]) == \
                    (entry["where"], entry["kind"], entry["msg"], entry["detail"]) \
                    and entry["t"] - last["t"] < 600:
                last["n"] = last.get("n", 1) + 1
                last["t"] = entry["t"]
                _write_log(list(reversed(log)))
                return
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        if len(log) >= MAX_LOG:
            _write_log(list(reversed(log))[-MAX_LOG + 1:] + [entry])
    except Exception:
        pass


def _write_log(entries):
    LOG_FILE.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def read_log(n=50):
    """Newest first."""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
        if len(out) >= n:
            break
    return out


def clear_log():
    try:
        LOG_FILE.unlink()
    except OSError:
        pass


def take_browser_errors(payload):
    """Errors the phone/browser side sent up (see BROWSER_JS)."""
    try:
        items = json.loads(payload or "[]")
    except ValueError:
        return
    for it in items[:20]:
        msg = str(it.get("msg", ""))[:300]
        n = int(it.get("n", 1) or 1)
        log_error(str(it.get("kind", "page")), detail=msg + (f" (×{n})" if n > 1 else ""),
                  source="phone")


# Runs in the page. Catches script errors and broken promises, and watches for
# two voices playing at once. New problems are sent to Python in small batches.
BROWSER_JS = """
export default function(component) {
  const { setTriggerValue } = component;
  const W = window;
  if (!W.__troyDoc) {
    const D = W.__troyDoc = { list: [], sent: 0, timer: null };
    D.add = (kind, msg) => {
      msg = String(msg || "").slice(0, 300);
      if (!msg || /ResizeObserver loop/.test(msg)) return;
      const same = D.list.find(x => x.kind === kind && x.msg === msg && Date.now() - x.t < 600000);
      if (same) { same.n++; same.t = Date.now(); same.dirty = true; }
      else { D.list.push({ t: Date.now(), kind, msg, n: 1, dirty: true }); }
      if (D.list.length > 30) D.list.shift();
      clearTimeout(D.timer);
      D.timer = setTimeout(D.flush, 1500);
    };
    D.flush = () => {
      const fresh = D.list.filter(x => x.dirty);
      if (!fresh.length || !D.send) return;
      fresh.forEach(x => x.dirty = false);
      try { D.send("errors", JSON.stringify(fresh.map(({kind, msg, n}) => ({kind, msg, n})))); } catch (e) {}
    };
    W.addEventListener("error", (e) => {
      const where = e.filename ? " (" + e.filename.split("/").pop() + ":" + e.lineno + ")" : "";
      D.add("phone page error", (e.message || "script error") + where);
    });
    W.addEventListener("unhandledrejection", (e) => {
      const r = e.reason;
      const msg = (r && (r.message || r.name)) || String(r);
      // Browsers refuse to auto-play sound until the first tap. Expected, not a bug.
      if (/NotAllowedError|play\\(\\) request was interrupted|AbortError/.test(msg)) return;
      D.add("phone promise error", msg);
    });
    // Watchdog: Troy's human voice and the phone voice talking at the same time.
    let both = 0;
    setInterval(() => {
      const A = W.troyAudio;
      if (!A || !W.speechSynthesis) return;
      const playing = (el) => el && !el.paused && !el.ended && el.currentTime > 0.3 &&
                              el.src && !el.src.startsWith("data:");
      const wav = playing(A.el) || (A.eq && playing(A.eq.el));
      both = (wav && W.speechSynthesis.speaking) ? both + 1 : 0;
      if (both === 2) {
        D.add("voice", "Two voices played at once (human voice + phone voice)");
        // Adjust on the spot: keep the newer phone voice, stop the old recording.
        try { A.el.pause(); } catch (e) {}
        try { if (A.eq) A.eq.el.pause(); } catch (e) {}
      }
    }, 600);
  }
  W.__troyDoc.send = setTriggerValue;
}
"""


# =====================================================================
# 1. CHECKUP — sample files built in memory, no network needed
# =====================================================================
class _Upload:
    """Looks like a file Paul attached in the message box."""
    def __init__(self, name, data):
        self.name, self._data = name, data

    def getvalue(self):
        return self._data


def _text_pdf(lines):
    """A tiny real PDF with selectable text (what pypdf reads)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 10 Tf 50 760 Td 13 TL " + " ".join(f"({esc(l)}) '" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


_BODY = ("This section tells the crew what to do before any digging starts. "
         "Call Texas 811 and wait for the locates. Walk the area with the unit owner. "
         "Get every signature on the permit before the first shovel goes in the ground.")
SAMPLE_PDF_LINES = (["SAMPLE PROCEDURE 05 EXCAVATION"]
                    + ["1.0 PURPOSE"] + [_BODY[i:i + 90] for i in range(0, len(_BODY), 90)]
                    + ["2.0 SCOPE"] + [_BODY[i:i + 90] for i in range(0, len(_BODY), 90)]
                    + ["3.0 RESPONSIBILITIES"] + [_BODY[i:i + 90] for i in range(0, len(_BODY), 90)])


def sample_files():
    """Every kind of file Paul sends, built fresh in memory."""
    from PIL import Image
    import openpyxl

    files = {}
    files["sample.pdf"] = _text_pdf(SAMPLE_PDF_LINES)

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (14, 165, 164)).save(buf, "PNG")
    files["sample.png"] = buf.getvalue()

    # A big phone photo (noise doesn't compress) — Troy must shrink it under 5 MB.
    big = Image.frombytes("RGB", (2300, 2300), os.urandom(2300 * 2300 * 3))
    buf = io.BytesIO()
    big.save(buf, "JPEG", quality=95)
    files["big_photo.jpg"] = buf.getvalue()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EPR Master Tracker"
    ws.append(["#", "EPR ID", "Date Received", "Days"])
    ws.append([1, "NKC23", datetime(2026, 4, 2), 5])
    ws.append([2, "XKC74", datetime(2026, 4, 27), "=D2+1"])
    wb.create_sheet("DJ Summary").append(["Total", 2])
    buf = io.BytesIO()
    wb.save(buf)
    files["sample.xlsx"] = buf.getvalue()

    img = base64.b64encode(os.urandom(60_000)).decode()
    coords = "[" + ",".join(f"[{i}.25,{i * 2}.5]" for i in range(3000)) + "]"
    files["sample.html"] = (
        f"<!DOCTYPE html><html><body><img src=\"data:image/png;base64,{img}\">"
        f"<script>const UNITS = {coords};\nfunction drawMap(){{ return 'real code here'; }}</script>"
        "</body></html>").encode()

    files["sample.csv"] = b"EPR,Requester\nNKC23,Carol Wentz\n"
    files["sample.txt"] = b"Plain text note for Troy."

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("inside.csv", "a,b\n1,2\n")
        z.writestr("inside.md", "# Notes\nhello")
        z.writestr("setup.exe", b"MZ")           # Troy should skip this one
    files["sample.zip"] = buf.getvalue()

    files["broken.xlsx"] = b"this is not really an excel file"
    files["notes.doc"] = b"old word file"
    return files


class _Stub:
    """Stands in for Streamlit when Troy's code is tested outside the app."""
    def __init__(self):
        object.__setattr__(self, "session_state", _State())

    def __getattr__(self, name):
        def anything(*a, **k):
            if len(a) == 1 and callable(a[0]) and not k:
                return a[0]          # @st.cache_resource etc.: plain function
            return lambda f=None, *x, **y: f if callable(f) else _Stub()
        return anything


class _State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v

    def pop(self, k, d=None):
        return dict.pop(self, k, d)


_SAFE_CALLS = {"set", "frozenset", "dict", "list", "tuple", "int", "float", "str", "bytes", "len"}


def _plain_value(value):
    for n in ast.walk(value):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in _SAFE_CALLS:
                continue
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and \
                    (f.value.id, f.attr) in (("re", "compile"), ("os", "environ"), ("str", "join")):
                continue
            if isinstance(f, ast.Attribute) and f.attr in ("join", "format", "strip", "upper",
                                                           "lower", "replace", "get"):
                continue
            return False
    return True


def load_app_parts(app_src):
    """Pull Troy's definitions out of app.py WITHOUT running the app: every
    import, constant and function, with Streamlit swapped for a stand-in."""
    tree = ast.parse(app_src)
    ns = {"__name__": "troy_app_under_test"}
    stub = _Stub()
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            if any(n.split(".")[0] == "streamlit" for n in names) or \
                    (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("streamlit")):
                continue
            keep.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            keep.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            seg = ast.get_source_segment(app_src, node) or ""
            if "st." in seg or "session_state" in seg:
                continue
            # Only plain settings (numbers, text, lists, dicts, re.compile). Anything
            # that CALLS app code would run the app — e.g. the startup checkup, which
            # would then load app.py again, forever.
            if node.value is not None and not _plain_value(node.value):
                continue
            keep.append(node)
    ns["st"] = stub
    for node in keep:
        mod = ast.Module(body=[node], type_ignores=[])
        try:
            exec(compile(mod, "app.py", "exec"), ns)
        except Exception:
            pass  # one odd line shouldn't hide the rest; the tests below will notice
    return ns


def _check(results, name, fn):
    try:
        ok, note = fn()
    except Exception as e:  # a crash is a failed check, never a crashed checkup
        ok, note = False, f"crashed: {type(e).__name__}: {str(e)[:160]}"
    results.append({"name": name, "ok": bool(ok), "note": note})


def offline_checks(app_src=None, study_src=None, memory_src=None):
    """Everything that can be tested without the internet. Takes source text so
    a proposed repair can be tested before it ever goes live."""
    if app_src is None:
        app_src = (HERE / "app.py").read_text(encoding="utf-8")
    if study_src is None:
        study_src = (HERE / "troy_study.py").read_text(encoding="utf-8")
    if memory_src is None:
        try:
            memory_src = (HERE / "troy_memory.py").read_text(encoding="utf-8")
        except OSError:
            memory_src = ""
    results = []

    def compiles(src, fname):
        def run():
            compile(src, fname, "exec")
            return True, "code is valid Python"
        return run
    _check(results, "Troy's main code (app.py) compiles", compiles(app_src, "app.py"))
    _check(results, "Study reader code (troy_study.py) compiles", compiles(study_src, "troy_study.py"))

    def packages():
        missing = []
        for mod in ("streamlit", "anthropic", "google.genai", "PIL", "pypdf", "pypdfium2",
                    "openpyxl", "zoneinfo"):
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        return (not missing, "all installed" if not missing else "missing: " + ", ".join(missing))
    _check(results, "Python packages installed", packages)

    try:
        ns = load_app_parts(app_src)
        samples = sample_files()
    except Exception as e:
        results.append({"name": "Load Troy's file readers", "ok": False,
                        "note": f"{type(e).__name__}: {str(e)[:160]}"})
        return results
    file_parts = ns.get("file_parts")
    types_ok = ns.get("FILE_TYPES") or {}

    def read(name):
        parts, problem = file_parts([_Upload(name, samples[name])])
        return parts, problem

    def t_pdf():
        parts, prob = read("sample.pdf")
        return (not prob and parts and parts[0]["mime"] == "application/pdf",
                prob or "PDF goes to the brain as a document")

    def t_png():
        parts, prob = read("sample.png")
        return (not prob and parts and parts[0]["mime"] == "image/png", prob or "photo accepted")

    def t_big():
        parts, prob = read("big_photo.jpg")
        size = len(parts[0]["data"]) if parts else 0
        return (not prob and 0 < size < 5_000_000,
                prob or f"{len(samples['big_photo.jpg']) // 1024} KB photo shrunk to {size // 1024} KB")

    def t_xlsx():
        parts, prob = read("sample.xlsx")
        txt = parts[0]["data"].decode("utf-8", "replace") if parts else ""
        good = ("Tab: EPR Master Tracker" in txt and "NKC23" in txt and "04/02/2026" in txt
                and "Tab: DJ Summary" in txt)
        return (not prob and good, prob or ("every tab read, dates readable" if good else
                                            "Excel text is missing rows, tabs or dates"))

    def t_html():
        parts, prob = read("sample.html")
        txt = parts[0]["data"].decode("utf-8", "replace") if parts else ""
        cut = len(txt) < len(samples["sample.html"]) // 2
        return (not prob and "real code here" in txt and cut,
                prob or (f"{len(samples['sample.html']) // 1024} KB page trimmed to "
                         f"{len(txt) // 1024} KB, code kept" if cut else "bulk data was not trimmed"))

    def t_text():
        bad = []
        for n in ("sample.csv", "sample.txt"):
            parts, prob = read(n)
            if prob or not parts:
                bad.append(n)
        return (not bad, "CSV and text read" if not bad else "failed: " + ", ".join(bad))

    def t_zip():
        parts, prob = read("sample.zip")
        names = sorted(p["name"] for p in parts or [])
        return (not prob and names == ["inside.csv", "inside.md"],
                prob or ("zip unpacked, unsafe .exe skipped" if names == ["inside.csv", "inside.md"]
                         else f"zip gave {names}"))

    def t_broken():
        parts, prob = read("broken.xlsx")
        return (bool(prob) and not parts, "damaged Excel gets a friendly message"
                if prob else "a damaged Excel file slipped through")

    def t_unknown():
        parts, prob = read("notes.doc")
        return (bool(prob), "unsupported file gets a friendly message" if prob
                else "an unsupported file slipped through")

    def t_types():
        want = {"pdf", "png", "jpg", "xlsx", "html", "csv", "txt", "zip"}
        missing = sorted(want - set(types_ok))
        return (not missing, "upload box takes " + ", ".join(sorted(types_ok)) if not missing
                else "upload box is missing: " + ", ".join(missing))

    def t_blocks():
        cb = ns.get("claude_blocks")
        parts, _ = file_parts([_Upload(n, samples[n]) for n in
                               ("sample.pdf", "sample.png", "sample.xlsx", "sample.csv")])
        blocks = cb(parts, "test")
        kinds = [b["type"] for b in blocks]
        return (kinds == ["document", "image", "text", "text", "text"],
                "files packed for Claude correctly" if kinds[:2] == ["document", "image"]
                else f"unexpected packing: {kinds}")

    def t_speech():
        st_ = ns.get("speech_text")
        out = st_("**Hello** _there_ [link](http://x) `code`")
        return ("*" not in out and "http" not in out, f"voice text cleaned: “{out}”")

    if not callable(file_parts):
        results.append({"name": "File reader found", "ok": False, "note": "file_parts is missing"})
    else:
        for name, fn in (("Upload box file types", t_types), ("PDF", t_pdf), ("Photo", t_png),
                         ("Big phone photo", t_big), ("Excel (.xlsx)", t_xlsx),
                         ("HTML / code file", t_html), ("CSV and text", t_text), ("Zip", t_zip),
                         ("Damaged file", t_broken), ("Unsupported file", t_unknown),
                         ("Packing files for Claude", t_blocks), ("Voice text cleanup", t_speech)):
            _check(results, "Reads: " + name if name not in
                   ("Packing files for Claude", "Voice text cleanup", "Upload box file types",
                    "Damaged file", "Unsupported file") else name, fn)

    def t_study():
        mod = types.ModuleType("troy_study_under_test")
        exec(compile(study_src, "troy_study.py", "exec"), mod.__dict__)
        r = mod.split_sections(samples["sample.pdf"])
        secs = r.get("sections") or []
        # The sample has headings 1.0 / 2.0 / 3.0: all three must be found as sections.
        titles = " ".join(s.get("title", "") for s in secs).upper()
        good = (r.get("method") == "headings" and len(secs) == 3
                and all(w in titles for w in ("PURPOSE", "SCOPE", "RESPONSIBILITIES"))
                and mod.sentences(secs[0]["text"]))
        return (bool(good), "3 of 3 headings found, sentences split for read-along" if good
                else f"Study mode split the sample PDF wrong: {len(secs)} sections by {r.get('method')}")
    _check(results, "Study a PDF: sections and sentences", t_study)

    def t_pictures():
        mod = types.ModuleType("troy_study_pics")
        exec(compile(study_src, "troy_study.py", "exec"), mod.__dict__)
        pics = list(mod.page_images(samples["sample.pdf"]))
        return (len(pics) >= 1, f"{len(pics)} page picture(s) made for scanned PDFs")
    _check(results, "Study a PDF: page pictures (scanned PDFs)", t_pictures)

    def t_memory():
        mod = types.ModuleType("troy_memory_under_test")
        exec(compile(memory_src, "troy_memory.py", "exec"), mod.__dict__)
        m, ch = mod.add_fact(mod.empty(), "Prefers step-by-step instructions", "preference")
        m, ch2 = mod.add_fact(m, "Works on EPR permits", "project")
        m, ch3 = mod.add_fact(m, "Prefers step-by-step instructions", "preference")   # duplicate
        m, ch4 = mod.add_fact(m, "my key is sk-ant-abc123secret", "about")              # secret
        block = mod.for_instructions(m)
        fid = m["facts"][0]["id"]
        gone, _ = mod.remove_fact(m, fid)
        newer = mod.merge(m, gone)          # the newer copy (the deletion) must win
        good = (ch and ch2 and not ch3 and not ch4 and len(m["facts"]) == 2
                and "step-by-step" in block and len(newer["facts"]) == 1)
        return (good, "learns, skips duplicates and secrets, forgetting sticks" if good
                else f"memory misbehaved: {len(m['facts'])} facts, dup={ch3}, secret={ch4}")
    _check(results, "Memory: learn, forget, never store secrets", t_memory)

    def t_think():
        mod = types.ModuleType("troy_think_under_test")
        exec(compile(memory_src, "troy_memory.py", "exec"), mod.__dict__)
        quick = mod.thinking_plan("auto", "hey Troy, good morning", False)
        work = mod.thinking_plan("auto", "Check my EPR tracker and tell me what moves", False)
        files = mod.thinking_plan("auto", "thanks", True)
        deep = mod.thinking_plan("deep", "hi", False)
        good = (not quick[1] and work[1] and files[1] and deep[1]
                and work[0] == deep[0] != quick[0])
        return (good, f"small talk → {quick[2]}; real work → {work[2]}" if good
                else "Troy decides is routing questions to the wrong model")
    _check(results, "How Troy thinks: picks quick vs deep", t_think)
    return results


def startup_signature():
    """Changes whenever Troy's code changes, so the startup check re-runs."""
    sig = []
    for f in ("app.py", "troy_study.py", "troy_memory.py", "troy_doctor.py", "requirements.txt"):
        try:
            s = (HERE / f).stat()
            sig.append(f"{f}:{s.st_size}:{int(s.st_mtime)}")
        except OSError:
            sig.append(f"{f}:missing")
    return "|".join(sig)


# ---- Online checks (keys and AI models). Free calls only, except the voice test.
def online_checks(claude_client=None, claude_model=None, gemini_client=None,
                  tts_models=(), voice_test=None, github=None):
    results = []

    if claude_client is not None:
        for model in ([claude_model] if isinstance(claude_model, str) else list(claude_model)):
            def t_claude(model=model):
                m = claude_client.models.retrieve(model)
                return True, f"key works; {getattr(m, 'display_name', model)} is available"
            _check(results, f"Claude key and model {model}", t_claude)
    else:
        results.append({"name": "Claude key", "ok": False, "note": "no Claude key found"})

    if gemini_client is not None:
        def t_gem():
            gemini_client.models.get(model="gemini-2.5-flash")
            return True, "key works; gemini-2.5-flash is available (voice-to-text)"
        _check(results, "Gemini key (voice-to-text)", t_gem)

        def t_tts():
            for m in tts_models:
                try:
                    gemini_client.models.get(model=m)
                    return True, f"human voice model available: {m}"
                except Exception:
                    continue
            return False, "none of Troy's human-voice models are available — Google may have retired them"
        _check(results, "Human voice model", t_tts)
    else:
        results.append({"name": "Gemini key", "ok": False,
                        "note": "no Gemini key — voice messages and human voice are off"})

    if voice_test is not None:
        def t_voice():
            wav = voice_test()
            return (bool(wav) and len(wav) > 1000, f"human voice made {len(wav or b'') // 1024} KB of audio")
        _check(results, "Human voice test (1 voice call)", t_voice)

    if github is not None:
        def t_gh():
            info = github.api("GET", f"/repos/{github.repo}")
            can = (info.get("permissions") or {}).get("push")
            return bool(can), ("GitHub key can propose fixes to " + github.repo) if can else \
                "GitHub key can read but not write — it needs Contents and Pull requests: Read and write"
        _check(results, "GitHub key (self-repair)", t_gh)
    return results


# =====================================================================
# 3. DOUBLE-CHECK — Troy's QA/QC on answers about files
# =====================================================================
QA_SYSTEM = """You are the quality checker for Troy, Paul's assistant. You get the same
file(s) Troy read, Paul's question, and Troy's answer. Check every specific fact in the
answer — numbers, counts, totals, names, dates, IDs, row/column/cell references, and
anything said to be in (or missing from) the file — against the file itself.
Do not judge style. Do not add new information Paul didn't ask for.
Reply with ONLY this JSON, nothing else:
{"verdict": "ok" | "fixed" | "unsure",
 "problems": ["short plain-English note for each wrong or unconfirmable fact"],
 "corrected_answer": "the full answer with only the wrong facts fixed, same voice and length (only when verdict is fixed)"}
Use "ok" when every checked fact matches. Use "fixed" when something was wrong and you can
fix it from the file. Use "unsure" when facts can't be confirmed from the file."""


def _json_from(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 else {}


def double_check(claude_client, model, file_blocks, question, answer, rounds=2):
    """Check the answer against the files; fix and re-check (quick loop).
    Returns (final_answer, footer). Never raises: if the checker itself fails,
    Paul still gets Troy's answer, and the failure is logged."""
    current, fixes = answer, []
    try:
        for r in range(rounds):
            msg = claude_client.messages.create(
                model=model, max_tokens=4096, system=QA_SYSTEM,
                messages=[{"role": "user", "content": list(file_blocks) + [{
                    "type": "text",
                    "text": f"PAUL ASKED:\n{question}\n\nTROY ANSWERED:\n{current}"}]}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            v = _json_from(raw)
            verdict = v.get("verdict")
            problems = [str(p) for p in (v.get("problems") or []) if str(p).strip()][:5]
            if verdict == "fixed" and str(v.get("corrected_answer", "")).strip():
                current = v["corrected_answer"].strip()
                fixes += problems
                continue                     # check the corrected answer once more
            if verdict == "unsure":
                note = "; ".join(problems) or "some facts couldn't be found in the file"
                lead = ("🔎 Double-checked and fixed: " + "; ".join(fixes) + ". ") if fixes else ""
                return current, lead + "⚠️ Couldn't confirm against the file: " + note
            if fixes:
                return current, "🔎 Double-checked against your file and fixed: " + "; ".join(fixes)
            return current, "🔎 Double-checked against your file."
        return current, ("🔎 Double-checked and fixed: " + "; ".join(fixes)
                         + ". (Still changing after two checks — worth a look.)")
    except Exception as e:
        log_error("double-checking an answer", e)
        return answer, ""


# =====================================================================
# 4. SELF-REPAIR — proposals on GitHub that Paul approves
# =====================================================================
class GitHub:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo

    def api(self, method, path, body=None):
        req = urllib.request.Request(
            "https://api.github.com" + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "troy-doctor"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"GitHub said {e.code}: {detail}") from None

    def get_file(self, path, ref="main"):
        d = self.api("GET", f"/repos/{self.repo}/contents/{path}?ref={ref}")
        return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]

    def put_file(self, path, text, message, branch, sha=None):
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(text.encode("utf-8")).decode()}
        if sha:
            body["sha"] = sha
        return self.api("PUT", f"/repos/{self.repo}/contents/{path}", body)


def github_from(secret_get):
    token = secret_get("GITHUB_TOKEN")
    if not token:
        return None
    return GitHub(token, secret_get("TROY_REPO") or "PaulContreras361/troy")


REPAIR_SYSTEM = """You repair Troy, a Streamlit (Python) personal assistant app used on an
iPhone and a Windows laptop. You get the problems Troy recorded and his current code.
Make the SMALLEST change that fixes the problems. Keep every existing feature and the
plain-English comments style. Never put keys or secrets in code. Only change these files:
app.py, troy_study.py, requirements.txt.

Reply with ONLY this JSON:
{"summary": "2-4 plain-English sentences for Paul: what was wrong and what you changed",
 "can_fix": true or false,
 "edits": [{"file": "app.py", "find": "exact text copied from the file", "replace": "new text"}]}

Rules for edits: "find" must be copied EXACTLY from the file (spaces and line breaks
included) and must appear exactly once in that file — include a few surrounding lines to
make it unique. If a problem is outside Troy's code (a key ran out of credit, Google
retired a model you can't replace safely, the phone's own settings), set can_fix false
and explain what Paul should do in the summary.
The summary is posted on a PUBLIC GitHub page: describe the code change only. Never include
file names Paul uploaded, anything he typed, names of people, or other personal details."""


def _apply_edits(files, edits):
    new = dict(files)
    for i, ed in enumerate(edits, 1):
        f = ed.get("file")
        if f not in REPAIRABLE:
            raise ValueError(f"edit {i} tries to change {f}, which repairs may not touch")
        find, repl = ed.get("find", ""), ed.get("replace", "")
        count = new[f].count(find) if find else 0
        if count != 1:
            raise ValueError(f"edit {i}: the text to replace appears {count} times in {f} (must be exactly once)")
        new[f] = new[f].replace(find, repl, 1)
    return new


def _failures(results):
    return {r["name"]: r["note"] for r in results if not r["ok"]}


def propose_fix(claude_client, github, problems_text, progress=lambda s: None):
    """Write a fix, test it, and open it on GitHub for Paul to approve.
    Returns a dict for the screen. Raises only for setup problems."""
    progress("Reading Troy's code from GitHub…")
    files, shas = {}, {}
    for f in REPAIRABLE:
        files[f], shas[f] = github.get_file(f)
    baseline = _failures(offline_checks(files["app.py"], files["troy_study.py"],
                                        files.get("troy_memory.py")))

    feedback, last_err = "", ""
    for attempt in (1, 2):                      # quick loop: one retry with the test results
        progress(f"Writing a fix (try {attempt} of 2)…")
        code = "\n\n".join(f"===== FILE: {f} =====\n{files[f]}" for f in REPAIRABLE)
        msg = claude_client.messages.create(
            model=REPAIR_MODEL, max_tokens=8000, system=REPAIR_SYSTEM,
            messages=[{"role": "user", "content":
                       f"PROBLEMS TROY RECORDED:\n{problems_text}\n\n{feedback}{code}"}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            plan = _json_from(raw)
        except ValueError:
            last_err, feedback = "the fix came back unreadable", "Your last reply was not valid JSON. "
            continue
        if not plan.get("can_fix", True) or not plan.get("edits"):
            return {"status": "no_code_fix", "summary": plan.get("summary", "No code change needed.")}
        try:
            new_files = _apply_edits(files, plan["edits"])
        except ValueError as e:
            last_err = str(e)
            feedback = f"Your last attempt could not be applied: {e}. Copy 'find' text exactly.\n\n"
            continue
        progress("Testing the fix with the full checkup…")
        after = offline_checks(new_files["app.py"], new_files["troy_study.py"],
                               new_files.get("troy_memory.py"))
        broke = {k: v for k, v in _failures(after).items() if k not in baseline}
        if broke:
            last_err = "the fix broke: " + "; ".join(f"{k} ({v})" for k, v in broke.items())
            feedback = ("Your last fix broke these checks, try again without breaking them: "
                        + json.dumps(broke) + "\n\n")
            continue
        fixed_checks = [k for k in baseline if k not in _failures(after)]
        progress("Sending the fix to GitHub for your approval…")
        branch = FIX_BRANCH_PREFIX + datetime.now(CENTRAL).strftime("%Y%m%d-%H%M%S")
        main_sha = github.api("GET", f"/repos/{github.repo}/git/ref/heads/main")["object"]["sha"]
        github.api("POST", f"/repos/{github.repo}/git/refs",
                   {"ref": f"refs/heads/{branch}", "sha": main_sha})
        changed = [f for f in REPAIRABLE if new_files[f] != files[f]]
        for f in changed:
            github.put_file(f, new_files[f], f"Troy self-repair: {f}", branch, shas[f])
        passed = sum(1 for r in after if r["ok"])
        # The repo is public: the proposal shows the code change and test results only —
        # never Troy's raw problem list (it can hold file names and what Paul typed).
        body = (plan["summary"]
                + f"\n\n**Checkup on this fix:** {passed} of {len(after)} checks passed"
                + (("; newly passing: " + ", ".join(fixed_checks)) if fixed_checks else "")
                + "\n\nApprove or reject this from Troy → Troy's health.")
        pr = github.api("POST", f"/repos/{github.repo}/pulls", {
            "title": "Troy self-repair: " + plan["summary"].split(".")[0][:70],
            "head": branch, "base": "main", "body": body})
        return {"status": "proposed", "summary": plan["summary"], "number": pr["number"],
                "url": pr["html_url"], "files": changed,
                "tests": f"{passed} of {len(after)} checks passed"}
    return {"status": "failed", "summary": "Troy couldn't make a fix that passes his checkup: " + last_err}


def pending_fixes(github):
    pulls = github.api("GET", f"/repos/{github.repo}/pulls?state=open&per_page=20")
    return [{"number": p["number"], "title": p["title"], "url": p["html_url"],
             "body": p.get("body") or "", "branch": p["head"]["ref"]}
            for p in pulls if p["head"]["ref"].startswith(FIX_BRANCH_PREFIX)]


def approve_fix(github, number, branch):
    github.api("PUT", f"/repos/{github.repo}/pulls/{number}/merge",
               {"merge_method": "squash", "commit_title": f"Troy self-repair #{number} (approved by Paul)"})
    try:
        github.api("DELETE", f"/repos/{github.repo}/git/refs/heads/{branch}")
    except Exception:
        pass


def reject_fix(github, number, branch):
    github.api("PATCH", f"/repos/{github.repo}/pulls/{number}", {"state": "closed"})
    try:
        github.api("DELETE", f"/repos/{github.repo}/git/refs/heads/{branch}")
    except Exception:
        pass


def last_applied_fix(github):
    pulls = github.api("GET", f"/repos/{github.repo}/pulls?state=closed&sort=updated"
                              f"&direction=desc&per_page=30")
    done = [p for p in pulls if p.get("merged_at") and p["head"]["ref"].startswith(FIX_BRANCH_PREFIX)]
    if not done:
        return None
    p = max(done, key=lambda p: p["merged_at"])
    return {"number": p["number"], "title": p["title"], "merge_sha": p["merge_commit_sha"],
            "merged_at": p["merged_at"]}


def undo_fix(github, fix):
    """Put the files back exactly as they were before that fix."""
    parent = github.api("GET", f"/repos/{github.repo}/commits/{fix['merge_sha']}")["parents"][0]["sha"]
    changed = github.api("GET", f"/repos/{github.repo}/pulls/{fix['number']}/files")
    for f in changed:
        path = f["filename"]
        _, now_sha = github.get_file(path)
        if f.get("status") == "added":
            github.api("DELETE", f"/repos/{github.repo}/contents/{path}",
                       {"message": f"Undo Troy self-repair #{fix['number']}", "sha": now_sha,
                        "branch": "main"})
            continue
        old_text, _ = github.get_file(path, ref=parent)
        github.put_file(path, old_text, f"Undo Troy self-repair #{fix['number']}", "main", now_sha)
    return [f["filename"] for f in changed]


def problems_for_repair(checks, log, paul_note=""):
    """One plain list of everything wrong, for the repair job."""
    lines = []
    if paul_note.strip():
        lines.append("Paul says: " + paul_note.strip())
    for r in checks or []:
        if not r["ok"]:
            lines.append(f"Checkup failed — {r['name']}: {r['note']}")
    for e in (log or [])[:15]:
        line = f"[{when(e['t'])}] {e['source']} — {e['where']}"
        if e.get("kind"):
            line += f" — {e['kind']}: {e.get('msg', '')}"
        if e.get("detail"):
            line += f" — {e['detail']}"
        if e.get("n", 1) > 1:
            line += f" (happened {e['n']} times)"
        if e.get("trace"):
            line += "\n    " + e["trace"].strip().splitlines()[-1][:300]
            frames = re.findall(r'File "[^"]*?([\w.]+)", line (\d+), in (\w+)', e["trace"])
            if frames:
                line += "\n    where: " + " → ".join(f"{f}:{n} {fn}" for f, n, fn in frames[-4:])
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":   # run the offline checkup from a terminal: python troy_doctor.py
    res = offline_checks()
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["name"] + " — " + r["note"])
    print(f"\n{sum(r['ok'] for r in res)} of {len(res)} passed")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
