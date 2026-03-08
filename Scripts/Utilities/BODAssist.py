import API
import json
import ast
import re
import os
import time
import sys
import importlib
import traceback

"""
BODAssist
Current scope: Collect + Prep/Sort + Fill (manual recipe mapping)

Implemented:
- Control gump with phase buttons: Run Collect, Run Prep/Sort, Run Fill, Run Turn-In, Run Full Loop.
- Travel configuration (Mage/Chiv) and fixed runebook routing.
- Auto BOD giver detection by NPC title keywords.
- Run Collect:
  - Slot 1 is Home.
  - Slots 2-9 map to selected BOD types.
  - Requests up to 3 deeds per giver and accepts the BOD offer gump.
- Crafting Station target by ground tile coordinates + pathfinding move from home.
- Run Prep/Sort (current behavior): recall home and move to Crafting Station.
- Fill engine for Blacksmith/Tailor/Carpentry/Tinker:
  - Parses deed tooltip for profession/material/quality/amount.
  - Uses recipe mappings from `Databases/craftables.db`.
  - Runs helperized fill phases (Travel -> Move -> Materials -> Tools -> Context -> Craft -> Combine/Recount).
- Learn Mode is manual-only (shared `RecipeBookEditor.py`).
  - Pulls resources from Resource Container.
  - Auto-tools via tinkering when possible.
  - Crafts items, stages in BOD Item Container, combines via deed gump, and re-checks deed progress until complete.
  - Handles exceptional failures through Salvage Bag/Trash flow when configured.
- Recipe book supports server tagging/filtering from `Databases/craftables.db`.

Setup:
- Put your home rune in runebook slot 1.
- Put giver runes in fixed slots:
  slot 2 Blacksmith, slot 3 Tailor, slot 4 Carpentry, slot 5 Tinker,
  slot 6 Alchemy, slot 7 Inscription, slot 8 Bowcraft, slot 9 Cooking.
- In the `Collect BODs` section, check the BOD types you want to collect.
- Set `Crafting Station` by targeting the ground tile at your crafting location.
- `Run Prep/Sort` recalls home, then pathfinds to the stored Crafting Station tile.
- Set `Resource Container` for ingots/cloth/leather/boards used during fill.
- Set `BOD Item Container` where crafted items are staged for deed combine/turn-in combine targeting.
- Optional: set `Salvage Bag` and `Trash Container` for exceptional failures and recycle overflow.
- Learn Mode is manual-only: use `Manual Recipe` to open `RecipeBookEditor.py` and enter recipe/material data.
- Recipes are stored in `Databases/craftables.db` for shared editing across scripts.

Not implemented yet:
- Turn-In automation.
- Full loop orchestration.
- Advanced Prep/Sort deed organization (large/small deed routing).

Full Feature Plan:
1) Control/UI
- Provide independent phase buttons and a full-loop button.
- Persist all configuration needed to run each phase without re-targeting.
- Surface current status/error in UI messages.

2) Travel + Collection
- Recall from home (slot 1) to each remaining runebook stop.
- Request all available BODs at each stop.
- Recall home after route completion.

3) Home Prep + Sorting
- Move to a configured work spot inside home.
- Validate access to required stations/containers.
- Move large BODs into BOD box to source matching small BODs.

4) Fill Engine
- Parse BOD requirements from deed contents.
- Pull resources/tools needed per deed.
- Craft required items and fill deeds until complete or blocked.
- Support partial progress tracking and safe resume.

5) Turn-In + Refresh
- Recall back to giver route.
- Turn in completed deeds and collect rewards.
- Request new deeds.

6) Full Loop Orchestration
- Chain: Collect -> Prep/Sort -> Fill -> Turn-In -> repeat.
- Include pause/recovery handling for missing resources/tools/routes.

TODO Checklist (Phased Build):
Phase 1
- [x] Script scaffold
- [x] Config persistence
- [x] Gump with independent phase buttons
- [x] Run Collect (home slot + full route + title-based giver detection + return home)

Phase 2
- [x] Home work spot targeting + move-to-spot
- [ ] BOD box target/set
- [ ] Large-vs-small deed classification
- [x] Run Prep/Sort implementation (home -> crafting station move)

Phase 3
- [x] BOD parsing helpers (type/material/amount/fill status)
- [x] Initial filler for one profession (expanded to Blacksmith/Tailor/Carpentry/Tinker)
- [x] Run Fill implementation with progress/status logs
- [x] Shared RecipeBookEditor integration + persistent recipe book
- [x] Fill helper pipeline stabilization and context handoff hardening

Phase 4
- [ ] Run Turn-In implementation
- [ ] Reward handling/logging
- [ ] New-deed re-collect at turn-in stops

Phase 5
- [ ] Run Full Loop implementation
- [ ] Error recovery and retry policy
- [ ] Final polish: status display, metrics, and safer stop/resume behavior
"""

# Persisted data key.
DATA_KEY = "auto_bod_config"
DEBUG_LOG_FILE = "BODAssist.debug.log"
LOGS_DIR = r"F:\Games\Ultima_Online\Clients\TazUO\TazUO\LegionScripts\Logs"
DEBUG_LOG_ENABLED = True
DEBUG_LOG_MAX_CHARS = 80000
LOG_DATA_KEY = "auto_bod_log_config"
LOG_EXPORT_FILE = "BODAssistDebug.txt"
SERVER_OPTIONS = []
DEFAULT_SERVER = ""
RECIPE_EDITOR_REQUEST_KEY = "recipe_editor_request"
RECIPE_EDITOR_RESULT_KEY = "recipe_editor_result"
RECIPE_EDITOR_WAIT_FAILSAFE_S = 180.0
RECIPE_EDITOR_SCRIPT_CANDIDATES = [
    "RecipeBookEditor.py",
    "RecipeBookEditor",
    "Utilities/RecipeBookEditor.py",
    "Utilities\\RecipeBookEditor.py",
]
RECIPE_EDITOR_FILE_CANDIDATES = [
    "RecipeBookEditor.py",
    os.path.join("Utilities", "RecipeBookEditor.py"),
]

# Runebook recall defaults.
RECALL_GUMP_ID = 0x59
RECALL_SETTLE_S = 4.5
BETWEEN_GIVERS_S = 0.8
HOME_BUTTON_MAGE = 50
HOME_BUTTON_CHIV = 75
FIXED_BOD_CONTEXT_INDEX = 1

# BOD request behavior.
BOD_REQUEST_PAUSE_S = 0.9
BOD_REQUEST_ATTEMPTS = 3
BOD_SCAN_SETTLE_S = 1.0
BOD_PARSE_DEBUG = False
BOD_OFFER_GUMP_ID = 0xBAE793EA
BOD_LARGE_OFFER_GUMP_ID = 0xDF22ACC7
BOD_OFFER_ACCEPT_BUTTON_ID = 1
BOD_OFFER_WAIT_S = 1.2

# Fill/Combine behavior.
BOD_COMBINE_BUTTON_IDS = [2, 1, 5, 6]
BOD_DEED_GUMP_ID = 0x344E24
BOD_COMBINE_BUTTON_ID = 4
BOD_COMBINE_TARGET_WAIT_S = 2.5
BOD_CRAFT_TIMEOUT_S = 4.0
LARGE_BOD_MAX_COMBINE_CYCLES = 24
LARGE_BOD_ABSOLUTE_MAX_CYCLES = 64
LARGE_BOD_NO_PROGRESS_LIMIT = 2
CRAFT_INDEX_MAX_PAGES_PER_CATEGORY = 8
CRAFT_NEXT_PAGE_BUTTON_ID = 3
CRAFT_BUTTON_PAUSE_S = 0.28
MOVE_ITEM_PAUSE_S = 0.45
RESTOCK_RETRY_COOLDOWN_S = 1.5
FILL_PHASE_DELAY_S = 0.5
OPEN_CRAFT_RETRY_BACKOFF_S = 1.1
OPEN_CRAFT_FAIL_COOLDOWN_S = 6.0
CONFIG_DB_LOCK_RETRY_ATTEMPTS = 4
CONFIG_DB_LOCK_RETRY_DELAY_S = 1.0

# Fill diagnostics hues by helper/phase.
DIAG_HUE_RUN = 88
DIAG_HUE_PARSE = 63
DIAG_HUE_MATERIAL = 93
DIAG_HUE_TOOL = 73
DIAG_HUE_CONTEXT = 53
DIAG_HUE_CRAFT = 115
DIAG_HUE_COMBINE = 143

# Containers used by fill workflow.
RESOURCE_CONTAINER_SERIAL = 0
BOD_ITEM_CONTAINER_SERIAL = 0
SALVAGE_BAG_SERIAL = 0
TRASH_CONTAINER_SERIAL = 0

# Auto tooling/crafting.
AUTO_TOOLING = True
TINKER_TOOL_IDS = [0x1EB8, 0x1EB9]
BLACKSMITH_TOOL_IDS = [0x0FBB]  # Tongs
TAILOR_TOOL_IDS = [0x0F9D]      # Sewing kit
CARPENTRY_TOOL_IDS = [0x1028, 0x102C, 0x1034, 0x1035]
KEEP_RESOURCE_NAMES = ["ingot", "cloth", "leather", "board", "feather"]

SALVAGE_CONTEXT_INDEX = 2

BLACKSMITH_GUMP_ID = 0xD466EA9C
TINKER_GUMP_ID = 0xD466EA9C
TAILOR_GUMP_ID = 0xD466EA9C
CARPENTRY_GUMP_ID = 0xD466EA9C
CRAFT_GUMP_ANCHORS_BY_PROFESSION = {
    "Blacksmith": ["BLACKSMITHING MENU", "BLACKSMITHING", "BLACKSMITH"],
    "Tailor": ["TAILORING MENU", "TAILORING", "TAILOR"],
    "Carpentry": ["CARPENTRY MENU", "CARPENTRY", "CARPENTER"],
    "Tinker": ["TINKERING MENU", "TINKERING", "TINKER"],
}

RECIPE_BOOK = []
KEY_MAPS = {}
RESOURCE_ITEM_MAP = {}

RECIPE_STORE = None
_script_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
_util_dir = _script_dir
if os.path.basename(str(_util_dir or "")).lower() != "utilities":
    _cand = os.path.join(_script_dir, "Utilities")
    if os.path.isdir(_cand):
        _util_dir = _cand
_project_root_dir = _util_dir
while _project_root_dir and os.path.basename(str(_project_root_dir or "")).lower() in ("resources", "utilities", "skills", "scripts"):
    _project_root_dir = os.path.dirname(_project_root_dir)
if _util_dir and _util_dir not in sys.path:
    sys.path.insert(0, _util_dir)
try:
    import RecipeStore as RECIPE_STORE
    try:
        RECIPE_STORE = importlib.reload(RECIPE_STORE)
    except Exception:
        pass
    try:
        RECIPE_STORE.set_base_dir(_project_root_dir or _util_dir)
    except Exception:
        pass
except Exception:
    RECIPE_STORE = None
LEARN_MODE = True
CRAFT_INDEX_CACHE = {}
SELECTED_SERVER = DEFAULT_SERVER
RECIPE_EDITOR_NONCE = 0
# If true, ingot restock will fail for unknown hues instead of pulling any hue.
STRICT_INGOT_HUE_MATCH = True

# Auto-detect BOD giver titles.
# Replace/extend with your shard-specific title list as needed.
BOD_GIVER_TITLE_HINTS = {
    "Alchemy": ["alchemist"],
    "Blacksmith": ["armorer", "blacksmith", "iron worker", "weaponsmith"],
    "Bowcraft": ["bowyer"],
    "Carpentry": ["carpenter"],
    "Cooking": ["baker", "cook"],
    "Inscription": ["scribe"],
    "Tailor": ["tailor", "weaver"],
    "Tinker": ["tinker"],
}

# Optional shard-specific deed hue mapping.
# If your shard colors small BOD deeds by profession, set hue->profession here.
# Example: 0x0489: "Blacksmith"
BOD_HUE_TO_PROFESSION = {
    1102: "Blacksmith",
    1155: "Tailor",
    1512: "Carpentry",
    1109: "Tinker",
    1425: "Bowcraft",
}

# UI order is left-to-right, top-to-bottom in a 4x2 grid.
BOD_TYPE_ORDER = [
    "Blacksmith", "Tailor", "Carpentry", "Tinker",
    "Alchemy", "Inscription", "Bowcraft", "Cooking",
]

# Fixed runebook slot mapping. Slot 1 is home.
BOD_SLOT_BY_TYPE = {
    "Blacksmith": 2,
    "Tailor": 3,
    "Carpentry": 4,
    "Tinker": 5,
    "Alchemy": 6,
    "Inscription": 7,
    "Bowcraft": 8,
    "Cooking": 9,
}

# Runtime state.
RUNNING = False
RUNBOOK_SERIAL = 0
CRAFT_STATION_X = 0
CRAFT_STATION_Y = 0
CRAFT_STATION_Z = 0
CRAFT_STATION_SET = False
USE_SACRED_JOURNEY = False
HOME_RECALL_BUTTON = HOME_BUTTON_MAGE
ENABLED_BOD_TYPES = {k: True for k in BOD_TYPE_ORDER}
WORK_ANCHOR_DISTANCE = 0
WORK_PATH_RETRIES = 3
WORK_PATH_TIMEOUT_S = 12

# Gump state.
CONTROL_GUMP = None
CONTROL_BUTTON = None
CONTROL_CONTROLS = []
LAST_CRAFT_ERROR = ""
OPENED_CONTAINERS = set()
FORCE_STOP = False
FATAL_STOP_REASON = ""
ACTIVE_CRAFT_GUMP_ID = 0
ACTIVE_CRAFT_PROFESSION = ""
ACTIVE_CRAFT_MATERIAL_KEY = ""
OPEN_CRAFT_BLOCK_UNTIL = 0.0
RESTOCK_BLOCK_UNTIL = {}
CALLBACK_ERR_LAST_AT = 0.0
LOG_TEXT = ""
LOG_LINES = []
LOG_GUMP = None
LOG_PATH_TEXTBOX = None
LOG_EXPORT_BASE = ""


def _debug_log_path():
    return os.path.join(LOGS_DIR, DEBUG_LOG_FILE)


def _write_debug_log(line):
    if not DEBUG_LOG_ENABLED:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts = "unknown-time"
    try:
        path = _debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass


def _append_log(msg):
    global LOG_TEXT, LOG_LINES
    text = str(msg or "")
    LOG_TEXT = (LOG_TEXT + text + "\n")[-DEBUG_LOG_MAX_CHARS:]
    LOG_LINES = LOG_TEXT.splitlines() or ["(log empty)"]
    if LOG_GUMP:
        _update_log_gump()


def _get_log_export_dir():
    global LOG_EXPORT_BASE
    LOG_EXPORT_BASE = LOGS_DIR
    return LOG_EXPORT_BASE


def _load_log_config():
    global LOG_EXPORT_BASE
    LOG_EXPORT_BASE = LOGS_DIR


def _save_log_config():
    data = {"export_path": LOGS_DIR}
    API.SavePersistentVar(LOG_DATA_KEY, json.dumps(data), API.PersistentVar.Char)


def _export_log_to_file():
    export_dir = _get_log_export_dir()
    path = ""
    try:
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, LOG_EXPORT_FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write(LOG_TEXT)
        _say(f"Saved: {LOG_EXPORT_FILE}")
    except Exception as ex:
        _say(f"Failed to export debug log path='{path or export_dir}': {ex}", 33)


def _open_log_gump():
    _update_log_gump()


def _update_log_gump():
    global LOG_GUMP, LOG_PATH_TEXTBOX
    if LOG_GUMP:
        LOG_GUMP.Dispose()
        LOG_GUMP = None

    g = API.CreateGump(True, True, False)
    g.SetRect(350, 140, 360, 420)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, 360, 420)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("BODAssist Debug Log", 14, "#FFFFFF", "alagard", "center", 360)
    title.SetPos(0, 6)
    g.Add(title)

    path_label = API.CreateGumpTTFLabel("Log Folder:", 12, "#FFFFFF", "alagard", "left", 120)
    path_label.SetPos(10, 32)
    g.Add(path_label)
    path_box = API.CreateGumpTextBox(_get_log_export_dir() or "", 230, 18, False)
    path_box.SetPos(90, 30)
    g.Add(path_box)
    LOG_PATH_TEXTBOX = path_box

    exp = API.CreateSimpleButton("Export", 70, 20)
    exp.SetPos(275, 52)
    g.Add(exp)
    API.AddControlOnClick(exp, _export_log_to_file)

    scroll = API.CreateGumpScrollArea(10, 76, 340, 330)
    g.Add(scroll)
    y = 0
    lines = LOG_LINES or ["(log empty)"]
    for line in lines:
        label = API.CreateGumpTTFLabel(line, 12, "#FFFFFF", "alagard", "left", 330)
        label.SetRect(0, y, 330, 16)
        scroll.Add(label)
        y += 18

    API.AddGump(g)
    LOG_GUMP = g


def _reset_debug_log_for_new_session():
    global LOG_TEXT, LOG_LINES
    LOG_TEXT = ""
    LOG_LINES = ["(log empty)"]
    if LOG_GUMP:
        _update_log_gump()
    if not DEBUG_LOG_ENABLED:
        return
    try:
        path = _debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[{ts}] [RUN] Debug log reset for new BODAssist session.\n")
    except Exception:
        pass


def _sleep(seconds):
    global FORCE_STOP
    try:
        API.Pause(seconds)
    except Exception as ex:
        msg = str(ex or "")
        if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
            FORCE_STOP = True
            return False
        return False
    return True


def _wait_and_pump(total_s, step_s=0.1):
    total = float(total_s or 0.0)
    step = max(0.05, float(step_s or 0.1))
    elapsed = 0.0
    while elapsed < total:
        if _should_stop():
            return False
        chunk = min(step, total - elapsed)
        if not _sleep(chunk):
            return False
        _process_callbacks_safe()
        elapsed += chunk
    return True


def _move_item_like_autominer(item_serial, container_target, amount, attempts=3):
    sid = int(item_serial or 0)
    amt = int(amount or 0)
    if sid <= 0 or amt <= 0:
        return False
    for _ in range(max(1, int(attempts))):
        try:
            API.ClearJournal()
        except Exception:
            pass
        try:
            API.MoveItem(int(sid), container_target, int(amt))
        except Exception:
            continue
        _wait_and_pump(1.0, 0.05)
        try:
            if API.InJournal("You must wait to perform another action", True):
                _wait_and_pump(1.2, 0.05)
                continue
        except Exception:
            pass
        return True
    return False


def _wait_for_move_settle(max_s=3.0):
    t0 = _now_s()
    while (_now_s() - t0) < float(max_s):
        if _should_stop():
            return False
        busy_move = False
        busy_gcd = False
        try:
            busy_move = bool(API.IsProcessingMoveQueue())
        except Exception:
            busy_move = False
        try:
            busy_gcd = bool(API.IsGlobalCooldownActive())
        except Exception:
            busy_gcd = False
        if not busy_move and not busy_gcd:
            return True
        _wait_and_pump(0.1, 0.05)
    return False


def _now_s():
    try:
        return float(time.time())
    except Exception:
        return 0.0


def _should_stop():
    try:
        return bool(getattr(API, "StopRequested", False)) or bool(FORCE_STOP)
    except Exception:
        return bool(FORCE_STOP)


def _process_callbacks_safe():
    global FORCE_STOP, CALLBACK_ERR_LAST_AT
    try:
        API.ProcessCallbacks()
        return True
    except Exception as ex:
        msg = str(ex or "")
        if _should_stop() or "ThreadInterrupted" in msg or "interrupted" in msg.lower():
            FORCE_STOP = True
            return False
        now = _now_s()
        if (now - float(CALLBACK_ERR_LAST_AT or 0.0)) >= 1.0:
            CALLBACK_ERR_LAST_AT = now
            _write_debug_log(f"Callback error: {msg}")
        return True


def _wait_for_gump_safe(gump_id=None, delay=0.0):
    if _should_stop():
        return False
    try:
        if gump_id is None:
            return bool(API.WaitForGump(delay=float(delay)))
        return bool(API.WaitForGump(int(gump_id), float(delay)))
    except Exception as ex:
        msg = str(ex or "")
        if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
            try:
                globals()["FORCE_STOP"] = True
            except Exception:
                pass
        return False


def _wait_for_target_safe(kind="any", timeout=2.0):
    if _should_stop():
        return False
    try:
        return bool(API.WaitForTarget(kind, float(timeout)))
    except Exception as ex:
        msg = str(ex or "")
        if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
            try:
                globals()["FORCE_STOP"] = True
            except Exception:
                pass
        return False


def _say(msg, hue=88):
    text = str(msg or "")
    try:
        API.SysMsg(text, hue)
    except Exception:
        pass
    try:
        _append_log(text)
    except Exception:
        pass
    _write_debug_log(text)


def _diag_step(step_id, helper_tag, message, hue=88):
    _say(f"[{str(step_id)}][{str(helper_tag)}] {str(message)}", hue)


def _has_recall_gump():
    # Prefer snapshot-based detection. API.HasGump(89) can report stale true.
    try:
        g = _gump_ids_snapshot() or []
    except Exception:
        g = []
    try:
        gid = int(RECALL_GUMP_ID)
    except Exception:
        gid = 0
    return bool(gid > 0 and gid in [int(x) for x in g])


def _diag_recall_state(step_id, helper_tag, label, hue=88):
    try:
        g = _gump_ids_snapshot() or []
    except Exception:
        g = []
    has = _has_recall_gump()
    _diag_step(step_id, helper_tag, f"{label}: recall_has={has}, gumps={g}", hue)


def _fill_phase_delay(step_id, helper_tag, phase_name, hue=88):
    secs = float(FILL_PHASE_DELAY_S)
    _diag_step(step_id, helper_tag, f"delay start: {phase_name} ({secs:.1f}s)", hue)
    t0 = _now_s()
    try:
        time.sleep(max(0.0, secs))
    except Exception:
        _wait_and_pump(secs, 0.1)
    elapsed = max(0.0, _now_s() - t0)
    _diag_step(step_id, helper_tag, f"delay end: {phase_name} (elapsed={elapsed:.2f}s)", hue)


def _parse_int_list(text):
    return [int(x) for x in re.findall(r"\d+", str(text or ""))]


def _dedupe_case_preserving(values):
    out = []
    seen = set()
    for raw in values or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _is_database_lock_error(ex):
    txt = str(ex or "").strip().lower()
    return ("database is locked" in txt) or ("database schema is locked" in txt)


def _read_with_lock_retries(read_fn, label):
    attempts = int(CONFIG_DB_LOCK_RETRY_ATTEMPTS or 1)
    if attempts < 1:
        attempts = 1
    for attempt in range(1, attempts + 1):
        try:
            return read_fn()
        except Exception as ex:
            if not _is_database_lock_error(ex) or attempt >= attempts:
                raise
            delay_s = float(CONFIG_DB_LOCK_RETRY_DELAY_S) * float(attempt)
            _write_debug_log(
                f"Config: {label} lock retry {attempt}/{attempts} after {delay_s:.1f}s: {ex}"
            )
            _sleep(delay_s)
    return read_fn()


def _server_options_from_key_maps():
    if not isinstance(KEY_MAPS, dict):
        return []
    return _dedupe_case_preserving(KEY_MAPS.keys())


def _current_server_options():
    opts = _dedupe_case_preserving(SERVER_OPTIONS)
    if opts:
        return opts
    return _server_options_from_key_maps()


def _preferred_default_server(options):
    opts = _dedupe_case_preserving(options)
    if not opts:
        return ""
    return str(opts[0])


def _load_server_options_from_store(raise_on_lock=False):
    if RECIPE_STORE is None:
        return []
    if not hasattr(RECIPE_STORE, "load_server_names"):
        return []
    try:
        raw = RECIPE_STORE.load_server_names()
    except Exception as ex:
        _write_debug_log(f"Config: server-list load error: {ex}")
        if bool(raise_on_lock) and _is_database_lock_error(ex):
            raise
        return []
    if not isinstance(raw, list):
        _write_debug_log(f"Config: server-list load invalid type: {type(raw).__name__}")
        return []
    return _dedupe_case_preserving(raw)


def _normalize_server_name(value):
    v = str(value or "").strip()
    opts = _current_server_options()
    if not opts:
        return v
    low = v.lower()
    for s in opts:
        if str(s).lower() == low:
            return str(s)
    return _preferred_default_server(opts)


def _normalize_recipe_type(value):
    v = str(value or "").strip().lower()
    if v in ("bod", "training"):
        return v
    return "bod"


def _deed_tooltip_lines(text):
    return [str(ln).strip() for ln in str(text or "").splitlines() if str(ln).strip()]


def _deed_signature(text):
    """
    Stable deed signature used to disambiguate recipes with similar names.
    Strips volatile fields and progress counters while preserving item/material lines.
    """
    out = []
    for ln in _deed_tooltip_lines(text):
        low = _normalize_text(ln)
        if low.startswith(("weight:", "hue:", "insured:", "durability:", "blessed:", "crafted by:")):
            continue
        line = re.sub(r"\b\d+\s*/\s*\d+\b", "count", low)
        line = re.sub(r"\bamount made\s*[: ]+\d+\b", "amount made count", line, flags=re.I)
        line = re.sub(r"\bamount to make\s*[: ]+\d+\b", "amount to make count", line, flags=re.I)
        line = re.sub(r"\buses remaining\s*[: ]+\d+\b", "uses remaining count", line, flags=re.I)
        if re.match(r"^[a-z][a-z0-9 '\-()/]*\s*:\s*\d+\s*$", line, re.I):
            line = re.sub(r"\s*:\s*\d+\s*$", ": count", line)
        elif re.match(r"^[a-z][a-z0-9 '\-()/]*\s+\d+\s*$", line, re.I):
            line = re.sub(r"\s+\d+\s*$", " count", line)
        norm = _normalize_name(line)
        if norm:
            out.append(norm)
    return " | ".join(out)


def _build_deed_key(item_name, profession="", material_key="", raw_text=""):
    n = _normalize_name(item_name)
    p = _normalize_text(profession)
    mk = str(material_key or "").strip().lower()
    sig = _deed_signature(raw_text)
    return f"{p}|{mk}|{n}|{sig}".strip("|")


def _material_options_for_profession(profession):
    srv = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    prof = _canonical_profession_name(profession)
    if not (srv and prof):
        return []
    srv_node = KEY_MAPS.get(srv, {}) if isinstance(KEY_MAPS, dict) else {}
    if not isinstance(srv_node, dict):
        return []
    node = srv_node.get(prof, {})
    if not isinstance(node, dict):
        return []
    mats = node.get("material_keys", {})
    if not isinstance(mats, dict):
        return []
    out = []
    for mk in sorted(mats.keys()):
        ent = mats.get(mk, {})
        if not isinstance(ent, dict):
            ent = {}
        base = _normalize_text(ent.get("material", "") or "")
        if not base:
            base = _normalize_text(str(mk).split("_")[0])
        suffix = str(mk or "").strip().lower()
        if base and suffix.startswith(base + "_"):
            suffix = suffix[len(base) + 1:]
        label_prefix = (base or str(mk or "").split("_")[0]).replace("_", " ").title()
        if str(mk or "").strip().lower() in ("ingot", "ingot_iron"):
            label = "Ingot - Iron"
        elif suffix and suffix != str(base):
            label = f"{label_prefix} - {str(suffix).replace('_', ' ').title()}"
        else:
            label = label_prefix
        out.append(
            {
                "key": str(mk or "").strip(),
                "label": str(label or ""),
                "base": str(base or "").strip(),
                "buttons": [int(x) for x in (ent.get("material_buttons", []) or []) if int(x) > 0][:2],
                "hue": ent.get("hue", None),
            }
        )
    return out


