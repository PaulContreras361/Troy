"""
troy_hotkey.py  -  Rev 0
Troy's push-to-talk desktop helper for Windows (Atticus-style).

  Hold Ctrl + Alt + Space, say what you need, let go.

What it does
  * Instant commands (no AI, no cost): open apps, put windows left/right/full
    on any screen, find files by what's inside them, web searches, websites,
    type a reply into the app you're in.
  * Everything else goes to Troy's brain (Claude), which can see your screen
    when you ask about it, and answers out loud.
  * Anything that changes a file goes through troy_hands.py and waits for
    your Allow. The brain can NOT run commands at all. Typing never presses
    Enter, so it never sends anything.
  * No auto-update. Nothing downloads new code by itself.

It is standalone: it edits none of Troy's other files. Its settings, log and
screenshots live in %LOCALAPPDATA%\\TroyHotkey (outside the GitHub folder).

Run:
  py troy_hotkey.py --check        see what's installed
  py troy_hotkey.py --selftest     test the logic (no mic needed)
  py troy_hotkey.py --text "open notepad"   run one request by typing
  pyw troy_hotkey.py               normal use (no black window)
"""

import os
import sys
import re
import json
import time
import queue
import shutil
import base64
import datetime
import threading
import subprocess
import webbrowser
import urllib.parse
import urllib.request
import urllib.error

# ============================== SETTINGS ==============================
HOTKEY = "ctrl+alt+space"          # hold this to talk
TALK_KEY = "space"                 # recording stops when this is let go
QUIT_HOTKEY = "ctrl+alt+shift+q"   # closes Troy Hotkey

BRAIN = "claude_code"              # "claude_code" = your Pro plan (no per-ask charge)
                                   # "api"         = your Claude API key (Console credits)
CLAUDE_CODE_MODEL = "haiku"        # fast model inside Claude Code
API_MODEL = "claude-haiku-5-5"     # model when BRAIN = "api"
BRAIN_TIMEOUT = 120                # seconds before giving up on the brain

WHISPER_MODEL = "base.en"          # speech model (~150 MB, downloads once)
SPEAK_REPLIES = True               # Troy says the answer out loud
SAFE_MODE = True                   # Allow box before any file change (leave on)

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "TroyHotkey")
HERE = os.path.dirname(os.path.abspath(__file__))
# ======================================================================

IS_WINDOWS = sys.platform.startswith("win")


