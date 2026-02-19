import API
import json
import os
import re
import time

"""
GumpKeyMapper

Purpose:
- Discover crafting gump button behavior with minimal user input.
- Write findings to a human-reviewable JSON file.
- Does NOT write to craftables.db directly.

Usage:
1) Open the target crafting gump in-game manually.
2) Set PROFESSION/SERVER and scan settings below.
3) Run script.
4) Review/edit `GumpKeyMapper.review.json`.
5) Import approved entries using `GumpKeyImport.py`.
"""

# Default startup values (editable in gump).
DEFAULT_SERVER = "UOAlive"
DEFAULT_PROFESSION = "Blacksmith"
DEFAULT_BUTTON_START = 1
DEFAULT_BUTTON_END = 220
DEFAULT_PRIMARY_BUTTON = 0  # 0 = none. If > 0, clicks this first then scans second-level buttons.
DEFAULT_WAIT_AFTER_CLICK_S = 0.30
MIN_SAFE_CLICK_WAIT_S = 0.65
SCAN_COOLDOWN_EVERY = 10
SCAN_COOLDOWN_S = 1.0
MAX_GUMP_RECOVERIES = 25
MAX_CONSECUTIVE_RECOVERIES = 3
RECOVERY_OPEN_ATTEMPTS = 1
RECOVERY_OPEN_WAIT_S = 0.80

# Output.
REVIEW_FILE = "GumpKeyMapper.review.json"
DEBUG_LOG_FILE = "GumpKeyMapper.debug.log.txt"
MAX_LINE_SAMPLE = 30

ANCHORS_BY_PROFESSION = {
    "Blacksmith": ["BLACKSMITHING MENU", "BLACKSMITHING", "BLACKSMITH"],
    "Tailor": ["TAILORING MENU", "TAILORING", "TAILOR"],
    "Carpentry": ["CARPENTRY MENU", "CARPENTRY", "CARPENTER"],
    "Tinker": ["TINKERING MENU", "TINKERING", "TINKER", "TINKER MENU", "TOOLS MENU"],
    "Bowcraft": ["BOWCRAFT", "FLETCHING", "BOWYER"],
}
SERVER_OPTIONS = ["OSI", "UOAlive", "Sosaria Reforged", "InsaneUO"]
PROFESSION_OPTIONS = ["Blacksmith", "Tailor", "Carpentry", "Tinker", "Bowcraft"]
BLACKSMITH_TOOL_IDS = [0x0FBB]  # Tongs
TAILOR_TOOL_IDS = [0x0F9D]      # Sewing kit
CARPENTRY_TOOL_IDS = [0x1028, 0x102C, 0x1034, 0x1035]
TINKER_TOOL_IDS = [0x1EB8, 0x1EB9]
TOOL_IDS_BY_PROFESSION = {
    "Blacksmith": BLACKSMITH_TOOL_IDS,
    "Tailor": TAILOR_TOOL_IDS,
    "Carpentry": CARPENTRY_TOOL_IDS,
    "Tinker": TINKER_TOOL_IDS,
    # Bowcraft tool IDs vary by shard; leave empty unless you add them.
    "Bowcraft": [],
}
SKIP_BUTTONS_BY_PROFESSION = {
    "Tinker": {4, 5, 6, 8, 9},
}
CRAFT_GUMP_ID_BY_PROFESSION = {
    "Blacksmith": 0xD466EA9C,
    "Tailor": 0xD466EA9C,
    "Carpentry": 0xD466EA9C,
    "Tinker": 0xD466EA9C,
    "Bowcraft": 0xD466EA9C,
}
TINKER_SUBGUMP_BACK_ID = 0x7E9DC90F

CONTROL_GUMP = None
INPUTS = {}
START_CONF = None
RUN_ABORTED = False
FORCE_STOP = False


def _say(msg, hue=88):
    _append_debug_log(msg)
    try:
        API.SysMsg(str(msg or ""), hue)
    except Exception:
        pass