def _all_material_options_for_server():
    srv = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    srv_node = KEY_MAPS.get(srv, {}) if isinstance(KEY_MAPS, dict) else {}
    if not isinstance(srv_node, dict):
        return []
    out = []
    for prof_name in srv_node.keys():
        out.extend(_material_options_for_profession(prof_name))
    return out


def _material_base_matches(base_value, target_base):
    base = _normalize_text(base_value or "")
    target = _normalize_text(target_base or "")
    if not base or not target:
        return False
    if base == target:
        return True
    aliases = {
        "scale": {"scale", "scales"},
        "scales": {"scale", "scales"},
        "leather": {"leather", "hide", "hides"},
        "hide": {"leather", "hide", "hides"},
        "hides": {"leather", "hide", "hides"},
    }
    left = aliases.get(base, {base})
    right = aliases.get(target, {target})
    return bool(left & right)


def _material_option_by_key(key, profession=None):
    needle = str(key or "").strip().lower()
    if not needle:
        return None
    opts = _material_options_for_profession(profession) if profession else []
    for o in opts:
        if str(o.get("key", "")).strip().lower() == needle:
            return o
    for o in _all_material_options_for_server():
        if str(o.get("key", "")).strip().lower() == needle:
            return o
    return None


def _material_option_index_for_key(key, profession):
    needle = str(key or "").strip()
    opts = _material_options_for_profession(profession)
    for i, o in enumerate(opts):
        if str(o.get("key", "")).strip() == needle:
            return i
    return 0


def _find_material_key_by_terms(base_hint, terms, profession=""):
    expected = [_normalize_text(t) for t in (terms or []) if _normalize_text(t)]
    options = _material_options_for_profession(profession) if profession else []
    if not options:
        options = _all_material_options_for_server()
    for opt in options:
        key = str(opt.get("key", "") or "").strip()
        base = _normalize_text(opt.get("base", "") or "")
        if not key or not base:
            continue
        if base_hint and not _material_base_matches(base, base_hint):
            continue
        key_text = _normalize_text(key.replace("_", " "))
        label_text = _normalize_text(opt.get("label", "") or "")
        if all((term in key_text) or (term in label_text) for term in expected):
            return key
    return ""


def _default_material_key_for_base(base_hint, profession=""):
    options = _material_options_for_profession(profession) if profession else []
    if not options:
        options = _all_material_options_for_server()
    candidates = []
    for opt in options:
        key = str(opt.get("key", "") or "").strip()
        base = _normalize_text(opt.get("base", "") or "")
        if not key or not base:
            continue
        if base_hint and not _material_base_matches(base, base_hint):
            continue
        candidates.append(dict(opt))
    if not candidates:
        return ""
    ranked = sorted(
        candidates,
        key=lambda opt: (
            int((opt.get("buttons", [99999, 99999]) + [99999, 99999])[1]),
            int((opt.get("buttons", [99999]) + [99999])[0]),
            len(str(opt.get("key", "") or "")),
            str(opt.get("key", "") or ""),
        ),
    )
    return str(ranked[0].get("key", "") or "")


def _infer_material_key(material_text, raw_text=""):
    low = _normalize_text(f"{material_text or ''} {raw_text or ''}")
    for metal_name in (
        "dull copper",
        "shadow iron",
        "agapite",
        "valorite",
        "verite",
        "bronze",
        "copper",
        "gold",
        "iron",
    ):
        if metal_name in low:
            key = _find_material_key_by_terms("ingot", [metal_name])
            if key:
                return key
    for color_name in ("red", "yellow", "black", "green", "white", "blue"):
        if f"{color_name} scale" in low:
            key = _find_material_key_by_terms("scale", [color_name])
            if key:
                return key
    if "scale" in low:
        key = _default_material_key_for_base("scale")
        if key:
            return key
    if "leather" in low:
        key = _default_material_key_for_base("leather")
        if key:
            return key
    if "cloth" in low:
        key = _default_material_key_for_base("cloth")
        if key:
            return key
    if "board" in low:
        key = _default_material_key_for_base("board")
        if key:
            return key
    if "ingot" in low:
        key = _default_material_key_for_base("ingot")
        if key:
            return key
    return ""


def _parse_material_key_needed(text, material_needed="", profession=""):
    low = _normalize_text(text)
    lines = [_normalize_text(x) for x in str(text or "").splitlines() if _normalize_text(x)]

    # Strong explicit scale matches first.
    scale_map = ["red", "yellow", "black", "green", "white", "blue"]
    for color_name in scale_map:
        needle = f"{color_name} scale"
        if needle in low:
            key = _find_material_key_by_terms("scale", [color_name], profession)
            if key:
                return key

    ingot_map = (
        "dull copper",
        "shadow iron",
        "agapite",
        "valorite",
        "verite",
        "bronze",
        "copper",
        "gold",
        "iron",
    )

    # Strict parse on material-focused lines first.
    material_lines = [ln for ln in lines if ("material" in ln or "ingot" in ln or "scale" in ln)]
    explicit_hits = []
    for ln in material_lines:
        m = re.search(r"\b(dull copper|shadow iron|copper|bronze|gold|agapite|verite|valorite|iron)\s+ingots?\b", ln)
        if m:
            hit = _find_material_key_by_terms("ingot", [str(m.group(1) or "")], profession)
            if hit:
                explicit_hits.append(hit)
            continue
        # Some shards omit the word ingot but still use "material: dull copper".
        if "material" in ln:
            for name in ingot_map:
                if name in ln:
                    hit = _find_material_key_by_terms("ingot", [name], profession)
                    if hit:
                        explicit_hits.append(hit)
                    break
    explicit_hits = [h for h in explicit_hits if h]
    if len(explicit_hits) == 1:
        return explicit_hits[0]
    if len(set(explicit_hits)) > 1:
        # Ambiguous tooltip data; do not guess subtype.
        return ""

    # Fallback to base material only (no guessed ingot subtype).
    mk = _infer_material_key(material_needed or "", "")
    opt = _material_option_by_key(mk, profession) if mk else None
    base = _normalize_text(opt.get("base", "") if isinstance(opt, dict) else "")
    if base in ("cloth", "leather", "hide", "hides", "board", "scale", "scales"):
        return mk
    # No explicit ingot subtype found in deed text.
    return ""


def _format_deed_material_display(material_needed="", material_key="", profession=""):
    mk = str(material_key or "").strip()
    if mk:
        opt = _material_option_by_key(mk, profession)
        if opt:
            return str(opt.get("label", mk))
        return mk
    base = _normalize_text(material_needed or "")
    if base == "ingot":
        return "Ingot (basic/no subtype)"
    if base == "cloth":
        return "Cloth (basic)"
    if base == "leather":
        return "Leather (basic)"
    if base == "board":
        return "Board (basic)"
    return base if base else "Unknown"


def _material_base_from_recipe(recipe):
    key = str(recipe.get("material_key", "") or "")
    opt = _material_option_by_key(key, str(recipe.get("profession", "") or ""))
    if opt:
        return str(opt.get("base", "ingot"))
    return str(recipe.get("material", "ingot") or "ingot")


def _key_map_item_entry(recipe):
    try:
        srv = _normalize_server_name(recipe.get("server", SELECTED_SERVER) or SELECTED_SERVER)
        prof = str(recipe.get("profession", "") or "")
        nm = _normalize_item_key_name(recipe.get("name", ""))
        if not (srv and prof and nm):
            return None
        node = (KEY_MAPS.get(srv, {}) or {}).get(prof, {}) or {}
        item_keys = node.get("item_keys", {}) if isinstance(node, dict) else {}
        ent = {}
        if isinstance(item_keys, dict):
            lookup_keys = []
            for candidate in [
                nm,
                nm.replace(" ", "_"),
                nm.replace("-", "_"),
                nm.replace("-", " "),
                nm.replace(" ", "_").replace("-", "_"),
            ]:
                key = str(candidate or "").strip()
                if key and key not in lookup_keys:
                    lookup_keys.append(key)
            for key in lookup_keys:
                hit = item_keys.get(key, {})
                if isinstance(hit, dict):
                    ent = hit
                    break
        if not isinstance(ent, dict):
            return None
        out = dict(ent)
        out["buttons"] = _normalize_item_buttons_for_category(
            srv,
            prof,
            str(out.get("category", "") or ""),
            out.get("buttons", []),
        )
        return out
    except Exception:
        return None


def _material_option_hue_by_key(material_key, profession="", server=""):
    srv = _normalize_server_name(server or SELECTED_SERVER)
    prof = str(profession or "")
    mk = str(material_key or "").strip().lower()
    if not (srv and mk):
        return None
    srv_node = KEY_MAPS.get(srv, {}) if isinstance(KEY_MAPS, dict) else {}
    if not isinstance(srv_node, dict):
        return None
    prof_candidates = [prof] if prof else []
    for p in srv_node.keys():
        pp = str(p or "")
        if pp and pp not in prof_candidates:
            prof_candidates.append(pp)
    for p in prof_candidates:
        node = srv_node.get(p, {})
        if not isinstance(node, dict):
            continue
        mats = node.get("material_keys", {})
        if not isinstance(mats, dict):
            continue
        ent = mats.get(mk, {})
        if not isinstance(ent, dict):
            continue
        hue = ent.get("hue", None)
        if hue is None:
            continue
        try:
            return int(hue)
        except Exception:
            return None
    return None


def _resolved_ingot_hue(material_key, profession="", server=""):
    mk = str(material_key or "").strip().lower()
    if not mk:
        return None
    keys = [mk]
    if mk == "ingot":
        keys.append("ingot_iron")
    elif mk == "ingot_iron":
        keys.append("ingot")
    for key in keys:
        hue = _material_option_hue_by_key(key, profession, server)
        if hue is not None:
            return int(hue)
    return None


def _non_iron_ingot_hues():
    srv = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    srv_node = KEY_MAPS.get(srv, {}) if isinstance(KEY_MAPS, dict) else {}
    out = set()
    if not isinstance(srv_node, dict):
        return out
    for prof_node in srv_node.values():
        if not isinstance(prof_node, dict):
            continue
        mats = prof_node.get("material_keys", {})
        if not isinstance(mats, dict):
            continue
        for mk, ent in mats.items():
            key = str(mk or "").strip().lower()
            if not key.startswith("ingot"):
                continue
            if key in ("ingot", "ingot_iron"):
                continue
            if not isinstance(ent, dict):
                continue
            hue = ent.get("hue", None)
            if hue is None:
                continue
            try:
                out.add(int(hue))
            except Exception:
                continue
    return out


def _merge_item_key_map_into_recipe(recipe):
    if not isinstance(recipe, dict):
        return recipe
    merged = dict(recipe)
    ent = _key_map_item_entry(merged) or {}
    if not ent:
        return merged

    server = _normalize_server_name(merged.get("server", SELECTED_SERVER) or SELECTED_SERVER)
    profession = str(merged.get("profession", "") or "")
    category = str(ent.get("category", "") or "")
    mapped_buttons = _normalize_item_buttons_for_category(server, profession, category, ent.get("buttons", []))
    if mapped_buttons:
        merged["buttons"] = mapped_buttons
    elif category:
        merged["buttons"] = _normalize_item_buttons_for_category(
            server, profession, category, merged.get("buttons", [])
        ) or [int(x) for x in (merged.get("buttons", []) or []) if int(x) > 0]

    if int(merged.get("item_id", 0) or 0) <= 0:
        try:
            merged["item_id"] = int(ent.get("item_id", 0) or 0)
        except Exception:
            pass
    if not str(merged.get("material_key", "") or "").strip():
        merged["material_key"] = str(ent.get("default_material_key", "") or "").strip()
    return merged


def _resource_name_key(material):
    return _normalize_text(material or "")


def _resource_map_lookup(material):
    key = _resource_name_key(material)
    if not key:
        return None
    ent = RESOURCE_ITEM_MAP.get(key, {}) if isinstance(RESOURCE_ITEM_MAP, dict) else {}
    if not ent and key.endswith("s"):
        ent = RESOURCE_ITEM_MAP.get(key[:-1], {}) if isinstance(RESOURCE_ITEM_MAP, dict) else {}
    return dict(ent) if isinstance(ent, dict) else None


def _resource_item_id(material):
    ent = _resource_map_lookup(material) or {}
    try:
        return int(ent.get("item_id", 0) or 0)
    except Exception:
        return 0


def _resource_item_defaults(material):
    mat = _resource_name_key(material)
    ent = _resource_map_lookup(mat) or {}
    iid = int(ent.get("item_id", 0) or 0)
    hue = ent.get("hue", None)
    if hue is not None:
        try:
            hue = int(hue)
        except Exception:
            hue = None
    if mat == "ingot":
        return int(iid), 60, 400, hue
    if mat == "cloth":
        return int(iid), 60, 300, hue
    if mat == "leather":
        return int(iid), 60, 300, hue
    if mat == "board":
        return int(iid), 80, 500, hue
    if mat in ("feather", "feathers"):
        return int(iid), 60, 300, hue
    if iid > 0:
        return int(iid), 10, 50, hue
    return 0, 10, 50, hue


def _parse_material_requirement_entry(raw_entry):
    if isinstance(raw_entry, dict):
        return dict(raw_entry)
    text = str(raw_entry or "").strip()
    if not text:
        return None
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return dict(parsed)


def _material_requirements_from_recipe(recipe, required_items=1):
    reqs = []
    needed = max(1, int(required_items or 1))
    # Prefer item-key resources (base material quantities per item) when present.
    item_ent = _key_map_item_entry(recipe) or {}
    resources = item_ent.get("resources", []) if isinstance(item_ent, dict) else []
    if isinstance(resources, list):
        for rr in resources:
            if not isinstance(rr, dict):
                continue
            base = _normalize_text(rr.get("material", "") or "")
            per_item = int(rr.get("per_item", 0) or 0)
            if not base or per_item <= 0:
                continue
            total = max(1, int(per_item) * int(needed))
            iid, _, default_pull, mapped_hue = _resource_item_defaults(base)
            reqs.append({
                "material": base,
                "item_id": int(iid or 0),
                "min_in_pack": int(total),
                "pull_amount": int(max(total, default_pull)),
                "hue": mapped_hue,
            })
    raw = recipe.get("materials", []) or []
    if isinstance(raw, list) and not reqs:
        for ent in raw:
            payload = _parse_material_requirement_entry(ent)
            if payload is None and isinstance(ent, dict):
                payload = dict(ent)
            if isinstance(payload, dict):
                base = _normalize_text(payload.get("material", "") or "")
                if not base:
                    base = _normalize_text(_material_base_from_recipe(recipe))
                iid_default, _, pull_default, hue_default = _resource_item_defaults(base)
                iid = int(payload.get("item_id", 0) or 0)
                if iid <= 0:
                    iid = int(iid_default or 0)
                hue = payload.get("hue", None)
                if hue is None:
                    hue = hue_default
                pull_amount = int(payload.get("pull_amount", 0) or 0)
                if pull_amount <= 0:
                    pull_amount = int(pull_default or 0)
                reqs.append({
                    "material": base,
                    "item_id": int(iid or 0),
                    "min_in_pack": int(payload.get("min_in_pack", 0) or 0),
                    "pull_amount": int(pull_amount or 0),
                    "hue": hue,
                })
            else:
                base = _normalize_text(str(ent or ""))
                if base:
                    reqs.append({
                        "material": base,
                        "item_id": 0,
                        "min_in_pack": 0,
                        "pull_amount": 0,
                        "hue": None,
                    })
    if not reqs:
        reqs.append({
            "material": _normalize_text(_material_base_from_recipe(recipe)),
            "item_id": 0,
            "min_in_pack": 0,
            "pull_amount": 0,
            "hue": None,
        })
    return reqs


def _material_buttons_from_recipe(recipe):
    # Recipe-local override wins; otherwise use mapped material option defaults.
    local = [int(x) for x in (recipe.get("material_buttons", []) or []) if int(x) > 0]
    if local:
        return local
    key = str(recipe.get("material_key", "") or "")
    opt = _material_option_by_key(key, str(recipe.get("profession", "") or ""))
    if not opt:
        return []
    return [int(x) for x in (opt.get("buttons", []) or []) if int(x) > 0]


def _wanted_hue_for_item(recipe, item_id):
    # Currently only ingots need hue filtering on this shard.
    ingot_id = int(_resource_item_id("ingot") or 0)
    if ingot_id <= 0 or int(item_id) != ingot_id:
        return None
    key = str(_recipe_material_key(recipe) or "").strip().lower()
    if not key:
        return None
    prof = str(recipe.get("profession", "") or "")
    srv = _normalize_server_name(recipe.get("server", SELECTED_SERVER) or SELECTED_SERVER)
    hue = _resolved_ingot_hue(key, prof, srv)
    if hue is None and STRICT_INGOT_HUE_MATCH:
        return "__MISSING__"
    return hue


def _manual_learn_recipe_for_deed(parsed, wait_s=-1.0):
    _say("Manual recipe required. Opening RecipeBookEditor.", 33)
    out = _launch_recipe_editor({
        "editor_mode": "bind_deed",
        "recipe_type": "bod",
        "server": str(SELECTED_SERVER or DEFAULT_SERVER),
        "profession": str(parsed.get("profession", "") or "Blacksmith"),
        "material": str(parsed.get("material_needed", "") or "ingot"),
        "material_key": str(parsed.get("material_key", "") or ""),
        "name": str(parsed.get("item_name", "") or ""),
        "buttons": "",
        "deed_key": str(parsed.get("deed_key", "") or ""),
        "item_id": 0,
        "deed_serial": int(parsed.get("deed_serial", 0) or 0),
        "required": int(parsed.get("required", 0) or 0),
        "filled": int(parsed.get("filled", 0) or 0),
        "remaining": int(parsed.get("remaining", 0) or 0),
        "exceptional": bool(parsed.get("exceptional", False)),
        "raw_text": str(parsed.get("raw_text", "") or ""),
    }, wait_s=wait_s)
    # Always refresh runtime caches from DB after editor returns so we can
    # recover even when save-ack handoff is missed.
    _reload_recipe_cache_from_store("post_recipe_editor")

    deed_key = str(parsed.get("deed_key", "") or "").strip()
    profession = str(parsed.get("profession", "") or "").strip()
    item_name = str(parsed.get("item_name", "") or "").strip()
    raw_text = str(parsed.get("raw_text", "") or "")

    learned = None
    if deed_key:
        learned = _find_recipe_for_deed_key(deed_key, profession or None)
    if not learned and item_name:
        learned = _find_recipe_for_item_name(item_name, profession or None, None)
    if not learned and raw_text:
        learned = _find_recipe_for_text(raw_text, profession or None, None)
    if learned:
        _write_debug_log(
            f"Manual learn: recovered mapping from refreshed cache for '{item_name or deed_key}'."
        )
        return _merge_item_key_map_into_recipe(dict(learned))

    return out if out else None


def _set_running(value):
    global RUNNING, FORCE_STOP
    RUNNING = bool(value)
    if RUNNING:
        FORCE_STOP = False
    if CONTROL_BUTTON:
        CONTROL_BUTTON.Text = "Pause" if RUNNING else "Start"


def _toggle_running():
    _set_running(not RUNNING)


def _hard_stop():
    global FORCE_STOP, ACTIVE_CRAFT_GUMP_ID, ACTIVE_CRAFT_PROFESSION, ACTIVE_CRAFT_MATERIAL_KEY, OPEN_CRAFT_BLOCK_UNTIL, OPENED_CONTAINERS
    FORCE_STOP = True
    _set_running(False)
    ACTIVE_CRAFT_GUMP_ID = 0
    ACTIVE_CRAFT_PROFESSION = ""
    ACTIVE_CRAFT_MATERIAL_KEY = ""
    OPEN_CRAFT_BLOCK_UNTIL = 0.0
    OPENED_CONTAINERS = set()
    try:
        API.CancelTarget()
    except Exception:
        pass
    _say("Stop requested. BODAssist halted safely.", 33)


def _pause_if_needed():
    if _should_stop():
        return False
    while not RUNNING:
        if _should_stop():
            return False
        if not _process_callbacks_safe():
            return False
        _sleep(0.1)
    return True


def _default_config():
    default_server = _preferred_default_server(_current_server_options())
    return {
        "runebook_serial": 0,
        "resource_container_serial": 0,
        "bod_item_container_serial": 0,
        "salvage_bag_serial": 0,
        "trash_container_serial": 0,
        "auto_tooling": True,
        "learn_mode": True,
        "craft_station_x": 0,
        "craft_station_y": 0,
        "craft_station_z": 0,
        "craft_station_set": False,
        "use_sacred_journey": False,
        "enabled_bod_types": {k: True for k in BOD_TYPE_ORDER},
        "selected_server": default_server,
    }


def _refresh_recall_buttons():
    global HOME_RECALL_BUTTON
    if USE_SACRED_JOURNEY:
        HOME_RECALL_BUTTON = HOME_BUTTON_CHIV
    else:
        HOME_RECALL_BUTTON = HOME_BUTTON_MAGE


def _normalize_recipe_entry(r):
    try:
        if not isinstance(r, dict):
            return None
        name = str(r.get("name", "") or "").strip()
        profession = _canonical_profession_name(r.get("profession", ""))
        if not name or not profession:
            return None
        return {
            "name": name,
            "profession": profession,
            "item_id": int(r.get("item_id", 0) or 0),
            "buttons": [int(x) for x in (r.get("buttons", []) or []) if int(x) > 0],
            "material": str(r.get("material", "ingot")).strip().lower(),
            "material_key": str(r.get("material_key", "") or "").strip(),
            "materials": list(r.get("materials", []) or []),
            "material_buttons": [int(x) for x in (r.get("material_buttons", []) or []) if int(x) > 0],
            "deed_key": str(r.get("deed_key", "") or "").strip(),
            "recipe_type": _normalize_recipe_type(r.get("recipe_type", "bod")),
            "server": _normalize_server_name(r.get("server", DEFAULT_SERVER)),
        }
    except Exception:
        return None


def _normalize_item_key_name(name):
    n = str(name or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"[^a-z0-9 '\-]", "", n)
    return n.strip()


def _normalize_item_buttons_for_category(server, profession, category, buttons):
    return [int(x) for x in (buttons or []) if int(x) > 0][:2]


def _load_recipe_book_from_file(raise_on_lock=False):
    if RECIPE_STORE is None:
        return None
    try:
        raw = RECIPE_STORE.load_recipes()
        if raw is None:
            _write_debug_log("Config: recipe load invalid type: NoneType")
            return None
        if not isinstance(raw, list):
            _write_debug_log(f"Config: recipe load invalid type: {type(raw).__name__}")
            return None
        out = [r for r in (_normalize_recipe_entry(x) for x in raw) if r]
        return out if out else []
    except Exception as ex:
        _write_debug_log(f"Config: recipe load error: {ex}")
        try:
            if hasattr(RECIPE_STORE, "last_init_error"):
                init_err = str(RECIPE_STORE.last_init_error() or "").strip()
                if init_err:
                    _write_debug_log(f"Config: recipe load DB init error: {init_err}")
        except Exception:
            pass
        if bool(raise_on_lock) and _is_database_lock_error(ex):
            raise
        return None
    return None


def _load_key_maps_from_file(raise_on_lock=False):
    if RECIPE_STORE is None:
        return None
    try:
        raw = RECIPE_STORE.load_key_maps()
        if raw is None:
            _write_debug_log("Config: key-map load invalid type: NoneType")
            return None
        if not isinstance(raw, dict):
            _write_debug_log(f"Config: key-map load invalid type: {type(raw).__name__}")
            return None
        return dict(raw)
    except Exception as ex:
        _write_debug_log(f"Config: key-map load error: {ex}")
        try:
            if hasattr(RECIPE_STORE, "last_init_error"):
                init_err = str(RECIPE_STORE.last_init_error() or "").strip()
                if init_err:
                    _write_debug_log(f"Config: key-map load DB init error: {init_err}")
        except Exception:
            pass
        if bool(raise_on_lock) and _is_database_lock_error(ex):
            raise
        return None


def _load_resource_item_map_from_file(raise_on_lock=False):
    if RECIPE_STORE is None:
        return None
    if not hasattr(RECIPE_STORE, "load_resource_item_map"):
        return None
    try:
        raw = RECIPE_STORE.load_resource_item_map()
        if raw is None:
            _write_debug_log("Config: resource-map load invalid type: NoneType")
            return None
        if not isinstance(raw, dict):
            _write_debug_log(f"Config: resource-map load invalid type: {type(raw).__name__}")
            return None
        return dict(raw)
    except Exception as ex:
        _write_debug_log(f"Config: resource-map load error: {ex}")
        try:
            if hasattr(RECIPE_STORE, "last_init_error"):
                init_err = str(RECIPE_STORE.last_init_error() or "").strip()
                if init_err:
                    _write_debug_log(f"Config: resource-map DB init error: {init_err}")
        except Exception:
            pass
        if bool(raise_on_lock) and _is_database_lock_error(ex):
            raise
        return None


def _reload_recipe_cache_from_store(reason=""):
    global RECIPE_BOOK, KEY_MAPS, RESOURCE_ITEM_MAP, SERVER_OPTIONS, DEFAULT_SERVER, SELECTED_SERVER
    if RECIPE_STORE is None:
        return False
    changed = False
    try:
        book = _load_recipe_book_from_file()
        if isinstance(book, list):
            RECIPE_BOOK = list(book)
            changed = True
    except Exception:
        pass
    try:
        key_maps = _load_key_maps_from_file()
        if isinstance(key_maps, dict):
            KEY_MAPS = dict(key_maps)
            changed = True
    except Exception:
        pass
    try:
        res_map = _load_resource_item_map_from_file()
        if isinstance(res_map, dict):
            RESOURCE_ITEM_MAP = dict(res_map)
            changed = True
    except Exception:
        pass
    try:
        server_options = _load_server_options_from_store()
        if not server_options:
            server_options = _server_options_from_key_maps()
        if server_options:
            SERVER_OPTIONS = _dedupe_case_preserving(server_options)
            DEFAULT_SERVER = _preferred_default_server(SERVER_OPTIONS)
            SELECTED_SERVER = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
            changed = True
    except Exception:
        pass
    if changed:
        _write_debug_log(
            "Recipe cache reload ({0}): recipes={1} key_servers={2} resources={3}".format(
                str(reason or "manual"),
                int(len(RECIPE_BOOK)),
                int(len(KEY_MAPS)),
                int(len(RESOURCE_ITEM_MAP)),
            )
        )
    return changed


def _get_persistent_json(key):
    raw = API.GetPersistentVar(str(key), "", API.PersistentVar.Char)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return None


def _set_persistent_json(key, obj):
    try:
        API.SavePersistentVar(str(key), json.dumps(obj or {}), API.PersistentVar.Char)
    except Exception:
        pass