# ------------------------------ log ------------------------------------
def log(entry):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        entry = dict(entry, time=datetime.datetime.now().isoformat(timespec="seconds"))
        with open(os.path.join(DATA_DIR, "hotkey_log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ============================ INSTANT COMMANDS ==========================
SIDE_WORDS = [
    ("full screen", "full"), ("fullscreen", "full"), ("maximized", "full"), ("maximize", "full"),
    ("full", "full"), ("left", "left"), ("right", "right"), ("top", "top"),
    ("bottom", "bottom"), ("middle", "center"), ("center", "center"),
]
SCREEN_WORDS = [
    ("second screen", "second"), ("second monitor", "second"), ("other screen", "second"),
    ("other monitor", "second"), ("monitor 2", "second"), ("screen 2", "second"),
    ("monitor two", "second"), ("screen two", "second"), ("external", "second"),
    ("big screen", "big"), ("big monitor", "big"), ("large screen", "big"),
    ("laptop", "laptop"), ("main screen", "main"), ("main monitor", "main"),
    ("first screen", "main"), ("monitor 1", "main"), ("screen 1", "main"),
]


def clean(text):
    """Lowercase, drop wake words and end punctuation."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(hey |ok |okay )?troy[,\s]+", "", t)
    t = re.sub(r"[.!?,;:]+$", "", t).strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _looks_like_site(s):
    return bool(re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?", s.strip()))


def parse_instant(text):
    """Return one action dict if this is a simple command, else None (goes to the brain)."""
    raw = (text or "").strip()
    raw_nowake = re.sub(r"^(hey |ok |okay )?troy[,\s]+", "", raw, flags=re.I)
    t = clean(raw)
    if not t:
        return None

    if t in ("never mind", "nevermind", "cancel", "stop", "stop talking", "nothing"):
        return {"do": "none"}

    # type / reply  (keeps your capitals and punctuation)
    m = re.match(r"^(?:type|reply)\s*:?\s+(.+)$", raw_nowake, flags=re.I | re.S)
    if m:
        return {"do": "type_text", "text": m.group(1).strip()}

    # websites
    m = re.match(r"^(?:go to|open|open site|open website|visit)\s+(\S+)$", t)
    if m and _looks_like_site(m.group(1)):
        return {"do": "open_url", "url": m.group(1)}

    # web search
    m = re.match(r"^(?:search the web for|search for|search|google|look up)\s+(.+)$", t)
    if m:
        return {"do": "web_search", "query": m.group(1)}

    # find files
    m = re.match(r"^(?:find|locate|where is|where are|where's)\s+(?:my\s+|the\s+|all\s+)?(.+)$", t)
    if m:
        return {"do": "find_files", "query": m.group(1)}

    # maximize X
    m = re.match(r"^maximize\s+(?:the\s+|my\s+)?(.+)$", t)
    if m and not re.search(r"\b(and)\b|,", m.group(1)):
        return {"do": "arrange", "app": m.group(1), "where": "full", "screen": None}

    # X on the left / X on my second screen / move X to the right
    m = re.match(r"^(?:put |move |snap |open |throw )?(?:the\s+|my\s+)?(.+?)\s+(?:on|to|onto)\s+(?:the\s+|my\s+)?(.+)$", t)
    if m:
        app, tail = m.group(1).strip(), m.group(2)
        if not re.search(r"\b(and|then)\b|,", app) and not re.search(r"\b(and|then)\b|,", tail):
            where = next((v for k, v in SIDE_WORDS if re.search(r"\b" + re.escape(k) + r"\b", tail)), None)
            screen = next((v for k, v in SCREEN_WORDS if k in tail), None)
            if where or screen:
                return {"do": "arrange", "app": app, "where": where or "full", "screen": screen}

    # open X
    m = re.match(r"^(?:please\s+)?(?:open|launch|start|run|bring up|pull up)\s+(?:up\s+)?(?:the\s+|my\s+)?(.+)$", t)
    if m and not re.search(r"\b(and|then|with|on|to)\b|,", m.group(1)):
        return {"do": "open_app", "name": m.group(1)}

    return None


def needs_screen(text):
    t = clean(text)
    return bool(re.search(
        r"\b(screen|this|that|here|looking at|on my display|what's wrong|whats wrong|"
        r"what is wrong|read (it|this|that)|explain (it|this|that)|summarize (it|this|that))\b", t))


def extract_json(text):
    """Pull the {...} answer out of the brain's reply."""
    if not text:
        return {"say": "", "actions": []}
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        try:
            obj = json.loads(text[s:e + 1])
            if isinstance(obj, dict):
                obj.setdefault("say", "")
                acts = obj.get("actions") or []
                obj["actions"] = [a for a in acts if isinstance(a, dict)]
                return obj
        except Exception:
            pass
    return {"say": text.strip(), "actions": []}


# ============================== SCREENS ================================
def pick_monitor(mons, screen, current=None):
    """mons: list of dicts with x,y,w,h,primary. screen: main/second/big/laptop/None."""
    if not mons:
        return None
    primary = next((m for m in mons if m.get("primary")), mons[0])
    if screen == "main":
        return primary
    if screen == "second":
        others = sorted([m for m in mons if m is not primary], key=lambda m: (m["x"], m["y"]))
        return others[0] if others else primary
    if screen == "big":
        return max(mons, key=lambda m: m["w"] * m["h"])
    if screen == "laptop":
        return min(mons, key=lambda m: m["w"] * m["h"])
    return current or primary


def place_rect(mon, where):
    x, y, w, h = mon["x"], mon["y"], mon["w"], mon["h"]
    if where == "left":
        return x, y, w // 2, h
    if where == "right":
        return x + w // 2, y, w - w // 2, h
    if where == "top":
        return x, y, w, h // 2
    if where == "bottom":
        return x, y + h // 2, w, h - h // 2
    if where == "center":
        cw, ch = int(w * 0.7), int(h * 0.8)
        return x + (w - cw) // 2, y + (h - ch) // 2, cw, ch
    return x, y, w, h   # full


# =========================== WINDOWS HANDS ==============================
APP_ALIASES = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "paint": "mspaint.exe", "file explorer": "explorer.exe", "explorer": "explorer.exe",
    "files": "explorer.exe", "task manager": "taskmgr.exe", "command prompt": "cmd.exe",
    "cmd": "cmd.exe", "powershell": "powershell.exe", "terminal": "wt.exe",
    "settings": "ms-settings:", "snipping tool": "snippingtool.exe",
}
EXE_HINTS = {
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge",
    "terminal": "windowsterminal", "code": "code", "vs code": "code", "vscode": "code",
    "visual studio code": "code", "explorer": "explorer", "file explorer": "explorer",
    "autocad": "acad", "excel": "excel", "word": "winword", "outlook": "outlook",
    "powerpoint": "powerpnt", "notepad": "notepad", "calculator": "calculatorapp",
    "teams": "ms-teams", "spotify": "spotify", "google earth": "googleearth",
}
START_MENU_DIRS = [
    os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
]
FENCE = [os.path.join(os.path.expanduser("~"), d) for d in ("Desktop", "Documents", "Downloads", "Pictures")] \
        + [f"{d}:\\" for d in "DEFGH"]

_user32 = None


def _win():
    """Load ctypes Windows bits only when on Windows."""
    global _user32
    if _user32 is None:
        import ctypes
        _user32 = ctypes.windll.user32
    return _user32


def monitors():
    import ctypes
    from ctypes import wintypes
    user32 = _win()

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    out = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_ssize_t)

    def cb(hmon, hdc, rect, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi))
        r = mi.rcWork
        out.append({"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top,
                    "primary": bool(mi.dwFlags & 1), "handle": hmon})
        return 1

    user32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return out