def _sleep(s):
    global FORCE_STOP
    try:
        API.Pause(float(s))
        return True
    except Exception as ex:
        msg = str(ex or "")
        if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
            FORCE_STOP = True
        return False


def _should_stop():
    global FORCE_STOP
    try:
        return bool(getattr(API, "StopRequested", False)) or bool(FORCE_STOP)
    except Exception:
        return bool(FORCE_STOP)


def _base_dir():
    try:
        return os.path.dirname(__file__)
    except Exception:
        return os.getcwd()


def _out_path():
    return os.path.join(_base_dir(), REVIEW_FILE)


def _log_path():
    return os.path.join(_base_dir(), DEBUG_LOG_FILE)


def _append_debug_log(msg):
    try:
        ts = _now_iso()
    except Exception:
        ts = "unknown-time"
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write("[{0}] {1}\n".format(ts, str(msg or "")))
    except Exception:
        pass


def _normalize_profession(name):
    n = str(name or "").strip().lower()
    m = {
        "blacksmith": "Blacksmith",
        "blacksmithy": "Blacksmith",
        "tailor": "Tailor",
        "tailoring": "Tailor",
        "carpentry": "Carpentry",
        "carpenter": "Carpentry",
        "tinker": "Tinker",
        "tinkering": "Tinker",
        "bowcraft": "Bowcraft",
        "fletching": "Bowcraft",
        "bowcraft/fletching": "Bowcraft",
        "bowyer": "Bowcraft",
    }
    return m.get(n, "")


def _gump_ids():
    out = set()
    try:
        allg = API.GetAllGumps() or []
    except Exception:
        allg = []
    for g in allg:
        try:
            if isinstance(g, int):
                out.add(int(g))
                continue
            for attr in ("ServerSerial", "ID", "Id", "GumpID", "GumpId", "Serial"):
                v = getattr(g, attr, None)
                if v is None:
                    continue
                out.add(int(v))
                break
        except Exception:
            continue
    return sorted(list(out))


def _has_gump(gid):
    try:
        return bool(API.HasGump(int(gid)))
    except Exception:
        return False


def _wait_for_gump(gid, timeout_s):
    try:
        return bool(API.WaitForGump(int(gid), float(timeout_s)))
    except Exception:
        return False


def _wait_for_any_gump(timeout_s):
    end = time.time() + max(0.05, float(timeout_s))
    while time.time() < end:
        if _gump_ids():
            return True
        if not _sleep(0.05):
            return False
    return False


def _gump_text(gid):
    try:
        return str(API.GetGumpContents(int(gid)) or "")
    except Exception:
        return ""


def _lineify(text):
    out = []
    for ln in str(text or "").splitlines():
        t = str(ln or "").strip()
        if t:
            out.append(t)
    return out


def _line_diff(before_lines, after_lines):
    b = set(before_lines or [])
    a = set(after_lines or [])
    added = [x for x in (after_lines or []) if x not in b]
    removed = [x for x in (before_lines or []) if x not in a]
    return added, removed


def _is_anchor_match(text, profession):
    prof = _normalize_profession(profession)
    if not prof:
        return False
    anchors = ANCHORS_BY_PROFESSION.get(prof, []) or []
    t = str(text or "").upper()
    for a in anchors:
        if str(a or "").upper() in t:
            return True
    return False


def _find_active_crafting_gump(profession):
    prof = _normalize_profession(profession)
    expected = int(CRAFT_GUMP_ID_BY_PROFESSION.get(prof, 0) or 0)
    if expected > 0 and _has_gump(expected):
        return expected
    best = 0
    best_len = -1
    for gid in _gump_ids():
        txt = _gump_text(gid)
        tlen = len(str(txt or ""))
        if _is_anchor_match(txt, prof):
            if tlen > best_len:
                best_len = tlen
                best = int(gid)
    if best > 0:
        return int(best)
    if expected > 0 and _wait_for_gump(expected, 0.2):
        return expected
    return 0