def _launch_recipe_editor(payload=None, wait_s=0.0):
    global RECIPE_EDITOR_NONCE
    RECIPE_EDITOR_NONCE += 1
    nonce = int(RECIPE_EDITOR_NONCE)
    req = {
        "nonce": nonce,
        "caller": "BODAssist",
        "payload": dict(payload or {}),
    }
    _set_persistent_json(RECIPE_EDITOR_REQUEST_KEY, req)
    _set_persistent_json(RECIPE_EDITOR_RESULT_KEY, {"nonce": nonce, "status": "pending"})
    launched = False
    play_sent = False
    script_candidates = []
    try:
        abs_editor = os.path.normpath(os.path.join(_util_dir, "RecipeBookEditor.py"))
        if abs_editor:
            script_candidates.append(abs_editor)
    except Exception:
        pass
    for script_name in RECIPE_EDITOR_SCRIPT_CANDIDATES:
        s = str(script_name or "").strip()
        if s and s not in script_candidates:
            script_candidates.append(s)

    for script_name in script_candidates:
        try:
            API.PlayScript(str(script_name))
            play_sent = True
        except Exception as ex:
            _write_debug_log(f"RecipeEditor PlayScript failed [{script_name}]: {ex}")
            continue
        try:
            # Handshake from editor confirms actual launch.
            ack_wait = 0.0
            while ack_wait < 2.5:
                if not _process_callbacks_safe():
                    break
                _sleep(0.1)
                ack_wait += 0.1
                res = _get_persistent_json(RECIPE_EDITOR_RESULT_KEY) or {}
                status = str(res.get("status", "") or "").strip().lower()
                if status not in ("opened", "saved", "cancel", "error"):
                    continue
                try:
                    got_nonce = int(res.get("nonce", 0) or 0)
                except Exception:
                    got_nonce = 0
                if got_nonce != nonce:
                    _write_debug_log(
                        f"RecipeEditor ack nonce mismatch: requested={nonce} got={got_nonce} status={status}"
                    )
                    continue
                if status == "error":
                    _write_debug_log(
                        "RecipeEditor launch error ack: nonce={0} detail={1}".format(
                            int(nonce), str(res.get("error", "") or "")
                        )
                    )
                    break
                launched = True
                break
            if launched:
                break
            _write_debug_log(f"RecipeEditor no ack after PlayScript [{script_name}]")
            continue
        except Exception as ex:
            _write_debug_log(f"RecipeEditor handshake failed [{script_name}]: {ex}")
            continue
    if not launched and not play_sent:
        # Fallback: run editor script directly in-process if Script Manager launch is unavailable.
        roots = []
        try:
            roots.append(os.path.dirname(__file__))
        except Exception:
            pass
        try:
            roots.append(os.getcwd())
        except Exception:
            pass
        try:
            roots.append(os.path.dirname(os.path.dirname(__file__)))
        except Exception:
            pass
        try:
            sp = str(getattr(API, "ScriptPath", "") or "").strip()
            if sp:
                roots.append(os.path.dirname(sp))
                roots.append(os.path.dirname(os.path.dirname(sp)))
        except Exception:
            pass
        seen_roots = []
        for r in roots:
            rr = os.path.normpath(str(r or ""))
            if rr and rr not in seen_roots:
                seen_roots.append(rr)
        candidate_paths = []
        for root in seen_roots:
            for rel in RECIPE_EDITOR_FILE_CANDIDATES:
                p = os.path.normpath(os.path.join(root, rel))
                if p not in candidate_paths:
                    candidate_paths.append(p)
        for p in candidate_paths:
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    code = f.read()
                local_ctx = {"API": API, "__file__": p, "__name__": "__main__"}
                exec(compile(code, p, "exec"), local_ctx, local_ctx)
                res = _get_persistent_json(RECIPE_EDITOR_RESULT_KEY) or {}
                if int(res.get("nonce", 0) or 0) == nonce and str(res.get("status", "") or "").strip().lower() in ("opened", "saved", "cancel"):
                    launched = True
                    break
            except Exception as ex:
                _write_debug_log(f"RecipeEditor fallback exec failed [{p}]: {ex}")
                continue
        if not launched:
            _say("RecipeBookEditor fallback lookup failed: " + " | ".join(candidate_paths[:6]), 33)
    if not launched:
        init_err = ""
        try:
            if RECIPE_STORE is not None and hasattr(RECIPE_STORE, "last_init_error"):
                init_err = str(RECIPE_STORE.last_init_error() or "")
        except Exception:
            init_err = ""
        if init_err:
            _say(f"Could not launch RecipeBookEditor.py (DB: {init_err}).", 33)
        elif play_sent:
            _say("Could not launch RecipeBookEditor.py (PlayScript sent but no editor ack).", 33)
        else:
            _say("Could not launch RecipeBookEditor.py (check script path/name in Script Manager).", 33)
        return None
    if float(wait_s) == 0.0:
        return None
    if float(wait_s) < 0:
        _say("RecipeBookEditor opened. Waiting for Save/Cancel...", 88)
        wait_limit = None
    else:
        wait_limit = float(wait_s)
    waited = 0.0
    step = 0.1
    last_probe_s = -1.0
    while True:
        if wait_limit is None and waited >= float(RECIPE_EDITOR_WAIT_FAILSAFE_S):
            _write_debug_log(
                f"RecipeEditor wait fail-safe timeout ({float(RECIPE_EDITOR_WAIT_FAILSAFE_S):.0f}s); continuing."
            )
            break
        if wait_limit is not None and waited >= wait_limit:
            break
        if _should_stop():
            _write_debug_log("RecipeEditor wait aborted: stop requested.")
            break
        if not _process_callbacks_safe():
            _write_debug_log("RecipeEditor wait aborted: callback processing failed.")
            break
        _sleep(step)
        waited += step
        res = _get_persistent_json(RECIPE_EDITOR_RESULT_KEY) or {}
        status = str(res.get("status", "") or "").strip().lower()
        if (waited - float(last_probe_s)) >= 2.0:
            try:
                dbg_nonce = int(res.get("nonce", 0) or 0)
            except Exception:
                dbg_nonce = 0
            _write_debug_log(
                "RecipeEditor wait probe: requested={0} got={1} status={2} waited={3:.1f}s".format(
                    int(nonce), int(dbg_nonce), str(status or "<empty>"), float(waited)
                )
            )
            last_probe_s = float(waited)
        try:
            got_nonce = int(res.get("nonce", 0) or 0)
        except Exception:
            got_nonce = 0
        if got_nonce != nonce:
            continue
        if status == "error":
            _say("RecipeBookEditor reported a startup error. Check RecipeBookEditor.debug.log.", 33)
            _write_debug_log(
                "RecipeEditor wait error: requested={0} detail={1}".format(
                    int(nonce), str(res.get("error", "") or "")
                )
            )
            break
        if status in ("saved", "cancel"):
            if status == "saved":
                out = _normalize_recipe_entry(res.get("recipe", {}))
                return out
            return None
    return None


def _load_config():
    global RUNBOOK_SERIAL, RESOURCE_CONTAINER_SERIAL, BOD_ITEM_CONTAINER_SERIAL, SALVAGE_BAG_SERIAL, TRASH_CONTAINER_SERIAL, AUTO_TOOLING, LEARN_MODE, RECIPE_BOOK, KEY_MAPS, RESOURCE_ITEM_MAP, SELECTED_SERVER, SERVER_OPTIONS, DEFAULT_SERVER
    global CRAFT_STATION_X, CRAFT_STATION_Y, CRAFT_STATION_Z, CRAFT_STATION_SET, USE_SACRED_JOURNEY, ENABLED_BOD_TYPES
    server_options = _read_with_lock_retries(
        lambda: _load_server_options_from_store(raise_on_lock=True),
        "server-list",
    )
    SERVER_OPTIONS = _dedupe_case_preserving(server_options)
    DEFAULT_SERVER = _preferred_default_server(SERVER_OPTIONS)
    raw = API.GetPersistentVar(DATA_KEY, "", API.PersistentVar.Char)
    if raw:
        try:
            try:
                data = json.loads(raw)
            except Exception:
                data = ast.literal_eval(raw)
            RUNBOOK_SERIAL = int(data.get("runebook_serial", 0) or 0)
            RESOURCE_CONTAINER_SERIAL = int(data.get("resource_container_serial", 0) or 0)
            BOD_ITEM_CONTAINER_SERIAL = int(data.get("bod_item_container_serial", 0) or 0)
            SALVAGE_BAG_SERIAL = int(data.get("salvage_bag_serial", 0) or 0)
            TRASH_CONTAINER_SERIAL = int(data.get("trash_container_serial", 0) or 0)
            AUTO_TOOLING = bool(data.get("auto_tooling", True))
            LEARN_MODE = bool(data.get("learn_mode", True))
            SELECTED_SERVER = str(data.get("selected_server", "") or "").strip()
            RECIPE_BOOK = []
            CRAFT_STATION_X = int(data.get("craft_station_x", 0) or 0)
            CRAFT_STATION_Y = int(data.get("craft_station_y", 0) or 0)
            CRAFT_STATION_Z = int(data.get("craft_station_z", 0) or 0)
            CRAFT_STATION_SET = bool(data.get("craft_station_set", False))
            USE_SACRED_JOURNEY = bool(data.get("use_sacred_journey", False))
            raw_enabled = data.get("enabled_bod_types", {}) or {}
            ENABLED_BOD_TYPES = {k: True for k in BOD_TYPE_ORDER}
            for bod_type in BOD_TYPE_ORDER:
                if bod_type in raw_enabled:
                    ENABLED_BOD_TYPES[bod_type] = bool(raw_enabled.get(bod_type))
        except Exception:
            data = _default_config()
            RUNBOOK_SERIAL = data["runebook_serial"]
            RESOURCE_CONTAINER_SERIAL = data["resource_container_serial"]
            BOD_ITEM_CONTAINER_SERIAL = data["bod_item_container_serial"]
            SALVAGE_BAG_SERIAL = data["salvage_bag_serial"]
            TRASH_CONTAINER_SERIAL = data["trash_container_serial"]
            AUTO_TOOLING = data["auto_tooling"]
            LEARN_MODE = data["learn_mode"]
            SELECTED_SERVER = str(data.get("selected_server", "") or "").strip()
            RECIPE_BOOK = []
            CRAFT_STATION_X = data["craft_station_x"]
            CRAFT_STATION_Y = data["craft_station_y"]
            CRAFT_STATION_Z = data["craft_station_z"]
            CRAFT_STATION_SET = data["craft_station_set"]
            USE_SACRED_JOURNEY = data["use_sacred_journey"]
            ENABLED_BOD_TYPES = {k: True for k in BOD_TYPE_ORDER}
    else:
        data = _default_config()
        RUNBOOK_SERIAL = data["runebook_serial"]
        RESOURCE_CONTAINER_SERIAL = data["resource_container_serial"]
        BOD_ITEM_CONTAINER_SERIAL = data["bod_item_container_serial"]
        SALVAGE_BAG_SERIAL = data["salvage_bag_serial"]
        TRASH_CONTAINER_SERIAL = data["trash_container_serial"]
        AUTO_TOOLING = data["auto_tooling"]
        LEARN_MODE = data["learn_mode"]
        SELECTED_SERVER = str(data.get("selected_server", "") or "").strip()
        RECIPE_BOOK = []
        CRAFT_STATION_X = data["craft_station_x"]
        CRAFT_STATION_Y = data["craft_station_y"]
        CRAFT_STATION_Z = data["craft_station_z"]
        CRAFT_STATION_SET = data["craft_station_set"]
        USE_SACRED_JOURNEY = data["use_sacred_journey"]
        ENABLED_BOD_TYPES = {k: True for k in BOD_TYPE_ORDER}

    # DB-backed recipe book overrides persistent config when present.
    _write_debug_log("Config: recipe DB stage begin.")
    if RECIPE_STORE is None:
        raise RuntimeError("Recipe DB module unavailable.")
    try:
        rs_file = str(getattr(RECIPE_STORE, "__file__", "<unknown>") or "<unknown>")
    except Exception:
        rs_file = "<unknown>"
    has_diag_logger = bool(hasattr(RECIPE_STORE, "set_diag_logger"))
    _write_debug_log(f"Config: RecipeStore module={rs_file} has_diag_logger={has_diag_logger}")
    if not has_diag_logger:
        _write_debug_log("Config: RecipeStore diagnostics unavailable (missing set_diag_logger).")
    recipe_store_diag_attached = False
    try:
        if hasattr(RECIPE_STORE, "set_diag_logger"):
            RECIPE_STORE.set_diag_logger(lambda msg: _write_debug_log(f"RecipeStore: {msg}"))
            recipe_store_diag_attached = True
    except Exception:
        recipe_store_diag_attached = False
    try:
        _write_debug_log("Config: startup DB init skipped (read-only startup).")

        _write_debug_log("Config: recipe load begin.")
        recipe_started_at = time.time()
        file_book = _read_with_lock_retries(
            lambda: _load_recipe_book_from_file(raise_on_lock=True),
            "recipe",
        )
        recipe_elapsed_s = max(0.0, float(time.time() - float(recipe_started_at)))
        _write_debug_log(f"Config: recipe load complete in {recipe_elapsed_s:.3f}s.")
        if isinstance(file_book, list):
            # Respect empty recipe files so users can intentionally start fresh.
            RECIPE_BOOK = list(file_book)
        else:
            raise RuntimeError("Recipe load failed.")

        _write_debug_log("Config: key-map load begin.")
        key_started_at = time.time()
        key_maps = _read_with_lock_retries(
            lambda: _load_key_maps_from_file(raise_on_lock=True),
            "key-map",
        )
        key_elapsed_s = max(0.0, float(time.time() - float(key_started_at)))
        _write_debug_log(f"Config: key-map load complete in {key_elapsed_s:.3f}s.")
        if not isinstance(key_maps, dict):
            raise RuntimeError("Key-map load failed.")
        KEY_MAPS = dict(key_maps)

        _write_debug_log("Config: resource-map load begin.")
        resource_started_at = time.time()
        resource_item_map = _read_with_lock_retries(
            lambda: _load_resource_item_map_from_file(raise_on_lock=True),
            "resource-map",
        )
        resource_elapsed_s = max(0.0, float(time.time() - float(resource_started_at)))
        _write_debug_log(f"Config: resource-map load complete in {resource_elapsed_s:.3f}s.")
        if not isinstance(resource_item_map, dict):
            raise RuntimeError("Resource-map load failed.")
        RESOURCE_ITEM_MAP = dict(resource_item_map)
    finally:
        if recipe_store_diag_attached:
            try:
                RECIPE_STORE.set_diag_logger(None)
            except Exception:
                pass
    if not SERVER_OPTIONS:
        SERVER_OPTIONS = _server_options_from_key_maps()
    if not SERVER_OPTIONS:
        raise RuntimeError("No game servers found in Databases/craftables.db game_servers.")
    DEFAULT_SERVER = _preferred_default_server(SERVER_OPTIONS)
    SELECTED_SERVER = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    _refresh_recall_buttons()
    try:
        km_ct = len(KEY_MAPS)
    except Exception:
        km_ct = 0
    try:
        rm_ct = len(RESOURCE_ITEM_MAP)
    except Exception:
        rm_ct = 0
    _write_debug_log(f"Config: recipe DB stage end. recipes={len(RECIPE_BOOK)} key_servers={km_ct} resources={rm_ct}")


def _save_config():
    data = {
        "runebook_serial": int(RUNBOOK_SERIAL or 0),
        "resource_container_serial": int(RESOURCE_CONTAINER_SERIAL or 0),
        "bod_item_container_serial": int(BOD_ITEM_CONTAINER_SERIAL or 0),
        "salvage_bag_serial": int(SALVAGE_BAG_SERIAL or 0),
        "trash_container_serial": int(TRASH_CONTAINER_SERIAL or 0),
        "auto_tooling": bool(AUTO_TOOLING),
        "learn_mode": bool(LEARN_MODE),
        "craft_station_x": int(CRAFT_STATION_X or 0),
        "craft_station_y": int(CRAFT_STATION_Y or 0),
        "craft_station_z": int(CRAFT_STATION_Z or 0),
        "craft_station_set": bool(CRAFT_STATION_SET),
        "use_sacred_journey": bool(USE_SACRED_JOURNEY),
        "enabled_bod_types": {k: bool(ENABLED_BOD_TYPES.get(k, True)) for k in BOD_TYPE_ORDER},
        "selected_server": str(SELECTED_SERVER or DEFAULT_SERVER),
    }
    API.SavePersistentVar(DATA_KEY, json.dumps(data), API.PersistentVar.Char)


def _set_runebook():
    global RUNBOOK_SERIAL
    _say("Target runebook.")
    serial = API.RequestTarget()
    if serial:
        RUNBOOK_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_runebook():
    global RUNBOOK_SERIAL
    RUNBOOK_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_resource_container():
    global RESOURCE_CONTAINER_SERIAL
    _say("Target resource container.")
    serial = API.RequestTarget()
    if serial:
        RESOURCE_CONTAINER_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_resource_container():
    global RESOURCE_CONTAINER_SERIAL
    RESOURCE_CONTAINER_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_bod_item_container():
    global BOD_ITEM_CONTAINER_SERIAL
    _say("Target BOD item container.")
    serial = API.RequestTarget()
    if serial:
        BOD_ITEM_CONTAINER_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_bod_item_container():
    global BOD_ITEM_CONTAINER_SERIAL
    BOD_ITEM_CONTAINER_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_salvage_bag():
    global SALVAGE_BAG_SERIAL
    _say("Target salvage bag.")
    serial = API.RequestTarget()
    if serial:
        SALVAGE_BAG_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_salvage_bag():
    global SALVAGE_BAG_SERIAL
    SALVAGE_BAG_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_trash_container():
    global TRASH_CONTAINER_SERIAL
    _say("Target trash container.")
    serial = API.RequestTarget()
    if serial:
        TRASH_CONTAINER_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_trash_container():
    global TRASH_CONTAINER_SERIAL
    TRASH_CONTAINER_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _toggle_auto_tooling():
    global AUTO_TOOLING
    AUTO_TOOLING = not AUTO_TOOLING
    _save_config()
    _rebuild_gump()


def _toggle_learn_mode():
    global LEARN_MODE
    LEARN_MODE = not LEARN_MODE
    _save_config()
    _rebuild_gump()


def _open_manual_recipe_from_control():
    _launch_recipe_editor({
        "editor_mode": "recipe_builder",
        "recipe_type": "bod",
        "server": str(SELECTED_SERVER or DEFAULT_SERVER),
        "profession": "Blacksmith",
        "material": "ingot",
        "material_key": str(_default_material_key_for_base("ingot", "Blacksmith") or ""),
        "name": "",
        "buttons": "",
    }, wait_s=0.0)


def _set_work_anchor():
    global CRAFT_STATION_X, CRAFT_STATION_Y, CRAFT_STATION_Z, CRAFT_STATION_SET
    _say("Target crafting station tile.")
    target_obj = API.RequestAnyTarget(8)
    pos = getattr(API, "LastTargetPos", None)
    x = int(getattr(pos, "X", 0) or 0)
    y = int(getattr(pos, "Y", 0) or 0)
    z = int(getattr(pos, "Z", 0) or 0)
    if (x == 0 and y == 0) and target_obj:
        x = int(getattr(target_obj, "X", 0) or 0)
        y = int(getattr(target_obj, "Y", 0) or 0)
        z = int(getattr(target_obj, "Z", 0) or 0)
    if x != 0 or y != 0:
        CRAFT_STATION_X = x
        CRAFT_STATION_Y = y
        CRAFT_STATION_Z = z
        CRAFT_STATION_SET = True
        _save_config()
        _say(f"Crafting Station set: ({x}, {y}, {z})")
    else:
        _say("Could not read tile coordinates from target.", 33)
    _rebuild_gump()


def _unset_work_anchor():
    global CRAFT_STATION_X, CRAFT_STATION_Y, CRAFT_STATION_Z, CRAFT_STATION_SET
    CRAFT_STATION_X = 0
    CRAFT_STATION_Y = 0
    CRAFT_STATION_Z = 0
    CRAFT_STATION_SET = False
    _save_config()
    _rebuild_gump()


def _set_mage():
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = False
    _refresh_recall_buttons()
    _save_config()
    _rebuild_gump()


def _set_chiv():
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = True
    _refresh_recall_buttons()
    _save_config()
    _rebuild_gump()


def _set_server(selected_index):
    global SELECTED_SERVER
    options = _current_server_options()
    if not options:
        _say("No servers found in craftables.db game_servers.", 33)
        return
    idx = int(selected_index)
    if idx < 0 or idx >= len(options):
        idx = 0
    SELECTED_SERVER = str(options[idx])
    _save_config()
    _rebuild_gump()


def _normalize_text(text):
    return str(text or "").strip().lower()


def _canonical_profession_name(name):
    low = _normalize_text(name)
    if low in ("blacksmith", "blacksmithing", "blacksmithy"):
        return "Blacksmith"
    if low in ("tailor", "tailoring"):
        return "Tailor"
    if low in ("carpentry", "carpenter"):
        return "Carpentry"
    if low in ("tinker", "tinkering"):
        return "Tinker"
    if low in ("bowcraft", "bowcraft and fletching", "bowcraft/fletching", "fletching", "bowyer"):
        return "Bowcraft"
    if low in ("alchemy", "alchemist"):
        return "Alchemy"
    if low in ("inscription", "scribe", "scribing"):
        return "Inscription"
    if low in ("cooking", "cook"):
        return "Cooking"
    return str(name or "").strip()


def _detect_profession_from_text(lower_text):
    low = _normalize_text(lower_text)
    # Direct profession words first.
    direct = {
        "blacksmith": "Blacksmith",
        "tailor": "Tailor",
        "carpentry": "Carpentry",
        "carpenter": "Carpentry",
        "tinker": "Tinker",
        "tinkering": "Tinker",
        "blacksmithy": "Blacksmith",
    }
    for key, prof in direct.items():
        if key in low:
            return prof
    # Fallback through known title hints.
    for prof, hints in BOD_GIVER_TITLE_HINTS.items():
        for hint in (hints or []):
            if _normalize_text(hint) and _normalize_text(hint) in low:
                return prof
    # Extra deed-style wording fallbacks.
    if "smith" in low or "weapon" in low or "armor" in low:
        return "Blacksmith"
    return ""


def _find_recipe_for_item_name(item_name, preferred_profession=None, preferred_material_key=None):
    needle = _normalize_name(item_name)
    if not needle:
        return None
    preferred_prof = _canonical_profession_name(preferred_profession) if preferred_profession else ""
    matches = []
    for r in RECIPE_BOOK:
        if _normalize_recipe_type(r.get("recipe_type", "bod")) != "bod":
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
            continue
        if preferred_prof and _canonical_profession_name(r.get("profession", "")) != preferred_prof:
            continue
        key = _normalize_name(r.get("name", ""))
        if not key:
            continue
        if needle == key:
            matches.append(r)
    if not matches:
        return None
    matches.sort(key=lambda r: len(str(r.get("name", ""))), reverse=True)
    return matches[0]


def _detect_profession_from_item_name(item_name):
    low = _normalize_name(item_name)
    if not low:
        return ""

    # First prefer explicit learned/seed recipe matches.
    by_recipe = _find_recipe_for_item_name(item_name, None)
    if by_recipe:
        return str(by_recipe.get("profession", "") or "")

    # Strong phrase overrides first.
    if "heater shield" in low:
        return "Blacksmith"
    if "metal shield" in low:
        return "Blacksmith"
    if "wooden shield" in low:
        return "Carpentry"

    keywords = {
        "Tailor": [
            "hat", "cap", "robe", "shirt", "doublet", "tunic", "dress", "skirt", "kilt",
            "pants", "shorts", "cloak", "apron", "sash", "tabi", "sandals", "boots",
            "gloves", "frock", "surcoat", "jester", "body sash", "straw hat",
        ],
        "Carpentry": [
            "board", "crate", "box", "chest", "table", "chair", "stool", "bench",
            "shelf", "bookcase", "cabinet", "bow", "crossbow", "shield", "staff",
            "quarter staff", "wooden",
        ],
        "Tinker": [
            "gear", "clock", "spyglass", "scissors", "ring", "bracelet", "necklace",
            "goblet", "candelabra", "jointing plane", "dovetail saw", "tinker",
        ],
        "Blacksmith": [
            "plate", "chain", "ringmail", "helmet", "gorget", "gauntlet", "arms",
            "leggings", "tunic", "shield", "buckler", "broadsword", "longsword",
            "katana", "cutlass", "scimitar", "mace", "maul", "war", "axe", "spear",
            "hammer", "smith", "metal",
        ],
    }

    scores = {"Blacksmith": 0, "Tailor": 0, "Carpentry": 0, "Tinker": 0}
    for prof, words in keywords.items():
        for w in words:
            wn = _normalize_name(w)
            if wn and wn in low:
                scores[prof] += 1
    best_prof = ""
    best_score = 0
    for prof in ("Tailor", "Carpentry", "Tinker", "Blacksmith"):
        s = int(scores.get(prof, 0))
        if s > best_score:
            best_prof = prof
            best_score = s
    return best_prof if best_score > 0 else ""


def _recipe_material(recipe):
    if not isinstance(recipe, dict):
        return ""
    return _normalize_text(recipe.get("material", ""))


def _recipe_material_key(recipe):
    if not isinstance(recipe, dict):
        return ""
    key = str(recipe.get("material_key", "") or "").strip()
    if key:
        return key
    return _infer_material_key(str(recipe.get("material", "") or ""), "")


def _name_variants_for_learning(name):
    raw = str(name or "").strip()
    if not raw:
        return []
    variants = [raw]
    low = _normalize_name(raw)

    prefixes = (
        "leather ", "studded ", "horned ", "barbed ", "spined ",
        "iron ", "dull copper ", "shadow iron ", "copper ", "bronze ",
        "gold ", "agapite ", "verite ", "valorite ",
        "oak ", "ash ", "yew ", "heartwood ", "bloodwood ", "frostwood ",
    )
    trimmed = low
    for p in prefixes:
        if trimmed.startswith(p):
            trimmed = trimmed[len(p):].strip()
            break
    if trimmed and trimmed not in variants:
        variants.append(trimmed)
    if trimmed.endswith("s") and not trimmed.endswith("ss"):
        singular = trimmed[:-1].strip()
        if singular and singular not in variants:
            variants.append(singular)
    return variants


def _detect_profession_from_deed_hue(item):
    try:
        hue = int(getattr(item, "Hue", 0) or 0)
    except Exception:
        hue = 0
    if hue in BOD_HUE_TO_PROFESSION:
        prof = str(BOD_HUE_TO_PROFESSION.get(hue, "") or "").strip()
        if prof in ("Blacksmith", "Tailor", "Carpentry", "Tinker", "Alchemy", "Inscription", "Bowcraft", "Cooking"):
            return prof
    return ""


def _infer_profession_from_tool_target():
    _say("Target a crafting tool in backpack to identify profession.")
    serial = API.RequestTarget(8)
    if not serial:
        return ""
    item = API.FindItem(int(serial))
    if not item:
        return ""
    gid = int(getattr(item, "Graphic", 0) or 0)
    if gid in BLACKSMITH_TOOL_IDS:
        return "Blacksmith"
    if gid in TAILOR_TOOL_IDS:
        return "Tailor"
    if gid in CARPENTRY_TOOL_IDS:
        return "Carpentry"
    if gid in TINKER_TOOL_IDS:
        return "Tinker"
    return ""


def _show_bod_title_help():
    _say("BODAssist title matching rules:")
    for bod_type in BOD_TYPE_ORDER:
        titles = BOD_GIVER_TITLE_HINTS.get(bod_type, [])
        slot = int(BOD_SLOT_BY_TYPE.get(bod_type, 0) or 0)
        joined = ", ".join([str(t) for t in (titles or []) if str(t).strip()]) or "<none>"
        _say(f"Slot {slot} {bod_type}: {joined}")