def monitor_of(hwnd, mons):
    import ctypes
    h = _win().MonitorFromWindow(ctypes.c_void_p(hwnd), 2)
    for m in mons:
        if m["handle"] == h:
            return m
    return None


def windows_list():
    import ctypes
    from ctypes import wintypes
    user32 = _win()
    try:
        import psutil
    except Exception:
        psutil = None
    out = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)

    def cb(hwnd, lp):
        if not user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            return True
        n = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, n + 1)
        title = buf.value
        if title in ("Troy Hotkey", "Program Manager", "Allow?"):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        exe = ""
        if psutil:
            try:
                exe = os.path.splitext(psutil.Process(pid.value).name())[0].lower()
            except Exception:
                pass
        out.append({"hwnd": hwnd, "title": title, "exe": exe})
        return True

    user32.EnumWindows(PROC(cb), 0)
    return out


def find_window(name):
    name = clean(name)
    hint = EXE_HINTS.get(name, name.replace(" ", ""))
    best, score = None, 0
    for w in windows_list():
        s = 0
        if w["exe"] and w["exe"] == hint:
            s = 100
        elif w["exe"] and (hint in w["exe"] or w["exe"] in hint):
            s = 70
        elif name in w["title"].lower():
            s = 50
        if s > score:
            best, score = w, s
    return best


def _start_menu_lookup(name):
    name = clean(name)
    words = name.split()
    best, best_score = None, 0
    for root in START_MENU_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for f in files:
                if not f.lower().endswith((".lnk", ".url")):
                    continue
                stem = os.path.splitext(f)[0].lower()
                if re.search(r"uninstall|readme|help|license|documentation", stem):
                    continue
                if stem == name:
                    s = 100
                elif stem.startswith(name):
                    s = 85 - min(len(stem) - len(name), 30) * 0.5
                elif name in stem:
                    s = 70 - min(len(stem) - len(name), 30) * 0.5
                elif all(wd in stem for wd in words):
                    s = 55
                else:
                    continue
                if s > best_score:
                    best, best_score = os.path.join(dirpath, f), s
    return best


def open_app(name):
    name_c = clean(name)
    if _looks_like_site(name_c):
        return open_url(name_c)
    target = APP_ALIASES.get(name_c) or _start_menu_lookup(name_c)
    if not target:
        return f"I couldn't find an app called {name}."
    try:
        os.startfile(target)
        return f"Opening {name}."
    except Exception as e:
        return f"Couldn't open {name} ({e})."


def arrange(app, where="full", screen=None):
    user32 = _win()
    w = find_window(app)
    if not w:
        msg = open_app(app)
        if msg.startswith(("I couldn't", "Couldn't")):
            return msg
        for _ in range(40):
            time.sleep(0.25)
            w = find_window(app)
            if w:
                break
        if not w:
            return f"{app} opened, but its window didn't show up in time."
    mons = monitors()
    mon = pick_monitor(mons, screen, monitor_of(w["hwnd"], mons))
    if not mon:
        return "I couldn't read your screens."
    import ctypes
    h = ctypes.c_void_p(w["hwnd"])
    user32.ShowWindow(h, 9)                      # restore
    x, y, cw, ch = place_rect(mon, where)
    user32.SetWindowPos(h, None, x, y, cw, ch, 0x0004 | 0x0040)
    if where == "full":
        user32.ShowWindow(h, 3)                  # maximize on that screen
    user32.SetForegroundWindow(h)
    spot = {"full": "full screen", "center": "the middle"}.get(where, f"the {where}")
    return f"{app.title()} is on {spot}" + (f" of the {screen} screen." if screen else ".")