def _dump_open_gump_diagnostics():
    ids = _gump_ids()
    _say(f"Mapper: diagnostic open_gumps={ids if ids else []}", 33)
    if not ids:
        for prof in PROFESSION_OPTIONS:
            egid = int(CRAFT_GUMP_ID_BY_PROFESSION.get(prof, 0) or 0)
            if egid > 0:
                _say(f"Mapper: diagnostic has_gump({prof},0x{egid:08X})={_has_gump(egid)}", 33)
        return
    shown = 0
    for gid in ids:
        txt = _gump_text(gid)
        lines = _lineify(txt)
        sample = lines[0] if lines else "<no text>"
        _say(
            f"Mapper: diagnostic gump 0x{int(gid):08X} "
            f"lines={len(lines)} sample='{str(sample)[:90]}'"
        )
        shown += 1
        if shown >= 8:
            break


def _backpack_serial():
    try:
        return int(getattr(API.Backpack, "Serial", 0) or 0)
    except Exception:
        return 0


def _items_in_backpack_recursive():
    bp = _backpack_serial()
    if bp <= 0:
        return []
    try:
        return list(API.ItemsInContainer(bp, True) or [])
    except Exception:
        return []


def _ensure_item_in_backpack_root(item):
    bp = _backpack_serial()
    if bp <= 0 or not item:
        return item
    try:
        c1 = int(getattr(item, "Container", 0) or 0)
    except Exception:
        c1 = 0
    try:
        c2 = int(getattr(item, "ContainerSerial", 0) or 0)
    except Exception:
        c2 = 0
    if c1 == bp or c2 == bp:
        return item
    ser = int(getattr(item, "Serial", 0) or 0)
    if ser <= 0:
        return item
    try:
        API.MoveItem(ser, API.Backpack, 1)
    except Exception:
        return item
    _sleep(0.45)
    try:
        live = API.FindItem(ser)
        if live:
            return live
    except Exception:
        pass
    return item


def _find_tool_for_profession(profession):
    prof = _normalize_profession(profession)
    tool_ids = TOOL_IDS_BY_PROFESSION.get(prof, []) or []
    if not tool_ids:
        return None
    for it in _items_in_backpack_recursive():
        try:
            gid = int(getattr(it, "Graphic", 0) or 0)
        except Exception:
            gid = 0
        if gid in tool_ids:
            return it
    return None


def _find_live_tool_serial(profession):
    prof = _normalize_profession(profession)
    tool_ids = TOOL_IDS_BY_PROFESSION.get(prof, []) or []
    if not tool_ids:
        return 0
    # Fast path: direct backpack search by graphic id.
    for gid in tool_ids:
        try:
            it = API.FindType(int(gid), API.Backpack)
        except Exception:
            it = None
        if it:
            try:
                ser = int(getattr(it, "Serial", 0) or 0)
            except Exception:
                ser = 0
            if ser > 0:
                return ser
    # Fallback: recursive scan.
    it = _find_tool_for_profession(prof)
    if not it:
        return 0
    try:
        return int(getattr(it, "Serial", 0) or 0)
    except Exception:
        return 0


def _try_tinker_back_to_main(wait_s=0.45):
    expected = int(CRAFT_GUMP_ID_BY_PROFESSION.get("Tinker", 0) or 0)
    sub = int(TINKER_SUBGUMP_BACK_ID)
    if sub <= 0:
        return False
    if not _has_gump(sub):
        return False
    _say("Mapper: detected Tinker sub-gump; sending button 0 to return to main.")
    _reply(0, sub)
    if not _sleep(max(0.25, float(wait_s))):
        return False
    if expected > 0 and (_has_gump(expected) or _wait_for_gump(expected, 0.6)):
        return True
    gid = _find_active_crafting_gump("Tinker")
    return gid > 0


