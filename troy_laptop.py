"""
troy_laptop.py - Troy's laptop powers, run by Claude.

Plain English:
  On the phone, Troy only talks. On Paul's Windows laptop, this file hands
  Claude a menu of real tools (screen, mouse, keyboard, files, AutoCAD,
  SketchUp, Outlook, the EPR checker) and runs them for him.

  The leash, same as Troy 2.0:
      0 OFF    talk only
      1 LOOK   read files, screenshots, see AutoCAD/SketchUp/email
      2 DO     open apps and files, draw, write drafts, file moves (with Allow)
      3 DRIVE  mouse, keyboard, AutoCAD command line
  Paul picks the level in Settings. Troy can't raise it himself.
  A second setting, "run without asking up to", decides which steps stop for
  an Allow / Deny box. File changes, saves and raw commands ALWAYS ask.

  Emergency stop: slam the mouse into the TOP-LEFT corner of the screen.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "troy_data" / "laptop_settings.json"
MAX_ROUNDS = 15            # most tool steps Troy may chain for one message
SHOT_WIDTH = 1280          # screenshots are shrunk to this width before Claude sees them
KEEP_SHOTS = 3             # only the newest screenshots stay in the conversation
LEVEL_NAMES = {0: "OFF", 1: "LOOK", 2: "DO", 3: "DRIVE"}


def available() -> bool:
    """Laptop powers only on Windows, never on Streamlit Cloud."""
    if os.environ.get("TROY_LAPTOP") == "1":          # lets the tests turn it on
        return True
    return sys.platform == "win32" and not os.environ.get("STREAMLIT_SHARING_MODE")


_tools = None


def tools():
    """Load the toolbox the first time it's needed (it imports pyautogui etc.)."""
    global _tools
    if _tools is None:
        import troy_tools
        _tools = troy_tools
    return _tools


# ---------------------------------------------------------------- settings
def load_settings() -> dict:
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:            # noqa: BLE001
        s = {}
    return {"level": int(s.get("level", 1)), "auto": int(s.get("auto", 1))}


def save_settings(level: int, auto: int) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps({"level": level, "auto": auto}), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- tool menu
def _lower_types(schema):
    """Troy 2.0's menus were written for Gemini ('STRING'); Claude wants 'string'."""
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            out[k] = v.lower() if k == "type" and isinstance(v, str) else _lower_types(v)
        return out
    if isinstance(schema, list):
        return [_lower_types(v) for v in schema]
    return schema


def claude_tools(level: int) -> list:
    t = tools()
    out = []
    for d in t.DECLARATIONS:
        if t.tool_level(d["name"]) <= level:
            schema = _lower_types(d.get("parameters") or {"type": "object", "properties": {}})
            schema.setdefault("properties", {})
            out.append({"name": d["name"], "description": d["description"][:1000],
                        "input_schema": schema})
    return out


def instructions(level: int, auto: int) -> str:
    return f"""

LAPTOP POWERS (Troy is running on Paul's Windows laptop)
You have real tools on this computer. Current level: {level} {LEVEL_NAMES[level]}.
Steps above level {auto} ({LEVEL_NAMES[auto]}) pause for Paul to press Allow; file changes,
saves and AutoCAD commands always pause. If Paul presses Deny, accept it and don't retry it.
If a task needs a higher level, say which level and let Paul raise it; never work around it.

How to work:
- Say in one short sentence what you're about to do, then do it. Prefer looking over guessing.
- Before any click or typing, take_screenshot. Coordinates you give click / move_mouse are
  pixels in the newest screenshot; Troy converts them to the real screen. Check with another
  screenshot afterwards. Small steps, never a long blind chain of clicks.
- AutoCAD: autocad_status first (it tells you the drawing units), work out the coordinates,
  then draw everything for one step in a single autocad_draw call, on sensible layers.
- SketchUp: sketchup_status first. Sizes are feet unless you set unit. Name every group.
- Email: you can read and search; you can only write DRAFTS. Never say an email was sent.
- Never claim a step worked unless the tool result says ok. Quote errors plainly.
"""


# ---------------------------------------------------------------- screenshots
_scale = {"x": 1.0, "y": 1.0}


def _shot_block(path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.width > SHOT_WIDTH:
        new_h = round(img.height * SHOT_WIDTH / img.width)
        _scale.update(x=img.width / SHOT_WIDTH, y=img.height / new_h)
        img = img.resize((SHOT_WIDTH, new_h))
    else:
        _scale.update(x=1.0, y=1.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return img.size, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                  "data": base64.b64encode(buf.getvalue()).decode()}}


def _real_coords(name, args):
    if name in ("click", "move_mouse") and "x" in args and "y" in args:
        try:
            if int(args["x"]) >= 0 and int(args["y"]) >= 0:
                args = dict(args, x=round(int(args["x"]) * _scale["x"]),
                            y=round(int(args["y"]) * _scale["y"]))
        except (TypeError, ValueError):
            pass
    return args