def _search_terms(q):
    q = re.sub(r"\b(my|the|a|an|file|files|about|for|on|in|of|named|called)\b", " ", q.lower())
    out = []
    for wd in re.findall(r"[\w-]+", q):
        if len(wd) > 4 and wd.endswith("s"):
            wd = wd[:-1]
        out.append(wd)
    return out[:6]


def find_files(query, limit=10):
    terms = _search_terms(query)
    if not terms:
        return [], "Tell me what to look for."
    results = []
    try:   # Windows Search index (searches inside files too)
        import win32com.client
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        cond = " AND ".join(f"(CONTAINS(*, '\"{t}*\"') OR System.FileName LIKE '%{t}%')" for t in terms)
        sql = (f"SELECT TOP {limit} System.ItemPathDisplay FROM SYSTEMINDEX "
               f"WHERE {cond} AND System.ItemType <> 'Directory' ORDER BY System.DateModified DESC")
        rs = conn.Execute(sql)[0]
        while not rs.EOF:
            results.append(rs.Fields.Item("System.ItemPathDisplay").Value)
            rs.MoveNext()
        conn.Close()
    except Exception:
        pass
    if not results:   # slow fallback: file names only, inside the fence, 8 s max
        stop = time.time() + 8
        for root in FENCE:
            if not os.path.isdir(root):
                continue
            for dp, dns, fns in os.walk(root):
                dns[:] = [d for d in dns if not d.startswith(".") and d.lower() not in
                          ("windows", "program files", "program files (x86)", "appdata", "$recycle.bin")]
                for f in fns:
                    fl = f.lower()
                    if all(t in fl for t in terms):
                        results.append(os.path.join(dp, f))
                        if len(results) >= limit:
                            break
                if len(results) >= limit or time.time() > stop:
                    break
            if len(results) >= limit or time.time() > stop:
                break
    if not results:
        return [], f"I didn't find anything for {query}."
    try:
        subprocess.Popen(f'explorer /select,"{results[0]}"')
    except Exception:
        pass
    n = len(results)
    return results, f"Found {n} match{'es' if n != 1 else ''}. Top one is {os.path.basename(results[0])}."


def open_file(path):
    if not path or not os.path.exists(path):
        return f"That file isn't there: {path}"
    os.startfile(path)
    return f"Opening {os.path.basename(path)}."


def open_url(url):
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."


def web_search(q):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))
    return f"Searching for {q}."


def type_text(text, target_hwnd=None):
    import keyboard
    import ctypes
    text = (text or "").replace("\r", " ").replace("\n", " ")   # never presses Enter
    if target_hwnd:
        _win().SetForegroundWindow(ctypes.c_void_p(target_hwnd))
        time.sleep(0.25)
    keyboard.write(text, delay=0.005)
    return "Typed it. I didn't send it."


def file_op(op, src, dst, allow):
    """File changes go through Troy's own troy_hands.py, after your Allow."""
    sys.path.insert(0, HERE)
    try:
        import troy_hands
    except Exception:
        return "troy_hands.py isn't in the Troy folder, so I can't change files."
    if op not in ("move", "copy", "rename", "delete", "make_folder"):
        return f"I can't do '{op}'."
    fn = getattr(troy_hands, op, None)
    if not fn:
        return f"troy_hands has no {op}."
    args = [src] + ([dst] if op in ("move", "copy", "rename") else [])
    try:
        plan = fn(*args)                       # confirm=False -> plain-English plan
    except TypeError as e:
        return f"troy_hands didn't accept that ({e})."
    if SAFE_MODE and not allow(f"{op.replace('_', ' ').title()}\n\n{plan}"):
        return "Okay, I left it alone."
    try:
        return str(fn(*args, confirm=True))
    except Exception as e:
        return f"That didn't work ({e})."


# ============================== SCREENSHOT ==============================
def grab_screen():
    """Screenshot of the screen you're on, shrunk for the brain. Returns file path or None."""
    try:
        from PIL import ImageGrab
        user32 = _win()
        mons = monitors()
        fg = user32.GetForegroundWindow()
        mon = monitor_of(fg, mons) if fg else None
        if mon:
            import ctypes
            from ctypes import wintypes

            class MI(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            mi = MI()
            mi.cbSize = ctypes.sizeof(MI)
            user32.GetMonitorInfoW(ctypes.c_void_p(mon["handle"]), ctypes.byref(mi))
            r = mi.rcMonitor
            img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
        else:
            img = ImageGrab.grab()
        img.thumbnail((1568, 1568))
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "screen.png")
        img.save(path, "PNG")
        return path
    except Exception:
        return None