def _open_gump_via_tool(profession, attempts=3, wait_s=0.45):
    prof = _normalize_profession(profession)
    tool_ser = _find_live_tool_serial(prof)
    if tool_ser <= 0:
        _say(f"Mapper: no {prof} tool found in backpack/subcontainers.", 33)
        return 0
    expected = int(CRAFT_GUMP_ID_BY_PROFESSION.get(prof, 0) or 0)
    for i in range(1, max(1, int(attempts)) + 1):
        if _should_stop():
            return 0
        if prof == "Tinker":
            if _try_tinker_back_to_main(wait_s=max(0.35, wait_s)):
                return expected if expected > 0 else _find_active_crafting_gump(prof)
        # Refresh tool serial every attempt so stale item references do not break open.
        tool_ser = _find_live_tool_serial(prof)
        if tool_ser <= 0:
            _say(f"Mapper: lost {prof} tool reference on attempt {i}.", 33)
            continue
        try:
            live = API.FindItem(tool_ser)
        except Exception:
            live = None
        if live:
            live = _ensure_item_in_backpack_root(live)
            try:
                tool_ser = int(getattr(live, "Serial", 0) or tool_ser)
            except Exception:
                pass
        try:
            API.CancelTarget()
        except Exception:
            pass
        try:
            API.UseObject(tool_ser)
        except Exception as ex:
            _say(f"Mapper: tool use failed attempt {i}: {ex}", 33)
            continue
        if not _sleep(max(0.35, float(wait_s))):
            return 0
        # Keep reopen pressure low to avoid client/server instability.
        t_end = time.time() + 1.4
        while time.time() < t_end:
            if expected > 0 and (_has_gump(expected) or _wait_for_gump(expected, 0.2)):
                _say(f"Mapper: opened {prof} gump via expected id 0x{expected:08X}.")
                return expected
            gid = _find_active_crafting_gump(prof)
            if gid > 0:
                _say(f"Mapper: opened {prof} gump via tool 0x{tool_ser:08X}.")
                return int(gid)
            _wait_for_any_gump(0.15)
            if not _sleep(0.08):
                return 0
    _say(f"Mapper: failed to open {prof} gump via tool 0x{tool_ser:08X}.", 33)
    return 0


def _single_shot_reopen(profession, wait_s=0.65):
    prof = _normalize_profession(profession)
    tool_ser = _find_live_tool_serial(prof)
    if tool_ser <= 0:
        return 0
    try:
        API.CancelTarget()
    except Exception:
        pass
    try:
        API.UseObject(int(tool_ser))
    except Exception:
        return 0
    if not _sleep(max(0.35, float(wait_s))):
        return 0
    expected = int(CRAFT_GUMP_ID_BY_PROFESSION.get(prof, 0) or 0)
    if expected > 0 and _has_gump(expected):
        return expected
    return _find_active_crafting_gump(prof)


def _reopen_once_raw_useobject(profession, wait_s=0.65):
    prof = _normalize_profession(profession)
    tool_ser = _find_live_tool_serial(prof)
    if tool_ser <= 0:
        return 0
    try:
        API.CancelTarget()
    except Exception:
        pass
    try:
        API.UseObject(int(tool_ser))
    except Exception:
        return 0
    if not _sleep(max(0.35, float(wait_s))):
        return 0
    expected = int(CRAFT_GUMP_ID_BY_PROFESSION.get(prof, 0) or 0)
    if expected > 0 and _has_gump(expected):
        return expected
    return 0


def _reply(button_id, gump_id):
    try:
        API.ReplyGump(int(button_id), int(gump_id))
        return True
    except Exception:
        try:
            API.ReplyGump(int(button_id))
            return True
        except Exception:
            return False


def _now_iso():
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown-time"


def _build_auto_proposals(discoveries, primary_button):
    # Intentionally conservative. Reviewer fills these manually before import.
    item_keys = []
    for d in discoveries:
        if not d.get("changed", False):
            continue
        b = int(d.get("button", 0) or 0)
        if b <= 0:
            continue
        pair = [int(primary_button), b] if int(primary_button or 0) > 0 else [b]
        item_keys.append(
            {
                "item_key": "",
                "name": "",
                "item_id": 0,
                "buttons": pair,
                "category": "",
                "default_material_key": "",
                "resources": [],
                "approved": False,
                "note": "Auto-discovered changed button path. Fill item fields and approve if valid.",
            }
        )
    return {"material_keys": [], "item_keys": item_keys}