def _get_mobile_title_text(serial):
    mobile = API.FindMobile(int(serial))
    if not mobile:
        return ""
    lines = []
    name = str(getattr(mobile, "Name", "") or "").strip()
    if name:
        lines.append(name)
    try:
        props = mobile.NameAndProps(True, 2)
        if props:
            lines.append(str(props))
    except Exception:
        pass
    return "\n".join(lines).strip()


def _set_bod_type_enabled(bod_type, enabled):
    if bod_type not in BOD_TYPE_ORDER:
        return
    ENABLED_BOD_TYPES[bod_type] = bool(enabled)
    _save_config()


def _toggle_bod_type_enabled(bod_type):
    if bod_type not in BOD_TYPE_ORDER:
        return
    ENABLED_BOD_TYPES[bod_type] = not bool(ENABLED_BOD_TYPES.get(bod_type, True))
    _save_config()
    _rebuild_gump()


def _slot_to_button(slot):
    if int(slot) < 1:
        return 0
    # Runebook slots are sequential gump buttons where slot 1 is home.
    return int(HOME_RECALL_BUTTON) + int(slot) - 1


def _tile_distance_to_xy(x, y):
    if x is None or y is None:
        return 999
    try:
        px = int(getattr(API.Player, "X", 0) or 0)
        py = int(getattr(API.Player, "Y", 0) or 0)
        return max(abs(px - int(x)), abs(py - int(y)))
    except Exception:
        return 999


def _container_debug_info(serial):
    sid = int(serial or 0)
    if sid <= 0:
        return {"ok": False, "reason": "serial_zero"}
    try:
        item = API.FindItem(sid)
    except Exception:
        item = None
    if not item:
        return {"ok": False, "reason": "not_found", "serial": sid}
    name = str(getattr(item, "Name", "") or "")
    x = int(getattr(item, "X", 0) or 0)
    y = int(getattr(item, "Y", 0) or 0)
    z = int(getattr(item, "Z", 0) or 0)
    dist = _tile_distance_to_xy(x, y)
    is_container = bool(getattr(item, "IsContainer", True))
    return {
        "ok": True,
        "serial": sid,
        "name": name,
        "x": x,
        "y": y,
        "z": z,
        "dist": dist,
        "is_container": is_container,
    }


def _move_to_work_anchor():
    if not CRAFT_STATION_SET:
        _say("Crafting Station is not set.", 33)
        return False
    if _tile_distance_to_xy(CRAFT_STATION_X, CRAFT_STATION_Y) <= WORK_ANCHOR_DISTANCE:
        return True

    for attempt in range(1, WORK_PATH_RETRIES + 1):
        _say(f"Pathfinding to crafting station (attempt {attempt}/{WORK_PATH_RETRIES}).")
        API.Pathfind(
            int(CRAFT_STATION_X),
            int(CRAFT_STATION_Y),
            int(CRAFT_STATION_Z),
            distance=WORK_ANCHOR_DISTANCE,
            wait=True,
            timeout=WORK_PATH_TIMEOUT_S
        )
        _sleep(0.25)
        if _tile_distance_to_xy(CRAFT_STATION_X, CRAFT_STATION_Y) <= WORK_ANCHOR_DISTANCE:
            _say("Arrived at crafting station.")
            return True
    _say("Could not pathfind to crafting station.", 33)
    return False


def _recall_to_button(button_id, close_gump_after=True):
    if not RUNBOOK_SERIAL:
        _say("No runebook set.")
        return False
    API.UseObject(RUNBOOK_SERIAL)
    _sleep(0.5)
    try:
        API.ReplyGump(int(button_id), RECALL_GUMP_ID)
    except Exception:
        API.ReplyGump(int(button_id))
    _sleep(RECALL_SETTLE_S)
    if bool(close_gump_after):
        _close_recall_gump_strict("recall_to_button")
    return True


def _recall_home(close_gump_after=True):
    return _recall_to_button(HOME_RECALL_BUTTON, close_gump_after=close_gump_after)


# Fill phase helper: recall home once and normalize post-recall UI state.
def _run_fill_travel_phase():
    if not CRAFT_STATION_SET:
        return True
    _set_running(True)
    try:
        _diag_step("F03", "RUN", "travel_phase: recall home", DIAG_HUE_RUN)
        _say("Fill: recalling home.")
        if not _recall_home(close_gump_after=False):
            _say("Fill travel phase: failed to recall home.", 33)
            return False
        _sleep(BOD_SCAN_SETTLE_S)
        _diag_step("F03", "RUN", "travel_phase: close recall gump", DIAG_HUE_RUN)
        _close_recall_gump_strict("fill_post_recall")
        return True
    finally:
        _set_running(False)


# Fill phase helper: move from recall point to configured crafting station.
def _run_fill_move_phase():
    if not CRAFT_STATION_SET:
        return True
    _set_running(True)
    try:
        _diag_step("F03B", "RUN", "move_phase: move to crafting station", DIAG_HUE_RUN)
        if not _move_to_work_anchor():
            return False
        _sleep(0.6)
        return True
    finally:
        _set_running(False)


def _request_bod_from_giver(giver_serial):
    if not giver_serial:
        return False
    mobile = API.FindMobile(int(giver_serial))
    if not mobile:
        _say(f"Giver 0x{int(giver_serial):08X} not found at this stop.", 33)
        return False

    def _accept_bod_offer_if_present():
        # Shard-specific: both small and large BOD offer gumps use Accept button 1.
        offer_gump_ids = [int(BOD_OFFER_GUMP_ID), int(BOD_LARGE_OFFER_GUMP_ID)]
        try:
            for offer_gump_id in offer_gump_ids:
                if API.WaitForGump(int(offer_gump_id), float(BOD_OFFER_WAIT_S)):
                    try:
                        API.ReplyGump(int(BOD_OFFER_ACCEPT_BUTTON_ID), int(offer_gump_id))
                    except Exception:
                        API.ReplyGump(int(BOD_OFFER_ACCEPT_BUTTON_ID))
                    _sleep(0.15)
                    return True
        except Exception:
            pass
        return False

    success_any = False
    for _ in range(BOD_REQUEST_ATTEMPTS):
        API.ContextMenu(int(giver_serial), int(FIXED_BOD_CONTEXT_INDEX))
        _sleep(BOD_REQUEST_PAUSE_S)
        if _accept_bod_offer_if_present():
            success_any = True
    return success_any


def _find_givers_by_titles(title_filters, max_distance=14):
    wanted = [_normalize_text(t) for t in (title_filters or []) if _normalize_text(t)]
    if not wanted:
        return []
    serials = []
    seen = set()
    for mob in API.GetAllMobiles(distance=max_distance) or []:
        serial = int(getattr(mob, "Serial", 0) or 0)
        if not serial or serial == int(getattr(API.Player, "Serial", 0) or 0) or serial in seen:
            continue
        seen.add(serial)
        text = _get_mobile_title_text(serial)
        if not text:
            continue
        hay = _normalize_text(text)
        for title in wanted:
            if title and title in hay:
                serials.append(serial)
                break
    return serials


def _items_in(container_serial, recursive=False):
    serial = 0
    query = None
    try:
        if hasattr(container_serial, "Serial"):
            serial = int(getattr(container_serial, "Serial", 0) or 0)
            query = container_serial
        else:
            serial = int(container_serial or 0)
            query = serial
    except Exception:
        serial = 0
        query = 0
    items = API.ItemsInContainer(query, bool(recursive)) or []
    # Some client states return empty backpack contents until backpack is re-synced/opened.
    try:
        bp = int(_backpack_serial() or 0)
    except Exception:
        bp = 0
    if serial > 0 and serial == bp and len(items) == 0 and serial != int(RECALL_GUMP_ID):
        try:
            API.UseObject(serial)
        except Exception:
            pass
        _wait_and_pump(0.25, 0.05)
        try:
            items = API.ItemsInContainer(query, bool(recursive)) or []
        except Exception:
            items = []
    return items


def _backpack_serial():
    try:
        bp = getattr(API, "Backpack", 0)
        if hasattr(bp, "Serial"):
            return int(getattr(bp, "Serial", 0) or 0)
        return int(bp or 0)
    except Exception:
        return 0


def _debug_ingot_distribution(item_id):
    out = {}
    try:
        out["pack"] = int(_count_in(API.Backpack, item_id) or 0)
    except Exception:
        out["pack"] = -1
    try:
        out["resource"] = int(_count_in(RESOURCE_CONTAINER_SERIAL, item_id) or 0) if RESOURCE_CONTAINER_SERIAL else -1
    except Exception:
        out["resource"] = -1
    try:
        out["bod_item"] = int(_count_in(BOD_ITEM_CONTAINER_SERIAL, item_id) or 0) if BOD_ITEM_CONTAINER_SERIAL else -1
    except Exception:
        out["bod_item"] = -1
    try:
        out["salvage"] = int(_count_in(SALVAGE_BAG_SERIAL, item_id) or 0) if SALVAGE_BAG_SERIAL else -1
    except Exception:
        out["salvage"] = -1
    try:
        out["trash"] = int(_count_in(TRASH_CONTAINER_SERIAL, item_id) or 0) if TRASH_CONTAINER_SERIAL else -1
    except Exception:
        out["trash"] = -1
    return out


def _ground_ingot_totals(item_id, hue=None, rng=2):
    total = 0
    found = []
    try:
        items = API.GetItemsOnGround(int(rng)) or []
    except Exception:
        items = []
    for it in items:
        try:
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            ih = int(getattr(it, "Hue", 0) or 0)
            if hue is not None and ih != int(hue):
                continue
            amt = int(getattr(it, "Amount", 1) or 1)
            total += amt
            found.append((int(getattr(it, "Serial", 0) or 0), amt, ih))
        except Exception:
            continue
    return total, found


def _player_weight_snapshot():
    try:
        cur = int(getattr(API.Player, "Weight", -1) or -1)
    except Exception:
        cur = -1
    try:
        mx = int(getattr(API.Player, "MaxWeight", -1) or -1)
    except Exception:
        mx = -1
    return cur, mx


def _ensure_container_open(container_serial, force=False):
    global OPENED_CONTAINERS
    serial = 0
    try:
        if hasattr(container_serial, "Serial"):
            serial = int(getattr(container_serial, "Serial", 0) or 0)
        else:
            serial = int(container_serial or 0)
    except Exception:
        serial = 0
    if serial <= 0 or serial == int(_backpack_serial() or 0):
        return
    if int(RUNBOOK_SERIAL or 0) > 0 and serial == int(RUNBOOK_SERIAL):
        # Never auto-open runebook during container scans/restock helpers.
        return
    if serial == int(RECALL_GUMP_ID):
        return
    if (not bool(force)) and serial in OPENED_CONTAINERS:
        return
    try:
        API.UseObject(serial)
        _sleep(0.25)
        OPENED_CONTAINERS.add(serial)
    except Exception:
        pass


def _force_open_container_for_scan(container_serial, attempts=3, pause_s=0.55):
    serial = int(container_serial or 0)
    if serial <= 0:
        return False
    _say(f"Opening resource container 0x{serial:08X} ...")
    for _ in range(max(1, int(attempts))):
        if _should_stop():
            return False
        try:
            API.UseObject(serial)
        except Exception:
            pass
        _sleep(float(pause_s))
        try:
            # Any visible contents means the client has synced the container for scans.
            if (API.ItemsInContainer(serial, False) or API.ItemsInContainer(serial, True)):
                _say(f"Resource container open/synced: 0x{serial:08X}")
                return True
        except Exception:
            pass
        # Fallback: some containers require context menu Open.
        try:
            API.ContextMenu(int(serial), 0)
        except Exception:
            pass
        _sleep(float(pause_s))
        try:
            if (API.ItemsInContainer(serial, False) or API.ItemsInContainer(serial, True)):
                _say(f"Resource container open/synced via context menu: 0x{serial:08X}")
                return True
        except Exception:
            pass
    _say(f"Could not confirm container sync for 0x{serial:08X}; continuing with scan.", 33)
    return True if not _should_stop() else False


def _is_container_gump_open(container_serial):
    serial = int(container_serial or 0)
    if serial <= 0:
        return False
    try:
        allg = API.GetAllGumps() or []
    except Exception:
        allg = []
    for g in allg:
        try:
            # Clients expose this as a gump serial/server serial for container windows.
            for attr in ("ServerSerial", "Serial", "ID", "Id"):
                v = getattr(g, attr, None)
                if v is None:
                    continue
                if int(v) == serial:
                    return True
        except Exception:
            continue
    return False


def _gump_ids_snapshot():
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


def _close_recall_gump_strict(tag=""):
    gid = int(RECALL_GUMP_ID)
    pre = _gump_ids_snapshot()
    had = gid in set(pre)
    if not had:
        return True
    closed = False
    for _ in range(4):
        try:
            API.CloseGump(gid)
        except Exception:
            pass
        _sleep(0.1)
        try:
            if not bool(API.HasGump(gid)):
                closed = True
                break
        except Exception:
            pass
        try:
            API.ReplyGump(0, gid)
        except Exception:
            pass
        _sleep(0.12)
        now = set(_gump_ids_snapshot())
        if gid not in now:
            closed = True
            break
    if closed:
        _say(f"RecallGump: closed ({str(tag or '')}).")
    else:
        _say(f"RecallGump: still open after close attempts ({str(tag or '')}).", 33)
    return closed


def _close_nonessential_gumps_for_restock():
    # Close any lingering UI that can steal UseObject focus while syncing container contents.
    keep = set()
    closed = []
    try:
        snapshot = list(_gump_ids_snapshot() or [])
    except Exception:
        snapshot = []
    for gid in snapshot:
        try:
            g = int(gid)
        except Exception:
            continue
        if g <= 0 or g in keep:
            continue
        try:
            API.CloseGump(g)
            closed.append(g)
            _sleep(0.06)
        except Exception:
            pass
    # Also close known craft/deed IDs explicitly in case they are represented by a different token.
    for gid in (
        int(BOD_DEED_GUMP_ID),
        int(BLACKSMITH_GUMP_ID),
        int(TINKER_GUMP_ID),
        int(TAILOR_GUMP_ID),
        int(CARPENTRY_GUMP_ID),
    ):
        try:
            API.CloseGump(gid)
            _sleep(0.03)
        except Exception:
            pass
    if closed:
        shown = ", ".join([str(int(x)) for x in closed[:8]])
        _say(f"RestockOpen: closed blocking gumps [{shown}] prior to container open.")
    return len(closed)


def _reposition_for_container_access(container_serial):
    info = _container_debug_info(container_serial)
    if not info.get("ok", False):
        return False
    try:
        dist = int(info.get("dist", 999) or 999)
    except Exception:
        dist = 999
    if dist <= 1:
        return True
    try:
        tx = int(info.get("x", 0) or 0)
        ty = int(info.get("y", 0) or 0)
        tz = int(info.get("z", 0) or 0)
        API.Pathfind(tx, ty, tz, distance=1, wait=True, timeout=6)
        _wait_and_pump(0.25, 0.05)
        info2 = _container_debug_info(container_serial)
        dist2 = int(info2.get("dist", 999) or 999)
        return dist2 <= 1
    except Exception:
        return False


def _container_item_counts(container_serial):
    sid = int(container_serial or 0)
    if sid <= 0:
        return 0, 0
    try:
        c0 = len(API.ItemsInContainer(sid, False) or [])
    except Exception:
        c0 = -1
    try:
        c1 = len(API.ItemsInContainer(sid, True) or [])
    except Exception:
        c1 = -1
    return c0, c1


def _run_container_diag():
    sid = int(RESOURCE_CONTAINER_SERIAL or 0)
    _say("ContainerDiag: starting.")
    if sid <= 0:
        _say("ContainerDiag: resource container is not set.", 33)
        return
    info = _container_debug_info(sid)
    _say(
        "ContainerDiag: target "
        f"0x{sid:08X} name='{str(info.get('name',''))}' "
        f"dist={int(info.get('dist', 999))} is_container={bool(info.get('is_container', False))}"
    )
    pre_g = _gump_ids_snapshot()
    c0, c1 = _container_item_counts(sid)
    _say(f"ContainerDiag: pre gumps={pre_g}")
    _say(f"ContainerDiag: pre counts shallow={c0} recursive={c1}")

    for i in range(1, 4):
        try:
            API.UseObject(sid)
            _say(f"ContainerDiag: UseObject attempt {i} sent.")
        except Exception as ex:
            _say(f"ContainerDiag: UseObject attempt {i} exception: {ex}", 33)
        _sleep(1.0)
        g = _gump_ids_snapshot()
        d0, d1 = _container_item_counts(sid)
        _say(f"ContainerDiag: post UseObject {i} gumps={g}")
        _say(f"ContainerDiag: post UseObject {i} counts shallow={d0} recursive={d1}")

    try:
        API.ContextMenu(sid, 0)
        _say("ContainerDiag: ContextMenu open attempt sent.")
    except Exception as ex:
        _say(f"ContainerDiag: ContextMenu exception: {ex}", 33)
    _sleep(1.0)
    cg = _gump_ids_snapshot()
    e0, e1 = _container_item_counts(sid)
    _say(f"ContainerDiag: post context gumps={cg}")
    _say(f"ContainerDiag: post context counts shallow={e0} recursive={e1}")
    _say("ContainerDiag: done.")


def _run_transfer_diag():
    _say("TransferDiag: starting.")
    sid = int(RESOURCE_CONTAINER_SERIAL or 0)
    if sid <= 0:
        _say("TransferDiag: resource container is not set.", 33)
        return
    if not _open_resource_container_like_diag(sid, attempts=3):
        _say("TransferDiag: could not open/sync resource container.", 33)
        return
    try:
        API.UseObject(sid)
    except Exception:
        pass
    _wait_and_pump(0.35, 0.05)
    ingot_id = int(_resource_item_id("ingot") or 0)
    if ingot_id <= 0:
        _say("TransferDiag: missing resource_catalog.game_item_id for 'ingot'.", 33)
        return
    before = int(_count_in_raw(API.Backpack, ingot_id, None) or 0)
    _say(f"TransferDiag: backpack ingots before={before}")

    # Primary path uses the same helper as Fill restock.
    if _transfer_once_resource_to_backpack(ingot_id, "", 0, amount=400, settle_s=0.9):
        after = int(_count_in_raw(API.Backpack, ingot_id, None) or 0)
        _say(f"TransferDiag: helper result backpack={after} delta={int(after)-int(before)}")
        _say("TransferDiag: SUCCESS via shared helper.")
        _say("TransferDiag: done.")
        return

    methods = [
        ("to_backpack_serial", lambda s, a: API.MoveItem(int(s), int(_backpack_serial() or 0), int(a))),
        ("to_player_serial", lambda s, a: API.MoveItem(int(s), int(getattr(API.Player, 'Serial', 0) or 0), int(a))),
    ]

    for name, mover in methods:
        src = _find_first_in_container_hued(sid, ingot_id, 0)
        if not src:
            src = _find_first_in_container(sid, ingot_id)
        if not src:
            _say(f"TransferDiag: no source ingot found for method {name}.", 33)
            continue
        src_ser = int(getattr(src, "Serial", 0) or 0)
        src_amt = int(getattr(src, "Amount", 0) or 0)
        _say(f"TransferDiag: method={name}, source=0x{src_ser:08X}, src_amt={src_amt}, move=1")
        try:
            try:
                API.ClearJournal()
            except Exception:
                pass
            mover(src_ser, 1)
            _wait_and_pump(0.9, 0.05)
        except Exception as ex:
            _say(f"TransferDiag: method={name} exception: {ex}", 33)
            continue
        after = int(_count_in_raw(API.Backpack, ingot_id, None) or 0)
        delta = int(after) - int(before)
        _say(f"TransferDiag: method={name} result backpack={after} delta={delta}")
        if delta > 0:
            _say(f"TransferDiag: SUCCESS via {name}.")
            _say("TransferDiag: done.")
            return
    _say("TransferDiag: no method increased backpack ingot count.", 33)
    _say("TransferDiag: done.")


def _run_db_diag():
    _say("DBDiag: starting.")
    if RECIPE_STORE is None:
        _say("DBDiag: RecipeStore module unavailable.", 33)
        return

    sel_server = _normalize_server_name(SELECTED_SERVER)
    try:
        summary = RECIPE_STORE.health_summary(sel_server) or {}
    except Exception as ex:
        _say(f"DBDiag: health_summary failed: {ex}", 33)
        summary = {}

    _say(
        "DBDiag: "
        f"db={str(summary.get('db_path', '') or '')} "
        f"schema_version={int(summary.get('schema_version', 0) or 0)}"
    )
    _say(
        "DBDiag: recipes "
        f"total={int(summary.get('recipes_total', 0) or 0)} "
        f"by_type={summary.get('recipes_by_type', {})} "
        f"by_server={summary.get('recipes_by_server', {})}"
    )
    _say(
        "DBDiag: key_maps "
        f"servers={int(summary.get('servers_count', 0) or 0)} "
        f"profession_nodes={int(summary.get('profession_nodes', 0) or 0)} "
        f"material_keys={int(summary.get('material_keys_total', 0) or 0)} "
        f"item_keys={int(summary.get('item_keys_total', 0) or 0)} "
        f"resources={int(summary.get('resources_total', 0) or 0)} "
        f"resources_mapped={int(summary.get('resources_with_item_id', 0) or 0)} "
        f"item_resource_costs={int(summary.get('item_resource_costs_total', 0) or 0)}"
    )
    _say(
        "DBDiag: selected_server "
        f"{sel_server} recipes={int(summary.get('selected_server_recipes', 0) or 0)} "
        f"material_keys={int(summary.get('selected_server_material_keys', 0) or 0)} "
        f"item_keys={int(summary.get('selected_server_item_keys', 0) or 0)} "
        f"item_resource_costs={int(summary.get('selected_server_item_resource_costs', 0) or 0)}"
    )
    _say("DBDiag: done.")


def _run_all_diagnostics():
    _say("[RUN] Starting all-phase diagnostics.", DIAG_HUE_RUN)

    try:
        px = int(getattr(API.Player, "X", 0) or 0)
        py = int(getattr(API.Player, "Y", 0) or 0)
        pz = int(getattr(API.Player, "Z", 0) or 0)
        w = int(getattr(API.Player, "Weight", 0) or 0)
        wmax = int(getattr(API.Player, "MaxWeight", 0) or 0)
        _say(f"[RUN] Player state: pos=({px},{py},{pz}) weight={w}/{wmax}", DIAG_HUE_RUN)
    except Exception as ex:
        _say(f"[RUN] Player state probe failed: {ex}", 53)

    _say(
        "[RUN] Config: "
        f"runebook=0x{int(RUNBOOK_SERIAL or 0):08X} "
        f"resource=0x{int(RESOURCE_CONTAINER_SERIAL or 0):08X} "
        f"bod_items=0x{int(BOD_ITEM_CONTAINER_SERIAL or 0):08X} "
        f"salvage=0x{int(SALVAGE_BAG_SERIAL or 0):08X} "
        f"trash=0x{int(TRASH_CONTAINER_SERIAL or 0):08X} "
        f"server={str(SELECTED_SERVER or DEFAULT_SERVER)}",
        DIAG_HUE_RUN,
    )

    _run_db_diag()
    _run_container_diag()
    _run_transfer_diag()

    _say("[RUN] All-phase diagnostics complete.", DIAG_HUE_RUN)


def _clear_pending_target_context(tag=""):
    cleared = False
    for _ in range(3):
        active = False
        try:
            active = bool(API.WaitForTarget("any", 0.01))
        except Exception:
            active = False
        if not active:
            break
        try:
            API.CancelTarget()
            cleared = True
        except Exception:
            pass
        _sleep(0.06)
    if cleared:
        _say(f"TargetGuard: cleared pending target cursor ({str(tag or '')}).")
    return cleared


# Fill material helper: open/sync resource container for recursive scans and moves.
def _open_resource_container_like_diag(container_serial, attempts=3):
    sid = int(container_serial or 0)
    if sid <= 0:
        return []
    _close_nonessential_gumps_for_restock()
    # Ensure runebook/recall UI focus does not interfere with object open.
    _clear_pending_target_context("restock_open_pre")
    for i in range(1, max(1, int(attempts)) + 1):
        _clear_pending_target_context(f"restock_open_attempt_{i}")
        try:
            API.UseObject(sid)
            _say(f"RestockOpen: UseObject attempt {i} sent.")
        except Exception as ex:
            _say(f"RestockOpen: UseObject attempt {i} exception: {ex}", 33)
        _wait_and_pump(1.0, 0.1)
        try:
            items = API.ItemsInContainer(sid, True) or []
        except Exception:
            items = []
        c0, c1 = _container_item_counts(sid)
        _say(f"RestockOpen: attempt {i} counts shallow={c0} recursive={c1}")
        if len(items) > 0:
            return items
    try:
        API.ContextMenu(sid, 0)
        _say("RestockOpen: ContextMenu open attempt sent.")
    except Exception as ex:
        _say(f"RestockOpen: ContextMenu exception: {ex}", 33)
    _wait_and_pump(1.0, 0.1)
    try:
        items = API.ItemsInContainer(sid, True) or []
    except Exception:
        items = []
    c0, c1 = _container_item_counts(sid)
    _say(f"RestockOpen: post-context counts shallow={c0} recursive={c1}")
    return items


def _force_open_container_visible(container_serial, attempts=3, pause_s=0.55):
    serial = int(container_serial or 0)
    if serial <= 0:
        return False
    _say(f"Opening container window 0x{serial:08X} ...")
    for _ in range(max(1, int(attempts))):
        if _should_stop():
            return False
        try:
            API.UseObject(serial)
        except Exception:
            pass
        _sleep(float(pause_s))
        if _is_container_gump_open(serial):
            _say(f"Container window open: 0x{serial:08X}")
            return True
    # Some client/container combos do not expose a detectable gump serial even when opened.
    # Keep behavior aligned with working scripts: issue open request and continue.
    _say(f"Open request sent for container 0x{serial:08X}; continuing.", 33)
    return True


def _prime_subcontainers(container_serial, max_depth=2):
    # Open nested containers so recursive scans can actually see their contents.
    root = int(container_serial or 0)
    if root <= 0:
        return
    seen = set()
    queue = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        if current in seen or depth > max_depth:
            continue
        seen.add(current)
        _ensure_container_open(current)
        items = _items_in(current, False)
        for it in items:
            try:
                is_container = bool(getattr(it, "IsContainer", False))
            except Exception:
                is_container = False
            if not is_container:
                continue
            child = int(getattr(it, "Serial", 0) or 0)
            if child <= 0:
                continue
            if int(RUNBOOK_SERIAL or 0) > 0 and child == int(RUNBOOK_SERIAL):
                # Skip runebook so backpack subcontainer priming doesn't open recall gump.
                continue
            queue.append((child, depth + 1))


def _find_first_in_container(container_serial, item_id):
    _prime_subcontainers(container_serial, max_depth=2)
    for _ in range(2):
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) == int(item_id):
                return it
        _ensure_container_open(container_serial)
    return None


def _find_first_in_container_hued(container_serial, item_id, hue=None):
    if hue is None:
        return _find_first_in_container(container_serial, item_id)
    wanted_hue = int(hue)
    non_iron_hues = _non_iron_ingot_hues()
    ingot_id = int(_resource_item_id("ingot") or 0)
    for _ in range(2):
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            item_hue = int(getattr(it, "Hue", 0) or 0)
            if ingot_id > 0 and int(item_id) == ingot_id and int(wanted_hue) == 0:
                # Base iron matching: accept any non-colored ingot hue.
                if item_hue in non_iron_hues:
                    continue
            else:
                if item_hue != wanted_hue:
                    continue
            return it
        _ensure_container_open(container_serial)
    return None