# ================================ BRAIN =================================
BRAIN_RULES = """You are Troy, Paul's personal assistant on his Windows laptop.
Reply with ONLY one JSON object, nothing else:
{"say": "<1-2 short plain-English sentences Troy says out loud>", "actions": [ ... ]}

Allowed actions (use only these, in order):
  {"do":"open_app","name":"AutoCAD"}
  {"do":"arrange","app":"chrome","where":"left|right|top|bottom|full|center","screen":"main|second|big|laptop|null"}
  {"do":"find_files","query":"pipeline drawings"}
  {"do":"open_file","path":"C:\\\\exact\\\\path\\\\from\\\\find_files.pdf"}
  {"do":"open_url","url":"https://..."}
  {"do":"web_search","query":"..."}
  {"do":"type_text","text":"..."}          (types into the app Paul was in; never presses Enter)
  {"do":"file_op","op":"move|copy|rename|delete|make_folder","src":"...","dst":"..."}

Rules:
- If it's a question, answer it in "say" and use "actions": [].
- You cannot run commands or scripts. Never invent file paths; use find_files.
- Several windows at once = several arrange actions.
- If a screenshot is provided, use it to answer questions about the screen.
- Be direct. No filler."""


def build_prompt(ask, screen_path):
    ctx = []
    try:
        mons = monitors()
        ctx.append("Screens: " + "; ".join(
            f"{'main' if m['primary'] else 'other'} {m['w']}x{m['h']} at x={m['x']}" for m in mons))
        wins = windows_list()[:25]
        ctx.append("Open windows: " + "; ".join(f"{w['exe'] or '?'}: {w['title'][:60]}" for w in wins))
    except Exception:
        pass
    if screen_path:
        ctx.append(f"Screenshot of Paul's current screen is at: {screen_path}  (read it).")
    return BRAIN_RULES + "\n\n" + "\n".join(ctx) + f"\n\nPaul said: \"{ask}\""


def ask_claude_code(prompt, screen_path):
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        raise RuntimeError("Claude Code isn't installed or isn't on PATH (type: claude --version).")
    args = [exe, "-p", "--output-format", "json", "--model", CLAUDE_CODE_MODEL, "--max-turns", "3",
            "--disallowedTools", "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task"]
    if screen_path:
        args += ["--allowedTools", "Read"]
    os.makedirs(DATA_DIR, exist_ok=True)
    flags = 0x08000000 if IS_WINDOWS else 0          # no black window
    r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=BRAIN_TIMEOUT, cwd=DATA_DIR, creationflags=flags)
    out = (r.stdout or "").strip()
    try:
        data = json.loads(out)
    except Exception:
        raise RuntimeError((r.stderr or out or "Claude Code gave no answer.").strip()[:300])
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result") or data.get("subtype") or "Claude Code error")[:300])
    return data.get("result", "")