def _parse_int(text, default_val=0):
    try:
        return int(str(text or "").strip())
    except Exception:
        return int(default_val or 0)


def _parse_float(text, default_val=0.0):
    try:
        return float(str(text or "").strip())
    except Exception:
        return float(default_val or 0.0)


def _close_gump():
    global CONTROL_GUMP
    if CONTROL_GUMP:
        try:
            CONTROL_GUMP.Dispose()
        except Exception:
            pass
    CONTROL_GUMP = None


def _on_cancel():
    global RUN_ABORTED
    RUN_ABORTED = True
    _close_gump()


def _on_start():
    global START_CONF
    f = INPUTS or {}
    dd_srv = f.get("server")
    dd_prof = f.get("profession")
    t_start = f.get("button_start")
    t_end = f.get("button_end")
    t_primary = f.get("primary_button")
    t_wait = f.get("wait_after")

    try:
        srv_idx = int(dd_srv.GetSelectedIndex()) if dd_srv else 0
    except Exception:
        srv_idx = 0
    if srv_idx < 0 or srv_idx >= len(SERVER_OPTIONS):
        srv_idx = 0

    try:
        prof_idx = int(dd_prof.GetSelectedIndex()) if dd_prof else 0
    except Exception:
        prof_idx = 0
    if prof_idx < 0 or prof_idx >= len(PROFESSION_OPTIONS):
        prof_idx = 0

    button_start = _parse_int(t_start.Text if t_start else "", DEFAULT_BUTTON_START)
    button_end = _parse_int(t_end.Text if t_end else "", DEFAULT_BUTTON_END)
    primary_button = _parse_int(t_primary.Text if t_primary else "", DEFAULT_PRIMARY_BUTTON)
    wait_after = _parse_float(t_wait.Text if t_wait else "", DEFAULT_WAIT_AFTER_CLICK_S)

    if button_start <= 0:
        _say("Mapper: Button Start must be > 0.", 33)
        return
    if button_end < button_start:
        _say("Mapper: Button End must be >= Button Start.", 33)
        return
    if wait_after <= 0:
        _say("Mapper: Wait After Click must be > 0.", 33)
        return

    START_CONF = {
        "server": SERVER_OPTIONS[srv_idx],
        "profession": PROFESSION_OPTIONS[prof_idx],
        "button_start": int(button_start),
        "button_end": int(button_end),
        "primary_button": int(primary_button),
        "wait_after_click_s": float(wait_after),
    }
    _close_gump()