def _find_first_in_container_multi(container_serial, item_ids):
    _ensure_container_open(container_serial)
    for item_id in item_ids:
        it = _find_first_in_container(container_serial, item_id)
        if it:
            return it
    return None


def _split_one_inside_resource(container_serial, source_item):
    try:
        cser = int(container_serial or 0)
        if cser <= 0 or not source_item:
            return 0
        src_ser = int(getattr(source_item, "Serial", 0) or 0)
        src_amt = int(getattr(source_item, "Amount", 0) or 0)
        if src_ser <= 0:
            return 0
        if src_amt <= 1:
            return src_ser
        src_graphic = int(getattr(source_item, "Graphic", 0) or 0)
        src_hue = int(getattr(source_item, "Hue", 0) or 0)
        try:
            API.MoveItem(int(src_ser), int(cser), 1, 24, 24)
        except Exception:
            API.MoveItem(int(src_ser), int(cser), 1)
        _wait_and_pump(0.35, 0.05)
        for it in _items_in(cser, True):
            if int(getattr(it, "Graphic", 0) or 0) != src_graphic:
                continue
            if int(getattr(it, "Hue", 0) or 0) != src_hue:
                continue
            if int(getattr(it, "Amount", 0) or 0) == 1:
                return int(getattr(it, "Serial", 0) or 0)
    except Exception:
        pass
    return 0


def _count_in(container_serial, item_id):
    total = 0
    for attempt in range(2):
        total = 0
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            total += int(getattr(it, "Amount", 1) or 1)
        if total > 0 or attempt > 0:
            break
        _ensure_container_open(container_serial)
    return total


def _count_in_hued(container_serial, item_id, hue=None):
    if hue is None:
        return _count_in(container_serial, item_id)
    wanted_hue = int(hue)
    non_iron_hues = _non_iron_ingot_hues()
    ingot_id = int(_resource_item_id("ingot") or 0)
    total = 0
    for attempt in range(2):
        total = 0
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            item_hue = int(getattr(it, "Hue", 0) or 0)
            if ingot_id > 0 and int(item_id) == ingot_id and int(wanted_hue) == 0:
                # Base iron matching: accept any non-colored ingot hue.
                if item_hue in non_iron_hues:
                    continue
            else:
                if item_hue != wanted_hue:
                    continue
            total += int(getattr(it, "Amount", 1) or 1)
        if total > 0 or attempt > 0:
            break
        _ensure_container_open(container_serial)
    return total


def _count_in_raw(container_serial, item_id, hue_filter=None):
    serial = container_serial
    try:
        if hasattr(container_serial, "Serial"):
            serial = container_serial.Serial
    except Exception:
        pass
    items = API.ItemsInContainer(serial, True) or []
    total = 0
    for it in items:
        if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
            continue
        if hue_filter is not None and int(getattr(it, "Hue", -1) or -1) != int(hue_filter):
            continue
        total += int(getattr(it, "Amount", 1) or 1)
    return total


def _select_restock_source_item(item_id, material_key="", hue=None):
    mk = str(material_key or "").strip().lower()
    if mk:
        return _find_first_in_container_by_material_key(RESOURCE_CONTAINER_SERIAL, item_id, mk)
    if hue is not None:
        return _find_first_in_container_hued(RESOURCE_CONTAINER_SERIAL, item_id, hue)
    return _find_first_in_container(RESOURCE_CONTAINER_SERIAL, item_id)


def _transfer_once_resource_to_backpack(item_id, material_key="", hue=None, amount=1, settle_s=0.9):
    before = int(_count_in_raw(API.Backpack, item_id, None) or 0)
    src = _select_restock_source_item(item_id, material_key, hue)
    if not src:
        return False
    src_ser = int(getattr(src, "Serial", 0) or 0)
    if src_ser <= 0:
        return False
    try:
        try:
            API.ClearJournal()
        except Exception:
            pass
        API.MoveItem(int(src_ser), API.Backpack, int(max(1, int(amount or 1))))
    except Exception:
        return False
    _wait_and_pump(float(settle_s), 0.05)
    after = int(_count_in_raw(API.Backpack, item_id, None) or 0)
    return int(after) > int(before)


# Fill material helper: restock required resource into backpack from resource container.
def _restock_resource(item_id, min_in_pack=40, pull_amount=400, hue=None, material_key=""):
    global RESTOCK_BLOCK_UNTIL
    mk = str(material_key or "").strip().lower()
    key = f"{int(item_id)}:{mk}:{'' if hue is None else int(hue)}"
    ingot_id = int(_resource_item_id("ingot") or 0)
    resource_before = 0
    if int(RESOURCE_CONTAINER_SERIAL or 0) > 0:
        if mk:
            resource_before = int(_count_in_by_material_key(RESOURCE_CONTAINER_SERIAL, item_id, mk) or 0)
        elif hue is not None:
            resource_before = int(_count_in_raw(RESOURCE_CONTAINER_SERIAL, item_id, hue) or 0)
        else:
            resource_before = int(_count_in_raw(RESOURCE_CONTAINER_SERIAL, item_id, None) or 0)
    now = _now_s()
    if not RESOURCE_CONTAINER_SERIAL:
        if mk:
            return _count_in_by_material_key(API.Backpack, item_id, mk)
        return _count_in_raw(API.Backpack, item_id, hue)
    if mk:
        current = _count_in_by_material_key(API.Backpack, item_id, mk)
    else:
        current = _count_in_raw(API.Backpack, item_id, hue)
    if now < float(RESTOCK_BLOCK_UNTIL.get(key, 0.0) or 0.0):
        if mk:
            return _count_in_by_material_key(API.Backpack, item_id, mk)
        return _count_in_raw(API.Backpack, item_id, hue)
    if current >= min_in_pack:
        RESTOCK_BLOCK_UNTIL[key] = now + 0.25
        return current
    # CrafterTrainer-style restock path: open container, read contents, move requested amount.
    _say(f"Opening resource container 0x{int(RESOURCE_CONTAINER_SERIAL):08X} for restock.")
    _open_resource_container_like_diag(int(RESOURCE_CONTAINER_SERIAL), attempts=3)
    _wait_and_pump(max(0.30, float(MOVE_ITEM_PAUSE_S)), 0.05)
    items = API.ItemsInContainer(int(RESOURCE_CONTAINER_SERIAL), True) or []
    _say(f"Resource scan items: {len(items)}")
    non_iron_hues = _non_iron_ingot_hues()

    source = None
    for item in items:
        if int(getattr(item, "Graphic", 0) or 0) != int(item_id):
            continue
        if mk:
            if ingot_id > 0 and int(item_id) == ingot_id and mk in ("ingot", "ingot_iron"):
                ih = int(getattr(item, "Hue", 0) or 0)
                if ih in non_iron_hues:
                    continue
            elif not _item_matches_material_key(item, mk):
                continue
        elif hue is not None:
            if int(getattr(item, "Hue", 0) or 0) != int(hue):
                continue
        source = item
        break

    if not source:
        RESTOCK_BLOCK_UNTIL[key] = now + RESTOCK_RETRY_COOLDOWN_S
        return current

    need = max(1, max(min_in_pack, pull_amount) - int(current))
    move_amt = min(int(need), int(getattr(source, "Amount", 0) or 0))
    if move_amt <= 0:
        RESTOCK_BLOCK_UNTIL[key] = now + RESTOCK_RETRY_COOLDOWN_S
        return current

    # Use the exact TransferDiag-success method in small chunks.
    pack_before = int(_count_in_raw(API.Backpack, item_id, None) or 0)
    moved_any = False
    chunk = 400
    remaining_to_move = int(move_amt)
    safety = 0
    while safety < 120 and remaining_to_move > 0:
        safety += 1
        if ingot_id > 0 and mk in ("ingot", "ingot_iron") and int(item_id) == ingot_id:
            iron_hue = hue
            if iron_hue is None:
                iron_hue = _resolved_ingot_hue(mk, "Blacksmith", SELECTED_SERVER)
            if iron_hue is None:
                iron_hue = 0
            have_now = int(_count_in_raw(API.Backpack, item_id, int(iron_hue)) or 0)
        elif mk:
            have_now = int(_count_in_by_material_key(API.Backpack, item_id, mk) or 0)
        else:
            have_now = int(_count_in_raw(API.Backpack, item_id, hue) or 0)
        if have_now >= int(min_in_pack):
            break

        src_cur = _select_restock_source_item(item_id, mk, hue)
        if not src_cur:
            break
        if int(getattr(src_cur, "Amount", 0) or 0) <= 0:
            break
        step_amt = int(min(int(chunk), int(remaining_to_move)))
        if step_amt <= 0:
            break
        if not _transfer_once_resource_to_backpack(item_id, mk, hue, amount=step_amt, settle_s=0.9):
            break
        moved_any = True
        remaining_to_move -= int(step_amt)

    pack_after = int(_count_in_raw(API.Backpack, item_id, None) or 0)
    if (not moved_any) or pack_after <= pack_before:
        _say("Restock chunked move did not land in backpack; aborting restock.", 33)
        RESTOCK_BLOCK_UNTIL[key] = now + RESTOCK_RETRY_COOLDOWN_S
        return current
    try:
        moved_item = API.FindItem(int(source.Serial))
    except Exception:
        moved_item = None
    moved_to_backpack = False
    if moved_item:
        try:
            mc = int(getattr(moved_item, "Container", 0) or 0)
        except Exception:
            mc = 0
        try:
            mcs = int(getattr(moved_item, "ContainerSerial", 0) or 0)
        except Exception:
            mcs = 0
        bp_ser = int(_backpack_serial() or 0)
        moved_to_backpack = (int(mc) == int(bp_ser)) or (int(mcs) == int(bp_ser))
        _say(f"Restock moved-item trace: serial=0x{int(source.Serial):08X}, container=0x{mc:08X}, container_serial=0x{mcs:08X}, amt={int(getattr(moved_item, 'Amount', 0) or 0)}")
    else:
        _say(f"Restock moved-item trace: source serial 0x{int(source.Serial):08X} not found after move.")
    RESTOCK_BLOCK_UNTIL[key] = _now_s() + 0.25

    if ingot_id > 0 and mk in ("ingot", "ingot_iron") and int(item_id) == ingot_id:
        iron_hue = hue
        if iron_hue is None:
            iron_hue = _resolved_ingot_hue(mk, "Blacksmith", SELECTED_SERVER)
        if iron_hue is None:
            iron_hue = 0
        result = _count_in_raw(API.Backpack, item_id, int(iron_hue))
    elif mk:
        result = _count_in_by_material_key(API.Backpack, item_id, mk)
    else:
        result = _count_in_raw(API.Backpack, item_id, hue)
    pack_any_after = int(_count_in_raw(API.Backpack, item_id, None) or 0)
    if mk:
        resource_after = int(_count_in_by_material_key(RESOURCE_CONTAINER_SERIAL, item_id, mk) or 0)
    elif hue is not None:
        resource_after = int(_count_in_raw(RESOURCE_CONTAINER_SERIAL, item_id, hue) or 0)
    else:
        resource_after = int(_count_in_raw(RESOURCE_CONTAINER_SERIAL, item_id, None) or 0)
    moved_delta = max(0, int(resource_before) - int(resource_after))
    _say(f"Restock result in pack: {int(result)} (pack_any={pack_any_after}, resource_delta={moved_delta})")
    if int(result) <= 0 and moved_delta > 0:
        # Do not treat delta-only movement as success for fill.
        # We must verify materials are actually usable from backpack.
        _wait_and_pump(0.5, 0.05)
        if ingot_id > 0 and mk in ("ingot", "ingot_iron") and int(item_id) == ingot_id:
            iron_hue = hue
            if iron_hue is None:
                iron_hue = _resolved_ingot_hue(mk, "Blacksmith", SELECTED_SERVER)
            if iron_hue is None:
                iron_hue = 0
            result = _count_in_raw(API.Backpack, item_id, int(iron_hue))
        elif mk:
            result = _count_in_by_material_key(API.Backpack, item_id, mk)
        else:
            result = _count_in_raw(API.Backpack, item_id, hue)
        pack_any_after = int(_count_in_raw(API.Backpack, item_id, None) or 0)
        if int(result) <= 0 and int(pack_any_after) > 0 and (moved_to_backpack or moved_any):
            # Shard/client count filter mismatch (e.g., iron subtype/hue parse mismatch).
            # Treat as success when item is verifiably in backpack.
            _say(
                "Restock count mismatch: using backpack any-count as success "
                f"(pack_any={pack_any_after}).",
                33
            )
            return int(max(min_in_pack, pack_any_after))
        if int(result) <= 0:
            _say(
                "Restock desync: resource stack changed but backpack count is still zero. "
                "Treating as failure (not usable for crafting).",
                33
            )
    return int(result)


def _move_item_to_container(item_serial, container_serial, amount=1):
    API.MoveItem(int(item_serial), int(container_serial), int(amount))
    _sleep(MOVE_ITEM_PAUSE_S)


def _is_exceptional_item(item):
    try:
        props = item.NameAndProps(True, 2) or ""
    except Exception:
        props = ""
    return "exceptional" in str(props).lower()


def _allow_keep_graphics():
    keep_ids = set()
    for name in KEEP_RESOURCE_NAMES:
        iid = int(_resource_item_id(name) or 0)
        if iid > 0:
            keep_ids.add(iid)
    for iid in (
        TINKER_TOOL_IDS
        + BLACKSMITH_TOOL_IDS
        + TAILOR_TOOL_IDS
        + CARPENTRY_TOOL_IDS
    ):
        try:
            gi = int(iid or 0)
        except Exception:
            gi = 0
        if gi > 0:
            keep_ids.add(gi)
    return keep_ids


def _move_non_keep_from_salvage_to_trash():
    if not SALVAGE_BAG_SERIAL or not TRASH_CONTAINER_SERIAL:
        return
    keep_ids = _allow_keep_graphics()
    for it in _items_in(SALVAGE_BAG_SERIAL, True):
        if int(getattr(it, "Graphic", 0) or 0) in keep_ids:
            continue
        _move_item_to_container(it.Serial, TRASH_CONTAINER_SERIAL, int(getattr(it, "Amount", 1) or 1))


def _run_salvage_cycle():
    if not SALVAGE_BAG_SERIAL:
        return
    API.ContextMenu(int(SALVAGE_BAG_SERIAL), SALVAGE_CONTEXT_INDEX)
    _sleep(0.8)
    _move_non_keep_from_salvage_to_trash()


def _get_item_text(item):
    txt = ""
    try:
        txt = item.NameAndProps(True, 2) or ""
    except Exception:
        txt = ""
    if not txt:
        try:
            txt = API.ItemNameAndProps(item.Serial, True, 2) or ""
        except Exception:
            txt = ""
    name = str(getattr(item, "Name", "") or "")
    return f"{name}\n{txt}".strip()


def _is_bod_deed(item):
    txt = _get_item_text(item).lower()
    # Keep this strict to avoid false positives on non-BOD deeds/items.
    if "bulk order deed" in txt:
        return True
    if "bulk order" in txt and "deed" in txt:
        return True
    return False


def _normalize_name(text):
    t = _normalize_text(text)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t


def _item_matches_material_key(item, material_key):
    mk = str(material_key or "").strip().lower()
    if not mk:
        return True
    txt = _normalize_text(_get_item_text(item))
    opt = _material_option_by_key(mk, "")
    base = _normalize_text(opt.get("base", "") if isinstance(opt, dict) else "")
    if not base:
        base = _normalize_text(str(mk).split("_")[0] if "_" in mk else mk)

    if _material_base_matches(base, "ingot"):
        if "ingot" not in txt:
            return False
        ingot_hue = _resolved_ingot_hue(mk, "", SELECTED_SERVER)
        if ingot_hue is None and STRICT_INGOT_HUE_MATCH:
            return False
        if ingot_hue is None:
            return True
        item_hue = int(getattr(item, "Hue", 0) or 0)
        if int(ingot_hue) == 0:
            return item_hue not in _non_iron_ingot_hues()
        return int(item_hue) == int(ingot_hue)

    if _material_base_matches(base, "board") and "board" not in txt:
        return False
    if _material_base_matches(base, "cloth") and "cloth" not in txt:
        return False
    if _material_base_matches(base, "leather") and ("leather" not in txt and "hide" not in txt):
        return False
    if _material_base_matches(base, "scale") and "scale" not in txt:
        return False

    suffix = mk
    if base and mk.startswith(base + "_"):
        suffix = mk[len(base) + 1:]
    terms = []
    for token in str(suffix or "").split("_"):
        t = _normalize_text(token)
        if not t:
            continue
        if t in (base, base.rstrip("s"), "ingot", "ingots", "scale", "scales", "hide", "hides"):
            continue
        terms.append(t)
    if not terms:
        return True
    return all(term in txt for term in terms)


def _find_first_in_container_by_material_key(container_serial, item_id, material_key):
    for _ in range(2):
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            if _item_matches_material_key(it, material_key):
                return it
        _ensure_container_open(container_serial, force=True)
        _prime_subcontainers(container_serial, max_depth=2)
    return None


def _count_in_by_material_key(container_serial, item_id, material_key):
    total = 0
    for attempt in range(2):
        total = 0
        for it in _items_in(container_serial, True):
            if int(getattr(it, "Graphic", 0) or 0) != int(item_id):
                continue
            if not _item_matches_material_key(it, material_key):
                continue
            total += int(getattr(it, "Amount", 1) or 1)
        if total > 0 or attempt > 0:
            break
        _ensure_container_open(container_serial, force=True)
        _prime_subcontainers(container_serial, max_depth=2)
    return total


def _default_material_for_profession(profession, raw_text=""):
    p = str(profession or "")
    low = _normalize_text(raw_text)
    if p in ("Blacksmith", "Tinker"):
        return "ingot"
    if p == "Carpentry":
        return "board"
    if p == "Tailor":
        if "leather" in low or "studded" in low:
            return "leather"
        return "cloth"
    return "ingot"


def _upsert_recipe(recipe):
    recipe = _normalize_recipe_entry(recipe) or recipe
    key_name = _normalize_name(recipe.get("name", ""))
    key_prof = str(recipe.get("profession", ""))
    key_mk = _recipe_material_key(recipe)
    key_type = _normalize_recipe_type(recipe.get("recipe_type", "bod"))
    key_server = _normalize_server_name(recipe.get("server", DEFAULT_SERVER))
    key_deed = str(recipe.get("deed_key", "") or "").strip()
    for i, r in enumerate(RECIPE_BOOK):
        if _normalize_recipe_type(r.get("recipe_type", "bod")) != key_type:
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != key_server:
            continue
        if str(r.get("profession", "")) != key_prof:
            continue
        if _recipe_material_key(r) != key_mk:
            continue
        r_deed = str(r.get("deed_key", "") or "").strip()
        if key_deed and r_deed and key_deed != r_deed:
            continue
        if not key_deed and not r_deed and _normalize_name(r.get("name", "")) != key_name:
            continue
        if not key_deed and r_deed:
            continue
        RECIPE_BOOK[i] = recipe
        _save_config()
        return
    RECIPE_BOOK.append(recipe)
    _save_config()


def _find_recipe_for_text(text, preferred_profession=None, preferred_material_key=None):
    preferred_prof = _canonical_profession_name(preferred_profession) if preferred_profession else ""
    deed_key = _build_deed_key(
        _extract_item_name_from_deed_text(text),
        preferred_prof or "",
        preferred_material_key or "",
        text,
    )
    if deed_key:
        exact_key = []
        for r in RECIPE_BOOK:
            if _normalize_recipe_type(r.get("recipe_type", "bod")) != "bod":
                continue
            if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
                continue
            if preferred_prof and _canonical_profession_name(r.get("profession", "")) != preferred_prof:
                continue
            if str(r.get("deed_key", "") or "").strip() == deed_key:
                exact_key.append(r)
        if exact_key:
            exact_key.sort(key=lambda r: len(str(r.get("name", ""))), reverse=True)
            return exact_key[0]
    hay = _normalize_name(text)
    matches = []
    for r in RECIPE_BOOK:
        if _normalize_recipe_type(r.get("recipe_type", "bod")) != "bod":
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
            continue
        if preferred_prof and _canonical_profession_name(r.get("profession", "")) != preferred_prof:
            continue
        key = _normalize_name(r["name"])
        if key and hay == key:
            matches.append(r)
    if not matches:
        return None
    matches.sort(key=lambda r: len(r["name"]), reverse=True)
    return matches[0]


def _find_recipe_for_deed_key(deed_key, preferred_profession=None):
    key = str(deed_key or "").strip()
    if not key:
        return None
    preferred_prof = _canonical_profession_name(preferred_profession) if preferred_profession else ""
    key_relaxed = _normalize_deed_key_for_match(key)
    matches = []
    for r in RECIPE_BOOK:
        if _normalize_recipe_type(r.get("recipe_type", "bod")) != "bod":
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
            continue
        if preferred_prof and _canonical_profession_name(r.get("profession", "")) != preferred_prof:
            continue
        row_key = str(r.get("deed_key", "") or "").strip()
        if row_key != key:
            if not key_relaxed:
                continue
            if _normalize_deed_key_for_match(row_key) != key_relaxed:
                continue
        matches.append(r)
    if not matches:
        return None
    matches.sort(key=lambda r: len(str(r.get("name", ""))), reverse=True)
    return matches[0]


def _normalize_deed_key_for_match(deed_key):
    text = str(deed_key or "").strip()
    if not text:
        return ""
    parts = text.split("|", 3)
    while len(parts) < 4:
        parts.append("")
    profession = _normalize_text(parts[0])
    material_key = _normalize_text(parts[1])
    item_name = _normalize_name(parts[2])
    signature = str(parts[3] or "")
    out = []
    for ln in [str(x).strip() for x in signature.split("|") if str(x).strip()]:
        line = _normalize_text(ln)
        line = re.sub(r"\b\d+\s*/\s*\d+\b", "count", line)
        line = re.sub(r"\bamount made\s*[: ]+\d+\b", "amount made count", line, flags=re.I)
        line = re.sub(r"\bamount to make\s*[: ]+\d+\b", "amount to make count", line, flags=re.I)
        line = re.sub(r"\buses remaining\s*[: ]+\d+\b", "uses remaining count", line, flags=re.I)
        if re.match(r"^[a-z][a-z0-9 '\-()/]*\s*:\s*\d+\s*$", line, re.I):
            line = re.sub(r"\s*:\s*\d+\s*$", ": count", line)
        elif re.match(r"^[a-z][a-z0-9 '\-()/]*\s+\d+\s*$", line, re.I):
            line = re.sub(r"\s+\d+\s*$", " count", line)
        norm = _normalize_name(line)
        if norm:
            out.append(norm)
    sig = " | ".join(out)
    return f"{profession}|{material_key}|{item_name}|{sig}".strip("|")


def _extract_item_name_from_deed_text(text):
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln and ln.strip()]

    # Prefer explicit "item: <name>" style lines first.
    for ln in lines:
        m = re.search(r"\bitem\b\s*[:\-]\s*(.+)$", ln, re.I)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                return candidate

    skip_words = (
        "bulk", "order", "deed", "amount", "made", "material", "quality",
        "exceptional", "large", "small", "combine", "contained", "items",
        "blessed", "bleesed", "bless", "filled", "completed",
        "blacksmith", "tailor", "carpentry", "tinker", "tinkering",
        "weight", "stone", "hue", "insured", "durability", "uses remaining",
    )
    skip_prefixes = (
        "weight:", "hue:", "insured:", "durability:", "uses remaining:",
        "crafted by:", "blessed:", "quantity:", "amount made:",
    )
    for ln in lines:
        low = _normalize_text(ln)
        if any(low.startswith(p) for p in skip_prefixes):
            continue
        if any(k in low for k in skip_words):
            continue
        # Most property tooltip lines are key:value. If it looks like one, skip it.
        if ":" in low:
            left = low.split(":", 1)[0].strip()
            if left in ("weight", "hue", "insured", "durability", "quantity", "uses remaining", "crafted by"):
                continue
        if re.search(r"\d+/\d+", low):
            continue
        if len(low) < 3:
            continue
        candidate = re.sub(r"^[\-\*\:\s]+", "", ln).strip()
        # Common BOD line style: "Item Name: 0" -> keep item name only.
        candidate = re.sub(r"\s*:\s*\d+\s*$", "", candidate).strip()
        if candidate:
            return candidate
    return ""


def _parse_material_needed(text, profession=""):
    low = _normalize_text(text)
    p = str(profession or "")

    if "leather" in low:
        return "leather"
    if "cloth" in low:
        return "cloth"
    if "board" in low or "boards" in low:
        return "board"
    if "ingot" in low:
        return "ingot"

    metal_words = (
        "iron", "dull copper", "shadow iron", "copper", "bronze",
        "gold", "agapite", "verite", "valorite",
    )
    if any(m in low for m in metal_words):
        return "ingot"

    if p in ("Blacksmith", "Tinker"):
        return "ingot"
    if p == "Carpentry":
        return "board"
    if p == "Tailor":
        return "cloth"
    return ""


def _deed_item_progress_lines(text):
    lines = _deed_tooltip_lines(text)
    out = []
    skip_left = {
        "amount made",
        "amount to make",
        "contained items",
        "items contained",
        "contains",
        "weight",
        "hue",
        "insured",
        "durability",
        "uses remaining",
        "crafted by",
        "quality",
        "material",
        "item name",
    }
    for ln in lines:
        m = re.match(r"^\s*(.+?)\s*:\s*(\d+)\s*/\s*(\d+)\s*$", str(ln), re.I)
        if not m:
            continue
        left = _normalize_text(m.group(1))
        if not left or left in skip_left:
            continue
        if left.startswith("amount "):
            continue
        out.append({
            "label": str(m.group(1)).strip(),
            "filled": int(m.group(2)),
            "required": int(m.group(3)),
        })
    return out


def _deed_item_count_lines(text):
    lines = _deed_tooltip_lines(text)
    out = []
    skip_left = {
        "amount made",
        "amount to make",
        "contained items",
        "items contained",
        "contains",
        "weight",
        "hue",
        "insured",
        "durability",
        "uses remaining",
        "crafted by",
        "quality",
        "material",
        "item name",
    }
    for ln in lines:
        if "/" in str(ln):
            continue
        m = re.match(r"^\s*(.+?)\s*:\s*(\d+)\s*$", str(ln), re.I)
        if not m:
            continue
        left = _normalize_text(m.group(1))
        if not left or left in skip_left:
            continue
        if left.startswith("amount "):
            continue
        out.append({
            "label": str(m.group(1)).strip(),
            "count": int(m.group(2)),
        })
    return out


def _classify_bod_size(text):
    low = _normalize_text(text)
    if not low:
        return "unknown"
    lines = [_normalize_text(x) for x in _deed_tooltip_lines(text)]
    for ln in lines:
        # Primary shard signal: explicit BOD size line in tooltip.
        if re.fullmatch(r"large\s+bulk\s+order(?:\s+deed)?", ln):
            return "large"
        if re.fullmatch(r"small\s+bulk\s+order(?:\s+deed)?", ln):
            return "small"
    if re.search(r"\blarge\s+bulk\s+order\s+deed\b", low):
        return "large"
    if re.search(r"\bsmall\s+bulk\s+order\s+deed\b", low):
        return "small"
    item_progress = _deed_item_progress_lines(text)
    item_counts = _deed_item_count_lines(text)
    if len(item_progress) >= 2:
        return "large"
    if len(item_counts) >= 2:
        return "large"
    if (
        "another deed" in low
        or "completed small" in low
        or "small bulk order deed" in low
        or "fill this large" in low
    ):
        return "large"
    if "contained items" in low or "items contained" in low:
        return "large"
    if "amount to make" in low:
        return "small"
    if len(item_progress) == 1:
        return "small"
    if len(item_counts) == 1:
        return "small"
    return "unknown"