def ask_api(prompt, screen_path):
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not key:
        raise RuntimeError("No API key. In CMD: setx ANTHROPIC_API_KEY \"your-key\"  then restart.")
    content = []
    if screen_path:
        with open(screen_path, "rb") as f:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(f.read()).decode()}})
    content.append({"type": "text", "text": prompt})
    body = json.dumps({"model": API_MODEL, "max_tokens": 700,
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=BRAIN_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API error {e.code}: {e.read().decode()[:200]}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def ask_brain(ask, screen_path):
    prompt = build_prompt(ask, screen_path)
    if BRAIN == "api":
        return extract_json(ask_api(prompt, screen_path))
    return extract_json(ask_claude_code(prompt, screen_path))


# ============================== DO ACTIONS ==============================
def run_action(a, ui, target_hwnd):
    do = a.get("do")
    try:
        if do == "none":
            return ""
        if do == "open_app":
            return open_app(a.get("name", ""))
        if do == "arrange":
            return arrange(a.get("app", ""), a.get("where") or "full", a.get("screen"))
        if do == "find_files":
            return find_files(a.get("query", ""))[1]
        if do == "open_file":
            return open_file(a.get("path", ""))
        if do == "open_url":
            return open_url(a.get("url", ""))
        if do == "web_search":
            return web_search(a.get("query", ""))
        if do == "type_text":
            return type_text(a.get("text", ""), target_hwnd)
        if do == "file_op":
            return file_op(a.get("op", ""), a.get("src", ""), a.get("dst", ""), ui.ask_allow)
        return f"I don't know how to '{do}'."
    except Exception as e:
        return f"{do} failed ({e})."


def handle(ask, ui, target_hwnd=None, screen_path=None):
    ask = (ask or "").strip()
    if not ask:
        ui.show("", "I didn't catch that.", hide_after=3)
        return
    ui.show("You", ask)
    act = parse_instant(ask)
    if act:
        msg = run_action(act, ui, target_hwnd)
        log({"ask": ask, "route": "instant", "action": act, "result": msg})
        if msg:
            ui.show("Troy", msg, hide_after=6)
        else:
            ui.hide()
        return
    ui.show("Troy is thinking…", ask)
    shot = screen_path if needs_screen(ask) else None
    try:
        plan = ask_brain(ask, shot)
    except Exception as e:
        log({"ask": ask, "route": BRAIN, "error": str(e)})
        ui.show("Troy", f"My brain didn't answer: {e}", hide_after=10)
        return
    results = [run_action(a, ui, target_hwnd) for a in plan["actions"][:8]]
    problems = [r for r in results if r and re.search(r"couldn't|can't|failed|isn't|didn't|left it alone", r, re.I)]
    say = plan.get("say", "").strip()
    if problems:
        say = (say + " " + " ".join(problems)).strip()
    if not say:
        say = " ".join(r for r in results if r) or "Done."
    log({"ask": ask, "route": BRAIN, "plan": plan, "results": results})
    ui.show("Troy", say, hide_after=max(6, len(say) // 12))
    if SPEAK_REPLIES:
        speak(say)


# ================================ VOICE =================================
_speech_proc = None


def speak(text):
    global _speech_proc
    stop_speaking()
    if not IS_WINDOWS or not text:
        return
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.Speak([Console]::In.ReadToEnd())")
    try:
        _speech_proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps],
                                        stdin=subprocess.PIPE, text=True, encoding="utf-8",
                                        creationflags=0x08000000)
        _speech_proc.stdin.write(text)
        _speech_proc.stdin.close()
    except Exception:
        _speech_proc = None


def stop_speaking():
    global _speech_proc
    if _speech_proc and _speech_proc.poll() is None:
        try:
            _speech_proc.terminate()
        except Exception:
            pass
    _speech_proc = None


class Ears:
    """Microphone + local Whisper. Audio never leaves the laptop."""

    def __init__(self):
        self.model = None
        self.error = None

    def load(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        except Exception as e:
            self.error = str(e)

    def record_while_held(self):
        import numpy as np
        import sounddevice as sd
        import keyboard
        chunks = []
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                            callback=lambda d, f, t, s: chunks.append(d.copy())):
            start = time.time()
            while keyboard.is_pressed(TALK_KEY) and time.time() - start < 60:
                if keyboard.is_pressed("esc"):
                    return None
                time.sleep(0.03)
        if not chunks:
            return None
        audio = np.concatenate(chunks).flatten()
        return audio if len(audio) > 16000 * 0.35 else None

    def transcribe(self, audio):
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        return " ".join(s.text for s in segs).strip()


# ================================== UI ==================================
class ConsoleUI:
    def show(self, who, text="", hide_after=None):
        print(f"[{who}] {text}" if who else text)

    def hide(self):
        pass

    def ask_allow(self, msg):
        print("\n--- Allow? ---\n" + msg)
        return input("Type y to Allow, anything else to Deny: ").strip().lower() == "y"


class Overlay:
    """Small Claude-style dark box at the bottom of the screen."""
    BG, FG, DIM, ACCENT = "#262624", "#f5f4ef", "#a3a29b", "#d97757"

    def __init__(self):
        import tkinter as tk
        self.tk = tk
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Troy Hotkey")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=self.BG)
        box = tk.Frame(self.root, bg=self.BG, padx=18, pady=12,
                       highlightthickness=1, highlightbackground="#3e3e38")
        box.pack(fill="both", expand=True)
        self.who = tk.Label(box, text="", bg=self.BG, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), anchor="w")
        self.who.pack(fill="x")
        self.text = tk.Label(box, text="", bg=self.BG, fg=self.FG, font=("Segoe UI", 12),
                             wraplength=560, justify="left", anchor="w")
        self.text.pack(fill="x")
        self._hide_job = None
        self.root.withdraw()
        self.root.after(50, self._pump)
        self._styled = False

    def _style_window(self):
        """Don't steal focus, and stay out of screenshots."""
        if self._styled or not IS_WINDOWS:
            return
        try:
            import ctypes
            u = _win()
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            ex = u.GetWindowLongW(hwnd, -20)
            u.SetWindowLongW(hwnd, -20, ex | 0x08000000 | 0x00000080)
            u.SetWindowDisplayAffinity(hwnd, 0x11)
            self._styled = True
        except Exception:
            pass

    def _place(self):
        self.root.update_idletasks()
        w = 600
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 90}")

    def _pump(self):
        try:
            while True:
                kind, *args = self.q.get_nowait()
                if kind == "show":
                    who, text, hide_after = args
                    self.who.config(text=who)
                    self.text.config(text=text)
                    self.root.deiconify()
                    self._place()
                    self._style_window()
                    if self._hide_job:
                        self.root.after_cancel(self._hide_job)
                        self._hide_job = None
                    if hide_after:
                        self._hide_job = self.root.after(int(hide_after * 1000), self.root.withdraw)
                elif kind == "hide":
                    self.root.withdraw()
                elif kind == "allow":
                    self._allow_box(*args)
                elif kind == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _allow_box(self, msg, holder):
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("Allow?")
        win.configure(bg=self.BG)
        win.attributes("-topmost", True)
        tk.Label(win, text="Troy wants to:", bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(win, text=msg, bg=self.BG, fg=self.FG, font=("Segoe UI", 11),
                 wraplength=460, justify="left").pack(anchor="w", padx=18)
        row = tk.Frame(win, bg=self.BG)
        row.pack(fill="x", padx=18, pady=14)

        def done(ok):
            holder["ok"] = ok
            holder["ev"].set()
            win.destroy()
        tk.Button(row, text="Deny", width=10, command=lambda: done(False)).pack(side="right")
        tk.Button(row, text="Allow", width=10, bg=self.ACCENT, fg="white",
                  command=lambda: done(True)).pack(side="right", padx=8)
        win.protocol("WM_DELETE_WINDOW", lambda: done(False))
        win.after(60000, lambda: done(False) if not holder["ev"].is_set() else None)
        win.focus_force()

    # thread-safe calls
    def show(self, who, text="", hide_after=None):
        self.q.put(("show", who, text, hide_after))

    def hide(self):
        self.q.put(("hide",))

    def ask_allow(self, msg):
        holder = {"ok": False, "ev": threading.Event()}
        self.q.put(("allow", msg, holder))
        holder["ev"].wait(65)
        return holder["ok"]

    def quit(self):
        self.q.put(("quit",))

    def run(self):
        self.root.mainloop()


# ================================ MAIN ==================================
def run_hotkey():
    import keyboard
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # real pixels on every screen
    except Exception:
        pass
    ui = Overlay()
    ears = Ears()
    busy = threading.Lock()
    ui.show("Troy Hotkey", "Loading speech model… (first time downloads ~150 MB)")

    def load():
        ears.load()
        if ears.error:
            ui.show("Troy Hotkey", f"Speech model didn't load: {ears.error}")
        else:
            ui.show("Troy Hotkey", "Ready. Hold Ctrl + Alt + Space and talk.", hide_after=4)
    threading.Thread(target=load, daemon=True).start()

    def job():
        if not busy.acquire(blocking=False):
            return
        try:
            stop_speaking()
            if not ears.model:
                ui.show("Troy Hotkey", "Still loading the speech model…", hide_after=3)
                return
            target = _win().GetForegroundWindow()
            shot = grab_screen()
            ui.show("Listening…", "Let go when you're done.  Esc cancels.")
            audio = ears.record_while_held()
            if audio is None:
                ui.hide()
                return
            ui.show("Hearing you…", "")
            handle(ears.transcribe(audio), ui, target, shot)
        except Exception as e:
            ui.show("Troy Hotkey", f"Something went wrong: {e}", hide_after=8)
            log({"error": str(e)})
        finally:
            busy.release()

    keyboard.add_hotkey(HOTKEY, lambda: threading.Thread(target=job, daemon=True).start())
    keyboard.add_hotkey(QUIT_HOTKEY, ui.quit)
    ui.run()


def check():
    print("Troy Hotkey Rev 0 - check\n")
    rows = []
    for mod, why in [("keyboard", "hotkey"), ("sounddevice", "microphone"), ("numpy", "microphone"),
                     ("faster_whisper", "speech to text"), ("PIL", "screenshots"),
                     ("win32com", "Windows Search (optional)"), ("psutil", "finding windows (optional)")]:
        try:
            __import__(mod)
            rows.append(("OK  ", mod, why))
        except Exception:
            rows.append(("MISSING", mod, why))
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    rows.append(("OK  " if claude else "MISSING", "Claude Code", claude or "type: claude --version"))
    hands = os.path.exists(os.path.join(HERE, "troy_hands.py"))
    rows.append(("OK  " if hands else "MISSING", "troy_hands.py", "file changes" if hands else "put this file in the Troy folder"))
    if BRAIN == "api":
        k = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        rows.append(("OK  " if k else "MISSING", "API key", "ANTHROPIC_API_KEY"))
    for s, n, w in rows:
        print(f"  {s:8} {n:16} {w}")
    print(f"\n  Brain: {BRAIN}   Data folder: {DATA_DIR}")
    print("\nAll OK? Run:  py troy_hotkey.py --text \"open notepad\"")


def selftest():
    ok = fail = 0

    def t(name, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
        else:
            fail += 1
            print(f"FAIL {name}\n   got:  {got}\n   want: {want}")

    P = parse_instant
    t("open", P("Open AutoCAD."), {"do": "open_app", "name": "autocad"})
    t("open wake", P("Hey Troy, open Excel"), {"do": "open_app", "name": "excel"})
    t("left", P("Notepad on the left"), {"do": "arrange", "app": "notepad", "where": "left", "screen": None})
    t("second", P("Move Chrome to my second screen"), {"do": "arrange", "app": "chrome", "where": "full", "screen": "second"})
    t("open+side", P("open chrome on the right of the big screen"), {"do": "arrange", "app": "chrome", "where": "right", "screen": "big"})
    t("maximize", P("maximize excel"), {"do": "arrange", "app": "excel", "where": "full", "screen": None})
    t("multi->brain", P("Code on my big screen, Chrome and Terminal on the laptop"), None)
    t("find", P("Find my pipeline drawings"), {"do": "find_files", "query": "pipeline drawings"})
    t("search", P("Search for Point Comfort tide chart"), {"do": "web_search", "query": "point comfort tide chart"})
    t("site", P("go to github.com"), {"do": "open_url", "url": "github.com"})
    t("open site", P("open youtube.com"), {"do": "open_url", "url": "youtube.com"})
    t("type", P("Reply: Sounds good, see you at 7."), {"do": "type_text", "text": "Sounds good, see you at 7."})
    t("question->brain", P("What's wrong with this code?"), None)
    t("open and->brain", P("open excel and word"), None)
    t("cancel", P("never mind"), {"do": "none"})
    t("on no side->brain", P("write a note on the permit"), None)
    t("screen yes", needs_screen("What's wrong with this code?"), True)
    t("screen no", needs_screen("How far is Houston"), False)
    t("json", extract_json('ok {"say":"Hi","actions":[{"do":"open_app","name":"x"}, 5]} end'),
      {"say": "Hi", "actions": [{"do": "open_app", "name": "x"}]})
    t("json bad", extract_json("just words"), {"say": "just words", "actions": []})
    t("terms", _search_terms("my pipeline drawings"), ["pipeline", "drawing"])
    mons = [{"x": 0, "y": 0, "w": 1920, "h": 1040, "primary": True},
            {"x": 1920, "y": 0, "w": 3440, "h": 1400, "primary": False}]
    t("mon second", pick_monitor(mons, "second")["x"], 1920)
    t("mon big", pick_monitor(mons, "big")["x"], 1920)
    t("mon laptop", pick_monitor(mons, "laptop")["x"], 0)
    t("mon none", pick_monitor(mons, None)["x"], 0)
    t("rect left", place_rect(mons[0], "left"), (0, 0, 960, 1040))
    t("rect right", place_rect(mons[1], "right"), (3640, 0, 1720, 1400))
    print(f"\nSelftest: {ok} passed, {fail} failed")
    return fail == 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(0 if selftest() else 1)
    if "--check" in a:
        check()
        sys.exit(0)
    if "--text" in a:
        i = a.index("--text")
        req = " ".join(a[i + 1:])
        handle(req, ConsoleUI(), None, grab_screen() if IS_WINDOWS and needs_screen(req) else None)
        time.sleep(1)
        sys.exit(0)
    if not IS_WINDOWS:
        print("Troy Hotkey runs on Windows. Try --selftest here.")
        sys.exit(1)
    run_hotkey()