def _open_setup_gump():
    global CONTROL_GUMP, INPUTS, START_CONF, RUN_ABORTED
    START_CONF = None
    RUN_ABORTED = False
    INPUTS = {}
    _close_gump()

    g = API.CreateGump(True, True, False)
    w = 430
    h = 240
    g.SetRect(640, 260, w, h)
    bg = API.CreateGumpColorBox(0.75, "#1B1B1B")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("Gump Key Mapper Setup", 15, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 8)
    g.Add(title)

    y = 40
    l_srv = API.CreateGumpTTFLabel("Server", 12, "#FFFFFF", "alagard", "left", 80)
    l_srv.SetPos(12, y)
    g.Add(l_srv)
    try:
        srv_idx = SERVER_OPTIONS.index(str(DEFAULT_SERVER))
    except Exception:
        srv_idx = 1
    d_srv = API.CreateDropDown(180, list(SERVER_OPTIONS), srv_idx)
    d_srv.SetPos(92, y - 2)
    g.Add(d_srv)

    y += 28
    l_prof = API.CreateGumpTTFLabel("Profession", 12, "#FFFFFF", "alagard", "left", 80)
    l_prof.SetPos(12, y)
    g.Add(l_prof)
    try:
        prof_idx = PROFESSION_OPTIONS.index(str(DEFAULT_PROFESSION))
    except Exception:
        prof_idx = 0
    d_prof = API.CreateDropDown(180, list(PROFESSION_OPTIONS), prof_idx)
    d_prof.SetPos(92, y - 2)
    g.Add(d_prof)

    y += 28
    l_bs = API.CreateGumpTTFLabel("Button Start", 12, "#FFFFFF", "alagard", "left", 90)
    l_bs.SetPos(12, y)
    g.Add(l_bs)
    t_bs = API.CreateGumpTextBox(str(int(DEFAULT_BUTTON_START)), 64, 18, False)
    t_bs.SetPos(100, y - 2)
    try:
        t_bs.NumbersOnly = True
    except Exception:
        pass
    g.Add(t_bs)

    l_be = API.CreateGumpTTFLabel("Button End", 12, "#FFFFFF", "alagard", "left", 80)
    l_be.SetPos(180, y)
    g.Add(l_be)
    t_be = API.CreateGumpTextBox(str(int(DEFAULT_BUTTON_END)), 64, 18, False)
    t_be.SetPos(252, y - 2)
    try:
        t_be.NumbersOnly = True
    except Exception:
        pass
    g.Add(t_be)

    y += 28
    l_pb = API.CreateGumpTTFLabel("Primary Button (0=none)", 12, "#FFFFFF", "alagard", "left", 150)
    l_pb.SetPos(12, y)
    g.Add(l_pb)
    t_pb = API.CreateGumpTextBox(str(int(DEFAULT_PRIMARY_BUTTON)), 64, 18, False)
    t_pb.SetPos(170, y - 2)
    try:
        t_pb.NumbersOnly = True
    except Exception:
        pass
    g.Add(t_pb)

    l_wait = API.CreateGumpTTFLabel("Wait (s)", 12, "#FFFFFF", "alagard", "left", 50)
    l_wait.SetPos(250, y)
    g.Add(l_wait)
    t_wait = API.CreateGumpTextBox(str(float(DEFAULT_WAIT_AFTER_CLICK_S)), 70, 18, False)
    t_wait.SetPos(305, y - 2)
    g.Add(t_wait)

    y += 40
    start_btn = API.CreateSimpleButton("Start Mapping", 120, 20)
    start_btn.SetPos(110, y)
    g.Add(start_btn)
    API.AddControlOnClick(start_btn, _on_start)

    cancel_btn = API.CreateSimpleButton("Cancel", 80, 20)
    cancel_btn.SetPos(245, y)
    g.Add(cancel_btn)
    API.AddControlOnClick(cancel_btn, _on_cancel)

    API.AddGump(g)
    CONTROL_GUMP = g
    INPUTS = {
        "server": d_srv,
        "profession": d_prof,
        "button_start": t_bs,
        "button_end": t_be,
        "primary_button": t_pb,
        "wait_after": t_wait,
    }