def _parse_large_deed_progress(text):
    low = _normalize_text(text)
    patterns = [
        r"\bcontained items?\s*[: ]+\s*(\d+)\s*/\s*(\d+)\b",
        r"\bitems? contained\s*[: ]+\s*(\d+)\s*/\s*(\d+)\b",
        r"\bcontains?\s*[: ]+\s*(\d+)\s*/\s*(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, low)
        if not m:
            continue
        return int(m.group(1)), int(m.group(2))
    item_progress = _deed_item_progress_lines(text)
    if len(item_progress) >= 2:
        made = sum(int(x.get("filled", 0) or 0) for x in item_progress)
        req = sum(int(x.get("required", 0) or 0) for x in item_progress)
        return int(made), int(req)
    item_counts = _deed_item_count_lines(text)
    if len(item_counts) >= 2:
        made = sum(int(x.get("count", 0) or 0) for x in item_counts)
        return int(made), 0
    return None, None


def _read_deed_gump_text(deed_serial):
    sid = int(deed_serial or 0)
    if sid <= 0 or _should_stop():
        return ""
    try:
        API.CloseGump(int(BOD_DEED_GUMP_ID))
    except Exception:
        pass
    _sleep(0.1)
    try:
        API.UseObject(int(sid))
    except Exception:
        return ""
    _sleep(0.1)
    if not _wait_for_gump_safe(int(BOD_DEED_GUMP_ID), 1.8):
        return ""
    try:
        txt = API.GetGumpContents(int(BOD_DEED_GUMP_ID)) or ""
    except Exception:
        txt = ""
    try:
        API.CloseGump(int(BOD_DEED_GUMP_ID))
    except Exception:
        pass
    return str(txt or "")


def _refresh_large_deed_parse_from_gump(item, parsed):
    current = dict(parsed or {})
    if bool(current.get("is_large", False)):
        return current
    deed_serial = int(current.get("deed_serial", getattr(item, "Serial", 0)) or 0)
    gump_text = _read_deed_gump_text(deed_serial)
    if not gump_text:
        return current
    merged_text = f"{str(current.get('raw_text', '') or '')}\n{gump_text}".strip()
    deed_size = _classify_bod_size(merged_text)
    if deed_size != "large":
        return current
    made, req = _parse_large_deed_progress(merged_text)
    progress_lines = int(len(_deed_item_progress_lines(merged_text)))
    count_lines = int(len(_deed_item_count_lines(merged_text)))
    current["deed_size"] = "large"
    current["is_large"] = True
    current["raw_text"] = merged_text
    current["item_progress_lines"] = progress_lines
    current["item_count_lines"] = count_lines
    if made is not None:
        current["filled"] = int(made)
        current["item_count"] = int(made)
    if req is not None:
        current["required"] = int(req)
        current["amount_to_make"] = int(req)
    _say("Large deed detected from deed gump text.")
    return current


def _candidate_page_buttons(profession):
    seed = [1, 21, 41, 61, 81, 101, 121, 141, 161, 181, 201]
    for r in RECIPE_BOOK:
        if str(r.get("profession", "")) != str(profession):
            continue
        buttons = r.get("buttons", []) or []
        if len(buttons) >= 2:
            b = int(buttons[0])
            if b not in seed:
                seed.append(b)
    return seed


def _candidate_item_buttons(profession):
    seed = [2, 3]
    for v in range(22, 642, 20):
        seed.append(v)
    for r in RECIPE_BOOK:
        if str(r.get("profession", "")) != str(profession):
            continue
        buttons = r.get("buttons", []) or []
        if len(buttons) >= 2:
            b = int(buttons[1])
            if b not in seed:
                seed.append(b)
    return seed


def _line_noise(line):
    low = _normalize_text(line)
    if len(low) < 2:
        return True
    bad = (
        "menu", "blacksmith", "tailor", "carpentry", "tinker", "craft",
        "material", "amount", "quality", "exceptional", "make now",
    )
    if any(b in low for b in bad):
        return True
    if re.search(r"^\d+/?\d*$", low):
        return True
    return False


def _gump_text_lines(gump_id):
    text = API.GetGumpContents(int(gump_id)) or ""
    lines = [ln.strip() for ln in str(text).splitlines() if ln and ln.strip()]
    return lines


def _craft_item_lines_from_gump(gump_id):
    lines = _gump_text_lines(gump_id)
    out = []
    for ln in lines:
        if _line_noise(ln):
            continue
        out.append(ln)
    return out


def _craft_page_signature(gump_id):
    lines = [_normalize_name(x) for x in _craft_item_lines_from_gump(gump_id)]
    return "|".join(lines)


def _gump_mentions_next_page(gump_id):
    raw = _normalize_text(API.GetGumpContents(int(gump_id)) or "")
    return ("next" in raw and "page" in raw)


def _try_next_craft_page(gump_id):
    gid = int(gump_id)
    if not _gump_mentions_next_page(gid):
        return False
    before = _craft_page_signature(gid)
    try:
        API.ReplyGump(int(CRAFT_NEXT_PAGE_BUTTON_ID), gid)
    except Exception:
        return False
    _sleep(0.2)
    if API.WaitForGump(gid, 0.6):
        _sleep(0.1)
    after = _craft_page_signature(gid)
    return bool(after and after != before)


def _build_profession_craft_index(profession, force_rebuild=False):
    key = str(profession or "")
    if not force_rebuild and key in CRAFT_INDEX_CACHE and CRAFT_INDEX_CACHE.get(key):
        return CRAFT_INDEX_CACHE.get(key, {})

    index = {}
    page_buttons = _candidate_page_buttons(profession)
    for pb in page_buttons:
        gid = _open_craft_gump_for_profession(profession)
        if not gid:
            continue
        try:
            API.ReplyGump(int(pb), int(gid))
        except Exception:
            continue
        _sleep(0.2)
        seen_pages = set()
        page_depth = 0
        while page_depth < CRAFT_INDEX_MAX_PAGES_PER_CATEGORY:
            sig = _craft_page_signature(gid)
            if not sig or sig in seen_pages:
                break
            seen_pages.add(sig)
            item_lines = _craft_item_lines_from_gump(gid)
            for idx, label in enumerate(item_lines):
                item_button = 2 + (idx * 20)
                path = [int(pb)] + ([int(CRAFT_NEXT_PAGE_BUTTON_ID)] * page_depth) + [int(item_button)]
                n = _normalize_name(label)
                if not n:
                    continue
                # Keep shortest path for duplicate labels.
                old = index.get(n)
                if (not old) or (len(path) < len(old.get("buttons", []))):
                    index[n] = {"label": label, "buttons": path}
            if not _try_next_craft_page(gid):
                break
            page_depth += 1

    CRAFT_INDEX_CACHE[key] = index
    return index


def _find_buttons_in_profession_index(profession, item_name):
    index = _build_profession_craft_index(profession, False)
    needle = _normalize_name(item_name)
    if not needle:
        return None
    if needle in index:
        return list(index[needle]["buttons"])
    # containment fallback
    best_key = ""
    best_len = 0
    for k in index.keys():
        if needle in k or k in needle:
            if len(k) > best_len:
                best_key = k
                best_len = len(k)
    if best_key:
        return list(index[best_key]["buttons"])
    return None


def _find_item_line_index(lines, item_name):
    needle = _normalize_name(item_name)
    filtered = []
    for ln in lines:
        if _line_noise(ln):
            continue
        filtered.append(ln)
    # First try exact/contains match.
    for i, ln in enumerate(filtered):
        ln_norm = _normalize_name(ln)
        if needle and (needle == ln_norm or needle in ln_norm or ln_norm in needle):
            return i
    # Then try token overlap.
    needle_tokens = [t for t in needle.split(" ") if t]
    best_i = -1
    best_score = 0
    for i, ln in enumerate(filtered):
        ln_norm = _normalize_name(ln)
        score = 0
        for t in needle_tokens:
            if t in ln_norm:
                score += 1
        if score > best_score:
            best_score = score
            best_i = i
    return best_i if best_score > 0 else -1


def _discover_recipe_buttons_deterministic(profession, item_name):
    # Deterministic path: build category/page index, then lookup by item label.
    buttons = _find_buttons_in_profession_index(profession, item_name)
    if buttons:
        return buttons
    return None


def _learn_recipe_for_deed(parsed):
    profession = parsed.get("profession")
    deed_name = parsed.get("item_name", "") or "Unknown Item"
    if profession not in ("Blacksmith", "Tailor", "Carpentry", "Tinker"):
        return None
    _say(f"Learn Mode (manual): enter mapping for '{deed_name}'.")
    return _manual_learn_recipe_for_deed(parsed)


def _parse_bod_deed(item):
    txt = _get_item_text(item)
    lower = txt.lower()
    deed_size = _classify_bod_size(txt)
    item_progress_lines = _deed_item_progress_lines(txt)
    item_count_lines = _deed_item_count_lines(txt)
    item_name = _extract_item_name_from_deed_text(txt)
    profession = _detect_profession_from_deed_hue(item)
    if not profession:
        profession = _detect_profession_from_text(lower)
    if not profession:
        profession = _detect_profession_from_item_name(item_name)

    required = None
    filled = 0
    amount_to_make = None
    item_count = None
    m = re.search(r"(\d+)\s*/\s*(\d+)", lower)
    if m:
        filled = int(m.group(1))
        required = int(m.group(2))
    m2 = re.search(r"amount to make[: ]+(\d+)", lower)
    if m2:
        amount_to_make = int(m2.group(1))
        if required is None:
            required = int(amount_to_make)
    large_filled, large_required = _parse_large_deed_progress(txt)
    if deed_size == "large" and large_required is not None:
        filled = int(large_filled)
        required = int(large_required)
        amount_to_make = int(large_required)
        item_count = int(large_filled)
    # Try to capture explicit crafted-item progress line from the tooltip.
    # Common variants seen are "<Item Name>: <count>" or "Item Name: <count>".
    if deed_size != "large":
        if item_name:
            try:
                name_pat = re.compile(r"\b%s\s*:\s*(\d+)\b" % re.escape(str(item_name)), re.I)
                m3 = name_pat.search(txt)
                if m3:
                    item_count = int(m3.group(1))
            except Exception:
                item_count = None
        if item_count is None:
            m4 = re.search(r"\bitem name\s*:\s*(\d+)\b", lower)
            if m4:
                item_count = int(m4.group(1))
        if item_count is None:
            m5 = re.search(r"\bamount made\s*:\s*(\d+)\b", lower)
            if m5:
                item_count = int(m5.group(1))
    if item_count is not None and filled <= 0:
        filled = int(item_count)
    if required is None:
        required = 10

    exceptional = ("exceptional" in lower)
    material_needed = _parse_material_needed(txt, profession or "")
    material_key = _parse_material_key_needed(txt, material_needed, profession or "")
    deed_key = _build_deed_key(item_name, profession or "", material_key, txt)
    recipe = None
    if deed_key:
        recipe = _find_recipe_for_deed_key(deed_key, profession or None)
    if item_name:
        recipe = recipe or _find_recipe_for_item_name(item_name, profession or None, None)
    if not recipe:
        recipe = _find_recipe_for_text(txt, profession, None)
    if not recipe:
        recipe = _find_recipe_for_text(txt, None, None)
    if not recipe and item_name:
        recipe = _find_recipe_for_item_name(item_name, None, None)
    if recipe:
        recipe = _merge_item_key_map_into_recipe(recipe)

    # Material is the strongest profession signal for non-ingot deeds.
    if material_needed in ("cloth", "leather"):
        profession = "Tailor"
    elif material_needed == "board":
        profession = "Carpentry"

    if not profession and recipe:
        profession = str(recipe.get("profession", "") or "")
    if not profession and material_needed in ("cloth", "leather"):
        profession = "Tailor"
    elif not profession and material_needed == "board":
        profession = "Carpentry"

    result = {
        "deed_serial": int(item.Serial),
        "profession": recipe["profession"] if recipe else (profession or ""),
        "recipe": recipe,
        "item_name": item_name,
        "material_needed": material_needed,
        "material_key": material_key,
        "deed_key": deed_key,
        "required": int(required),
        "filled": int(filled),
        "remaining": max(0, int(required) - int(filled)),
        "amount_to_make": int(amount_to_make) if amount_to_make is not None else int(required),
        "item_count": int(item_count) if item_count is not None else int(filled),
        "exceptional": bool(exceptional),
        "deed_size": deed_size,
        "is_large": bool(deed_size == "large"),
        "item_progress_lines": int(len(item_progress_lines)),
        "item_count_lines": int(len(item_count_lines)),
        "raw_text": txt,
    }
    return result


def _find_backpack_item_by_serial(serial):
    sid = int(serial or 0)
    if sid <= 0:
        return None
    for it in _items_in(API.Backpack, True):
        if int(getattr(it, "Serial", 0) or 0) == sid:
            return it
    try:
        return API.FindItem(sid)
    except Exception:
        return None


def _deed_progress_ready(parsed):
    req = int(parsed.get("amount_to_make", parsed.get("required", 0)) or 0)
    made = int(parsed.get("item_count", parsed.get("filled", 0)) or 0)
    if req <= 0:
        req = int(parsed.get("required", 0) or 0)
    if made <= 0:
        made = int(parsed.get("filled", 0) or 0)
    if req <= 0:
        return False, req, made
    return made >= req, req, made


# Fill context helper: open and bind the correct craft gump for the profession.
def _open_craft_gump_for_profession(profession):
    global ACTIVE_CRAFT_GUMP_ID, ACTIVE_CRAFT_PROFESSION, ACTIVE_CRAFT_MATERIAL_KEY, OPEN_CRAFT_BLOCK_UNTIL

    def _wait_for_profession_gump(expected_id, timeout_s=2.8):
        t0 = _now_s()
        while (_now_s() - t0) < float(timeout_s):
            if _should_stop():
                return 0
            try:
                if int(expected_id or 0) > 0 and API.HasGump(int(expected_id)):
                    return int(expected_id)
            except Exception:
                pass
            anchor_gid = _find_craft_gump_by_anchors(profession)
            if anchor_gid > 0:
                return int(anchor_gid)
            _wait_and_pump(0.08, 0.04)
        return 0

    def _gump_ids_snapshot():
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
                    if v is not None:
                        out.add(int(v))
                        break
            except Exception:
                continue
        return out

    def _open_with_tool(tool_item, expected_id, tool_ids):
        global OPEN_CRAFT_BLOCK_UNTIL
        # Open the craft gump for the target profession using the provided tool.
        # Keep existing craft gumps open to avoid gump churn/socket pressure.
        # Only close deed gump if present because it can steal focus.
        now = _now_s()
        block_until = float(OPEN_CRAFT_BLOCK_UNTIL or 0.0)
        if now < block_until:
            remain = max(0.0, block_until - now)
            _say(f"OpenCraft: cooldown active ({remain:.1f}s); skipping reopen attempt.", 33)
            _wait_and_pump(min(0.8, remain), 0.05)
            return 0

        def _action_throttle_seen():
            try:
                return bool(
                    API.InJournal("must wait to perform another action", True)
                    or API.InJournal("must wait to perform another", True)
                )
            except Exception:
                return False

        try:
            API.CloseGump(int(BOD_DEED_GUMP_ID))
        except Exception:
            pass
        _clear_pending_target_context("open_craft_gump")
        _sleep(0.08)
        before = _gump_ids_snapshot()
        for attempt in range(1, 4):
            if _should_stop():
                return 0
            if not _wait_for_move_settle(3.0):
                _say("OpenCraft: move/gcd still busy before tool use; retrying.", 33)
                _wait_and_pump(0.4, 0.05)
                continue
            live_tool = None
            try:
                live_tool = API.FindItem(int(getattr(tool_item, "Serial", 0) or 0))
            except Exception:
                live_tool = None
            if not live_tool:
                live_tool = _find_first_in_container_multi(API.Backpack, tool_ids)
            if not live_tool:
                _say(f"OpenCraft: no live tool found in backpack for {profession}.", 33)
                return 0
            # Ensure tool is physically in backpack root so UseObject is reliable.
            try:
                bp_ser = int(_backpack_serial() or 0)
                c1 = int(getattr(live_tool, "Container", 0) or 0)
                c2 = int(getattr(live_tool, "ContainerSerial", 0) or 0)
                if bp_ser > 0 and c1 != bp_ser and c2 != bp_ser:
                    try:
                        API.MoveItem(int(getattr(live_tool, "Serial", 0) or 0), API.Backpack, 1)
                    except Exception:
                        pass
                    _wait_and_pump(0.5, 0.05)
                    _wait_for_move_settle(1.0)
                    try:
                        live_tool = API.FindItem(int(getattr(live_tool, "Serial", 0) or 0))
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                try:
                    API.ClearJournal()
                except Exception:
                    pass
                API.UseObject(int(getattr(live_tool, "Serial", 0) or 0))
            except Exception as ex:
                _say(f"OpenCraft: UseObject tool failed for {profession}: {ex}", 33)
                _sleep(0.25)
                continue
            _wait_and_pump(0.14, 0.05)
            if _action_throttle_seen():
                OPEN_CRAFT_BLOCK_UNTIL = _now_s() + float(OPEN_CRAFT_FAIL_COOLDOWN_S)
                _say(
                    f"OpenCraft: shard action throttle detected; delaying further open attempts for {OPEN_CRAFT_FAIL_COOLDOWN_S:.1f}s.",
                    33
                )
                return 0
            opened_gid = _wait_for_profession_gump(int(expected_id), 2.8)
            if opened_gid > 0:
                ACTIVE_CRAFT_GUMP_ID = int(opened_gid)
                ACTIVE_CRAFT_PROFESSION = str(profession or "")
                ACTIVE_CRAFT_MATERIAL_KEY = ""
                OPEN_CRAFT_BLOCK_UNTIL = 0.0
                return int(opened_gid)
            try:
                if expected_id and API.HasGump(int(expected_id)):
                    ACTIVE_CRAFT_GUMP_ID = int(expected_id)
                    ACTIVE_CRAFT_PROFESSION = str(profession or "")
                    ACTIVE_CRAFT_MATERIAL_KEY = ""
                    OPEN_CRAFT_BLOCK_UNTIL = 0.0
                    return int(expected_id)
            except Exception:
                pass
            if _action_throttle_seen():
                OPEN_CRAFT_BLOCK_UNTIL = _now_s() + float(OPEN_CRAFT_FAIL_COOLDOWN_S)
                _say(
                    f"OpenCraft: shard action throttle detected; delaying further open attempts for {OPEN_CRAFT_FAIL_COOLDOWN_S:.1f}s.",
                    33
                )
                return 0
            try:
                if API.InJournal("must be near", True) or API.InJournal("must be closer", True):
                    _say("OpenCraft: shard reported proximity requirement while opening craft gump.", 33)
            except Exception:
                pass
            _wait_and_pump(float(OPEN_CRAFT_RETRY_BACKOFF_S) * float(attempt), 0.05)
        try:
            after = _gump_ids_snapshot()
        except Exception:
            after = []
        OPEN_CRAFT_BLOCK_UNTIL = _now_s() + float(OPEN_CRAFT_FAIL_COOLDOWN_S)
        _say(
            f"OpenCraft: failed to open {profession} gump 0x{int(expected_id):08X}; "
            f"gumps before={sorted(list(before))} after={sorted(list(after))}.",
            33
        )
        return 0

    if (
        str(ACTIVE_CRAFT_PROFESSION or "") == str(profession or "")
        and int(ACTIVE_CRAFT_GUMP_ID or 0) > 0
        and _is_gump_open(int(ACTIVE_CRAFT_GUMP_ID))
    ):
        return int(ACTIVE_CRAFT_GUMP_ID)

    if profession == "Blacksmith":
        tool = _find_first_in_container_multi(API.Backpack, BLACKSMITH_TOOL_IDS)
        if not tool:
            return 0
        return _open_with_tool(tool, BLACKSMITH_GUMP_ID, BLACKSMITH_TOOL_IDS)
    if profession == "Tailor":
        tool = _find_first_in_container_multi(API.Backpack, TAILOR_TOOL_IDS)
        if not tool:
            return 0
        return _open_with_tool(tool, TAILOR_GUMP_ID, TAILOR_TOOL_IDS)
    if profession == "Carpentry":
        tool = _find_first_in_container_multi(API.Backpack, CARPENTRY_TOOL_IDS)
        if not tool:
            return 0
        return _open_with_tool(tool, CARPENTRY_GUMP_ID, CARPENTRY_TOOL_IDS)
    if profession == "Tinker":
        tool = _find_first_in_container_multi(API.Backpack, TINKER_TOOL_IDS)
        if not tool:
            return 0
        return _open_with_tool(tool, TINKER_GUMP_ID, TINKER_TOOL_IDS)
    return 0


def _is_gump_open(gump_id):
    global ACTIVE_CRAFT_GUMP_ID, ACTIVE_CRAFT_PROFESSION, ACTIVE_CRAFT_MATERIAL_KEY
    gid = int(gump_id or 0)
    if gid <= 0:
        return False
    try:
        ok = bool(API.HasGump(gid))
        if not ok and int(ACTIVE_CRAFT_GUMP_ID or 0) == gid:
            ACTIVE_CRAFT_GUMP_ID = 0
            ACTIVE_CRAFT_PROFESSION = ""
            ACTIVE_CRAFT_MATERIAL_KEY = ""
        return ok
    except Exception:
        if int(ACTIVE_CRAFT_GUMP_ID or 0) == gid:
            ACTIVE_CRAFT_GUMP_ID = 0
            ACTIVE_CRAFT_PROFESSION = ""
            ACTIVE_CRAFT_MATERIAL_KEY = ""
        return False


def _is_active_craft_context(profession, gump_id):
    gid = int(gump_id or 0)
    prof = str(profession or "")
    if gid <= 0 or not prof:
        return False
    if not _is_gump_open(gid):
        return False
    if str(ACTIVE_CRAFT_PROFESSION or "") != prof:
        return False
    if int(ACTIVE_CRAFT_GUMP_ID or 0) > 0 and int(ACTIVE_CRAFT_GUMP_ID or 0) != gid:
        return False
    return True


def _gump_matches_anchors(gump_id, anchors):
    gid = int(gump_id or 0)
    if gid <= 0:
        return False
    try:
        txt = API.GetGumpContents(gid) or ""
    except Exception:
        txt = ""
    if not txt:
        return False
    lower = str(txt).lower()
    for a in (anchors or []):
        if str(a or "").lower() in lower:
            return True
    return False


def _find_craft_gump_by_anchors(profession):
    anchors = CRAFT_GUMP_ANCHORS_BY_PROFESSION.get(str(profession or ""), [])
    if not anchors:
        return 0
    ids = _gump_ids_snapshot() or []
    seen = set()
    for gid in ids:
        try:
            g = int(gid)
        except Exception:
            continue
        if g <= 0 or g in seen:
            continue
        seen.add(g)
        if _gump_matches_anchors(g, anchors):
            return g
    return 0


def _click_recipe_buttons(gump_id, buttons):
    gid = int(gump_id)
    for b in buttons:
        if _should_stop():
            return False
        if gid > 0:
            try:
                API.ReplyGump(int(b), gid)
            except Exception:
                API.ReplyGump(int(b))
        else:
            API.ReplyGump(int(b))
        if not _process_callbacks_safe():
            return False
        _sleep(CRAFT_BUTTON_PAUSE_S)
        if gid > 0:
            _wait_for_gump_safe(gid, 0.5)
        else:
            _wait_for_gump_safe(None, 0.5)
    return True


def _apply_material_selection(gump_id, recipe):
    mat_buttons = _material_buttons_from_recipe(recipe)
    if not mat_buttons:
        return True
    try:
        _click_recipe_buttons(int(gump_id), mat_buttons)
        return True
    except Exception:
        return False


def _tinker_item_buttons(item_key):
    srv = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    srv_node = KEY_MAPS.get(srv, {}) if isinstance(KEY_MAPS, dict) else {}
    if not isinstance(srv_node, dict):
        return []
    tinker_node = srv_node.get("Tinker", {})
    if not isinstance(tinker_node, dict):
        return []
    item_keys = tinker_node.get("item_keys", {})
    if not isinstance(item_keys, dict):
        return []
    ent = item_keys.get(str(item_key or "").strip(), {})
    if not isinstance(ent, dict):
        return []
    return [int(x) for x in (ent.get("buttons", []) or []) if int(x) > 0][:2]


def _tinker_ingot_buttons():
    opt = _material_option_by_key("ingot", "Tinker")
    if not isinstance(opt, dict):
        return []
    return [int(x) for x in (opt.get("buttons", []) or []) if int(x) > 0][:2]


# Tool helper: ensure requested tool exists, crafting it via tinkering when needed.
def _ensure_tool_ids(tool_ids, craft_buttons=None):
    # Explicitly open/scan backpack first; some client states need this before item scans are reliable.
    bp = int(_backpack_serial() or 0)
    bp_ref = bp if bp > 0 else API.Backpack
    _ensure_container_open(bp_ref)
    if _find_first_in_container_multi(bp_ref, tool_ids):
        return True
    if RESOURCE_CONTAINER_SERIAL:
        stock_tool = _find_first_in_container_multi(RESOURCE_CONTAINER_SERIAL, tool_ids)
        if stock_tool:
            _move_item_to_container(stock_tool.Serial, API.Backpack, 1)
            _ensure_container_open(bp_ref)
            if _find_first_in_container_multi(bp_ref, tool_ids):
                return True
    if not AUTO_TOOLING or not craft_buttons:
        return False
    # Need a tinker tool to craft other tools.
    if tool_ids != TINKER_TOOL_IDS:
        if not _ensure_tool_ids(TINKER_TOOL_IDS, _tinker_item_buttons("tinker_s_tools")):
            return False
    ingot_id = int(_resource_item_id("ingot") or 0)
    if ingot_id <= 0:
        _say("Missing resource item-id mapping for 'ingot' in craftables.db resource_catalog.", 33)
        return False
    iron_hue = _resolved_ingot_hue("ingot", "Tinker", SELECTED_SERVER)
    if iron_hue is None and STRICT_INGOT_HUE_MATCH:
        _say("Missing ingot hue mapping for ingot in craftables.db material_options.", 33)
        return False
    if _restock_resource(ingot_id, min_in_pack=30, pull_amount=120, hue=iron_hue, material_key="ingot") < 5:
        return False
    gid = _open_craft_gump_for_profession("Tinker")
    if not gid:
        return False
    ingot_buttons = _tinker_ingot_buttons()
    if ingot_buttons:
        _click_recipe_buttons(gid, ingot_buttons)
    _click_recipe_buttons(gid, craft_buttons)
    _sleep(0.4)
    return _find_first_in_container_multi(bp_ref, tool_ids) is not None


def _ensure_tools_for_profession(profession):
    if profession == "Blacksmith":
        return _ensure_tool_ids(BLACKSMITH_TOOL_IDS, _tinker_item_buttons("tongs"))
    if profession == "Tailor":
        return _ensure_tool_ids(TAILOR_TOOL_IDS, _tinker_item_buttons("sewing_kit"))
    if profession == "Carpentry":
        return _ensure_tool_ids(CARPENTRY_TOOL_IDS, _tinker_item_buttons("dovetail_saw"))
    if profession == "Tinker":
        return _ensure_tool_ids(TINKER_TOOL_IDS, _tinker_item_buttons("tinker_s_tools"))
    return True


# D07 helper: ensure all materials required by the deed recipe are in backpack.
def ensure_materials_for_deed(parsed):
    _diag_step("D07", "MATERIAL", "ensure_materials_for_deed: start", DIAG_HUE_MATERIAL)
    recipe = (parsed or {}).get("recipe", None)
    if not recipe:
        _diag_step("D07", "MATERIAL", "ensure_materials_for_deed: missing recipe", DIAG_HUE_MATERIAL)
        return False
    req = int((parsed or {}).get("amount_to_make", (parsed or {}).get("required", 0)) or 0)
    made = int((parsed or {}).get("item_count", (parsed or {}).get("filled", 0)) or 0)
    remaining = max(1, req - made) if req > 0 else 1
    ok = bool(_ensure_material_for_recipe(recipe, remaining))
    _diag_step("D07", "MATERIAL", f"ensure_materials_for_deed: {'ok' if ok else 'fail'}", DIAG_HUE_MATERIAL)
    return ok


# D08 helper: ensure profession tool exists (from backpack/resource/auto-tooling).
def ensure_tool_for_profession(profession):
    prof = str(profession or "")
    _diag_step("D08", "TOOL", f"ensure_tool_for_profession: {prof}", DIAG_HUE_TOOL)
    ok = bool(_ensure_tools_for_profession(prof))
    _diag_step("D08", "TOOL", f"ensure_tool_for_profession: {'ok' if ok else 'fail'}", DIAG_HUE_TOOL)
    return ok


# D09 helper: ensure correct craft gump context is open and (optionally) material is selected.
def ensure_craft_context(profession, recipe, open_gid=0, apply_material=True):
    global ACTIVE_CRAFT_GUMP_ID, ACTIVE_CRAFT_PROFESSION, ACTIVE_CRAFT_MATERIAL_KEY
    gid = int(open_gid or 0)
    prior_gid = int(gid)
    prof = str(profession or "")
    apply_mat = bool(apply_material)
    opened_now = False
    was_open = bool(gid > 0 and _is_gump_open(gid))
    _diag_step("D09", "CONTEXT", f"ensure_craft_context: prof={prof}, gid={gid}", DIAG_HUE_CONTEXT)
    # If caller passed a live gump but active-context metadata drifted, rebind instead of reopening.
    if gid > 0 and _is_gump_open(gid):
        if str(ACTIVE_CRAFT_PROFESSION or "") != str(prof or ""):
            ACTIVE_CRAFT_MATERIAL_KEY = ""
        ACTIVE_CRAFT_GUMP_ID = int(gid)
        ACTIVE_CRAFT_PROFESSION = str(prof or "")
    if gid <= 0 or (not _is_active_craft_context(prof, gid)):
        _clear_pending_target_context("ensure_craft_context")
        gid = _open_craft_gump_for_profession(prof)
        opened_now = bool(gid > 0 and ((not was_open) or int(gid) != int(prior_gid)))
        if not gid:
            _diag_step("D09", "CONTEXT", "ensure_craft_context: open_gump fail", DIAG_HUE_CONTEXT)
            return 0, "open_gump"
    # Only apply material selection when explicitly requested by caller.
    mat_buttons = _material_buttons_from_recipe(recipe)
    wanted_material_key = str((recipe or {}).get("material_key", "") or "").strip().lower()
    current_material_key = str(ACTIVE_CRAFT_MATERIAL_KEY or "").strip().lower()
    material_changed = bool(wanted_material_key and wanted_material_key != current_material_key)
    should_apply_material = bool(apply_mat and bool(mat_buttons) and (opened_now or material_changed))
    if should_apply_material:
        _diag_step(
            "D09",
            "CONTEXT",
            f"ensure_craft_context: material_select begin gid=0x{int(gid or 0):08X} opened_now={opened_now} apply_material={apply_mat}",
            DIAG_HUE_CONTEXT
        )
        if not _apply_material_selection(gid, recipe):
            _diag_step("D09", "CONTEXT", f"ensure_craft_context: material_select fail gid={gid}", DIAG_HUE_CONTEXT)
            return gid, "material_select"
        _wait_and_pump(0.20, 0.05)
        if not _is_gump_open(gid):
            _diag_step(
                "D09",
                "CONTEXT",
                f"ensure_craft_context: gump closed after material_select gid=0x{int(gid or 0):08X}",
                DIAG_HUE_CONTEXT
            )
            ACTIVE_CRAFT_MATERIAL_KEY = ""
            return 0, "material_select"
        ACTIVE_CRAFT_MATERIAL_KEY = wanted_material_key
    elif apply_mat and not bool(mat_buttons):
        _diag_step(
            "D09",
            "CONTEXT",
            f"ensure_craft_context: material_select skipped gid=0x{int(gid or 0):08X} reason=no_material_buttons",
            DIAG_HUE_CONTEXT
        )
    elif apply_mat:
        _diag_step(
            "D09",
            "CONTEXT",
            (
                f"ensure_craft_context: material_select skipped gid=0x{int(gid or 0):08X} "
                f"reason=unchanged opened_now={opened_now} material_changed={material_changed}"
            ),
            DIAG_HUE_CONTEXT
        )
    else:
        _diag_step(
            "D09",
            "CONTEXT",
            f"ensure_craft_context: material_select skipped gid=0x{int(gid or 0):08X} apply_material={apply_mat}",
            DIAG_HUE_CONTEXT
        )
    _diag_step("D09", "CONTEXT", f"ensure_craft_context: ok gid={gid}", DIAG_HUE_CONTEXT)
    return gid, ""


# Material helper: enforce recipe material requirements in backpack before crafting.
def _ensure_material_for_recipe(recipe, required_items=1):
    reqs = _material_requirements_from_recipe(recipe, required_items)
    for r in reqs:
        mat = _normalize_text(r.get("material", "") or "")
        if mat == "ingot":
            ingot_id = int(_resource_item_id("ingot") or 0)
            if ingot_id <= 0:
                _say("Missing resource item-id mapping for 'ingot' in craftables.db resource_catalog.", 33)
                return False
            hue = r.get("hue", None)
            if hue is None:
                hue = _wanted_hue_for_item(recipe, ingot_id)
            mk = str(recipe.get("material_key", "") or "").strip().lower()
            if hue == "__MISSING__":
                mk = mk or "unknown"
                _say(f"Missing ingot hue mapping for {mk}. Set material_options.material_option_hue.", 33)
                return False
            iid = int(r.get("item_id", 0) or ingot_id)
            minimum = int(r.get("min_in_pack", 0) or 60)
            pull = int(r.get("pull_amount", 0) or 400)
            have = _restock_resource(iid, min_in_pack=minimum, pull_amount=pull, hue=hue, material_key=mk)
            if have < 10:
                res_any = 0
                res_hue = 0
                res_key = 0
                try:
                    if RESOURCE_CONTAINER_SERIAL:
                        res_any = int(_count_in_hued(RESOURCE_CONTAINER_SERIAL, iid, None) or 0)
                        if mk:
                            res_key = int(_count_in_by_material_key(RESOURCE_CONTAINER_SERIAL, iid, mk) or 0)
                        if hue is None:
                            res_hue = res_any
                        else:
                            res_hue = int(_count_in_hued(RESOURCE_CONTAINER_SERIAL, iid, hue) or 0)
                except Exception:
                    pass
                _say(
                    f"Missing ingots for {recipe.get('name','item')} "
                    f"(pack {int(have)}, resource any {res_any}, resource key {res_key}, resource hue {res_hue}, wanted hue {hue}, key {mk}).",
                    33
                )
                return False
            continue
        if mat == "cloth":
            iid = int(r.get("item_id", 0) or int(_resource_item_id("cloth") or 0))
            if iid <= 0:
                _say("Missing resource item-id mapping for 'cloth' in craftables.db resource_catalog.", 33)
                return False
            minimum = int(r.get("min_in_pack", 0) or 60)
            pull = int(r.get("pull_amount", 0) or 300)
            if _restock_resource(iid, min_in_pack=minimum, pull_amount=pull) < 10:
                return False
            continue
        if mat == "leather":
            iid = int(r.get("item_id", 0) or int(_resource_item_id("leather") or 0))
            if iid <= 0:
                _say("Missing resource item-id mapping for 'leather' in craftables.db resource_catalog.", 33)
                return False
            minimum = int(r.get("min_in_pack", 0) or 60)
            pull = int(r.get("pull_amount", 0) or 300)
            if _restock_resource(iid, min_in_pack=minimum, pull_amount=pull) < 10:
                return False
            continue
        if mat == "board":
            iid = int(r.get("item_id", 0) or int(_resource_item_id("board") or 0))
            if iid <= 0:
                _say("Missing resource item-id mapping for 'board' in craftables.db resource_catalog.", 33)
                return False
            minimum = int(r.get("min_in_pack", 0) or 80)
            pull = int(r.get("pull_amount", 0) or 500)
            if _restock_resource(iid, min_in_pack=minimum, pull_amount=pull) < 10:
                return False
            continue
        if mat in ("feather", "feathers"):
            iid = int(r.get("item_id", 0) or int(_resource_item_id("feather") or 0))
            if iid <= 0:
                _say("Missing resource item-id mapping for 'feather' in craftables.db resource_catalog.", 33)
                return False
            minimum = int(r.get("min_in_pack", 0) or 60)
            pull = int(r.get("pull_amount", 0) or 300)
            if _restock_resource(iid, min_in_pack=minimum, pull_amount=pull) < 10:
                return False
            continue
        if mat == "scale":
            # No generic scale item-id mapping in script yet; assume player stocked scales manually.
            continue
        iid = int(r.get("item_id", 0) or 0)
        minimum = int(r.get("min_in_pack", 0) or 10)
        pull = int(r.get("pull_amount", 0) or max(50, minimum))
        hue = r.get("hue", None)
        if iid <= 0:
            _say(
                f"Missing resource item-id mapping for '{mat}' "
                "(set resources.item_id in Databases/craftables.db).",
                33
            )
            return False
        if _restock_resource(iid, min_in_pack=minimum, pull_amount=pull, hue=hue) < minimum:
            return False
    return True


def _find_new_crafted_item(item_id, baseline):
    if int(item_id) <= 0:
        return None
    if _count_in(API.Backpack, item_id) <= baseline:
        return None
    for it in _items_in(API.Backpack, False):
        if int(getattr(it, "Graphic", 0) or 0) == int(item_id):
            return it
    return _find_first_in_container(API.Backpack, item_id)


def _item_name_matches_recipe(item, recipe_name):
    target = _normalize_name(recipe_name or "")
    if not target:
        return False
    text = _normalize_name(str(getattr(item, "Name", "") or ""))
    if target and (target == text or target in text or text in target):
        return True
    try:
        props = item.NameAndProps(True, 1) or ""
    except Exception:
        props = ""
    ptext = _normalize_name(props)
    if target and (target in ptext):
        return True
    return False


def _find_new_crafted_item_by_name(recipe_name, before_serials):
    current = _items_in(API.Backpack, False)
    for it in current:
        serial = int(getattr(it, "Serial", 0) or 0)
        if serial in before_serials:
            continue
        if _item_name_matches_recipe(it, recipe_name):
            return it
    # Fallback: first new item if name matching failed due to shard-specific tooltip text.
    for it in current:
        serial = int(getattr(it, "Serial", 0) or 0)
        if serial in before_serials:
            continue
        return it
    return None


# Craft helper: execute a single craft attempt and route crafted output/salvage.
def _craft_recipe_once(recipe, exceptional_required, open_gid=None):
    global LAST_CRAFT_ERROR
    LAST_CRAFT_ERROR = ""
    gid = int(open_gid or 0)
    if gid <= 0 or not _is_active_craft_context(recipe["profession"], gid):
        LAST_CRAFT_ERROR = "invalid_craft_context"
        return False, gid

    recipe_item_id = int(recipe.get("item_id", 0) or 0)
    craft_buttons = [int(x) for x in (recipe.get("buttons", []) or []) if int(x) > 0]
    if not craft_buttons:
        LAST_CRAFT_ERROR = "recipe_buttons_missing"
        _say(f"Recipe mapping for {recipe.get('name','item')} has no craft buttons.", 33)
        return False, gid
    _diag_step("D10A", "CRAFT", f"craft_once buttons={craft_buttons}", DIAG_HUE_CRAFT)
    baseline = _count_in(API.Backpack, recipe_item_id) if recipe_item_id > 0 else 0
    before_serials = set(int(getattr(it, "Serial", 0) or 0) for it in _items_in(API.Backpack, False))
    _click_recipe_buttons(gid, craft_buttons)
    waited = 0.0
    while waited < BOD_CRAFT_TIMEOUT_S:
        if _should_stop():
            LAST_CRAFT_ERROR = "stopped"
            return False, gid
        if not _process_callbacks_safe():
            LAST_CRAFT_ERROR = "stopped"
            return False, gid
        item = _find_new_crafted_item(recipe_item_id, baseline)
        if not item and recipe_item_id <= 0:
            item = _find_new_crafted_item_by_name(recipe.get("name", ""), before_serials)
        if item:
            if recipe_item_id <= 0:
                # Auto-capture graphic id after first successful craft for learned recipes.
                recipe["item_id"] = int(getattr(item, "Graphic", 0) or 0)
                _upsert_recipe(recipe)
            if exceptional_required and not _is_exceptional_item(item):
                if SALVAGE_BAG_SERIAL:
                    _move_item_to_container(item.Serial, SALVAGE_BAG_SERIAL, 1)
                    _run_salvage_cycle()
                elif TRASH_CONTAINER_SERIAL:
                    _move_item_to_container(item.Serial, TRASH_CONTAINER_SERIAL, 1)
                return False, gid
            if BOD_ITEM_CONTAINER_SERIAL:
                _move_item_to_container(item.Serial, BOD_ITEM_CONTAINER_SERIAL, 1)
            _sleep(0.12)
            return True, gid
        _sleep(0.2)
        waited += 0.2
    LAST_CRAFT_ERROR = "craft_timeout"
    return False, gid


# D10 helper: craft N items with context validation/retry guardrails.
def craft_n_items(recipe, exceptional_required, n, open_gid=0):
    global LAST_CRAFT_ERROR
    target = max(0, int(n or 0))
    gid = int(open_gid or 0)
    _diag_step("D10", "CRAFT", f"craft_n_items: target={target}, gid={gid}", DIAG_HUE_CRAFT)
    if target <= 0:
        _diag_step("D10", "CRAFT", "craft_n_items: no-op target<=0", DIAG_HUE_CRAFT)
        return 0, gid, ""
    crafted_ok = 0
    attempts = 0
    max_attempts = max(target * 4, 8)
    fatal_streak = 0
    last_err = ""
    while crafted_ok < target and attempts < max_attempts:
        attempts += 1
        if _should_stop():
            LAST_CRAFT_ERROR = "stopped"
            _diag_step("D10", "CRAFT", "craft_n_items: stopped", DIAG_HUE_CRAFT)
            return crafted_ok, gid, "stopped"
        gid, ctx_err = ensure_craft_context(recipe.get("profession", ""), recipe, gid, apply_material=False)
        if ctx_err:
            LAST_CRAFT_ERROR = ctx_err
            last_err = ctx_err
            fatal_streak += 1
            if fatal_streak >= 2:
                break
            continue
        crafted, gid = _craft_recipe_once(recipe, exceptional_required, gid)
        if crafted:
            crafted_ok += 1
            fatal_streak = 0
            last_err = ""
            continue
        last_err = LAST_CRAFT_ERROR or "craft_failed"
        if last_err in ("invalid_craft_context", "open_gump", "material_select", "craft_timeout"):
            fatal_streak += 1
            if fatal_streak >= 2:
                break
            continue
        # Keep trying for transient failures (e.g., non-exceptional item salvaged).
    _diag_step("D10", "CRAFT", f"craft_n_items: done crafted={crafted_ok}/{target} last_err={last_err or 'none'}", DIAG_HUE_CRAFT)
    return crafted_ok, gid, last_err


# Combine helper: open deed and combine from configured BOD item container.
def _combine_deed_from_container(deed_serial):
    if not BOD_ITEM_CONTAINER_SERIAL:
        return False
    if _should_stop():
        return False
    # Open the specific deed by serial, wait for the deed gump, then click Combine (button 4).
    try:
        API.CloseGump(int(BOD_DEED_GUMP_ID))
    except Exception:
        pass
    API.UseObject(int(deed_serial))
    if _wait_for_gump_safe(int(BOD_DEED_GUMP_ID), 1.8):
        try:
            API.ReplyGump(int(BOD_COMBINE_BUTTON_ID), int(BOD_DEED_GUMP_ID))
        except Exception:
            try:
                API.ReplyGump(int(BOD_COMBINE_BUTTON_ID))
            except Exception:
                pass
        if _wait_for_target_safe("any", BOD_COMBINE_TARGET_WAIT_S):
            API.Target(int(BOD_ITEM_CONTAINER_SERIAL))
            _sleep(0.6)
            try:
                API.CloseGump(int(BOD_DEED_GUMP_ID))
            except Exception:
                pass
            return True
    # Fallback legacy button sweep if shard timing/layout differs.
    _sleep(0.2)
    for bid in [int(BOD_COMBINE_BUTTON_ID)] + [int(x) for x in BOD_COMBINE_BUTTON_IDS]:
        try:
            API.ReplyGump(int(bid))
        except Exception:
            pass
        if _wait_for_target_safe("any", BOD_COMBINE_TARGET_WAIT_S):
            API.Target(int(BOD_ITEM_CONTAINER_SERIAL))
            _sleep(0.6)
            try:
                API.CloseGump(int(BOD_DEED_GUMP_ID))
            except Exception:
                pass
            return True
        _sleep(0.2)
    return False


# D11 helper: combine deed, then re-parse tooltip progress for loop control.
def combine_and_recount(deed_serial, fallback_amount=0):
    _diag_step("D11", "COMBINE", f"combine_and_recount: deed=0x{int(deed_serial or 0):08X}", DIAG_HUE_COMBINE)
    if not _combine_deed_from_container(deed_serial):
        _diag_step("D11", "COMBINE", "combine_and_recount: combine failed", DIAG_HUE_COMBINE)
        return False, None, 0, int(fallback_amount or 0)
    deed_item = _find_backpack_item_by_serial(deed_serial)
    if not deed_item:
        _diag_step("D11", "COMBINE", "combine_and_recount: deed not found in backpack", DIAG_HUE_COMBINE)
        return False, None, 0, int(fallback_amount or 0)
    refreshed = _parse_bod_deed(deed_item)
    if not refreshed:
        _diag_step("D11", "COMBINE", "combine_and_recount: parse failed", DIAG_HUE_COMBINE)
        return False, None, 0, int(fallback_amount or 0)
    amount_to_make = int(refreshed.get("amount_to_make", refreshed.get("required", fallback_amount)) or fallback_amount)
    item_count = int(refreshed.get("item_count", refreshed.get("filled", 0)) or 0)
    _diag_step("D11", "COMBINE", f"combine_and_recount: progress={item_count}/{amount_to_make}", DIAG_HUE_COMBINE)
    return True, refreshed, item_count, amount_to_make


def _large_deed_progress(parsed):
    made, req = _parse_large_deed_progress((parsed or {}).get("raw_text", ""))
    if req is None:
        req = int((parsed or {}).get("amount_to_make", (parsed or {}).get("required", 0)) or 0)
    if made is None:
        made = int((parsed or {}).get("item_count", (parsed or {}).get("filled", 0)) or 0)
    return int(made), int(req)


def _fill_large_deed(item, parsed=None):
    _diag_step("L01", "LARGE", f"fill_large_deed: start deed=0x{int(getattr(item, 'Serial', 0) or 0):08X}", DIAG_HUE_COMBINE)
    if parsed is None:
        parsed = _parse_bod_deed(item)
    if not parsed:
        _say(f"Fill skip: unrecognized large BOD 0x{int(getattr(item, 'Serial', 0) or 0):08X}.", 33)
        return False
    if not bool(parsed.get("is_large", False)):
        _say("Internal skip: large fill called for non-large deed.", 33)
        return False

    deed_serial = int(parsed.get("deed_serial", getattr(item, "Serial", 0)) or 0)
    made, req = _large_deed_progress(parsed)
    req_label = str(req) if int(req) > 0 else "?"
    if int(req) > 0 and int(made) >= int(req):
        _say(f"Large deed already complete: {made}/{req}.")
        return True

    _say(f"Filling large deed via combine: {made}/{req_label}")
    max_cycles = LARGE_BOD_MAX_COMBINE_CYCLES
    if int(req) > 0:
        max_cycles = min(
            int(LARGE_BOD_ABSOLUTE_MAX_CYCLES),
            max(int(LARGE_BOD_MAX_COMBINE_CYCLES), int(req) * 2)
        )
    no_progress_cycles = 0
    last_made = int(made)
    cycle = 0

    while cycle < int(max_cycles):
        if _should_stop():
            _say("Fill interrupted by stop request.", 33)
            return False
        cycle += 1
        _diag_step("L02", "LARGE", f"fill_large_deed: cycle={cycle}/{int(max_cycles)}", DIAG_HUE_COMBINE)
        if not _combine_deed_from_container(deed_serial):
            _say("Large deed combine step failed.", 33)
            return False
        _fill_phase_delay("L02D", "LARGE", "combine->progress_check", DIAG_HUE_COMBINE)

        deed_item = _find_backpack_item_by_serial(deed_serial)
        if not deed_item:
            _say("Large deed no longer in backpack after combine.", 33)
            return False
        refreshed = _parse_bod_deed(deed_item)
        if not refreshed:
            _say("Could not re-parse large deed progress after combine.", 33)
            return False
        made, req = _large_deed_progress(refreshed)
        req_label = str(req) if int(req) > 0 else "?"
        _say(f"Large deed progress: {made}/{req_label}")

        if int(req) > 0 and int(made) >= int(req):
            try:
                API.CloseGump(int(BOD_DEED_GUMP_ID))
            except Exception:
                pass
            return True

        if int(made) <= int(last_made):
            no_progress_cycles += 1
        else:
            no_progress_cycles = 0
        last_made = int(made)
        if int(no_progress_cycles) >= int(LARGE_BOD_NO_PROGRESS_LIMIT):
            _say("No large deed progress after combine; stopping to avoid loop.", 33)
            return False

    _say(f"Large deed combine cycle limit reached ({int(max_cycles)}).", 33)
    return False


def _fill_single_deed(item, parsed=None):
    global LAST_CRAFT_ERROR
    _diag_step("D01", "PARSE", f"fill_single_deed: start deed=0x{int(getattr(item, 'Serial', 0) or 0):08X}", DIAG_HUE_PARSE)
    # Prevent stale deed windows from blocking craft gumps.
    try:
        API.CloseGump(int(BOD_DEED_GUMP_ID))
    except Exception:
        pass
    if parsed is None:
        parsed = _parse_bod_deed(item)
    if not parsed:
        _diag_step("D01", "PARSE", "fill_single_deed: parse failed", DIAG_HUE_PARSE)
        _say(f"Skipping unrecognized BOD: 0x{int(item.Serial):08X}", 33)
        return False
    if not bool(parsed.get("is_large", False)):
        parsed = _refresh_large_deed_parse_from_gump(item, parsed)
    if bool(parsed.get("is_large", False)):
        _say("Large BOD detected in single-deed flow; redirecting to large combine flow.")
        return _fill_large_deed(item, parsed)
    profession = parsed.get("profession", "")
    supported = ("Blacksmith", "Tailor", "Carpentry", "Tinker")
    if profession not in supported:
        _diag_step("D02", "PARSE", f"fill_single_deed: unsupported profession={profession or 'unknown'}", DIAG_HUE_PARSE)
        prof_text = profession if profession else "unknown profession"
        _say(f"Skipping deed with {prof_text}.", 33)
        return False
    if not bool(ENABLED_BOD_TYPES.get(profession, True)):
        _say(f"Skipping {profession} deed (unchecked in Collect BODs).")
        return False
    if not parsed.get("recipe"):
        if LEARN_MODE:
            learned = _learn_recipe_for_deed(parsed)
            if learned:
                parsed["recipe"] = learned
                parsed["profession"] = learned["profession"]
        if not parsed.get("recipe"):
            _diag_step("D03", "PARSE", "fill_single_deed: missing recipe mapping", DIAG_HUE_PARSE)
            _say(f"No recipe mapping for deed item '{parsed.get('item_name', 'unknown')}'.", 33)
            return False
    # Material handling is recipe-driven only: do not override material_key from deed parse.
    parsed["recipe"] = dict(parsed["recipe"])

    amount_to_make = int(parsed.get("amount_to_make", parsed.get("required", 0)) or 0)
    item_count = int(parsed.get("item_count", parsed.get("filled", 0)) or 0)
    if amount_to_make <= 0:
        amount_to_make = int(parsed.get("required", 0) or 0)
    if amount_to_make <= 0:
        _diag_step("D04", "PARSE", "fill_single_deed: amount_to_make unresolved", DIAG_HUE_PARSE)
        _say("Could not determine Amount to Make from deed.", 33)
        return False
    if item_count >= amount_to_make:
        try:
            API.CloseGump(int(BOD_DEED_GUMP_ID))
        except Exception:
            pass
        return True

    _say(f"Filling {parsed['recipe']['name']} ({parsed['profession']}) {item_count}/{amount_to_make}")
    _diag_step("D05", "PARSE", f"fill_single_deed: begin progress={item_count}/{amount_to_make}", DIAG_HUE_PARSE)

    # Keep phase boundaries strict to reduce race/desync:
    # RESTOCK -> TOOL -> CONTEXT -> CRAFT -> COMBINE/RECOUNT
    craft_gid = 0
    max_cycles = max(amount_to_make * 2, 6)
    no_progress_cycles = 0
    last_count = item_count
    cycle = 0

    while item_count < amount_to_make and cycle < max_cycles:
        cycle += 1
        remaining = max(0, int(amount_to_make) - int(item_count))
        if remaining <= 0:
            break
        _diag_step("D06", "PARSE", f"fill_single_deed: cycle={cycle} remaining={remaining}", DIAG_HUE_PARSE)

        if not ensure_materials_for_deed(parsed):
            LAST_CRAFT_ERROR = "missing_material"
            _say(f"Missing materials for {parsed['recipe']['name']}.", 33)
            return False
        _fill_phase_delay("D07D", "MATERIAL", "materials->tools", DIAG_HUE_MATERIAL)

        if AUTO_TOOLING and not ensure_tool_for_profession(parsed["profession"]):
            LAST_CRAFT_ERROR = "missing_tools"
            _say(f"Auto tooling could not ensure {parsed['profession']} tools.", 33)
            return False
        _fill_phase_delay("D08D", "TOOL", "tools->context", DIAG_HUE_TOOL)

        craft_gid, ctx_err = ensure_craft_context(parsed["profession"], parsed["recipe"], craft_gid)
        if ctx_err:
            LAST_CRAFT_ERROR = ctx_err
            _say(f"Could not open {parsed['profession']} gump.", 33)
            no_progress_cycles += 1
            if no_progress_cycles >= 2:
                _say(f"Stopping deed after repeated failure: {ctx_err}.", 33)
                return False
            continue
        _fill_phase_delay("D09D", "CONTEXT", "context->craft", DIAG_HUE_CONTEXT)

        crafted_ok, craft_gid, craft_err = craft_n_items(
            parsed["recipe"],
            parsed["exceptional"],
            remaining,
            craft_gid
        )
        if crafted_ok <= 0:
            if craft_err:
                _say(f"Stopping deed after repeated failure: {craft_err}.", 33)
            no_progress_cycles += 1
            if no_progress_cycles >= 2:
                return False
            continue
        _fill_phase_delay("D10D", "CRAFT", "craft->combine", DIAG_HUE_CRAFT)

        ok, refreshed, item_count, amount_to_make = combine_and_recount(parsed["deed_serial"], amount_to_make)
        if not ok or not refreshed:
            _say("Combine step did not trigger target cursor.", 33)
            return False
        _fill_phase_delay("D11D", "COMBINE", "combine->progress_check", DIAG_HUE_COMBINE)

        _say(f"Deed progress: {item_count}/{amount_to_make}")
        _diag_step("D12", "PARSE", f"fill_single_deed: loop progress={item_count}/{amount_to_make}", DIAG_HUE_PARSE)

        if item_count <= last_count:
            no_progress_cycles += 1
        else:
            no_progress_cycles = 0
        last_count = item_count
        if no_progress_cycles >= 2:
            _say("No deed progress after combine; stopping to avoid loop.", 33)
            return False

    done = int(item_count) >= int(amount_to_make)
    _diag_step("D13", "PARSE", f"fill_single_deed: done={done}", DIAG_HUE_PARSE)
    try:
        API.CloseGump(int(BOD_DEED_GUMP_ID))
    except Exception:
        pass
    return done


def _find_backpack_bods():
    out = []
    for it in _items_in(API.Backpack, False):
        if _is_bod_deed(it):
            out.append(it)
    return out


def _collect_bods_once():
    if not RUNBOOK_SERIAL:
        _say("Runebook is not set.", 33)
        return
    selected_types = [t for t in BOD_TYPE_ORDER if bool(ENABLED_BOD_TYPES.get(t, True))]
    if not selected_types:
        _say("No BOD types selected. Enable at least one in Collect BODs.", 33)
        return
    _set_running(True)
    try:
        _say(f"Collect: home slot 1, visiting {len(selected_types)} selected BOD stop(s).")
        for bod_type in selected_types:
            if not _pause_if_needed():
                _say("Collect interrupted.", 33)
                break
            slot = int(BOD_SLOT_BY_TYPE.get(bod_type, 0) or 0)
            if slot <= 1:
                continue
            button = _slot_to_button(slot)
            _say(f"Recalling to slot {slot} ({bod_type}).")
            if not _recall_to_button(button):
                continue
            _sleep(BOD_SCAN_SETTLE_S)
            title_filters = BOD_GIVER_TITLE_HINTS.get(bod_type, [])
            matched_serials = _find_givers_by_titles(title_filters)
            if matched_serials:
                _say(f"Found {len(matched_serials)} {bod_type} giver(s) at slot {slot}.")
                for giver_serial in matched_serials:
                    _request_bod_from_giver(giver_serial)
            else:
                _say(f"No {bod_type} title matches at slot {slot}.", 33)
            _sleep(BETWEEN_GIVERS_S)
        _say("Collect complete. Recalling home.")
        _recall_home()
    finally:
        _set_running(False)


def _run_collect():
    _collect_bods_once()


def _not_implemented(name):
    _say(f"{name} is not implemented yet.", 33)


def _run_prep_sort():
    if not RUNBOOK_SERIAL:
        _say("Runebook is not set.", 33)
        return
    if not CRAFT_STATION_SET:
        _say("Crafting Station is not set.", 33)
        return
    _set_running(True)
    try:
        _say("Prep/Sort: recalling home.")
        if not _recall_home():
            _say("Failed to recall home.", 33)
            return
        _sleep(BOD_SCAN_SETTLE_S)
        if not _move_to_work_anchor():
            return
        _say("Prep/Sort complete. At crafting station.")
    finally:
        _set_running(False)


def _run_fill():
    _diag_step("F01", "RUN", "run_fill: start", DIAG_HUE_RUN)
    try:
        src = str(__file__)
    except Exception:
        src = "<unknown>"
    _say(f"Fill runtime: {src}")
    _say(f"Fill resource serial: 0x{int(RESOURCE_CONTAINER_SERIAL or 0):08X}")
    _diag_step("F02", "RUN", "run_fill: config validation", DIAG_HUE_RUN)
    if not RESOURCE_CONTAINER_SERIAL:
        _say("Resource container is not set.", 33)
        return
    if not BOD_ITEM_CONTAINER_SERIAL:
        _say("BOD Item container is not set.", 33)
        return
    if int(BOD_ITEM_CONTAINER_SERIAL or 0) == int(RESOURCE_CONTAINER_SERIAL or 0):
        _say("Resource Container and BOD Item Container cannot be the same. Re-set one of them.", 33)
        return
    if not RUNBOOK_SERIAL:
        _say("Runebook is not set.", 33)
        return
    _diag_step("F03", "RUN", "run_fill: travel phase", DIAG_HUE_RUN)
    if not _run_fill_travel_phase():
        return
    _diag_recall_state("F03S", "RUN", "post travel phase", DIAG_HUE_RUN)
    _fill_phase_delay("F03D", "RUN", "travel->move", DIAG_HUE_RUN)
    _diag_step("F03B", "RUN", "run_fill: move phase", DIAG_HUE_RUN)
    if not _run_fill_move_phase():
        return
    _diag_recall_state("F03BS", "RUN", "post move phase", DIAG_HUE_RUN)
    _fill_phase_delay("F03BD", "RUN", "move->validate_resource", DIAG_HUE_RUN)

    # Validate container access only after travel/move to the crafting spot.
    _diag_step("F04", "RUN", "run_fill: validate resource container access", DIAG_HUE_RUN)
    cinfo = _container_debug_info(RESOURCE_CONTAINER_SERIAL)
    if not cinfo.get("ok", False):
        _say(
            f"Resource container invalid: {str(cinfo.get('reason','unknown'))} "
            f"(serial 0x{int(RESOURCE_CONTAINER_SERIAL or 0):08X}). Re-set Resource Container.",
            33
        )
        return
    _say(
        f"Resource container info (post-move): name='{str(cinfo.get('name',''))}', "
        f"dist={int(cinfo.get('dist', 999))}, is_container={bool(cinfo.get('is_container', False))}"
    )
    if not bool(cinfo.get("is_container", False)):
        _say("Resource serial is not a container. Re-set Resource Container.", 33)
        return
    if int(cinfo.get("dist", 999) or 999) > 3:
        _say("Resource container is out of range from crafting spot (dist > 3).", 33)
    _diag_recall_state("F04S", "RUN", "post validate resource", DIAG_HUE_RUN)
    _fill_phase_delay("F04D", "RUN", "validate_resource->scan_bods", DIAG_HUE_RUN)

    all_bods = _find_backpack_bods()
    _diag_step("F05", "RUN", f"run_fill: backpack deeds found={len(all_bods)}", DIAG_HUE_RUN)
    _diag_recall_state("F05S", "RUN", "post scan backpack deeds", DIAG_HUE_RUN)
    if not all_bods:
        _say("No BOD deeds found in backpack.", 33)
        return

    selected = [p for p in ("Blacksmith", "Tailor", "Carpentry", "Tinker", "Alchemy", "Inscription", "Bowcraft", "Cooking") if bool(ENABLED_BOD_TYPES.get(p, False))]
    _say(f"Fill selected BOD types: {', '.join(selected) if selected else '<none>'}")
    _diag_step("F06", "RUN", "run_fill: filter deeds by selected/supported type", DIAG_HUE_RUN)
    supported = ("Blacksmith", "Tailor", "Carpentry", "Tinker")
    selected_supported = [p for p in supported if bool(ENABLED_BOD_TYPES.get(p, False))]
    if not selected_supported:
        _say("No fill-supported BOD types selected. Enable one of Blacksmith/Tailor/Carpentry/Tinker.", 33)
        return

    small_work = []
    large_work = []
    skipped = 0
    for deed in all_bods:
        parsed = _parse_bod_deed(deed)
        if not parsed:
            _say(f"Fill skip: unrecognized deed 0x{int(getattr(deed, 'Serial', 0) or 0):08X}.", 33)
            skipped += 1
            continue
        deed_name = str(parsed.get("item_name", "") or "unknown item")
        prof = str(parsed.get("profession", "") or "")
        deed_size = str(parsed.get("deed_size", "unknown") or "unknown")
        progress_lines = int(parsed.get("item_progress_lines", 0) or 0)
        count_lines = int(parsed.get("item_count_lines", 0) or 0)
        _say(
            f"Fill parse: deed=0x{int(getattr(deed, 'Serial', 0) or 0):08X} "
            f"size={deed_size} progress_lines={progress_lines} count_lines={count_lines} "
            f"name='{deed_name}' profession='{prof or 'unknown'}'"
        )
        if prof not in supported:
            _say(f"Fill skip: '{deed_name}' unresolved profession '{prof or 'unknown'}'.", 33)
            skipped += 1
            continue
        if prof not in selected_supported:
            _say(f"Fill skip: '{deed_name}' is {prof}, not selected.", 33)
            skipped += 1
            continue
        if bool(parsed.get("is_large", False)):
            made = int(parsed.get("item_count", parsed.get("filled", 0)) or 0)
            req = int(parsed.get("amount_to_make", parsed.get("required", 0)) or 0)
            _say(f"Fill defer: large deed '{deed_name}' {made}/{req if req > 0 else '?'}")
            large_work.append((deed, parsed))
            continue
        small_work.append((deed, parsed))
    if not small_work and not large_work:
        _say("No deeds matched selected fill types in backpack.", 33)
        return

    _diag_recall_state("F06S", "RUN", "post deed filtering", DIAG_HUE_RUN)
    _fill_phase_delay("F06D", "RUN", "filter->process_worklist", DIAG_HUE_RUN)
    total_work = int(len(small_work) + len(large_work))
    _diag_step("F07", "RUN", f"run_fill: processing worklist count={total_work}", DIAG_HUE_RUN)
    _diag_recall_state("F07S", "RUN", "pre run loop setup", DIAG_HUE_RUN)
    _set_running(True)
    try:
        _diag_recall_state("F07S", "RUN", "post run loop setup", DIAG_HUE_RUN)
        _say(
            f"Fill: small deeds={len(small_work)}, "
            f"deferred large deeds={len(large_work)}. Skipped {skipped}."
        )
        for deed, parsed in small_work:
            if not _pause_if_needed():
                _say("Fill interrupted.", 33)
                break
            if not _process_callbacks_safe():
                _say("Fill interrupted by callback stop.", 33)
                break
            _diag_recall_state("F07S", "RUN", "loop tick pre-deed", DIAG_HUE_RUN)
            _diag_step("F08", "RUN", f"run_fill: deed 0x{int(getattr(deed, 'Serial', 0) or 0):08X}", DIAG_HUE_RUN)
            _diag_recall_state("F08S", "RUN", "pre fill_single_deed", DIAG_HUE_RUN)
            _fill_single_deed(deed, parsed)
            _fill_phase_delay("F08D", "RUN", "deed->next_deed", DIAG_HUE_RUN)
        if large_work and _pause_if_needed() and _process_callbacks_safe():
            _say(f"Fill: processing deferred large deeds ({len(large_work)}).")
        for deed, parsed in large_work:
            if not _pause_if_needed():
                _say("Fill interrupted.", 33)
                break
            if not _process_callbacks_safe():
                _say("Fill interrupted by callback stop.", 33)
                break
            _diag_recall_state("F10S", "RUN", "loop tick pre-large-deed", DIAG_HUE_RUN)
            _diag_step("F10", "RUN", f"run_fill: large deed 0x{int(getattr(deed, 'Serial', 0) or 0):08X}", DIAG_HUE_RUN)
            _diag_recall_state("F10LS", "RUN", "pre fill_large_deed", DIAG_HUE_RUN)
            _fill_large_deed(deed, parsed)
            _fill_phase_delay("F10D", "RUN", "large_deed->next_deed", DIAG_HUE_RUN)
        _diag_step("F09", "RUN", "run_fill: salvage cycle", DIAG_HUE_RUN)
        _run_salvage_cycle()
        _say("Fill pass complete.")
        _diag_step("F11", "RUN", "run_fill: complete", DIAG_HUE_RUN)
    finally:
        _set_running(False)


def _run_turn_in():
    _not_implemented("Turn-In")


def _run_full_loop():
    _not_implemented("Full Loop")


def _create_control_gump():
    global CONTROL_GUMP, CONTROL_BUTTON, CONTROL_CONTROLS
    CONTROL_CONTROLS = []
    g = API.CreateGump(True, True, False)
    w = 460
    h = 486
    g.SetRect(420, 200, w, h)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)
    CONTROL_CONTROLS.append(bg)

    title = API.CreateGumpTTFLabel("BODAssist", 16, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 6)
    g.Add(title)
    CONTROL_CONTROLS.append(title)

    y = 34
    travel_mode = "Chiv" if USE_SACRED_JOURNEY else "Mage"
    travel_label = API.CreateGumpTTFLabel(f"Travel: {travel_mode}", 12, "#FFFFFF", "alagard", "left", 140)
    travel_label.SetPos(10, y)
    g.Add(travel_label)
    CONTROL_CONTROLS.append(travel_label)
    mage_btn = API.CreateSimpleButton("Mage", 50, 18)
    mage_btn.SetPos(315, y - 2)
    g.Add(mage_btn)
    API.AddControlOnClick(mage_btn, _set_mage)
    CONTROL_CONTROLS.append(mage_btn)
    chiv_btn = API.CreateSimpleButton("Chiv", 50, 18)
    chiv_btn.SetPos(370, y - 2)
    g.Add(chiv_btn)
    API.AddControlOnClick(chiv_btn, _set_chiv)
    CONTROL_CONTROLS.append(chiv_btn)

    y += 24
    rb_status = "Set" if RUNBOOK_SERIAL else "Unset"
    rb_label = API.CreateGumpTTFLabel(f"Runebook: {rb_status}", 12, "#FFFFFF", "alagard", "left", 180)
    rb_label.SetPos(10, y)
    g.Add(rb_label)
    CONTROL_CONTROLS.append(rb_label)
    rb_set = API.CreateSimpleButton("Set", 50, 18)
    rb_set.SetPos(315, y - 2)
    g.Add(rb_set)
    API.AddControlOnClick(rb_set, _set_runebook)
    CONTROL_CONTROLS.append(rb_set)
    rb_unset = API.CreateSimpleButton("Unset", 50, 18)
    rb_unset.SetPos(370, y - 2)
    g.Add(rb_unset)
    API.AddControlOnClick(rb_unset, _unset_runebook)
    CONTROL_CONTROLS.append(rb_unset)

    y += 24
    wa_status = f"({int(CRAFT_STATION_X)}, {int(CRAFT_STATION_Y)}, {int(CRAFT_STATION_Z)})" if CRAFT_STATION_SET else "Unset"
    wa_label = API.CreateGumpTTFLabel(f"Crafting Station: {wa_status}", 12, "#FFFFFF", "alagard", "left", 360)
    wa_label.SetPos(10, y)
    g.Add(wa_label)
    CONTROL_CONTROLS.append(wa_label)
    wa_set = API.CreateSimpleButton("Set", 50, 18)
    wa_set.SetPos(315, y - 2)
    g.Add(wa_set)
    API.AddControlOnClick(wa_set, _set_work_anchor)
    CONTROL_CONTROLS.append(wa_set)
    wa_unset = API.CreateSimpleButton("Unset", 50, 18)
    wa_unset.SetPos(370, y - 2)
    g.Add(wa_unset)
    API.AddControlOnClick(wa_unset, _unset_work_anchor)
    CONTROL_CONTROLS.append(wa_unset)

    y += 24
    rc_status = "Set" if RESOURCE_CONTAINER_SERIAL else "Unset"
    rc_label = API.CreateGumpTTFLabel(f"Resource Container: {rc_status}", 12, "#FFFFFF", "alagard", "left", 260)
    rc_label.SetPos(10, y)
    g.Add(rc_label)
    CONTROL_CONTROLS.append(rc_label)
    rc_set = API.CreateSimpleButton("Set", 50, 18)
    rc_set.SetPos(315, y - 2)
    g.Add(rc_set)
    API.AddControlOnClick(rc_set, _set_resource_container)
    CONTROL_CONTROLS.append(rc_set)
    rc_unset = API.CreateSimpleButton("Unset", 50, 18)
    rc_unset.SetPos(370, y - 2)
    g.Add(rc_unset)
    API.AddControlOnClick(rc_unset, _unset_resource_container)
    CONTROL_CONTROLS.append(rc_unset)

    y += 24
    bi_status = "Set" if BOD_ITEM_CONTAINER_SERIAL else "Unset"
    bi_label = API.CreateGumpTTFLabel(f"BOD Item Container: {bi_status}", 12, "#FFFFFF", "alagard", "left", 260)
    bi_label.SetPos(10, y)
    g.Add(bi_label)
    CONTROL_CONTROLS.append(bi_label)
    bi_set = API.CreateSimpleButton("Set", 50, 18)
    bi_set.SetPos(315, y - 2)
    g.Add(bi_set)
    API.AddControlOnClick(bi_set, _set_bod_item_container)
    CONTROL_CONTROLS.append(bi_set)
    bi_unset = API.CreateSimpleButton("Unset", 50, 18)
    bi_unset.SetPos(370, y - 2)
    g.Add(bi_unset)
    API.AddControlOnClick(bi_unset, _unset_bod_item_container)
    CONTROL_CONTROLS.append(bi_unset)

    y += 24
    sv_status = "Set" if SALVAGE_BAG_SERIAL else "Unset"
    sv_label = API.CreateGumpTTFLabel(f"Salvage Bag: {sv_status}", 12, "#FFFFFF", "alagard", "left", 260)
    sv_label.SetPos(10, y)
    g.Add(sv_label)
    CONTROL_CONTROLS.append(sv_label)
    sv_set = API.CreateSimpleButton("Set", 50, 18)
    sv_set.SetPos(315, y - 2)
    g.Add(sv_set)
    API.AddControlOnClick(sv_set, _set_salvage_bag)
    CONTROL_CONTROLS.append(sv_set)
    sv_unset = API.CreateSimpleButton("Unset", 50, 18)
    sv_unset.SetPos(370, y - 2)
    g.Add(sv_unset)
    API.AddControlOnClick(sv_unset, _unset_salvage_bag)
    CONTROL_CONTROLS.append(sv_unset)

    y += 24
    tr_status = "Set" if TRASH_CONTAINER_SERIAL else "Unset"
    tr_label = API.CreateGumpTTFLabel(f"Trash Container: {tr_status}", 12, "#FFFFFF", "alagard", "left", 260)
    tr_label.SetPos(10, y)
    g.Add(tr_label)
    CONTROL_CONTROLS.append(tr_label)
    tr_set = API.CreateSimpleButton("Set", 50, 18)
    tr_set.SetPos(315, y - 2)
    g.Add(tr_set)
    API.AddControlOnClick(tr_set, _set_trash_container)
    CONTROL_CONTROLS.append(tr_set)
    tr_unset = API.CreateSimpleButton("Unset", 50, 18)
    tr_unset.SetPos(370, y - 2)
    g.Add(tr_unset)
    API.AddControlOnClick(tr_unset, _unset_trash_container)
    CONTROL_CONTROLS.append(tr_unset)

    y += 24
    tool_state = "On" if AUTO_TOOLING else "Off"
    tool_label = API.CreateGumpTTFLabel(f"Auto Tooling: {tool_state}", 12, "#FFFFFF", "alagard", "left", 260)
    tool_label.SetPos(10, y)
    g.Add(tool_label)
    CONTROL_CONTROLS.append(tool_label)
    tool_btn = API.CreateSimpleButton("Toggle", 80, 18)
    tool_btn.SetPos(340, y - 2)
    g.Add(tool_btn)
    API.AddControlOnClick(tool_btn, _toggle_auto_tooling)
    CONTROL_CONTROLS.append(tool_btn)

    y += 24
    server_options = _current_server_options()
    if not server_options:
        server_options = [str(SELECTED_SERVER or DEFAULT_SERVER or "<none>")]
    display_server = _normalize_server_name(SELECTED_SERVER or DEFAULT_SERVER)
    if not display_server:
        display_server = str(server_options[0] if server_options else "<none>")
    srv_idx = 0
    try:
        srv_idx = list(server_options).index(str(display_server))
    except Exception:
        srv_idx = 0
    srv_label = API.CreateGumpTTFLabel(f"Server: {str(display_server)}", 12, "#FFFFFF", "alagard", "left", 220)
    srv_label.SetPos(10, y)
    g.Add(srv_label)
    CONTROL_CONTROLS.append(srv_label)
    srv_dd = API.CreateDropDown(150, list(server_options), srv_idx)
    srv_dd.SetPos(220, y - 2)
    g.Add(srv_dd)
    srv_dd.OnDropDownOptionSelected(_set_server)
    CONTROL_CONTROLS.append(srv_dd)

    y += 24
    learn_state = "On" if LEARN_MODE else "Off"
    learn_label = API.CreateGumpTTFLabel(f"Learn Mode: {learn_state} (recipes: {len(RECIPE_BOOK)})", 12, "#FFFFFF", "alagard", "left", 300)
    learn_label.SetPos(10, y)
    g.Add(learn_label)
    CONTROL_CONTROLS.append(learn_label)
    learn_btn = API.CreateSimpleButton("Toggle", 80, 18)
    learn_btn.SetPos(340, y - 2)
    g.Add(learn_btn)
    API.AddControlOnClick(learn_btn, _toggle_learn_mode)
    CONTROL_CONTROLS.append(learn_btn)
    manual_btn = API.CreateSimpleButton("Manual Recipe", 100, 18)
    manual_btn.SetPos(230, y - 2)
    g.Add(manual_btn)
    API.AddControlOnClick(manual_btn, _open_manual_recipe_from_control)
    CONTROL_CONTROLS.append(manual_btn)

    y += 24
    auto_label = API.CreateGumpTTFLabel("Collect BODs", 13, "#FFFFFF", "alagard", "left", 330)
    auto_label.SetPos(10, y)
    g.Add(auto_label)
    CONTROL_CONTROLS.append(auto_label)
    help_btn = API.CreateSimpleButton("Title Help", 80, 18)
    help_btn.SetPos(340, y - 2)
    g.Add(help_btn)
    API.AddControlOnClick(help_btn, _show_bod_title_help)
    CONTROL_CONTROLS.append(help_btn)

    y += 22
    grid_start_x = 10
    grid_start_y = y
    col_w = 102
    row_h = 20
    for idx, bod_type in enumerate(BOD_TYPE_ORDER):
        row = int(idx / 4)
        col = int(idx % 4)
        cb = API.CreateGumpCheckbox(bod_type, 996, bool(ENABLED_BOD_TYPES.get(bod_type, True)))
        cb.SetPos(grid_start_x + (col * col_w), grid_start_y + (row * row_h))
        g.Add(cb)
        API.AddControlOnClick(cb, lambda t=bod_type: _toggle_bod_type_enabled(t))
        CONTROL_CONTROLS.append(cb)

    y = grid_start_y + (row_h * 2) + 8
    row_btn_w = 100
    row_btn_gap = int((w - (4 * row_btn_w)) / 5)
    x1 = row_btn_gap
    x2 = x1 + row_btn_w + row_btn_gap
    x3 = x2 + row_btn_w + row_btn_gap
    x4 = x3 + row_btn_w + row_btn_gap

    collect_btn = API.CreateSimpleButton("Run Collect", row_btn_w, 20)
    collect_btn.SetPos(x1, y)
    g.Add(collect_btn)
    API.AddControlOnClick(collect_btn, _run_collect)
    CONTROL_CONTROLS.append(collect_btn)

    prep_btn = API.CreateSimpleButton("Run Prep/Sort", row_btn_w, 20)
    prep_btn.SetPos(x2, y)
    g.Add(prep_btn)
    API.AddControlOnClick(prep_btn, _run_prep_sort)
    CONTROL_CONTROLS.append(prep_btn)

    fill_btn = API.CreateSimpleButton("Run Fill", row_btn_w, 20)
    fill_btn.SetPos(x3, y)
    g.Add(fill_btn)
    API.AddControlOnClick(fill_btn, _run_fill)
    CONTROL_CONTROLS.append(fill_btn)

    turn_btn = API.CreateSimpleButton("Run Turn-In", row_btn_w, 20)
    turn_btn.SetPos(x4, y)
    g.Add(turn_btn)
    API.AddControlOnClick(turn_btn, _run_turn_in)
    CONTROL_CONTROLS.append(turn_btn)

    y += 24
    diag_row_w = 64 + 6 + 120 + 6 + 120
    row_x = int((w - diag_row_w) / 2)
    stop_btn = API.CreateSimpleButton("Stop", 64, 20)
    stop_btn.SetPos(row_x, y)
    g.Add(stop_btn)
    API.AddControlOnClick(stop_btn, _hard_stop)
    CONTROL_CONTROLS.append(stop_btn)

    diag_btn = API.CreateSimpleButton("Diagnostics", 120, 20)
    diag_btn.SetPos(row_x + 70, y)
    g.Add(diag_btn)
    API.AddControlOnClick(diag_btn, _run_all_diagnostics)
    CONTROL_CONTROLS.append(diag_btn)

    log_btn = API.CreateSimpleButton("Debug Log", 120, 20)
    log_btn.SetPos(row_x + 196, y)
    g.Add(log_btn)
    API.AddControlOnClick(log_btn, _open_log_gump)
    CONTROL_CONTROLS.append(log_btn)

    y += 24
    loop_btn = API.CreateSimpleButton("Run Full Loop", 100, 20)
    loop_btn.SetPos(int((w - 100) / 2), y)
    g.Add(loop_btn)
    API.AddControlOnClick(loop_btn, _run_full_loop)
    CONTROL_CONTROLS.append(loop_btn)

    API.AddGump(g)
    CONTROL_GUMP = g