def _trim_old_shots(convo):
    """Swap all but the newest screenshots for a note, so old pictures aren't paid for again."""
    seen = 0
    for msg in reversed(convo):
        if msg["role"] != "user" or not isinstance(msg["content"], list):
            continue
        for block in msg["content"]:
            if block.get("type") != "tool_result" or not isinstance(block.get("content"), list):
                continue
            if any(b.get("type") == "image" for b in block["content"]):
                seen += 1
                if seen > KEEP_SHOTS:
                    block["content"] = [b for b in block["content"] if b.get("type") != "image"] + \
                        [{"type": "text", "text": "[older screenshot removed]"}]


# ---------------------------------------------------------------- running tools
def needs_ok(name: str, auto: int) -> bool:
    t = tools()
    return t.tool_level(name) > auto or name in getattr(t, "ALWAYS_ASK", set())


def plan_text(name: str, args: dict) -> str:
    """What the Allow box shows for one step."""
    for mod_name in ("troy_files",):
        mod = sys.modules.get(mod_name)
        plans = getattr(mod, "PLANS", {}) if mod else {}
        if name in plans:
            try:
                return str(plans[name](args))
            except Exception as e:   # noqa: BLE001
                return f"{name}: couldn't preview ({e})"
    shown = json.dumps(args, ensure_ascii=False)
    if len(shown) > 600:
        shown = shown[:600] + " …"
    return f"{name} {shown}"


def _run_tool(call, level):
    t = tools()
    name, args = call["name"], _real_coords(call["name"], call["input"] or {})
    result = t.execute(name, args, current_level=level)
    content = [{"type": "text", "text": json.dumps(result, default=str)[:20000]}]
    if name == "take_screenshot" and result.get("ok"):
        try:
            (w, h), block = _shot_block(result["path"])
            content[0]["text"] += f"\n(The picture below is {w} x {h}; use its pixels for clicks.)"
            content.append(block)
        except Exception as e:   # noqa: BLE001
            content[0]["text"] += f"\n(Couldn't attach the picture: {e})"
    return {"type": "tool_result", "tool_use_id": call["id"], "content": content,
            "is_error": not result.get("ok", False)}, bool(result.get("ok"))


def _blocks(response):
    out = []
    for b in response.content:
        kind = getattr(b, "type", "")
        if kind == "text":
            out.append({"type": "text", "text": b.text})
        elif kind == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input or {}})
    return out


def run(client, model, system, messages=None, level=1, auto=1, state=None,
        allow=None, max_tokens=4096):
    """
    Talk to Claude with tools until he has a final answer, or a step needs Paul.

    First call:   run(client, model, system, messages=[...], level, auto)
    After a box:  run(client, model, system, state=<the paused state>, allow=True/False, ...)

    Returns {"type": "done", "text": ..., "used": [...]}
         or {"type": "approval", "text": ..., "calls": [{name, plan}], "state": {...}}
    """
    if state is None:
        state = {"convo": [dict(m) for m in messages], "used": [], "rounds": 0,
                 "said": [], "waiting": None}
    convo = state["convo"]
    t_list = claude_tools(level)

    while True:
        if state["waiting"] is not None:
            calls = state["waiting"]
            state["waiting"] = None
            results = []
            for c in calls:
                if c.get("_asked") and not allow:
                    results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                                    "content": "Paul pressed Deny. Don't do this step; ask him "
                                               "what he'd like instead if it matters."})
                    state["used"].append({"name": c["name"], "ok": False, "denied": True})
                    tools().log_action(c["name"], c["input"], "refused", "denied by Paul")
                else:
                    r, good = _run_tool(c, level)
                    results.append(r)
                    state["used"].append({"name": c["name"], "ok": good})
            convo.append({"role": "user", "content": results})
            _trim_old_shots(convo)

        if state["rounds"] >= MAX_ROUNDS:
            state["said"].append(f"(Stopped after {MAX_ROUNDS} steps for this message. "
                                 "Tell me to keep going if you want more.)")
            return {"type": "done", "text": "\n\n".join(state["said"]).strip(), "used": state["used"]}

        response = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          tools=t_list, messages=convo)
        state["rounds"] += 1
        blocks = _blocks(response)
        convo.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
        text = "\n".join(b["text"] for b in blocks if b["type"] == "text").strip()
        if text:
            state["said"].append(text)
        calls = [dict(b) for b in blocks if b["type"] == "tool_use"]
        if not calls or response.stop_reason != "tool_use":
            return {"type": "done", "text": "\n\n".join(state["said"]).strip(), "used": state["used"]}

        for c in calls:
            # A step above the current level is simply refused, so no box for it.
            c["_asked"] = needs_ok(c["name"], auto) and tools().tool_level(c["name"]) <= level
            tools().log_action(c["name"], c["input"], "requested", f"level {tools().tool_level(c['name'])}")
        state["waiting"] = calls
        allow = None
        if any(c["_asked"] for c in calls):
            return {"type": "approval", "text": text,
                    "calls": [{"name": c["name"], "plan": plan_text(c["name"], c["input"]),
                               "asked": c["_asked"]} for c in calls],
                    "state": state}