def _run_mapping(config):
    global FORCE_STOP
    profession = _normalize_profession(config.get("profession", ""))
    if not profession:
        _say("Mapper: invalid PROFESSION setting.", 33)
        return
    button_start = int(config.get("button_start", DEFAULT_BUTTON_START) or DEFAULT_BUTTON_START)
    button_end = int(config.get("button_end", DEFAULT_BUTTON_END) or DEFAULT_BUTTON_END)
    primary_button = int(config.get("primary_button", DEFAULT_PRIMARY_BUTTON) or 0)
    wait_after = float(config.get("wait_after_click_s", DEFAULT_WAIT_AFTER_CLICK_S) or DEFAULT_WAIT_AFTER_CLICK_S)
    wait_after = max(float(wait_after), float(MIN_SAFE_CLICK_WAIT_S))
    server = str(config.get("server", DEFAULT_SERVER) or DEFAULT_SERVER)
    if int(button_end) < int(button_start):
        _say("Mapper: BUTTON_END must be >= BUTTON_START.", 33)
        return

    _say(f"Mapper: opening {profession} crafting gump via tool...")
    if _should_stop():
        return
    gid = _open_gump_via_tool(profession, attempts=1, wait_s=max(0.25, wait_after))
    if gid <= 0:
        _say(f"Mapper: fallback: searching already-open {profession} gump.")
        gid = _find_active_crafting_gump(profession)
    if gid <= 0:
        _say("Mapper: no matching crafting gump found. Open the gump and rerun.", 33)
        _dump_open_gump_diagnostics()
        return

    pre_text = _gump_text(gid)
    pre_lines = _lineify(pre_text)
    _say(f"Mapper: gump 0x{gid:08X} detected. snapshot_lines={len(pre_lines)}")

    if int(primary_button or 0) > 0:
        _say(f"Mapper: applying primary button {int(primary_button)}")
        _reply(int(primary_button), gid)
        if not _sleep(wait_after) or _should_stop():
            _say("Mapper: interrupted during primary button step.", 33)
            return
        gid2 = _find_active_crafting_gump(profession)
        if gid2 > 0:
            gid = gid2
            pre_text = _gump_text(gid)
            pre_lines = _lineify(pre_text)
            _say(f"Mapper: primary applied. active_gump=0x{gid:08X} lines={len(pre_lines)}")
        else:
            _say("Mapper: gump closed after primary button. Scan aborted.", 33)
            return

    discoveries = []
    skip_buttons = set(SKIP_BUTTONS_BY_PROFESSION.get(profession, set()) or set())
    expected_gid = int(CRAFT_GUMP_ID_BY_PROFESSION.get(profession, 0) or 0)
    recovery_count = 0
    consecutive_recoveries = 0
    click_count = 0
    for btn in range(int(button_start), int(button_end) + 1):
        if _should_stop():
            _say("Mapper: stop requested. Aborting scan.")
            return
        if int(btn) == int(primary_button or 0):
            continue
        if int(btn) in skip_buttons:
            discoveries.append(
                {
                    "button": int(btn),
                    "changed": False,
                    "closed_gump": False,
                    "reply_ok": False,
                    "skipped": True,
                    "note": f"Skipped by profession rule for {profession}.",
                }
            )
            continue
        # Safety: never send button replies to a non-crafting gump.
        if expected_gid > 0 and int(gid) != int(expected_gid):
            if profession == "Tinker" and int(gid) == int(TINKER_SUBGUMP_BACK_ID):
                if _try_tinker_back_to_main(wait_s=max(0.35, wait_after)):
                    gid = int(expected_gid)
                    continue
            if _has_gump(expected_gid):
                gid = int(expected_gid)
            else:
                _say(
                    f"Mapper: active gump drifted (have=0x{int(gid):08X}, expected=0x{int(expected_gid):08X}); recovering.",
                    33,
                )
                gid = _reopen_once_raw_useobject(profession, wait_s=max(0.6, wait_after))
                if gid <= 0:
                    _say("Mapper: could not recover expected crafting gump; stopping scan.", 33)
                    break
        click_count += 1
        before_text = _gump_text(gid)
        before_lines = _lineify(before_text)
        ok = _reply(btn, gid)
        if not _sleep(wait_after) or _should_stop():
            _say("Mapper: interrupted during scan.", 33)
            return
        if click_count % int(SCAN_COOLDOWN_EVERY) == 0:
            _say(f"Mapper: cooldown after {click_count} clicks.")
            if not _sleep(SCAN_COOLDOWN_S) or _should_stop():
                _say("Mapper: interrupted during cooldown.", 33)
                return
        next_gid = _find_active_crafting_gump(profession)
        closed = next_gid <= 0
        if closed:
            discoveries.append(
                {
                    "button": int(btn),
                    "changed": True,
                    "closed_gump": True,
                    "before_line_count": len(before_lines),
                    "after_line_count": 0,
                    "new_lines": [],
                    "removed_lines": [],
                    "after_lines_sample": [],
                    "note": "Button appears to close or leave crafting gump. Auto-skipping in this run.",
                }
            )
            skip_buttons.add(int(btn))
            recovery_count += 1
            consecutive_recoveries += 1
            if recovery_count > int(MAX_GUMP_RECOVERIES):
                _say(
                    f"Mapper: too many gump recoveries ({recovery_count}); stopping to avoid disconnect risk.",
                    33,
                )
                break
            if consecutive_recoveries > int(MAX_CONSECUTIVE_RECOVERIES):
                _say(
                    f"Mapper: too many consecutive closes ({consecutive_recoveries}); stopping to avoid disconnect risk.",
                    33,
                )
                break
            _say(f"Mapper: button {btn} closed gump; reopening and continuing.")
            gid = _reopen_once_raw_useobject(profession, wait_s=max(0.6, wait_after))
            if gid <= 0:
                gid = _find_active_crafting_gump(profession)
            if gid <= 0:
                _say(
                    "Mapper: failed to recover crafting gump; stopping scan early to avoid disconnect risk.",
                    33,
                )
                break
            if int(primary_button or 0) > 0:
                _reply(int(primary_button), gid)
                if not _sleep(wait_after) or _should_stop():
                    _say("Mapper: interrupted during recovery baseline apply.", 33)
                    return
                maybe_gid = _find_active_crafting_gump(profession)
                if maybe_gid > 0:
                    gid = int(maybe_gid)
            continue

        consecutive_recoveries = 0
        gid = int(next_gid)
        after_text = _gump_text(gid)
        after_lines = _lineify(after_text)
        added, removed = _line_diff(before_lines, after_lines)
        changed = bool(added or removed or (before_text != after_text))
        discoveries.append(
            {
                "button": int(btn),
                "changed": bool(changed),
                "closed_gump": False,
                "reply_ok": bool(ok),
                "before_line_count": len(before_lines),
                "after_line_count": len(after_lines),
                "new_lines": list(added[:MAX_LINE_SAMPLE]),
                "removed_lines": list(removed[:MAX_LINE_SAMPLE]),
                "after_lines_sample": list(after_lines[:MAX_LINE_SAMPLE]),
            }
        )

        # Try to restore baseline by reapplying primary (if set) when state drifted.
        if int(primary_button or 0) > 0 and changed:
            _reply(int(primary_button), gid)
            if not _sleep(wait_after) or _should_stop():
                _say("Mapper: interrupted during baseline restore.", 33)
                return
            maybe_gid = _find_active_crafting_gump(profession)
            if maybe_gid > 0:
                gid = int(maybe_gid)

    payload = {
        "metadata": {
            "created_at": _now_iso(),
            "server": str(server or ""),
            "profession": profession,
            "gump_id": int(gid or 0),
            "button_start": int(button_start),
            "button_end": int(button_end),
            "primary_button": int(primary_button or 0),
            "wait_after_click_s": float(wait_after),
        },
        "raw_snapshot": {
            "lines": pre_lines[:MAX_LINE_SAMPLE],
        },
        "discoveries": discoveries,
        "proposals": _build_auto_proposals(discoveries, primary_button),
        "notes": [
            "Set approved=true only for validated entries.",
            "For item_keys fill: item_key, name, buttons, category, default_material_key.",
            "For material_keys fill: material_key, material, material_buttons.",
        ],
    }

    out = _out_path()
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as ex:
        _say(f"Mapper: failed to write review file: {ex}", 33)
        return

    _say(f"Mapper: wrote review file: {out}")
    _say(f"Mapper: discoveries={len(discoveries)}")


def _run():
    _open_setup_gump()
    while CONTROL_GUMP is not None:
        if _should_stop():
            _close_gump()
            _say("Mapper: stop requested. Closed setup gump.")
            return
        try:
            API.ProcessCallbacks()
        except Exception as ex:
            msg = str(ex or "")
            if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
                try:
                    globals()["FORCE_STOP"] = True
                except Exception:
                    pass
                _close_gump()
                _say("Mapper: stop requested during callbacks.")
                return
        if not _sleep(0.1):
            _close_gump()
            _say("Mapper: stop requested during setup wait.")
            return
    if RUN_ABORTED:
        _say("Mapper: cancelled.")
        return
    if not isinstance(START_CONF, dict):
        _say("Mapper: no configuration selected.", 33)
        return
    if _should_stop():
        _say("Mapper: stop requested before mapping start.")
        return
    _run_mapping(START_CONF)


_run()