def _rebuild_gump():
    global CONTROL_GUMP
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
    _create_control_gump()


def _main():
    _load_log_config()
    _reset_debug_log_for_new_session()
    try:
        sr = bool(getattr(API, "StopRequested", False))
    except Exception:
        sr = False
    _write_debug_log(f"Startup state: stop_requested={sr}, force_stop={bool(FORCE_STOP)}, util_dir={_util_dir}")
    _write_debug_log("Startup: _load_config begin.")
    _load_config()
    _write_debug_log("Startup: _load_config end.")
    _write_debug_log("Startup: _create_control_gump begin.")
    _create_control_gump()
    _write_debug_log("Startup: _create_control_gump end.")
    _say("BODAssist loaded. Learn Mode uses RecipeBookEditor to map unknown deeds into the persistent recipe book.")
    while not _should_stop():
        try:
            if not _process_callbacks_safe():
                break
            _sleep(0.1)
        except Exception as ex:
            msg = str(ex or "")
            if _should_stop() or "ThreadInterrupted" in msg or "interrupted" in msg.lower():
                _write_debug_log(f"Runtime loop interrupted: {msg}")
                break
            _say(f"BODAssist runtime paused after callback error: {msg}", 33)
            _set_running(False)
            _sleep(0.3)
    _write_debug_log(f"Runtime loop exit: stop={_should_stop()} force_stop={bool(FORCE_STOP)}")


try:
    _main()
except Exception as ex:
    msg = str(ex or "")
    if "ThreadInterrupted" in msg or "interrupted" in msg.lower() or _should_stop():
        _write_debug_log(f"Startup interrupted: {msg}")
        pass
    else:
        _say(f"BODAssist startup failed: {msg or type(ex).__name__}", 33)
        _write_debug_log(f"Startup fatal exception: {msg}")
        _write_debug_log(traceback.format_exc())
        raise
