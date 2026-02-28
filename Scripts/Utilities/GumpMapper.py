"""
GumpMapper for TazUO LegionScripts.

Purpose:
- Automatically map server-side gumps and export a deterministic button map.
- Capture PacketGumpText and visible gump text for future automation scripts.

Assumptions:
- API.py exists and exposes Legion gump methods.
- Operator can target a root object that opens a root gump.

Risks:
- Script sends gump replies automatically and can traverse many buttons.
"""

import API
import copy
import io
import json
import os
import re
import time
import hashlib
from collections import deque

SCRIPT_NAME = "GumpMapper"
SCRIPT_VERSION = "1.0.0"
RUN_SCHEMA_VERSION = "1.0.0"
PARSER_SCHEMA_VERSION = "1.0.0"

PERSIST_KEY = "gump_mapper_config_v1"
ABORT_FLAG_KEY = "gump_mapper_abort"
RESUME_KEY = "gump_mapper_resume_v1"
DEFAULT_EXPORT_SUBDIR = "gump_maps"
LIVE_FILE_SUFFIX = "_live"
CHECKPOINT_SCHEMA_VERSION = "1.0.0"
DIAG_LOG_EXTENSION = ".diag.log"
ENABLE_PERSISTENT_DIAG_LOG = True

DEFAULT_HUE = 88
WARN_HUE = 33
GOOD_HUE = 68

ROOT_TARGET_TIMEOUT_S = 12.0
ROOT_WAIT_S = 8.0
ROOT_SETTLE_S = 0.25

BASE_PAUSE_S = 0.30
POST_POLL_S = 0.10
CLICK_WAIT_S = 2.20
QUEUE_WAIT_S = 12.0
ABORT_POLL_S = 0.60
MAX_BACKOFF = 5
MAX_BACKOFF_S = 4.0
MIN_ROOT_REOPEN_GAP_S = 2.0

MAX_DEPTH = 4
MAX_BUTTONS_PER_GUMP = 80
MAX_TOTAL_CAPTURES = 500
MAX_TOTAL_EDGES = 2500
MAX_CHILDREN_PER_CLICK = 4
MAX_REPEAT_LAYOUTS = 20
MAX_NO_RESPONSE = 12
MAX_CONSECUTIVE_ROOT_OPEN_FAILS = 3
MAX_CONSECUTIVE_NO_GUMP_STATES = 3
MAX_PATH_REOPEN_FAILS_PER_CAPTURE = 3
CONNECTION_SUSPECT_IDLE_S = 8.0
CONNECTION_SUSPECT_MIN_NO_GUMP_EVENTS = 3
CONNECTION_SUSPECT_LOG_GAP_S = 5.0
JOURNAL_SCAN_INTERVAL_S = 1.0
ACTION_RING_MAX = 60
ACTION_DUMP_SIZE = 12
AUTO_CANCEL_TARGET_CURSOR = True

REQUIRE_SAVE_CONFIRMATION = False
PROGRESS_GUMP_X = 130
PROGRESS_GUMP_Y = 320
PROGRESS_GUMP_W = 430
PROGRESS_GUMP_H = 194

RE_WS = r'[ \t\r\n]+'
RE_STRING = r'\"(?:\\\\.|[^\"\\\\])*\"'
RE_HEX = r'[-+]?0[xX][0-9A-Fa-f]+'
RE_INT = r'[-+]?\d+'
RE_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'
RE_COMMA = r','
RE_LBRACK = r'\['
RE_RBRACK = r'\]'
RE_LPAREN = r'\('
RE_RPAREN = r'\)'
RE_UNKNOWN = r'.'

TOKEN_RULES = [
    ("WS", re.compile(RE_WS)),
    ("STRING", re.compile(RE_STRING)),
    ("HEX", re.compile(RE_HEX)),
    ("INT", re.compile(RE_INT)),
    ("IDENT", re.compile(RE_IDENT)),
    ("COMMA", re.compile(RE_COMMA)),
    ("LBRACK", re.compile(RE_LBRACK)),
    ("RBRACK", re.compile(RE_RBRACK)),
    ("LPAREN", re.compile(RE_LPAREN)),
    ("RPAREN", re.compile(RE_RPAREN)),
    ("UNKNOWN", re.compile(RE_UNKNOWN)),
]
LINE_TOKEN_RULE = re.compile(r'"(?:\\\\.|[^"\\\\])*"|[^\s]+')

COMMAND_REGISTRY = {
    "button": {
        "arg_names": ["x", "y", "normal_id", "pressed_id", "type", "param", "button_id"],
        "button_field": "button_id",
        "x_field": "x",
        "y_field": "y",
    },
    "buttontileart": {
        "arg_names": ["x", "y", "normal_id", "pressed_id", "type", "param", "button_id", "item_id", "hue", "item_x", "item_y"],
        "button_field": "button_id",
        "x_field": "x",
        "y_field": "y",
    },
    "text": {
        "arg_names": ["x", "y", "hue", "text_index"],
        "text_index_field": "text_index",
        "x_field": "x",
        "y_field": "y",
    },
    "croppedtext": {
        "arg_names": ["x", "y", "width", "height", "hue", "text_index"],
        "text_index_field": "text_index",
        "x_field": "x",
        "y_field": "y",
    },
    "htmlgump": {
        "arg_names": ["x", "y", "width", "height", "text_or_index", "background", "scrollbar"],
        "text_value_field": "text_or_index",
        "x_field": "x",
        "y_field": "y",
    },
    "textentry": {
        "arg_names": ["x", "y", "width", "height", "hue", "entry_id", "initial_text"],
        "text_value_field": "initial_text",
        "x_field": "x",
        "y_field": "y",
    },
    "textentrylimited": {
        "arg_names": ["x", "y", "width", "height", "hue", "entry_id", "initial_text", "char_limit"],
        "text_value_field": "initial_text",
        "x_field": "x",
        "y_field": "y",
    },
}

RUN_DIAGNOSTICS = []
_ABORT_CACHE = {"last_check": 0.0, "value": False}
_DIAG_LOG_STATE = {"enabled": False, "path": "", "session_id": "", "sequence": 0}
_CONNECTION_DIAG = {
    "events_registered": False,
    "last_event": "",
    "last_event_utc": "",
    "connected_event_count": 0,
    "disconnected_event_count": 0,
    "event_hook_error": "",
}
_RUNTIME_DIAG = {
    "last_good_gump_time": 0.0,
    "no_gump_events": 0,
    "last_suspect_log_time": 0.0,
    "last_journal_scan_time": 0.0,
    "journal_last_text": "",
    "journal_last_match": "",
    "journal_match_count": 0,
    "journal_last_logged_match": "",
    "last_stop_requested": False,
    "host_stop_transition_seen": False,
    "host_stop_transition_utc": "",
    "host_stop_disconnect_suspected": False,
    "action_ring": deque([], int(ACTION_RING_MAX)),
}
_PROGRESS_GUMP = {
    "panel": None,
    "server_label": None,
    "root_label": None,
    "status_label": None,
    "counts_label": None,
    "queue_label": None,
    "stop_label": None,
    "last_render_key": "",
}
DISCONNECT_JOURNAL_KEYWORDS = [
    "disconnected",
    "connection lost",
    "lost connection",
    "server is not responding",
    "timed out",
    "connection to the server",
    "cannot communicate",
    "link dead",
]
TARGET_PROMPT_JOURNAL_KEYWORDS = [
    "target an item",
    "target an object",
    "target a",
    "what do you want to target",
    "select target",
]
TARGET_PROMPT_CANCEL_WAIT_S = 0.20
UTILITY_BUTTON_MODULO = 7
UTILITY_BUTTON_KEYWORDS = (
    "repair",
    "enhance",
    "smelt",
    "recycle",
    "mark",
    "alter",
)
BLACKSMITH_CATEGORY_NAME_ORDER = (
    "Metal Armor",
    "Helmets",
    "Shields",
    "Bladed",
    "Axes",
    "Polearms",
    "Bashing",
    "Cannons",
    "Throwing",
    "Miscellaneous",
)
BLACKSMITH_MATERIAL_NAME_WHITELIST = (
    "Iron",
    "Dull Copper",
    "Shadow Iron",
    "Copper",
    "Bronze",
    "Gold",
    "Agapite",
    "Verite",
    "Valorite",
    "Red Scales",
    "Yellow Scales",
    "Black Scales",
    "Green Scales",
    "White Scales",
    "Blue Scales",
)
BLACKSMITH_INGOT_NAME_WHITELIST = (
    "Iron",
    "Dull Copper",
    "Shadow Iron",
    "Copper",
    "Bronze",
    "Gold",
    "Agapite",
    "Verite",
    "Valorite",
)
BLACKSMITH_SCALE_NAME_WHITELIST = (
    "Red Scales",
    "Yellow Scales",
    "Black Scales",
    "Green Scales",
    "White Scales",
    "Blue Scales",
)


def _safe_str(value):
    """Return safe string."""
    try:
        return "" if value is None else str(value)
    except Exception:
        return ""


def _safe_int(value, default_value=0):
    """Return safe integer."""
    try:
        return int(value)
    except Exception:
        return int(default_value)


def _safe_opt_int(value):
    """Return integer or None."""
    try:
        return int(value)
    except Exception:
        return None


def _utc_now_iso():
    """Return UTC timestamp string."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception:
        return "1970-01-01T00:00:00Z"


def _utc_now_compact():
    """Return compact UTC timestamp for file names."""
    try:
        return time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    except Exception:
        return "19700101_000000"


def _sha1_text(text):
    """Return SHA1 hex digest for text."""
    raw = _safe_str(text)
    try:
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()
    except Exception:
        return ""


def _sys(message, hue=DEFAULT_HUE):
    """Send SysMsg safely."""
    try:
        API.SysMsg(_safe_str(message), int(hue))
    except Exception:
        pass


def _json_default(value):
    """Serialize unsupported values as safe strings for JSON logging."""
    return _safe_str(value)


def _recent_actions(limit):
    """Return the most recent action records from in-memory ring buffer."""
    items = list(_RUNTIME_DIAG.get("action_ring", deque()))
    keep = max(1, _safe_int(limit, int(ACTION_DUMP_SIZE),))
    if len(items) <= keep:
        return items
    return items[-keep:]


def _record_action(message, level, context):
    """Record a compact action event for post-incident debugging."""
    ring = _RUNTIME_DIAG.get("action_ring")
    if not isinstance(ring, deque):
        ring = deque([], int(ACTION_RING_MAX))
        _RUNTIME_DIAG["action_ring"] = ring
    ring.append(
        {
            "time_utc": _utc_now_iso(),
            "message": _safe_str(message),
            "level": _safe_str(level),
            "context": context if isinstance(context, dict) else {},
        }
    )


def _mark_good_gump_interaction():
    """Mark that the server still responded with gump data."""
    _RUNTIME_DIAG["last_good_gump_time"] = float(time.time())
    _RUNTIME_DIAG["no_gump_events"] = 0


def _mark_no_gump_interaction():
    """Increment no-gump counter for disconnect suspicion checks."""
    _RUNTIME_DIAG["no_gump_events"] = _safe_int(_RUNTIME_DIAG.get("no_gump_events", 0), 0) + 1


def _scan_journal_disconnect_markers():
    """Update journal-based disconnect indicators with throttled polling."""
    now = float(time.time())
    last_scan = float(_RUNTIME_DIAG.get("last_journal_scan_time", 0.0) or 0.0)
    if (now - last_scan) < float(JOURNAL_SCAN_INTERVAL_S):
        return
    _RUNTIME_DIAG["last_journal_scan_time"] = now

    latest_text = ""
    latest_match = ""
    match_count = 0
    try:
        entries = API.GetJournalEntries(30.0)
    except Exception:
        entries = []
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        text = _safe_str(getattr(entry, "Text", "") if entry is not None else "").strip()
        if not text:
            continue
        latest_text = text
        lower = text.lower()
        for key in DISCONNECT_JOURNAL_KEYWORDS:
            if key in lower:
                latest_match = key
                match_count += 1
                break
    _RUNTIME_DIAG["journal_last_text"] = latest_text
    _RUNTIME_DIAG["journal_last_match"] = latest_match
    _RUNTIME_DIAG["journal_match_count"] = int(match_count)


def _journal_indicates_target_prompt():
    """Return True when the latest journal text looks like a target prompt."""
    latest_text = _safe_str(_RUNTIME_DIAG.get("journal_last_text", "")).strip()
    if not latest_text:
        return False, ""
    lower = latest_text.lower()
    for key in TARGET_PROMPT_JOURNAL_KEYWORDS:
        if key in lower:
            return True, latest_text
    return False, latest_text


def _emit_action_dump(reason, extra=None):
    """Emit a recent action dump to diagnostics for incident analysis."""
    payload = {"reason": _safe_str(reason), "recent_actions": _recent_actions(int(ACTION_DUMP_SIZE))}
    if isinstance(extra, dict):
        payload["extra"] = copy.deepcopy(extra)
    _diag("warn", "connection_action_dump", payload)


def _maybe_log_journal_disconnect_suspect():
    """Log when journal text first indicates a possible disconnect."""
    match = _safe_str(_RUNTIME_DIAG.get("journal_last_match", "")).strip()
    if not match:
        return
    last = _safe_str(_RUNTIME_DIAG.get("journal_last_logged_match", "")).strip()
    if match == last:
        return
    _RUNTIME_DIAG["journal_last_logged_match"] = match
    _diag(
        "error",
        "connection_journal_disconnect_suspect",
        {
            "journal_last_match": match,
            "journal_last_text": _safe_str(_RUNTIME_DIAG.get("journal_last_text", "")),
            "journal_match_count": _safe_int(_RUNTIME_DIAG.get("journal_match_count", 0), 0),
            "connection": _connection_health_snapshot(),
        },
    )


def _maybe_log_connection_suspect(reason, extra=None):
    """Log a connection suspect event when no-gump silence persists."""
    now = float(time.time())
    last_good = float(_RUNTIME_DIAG.get("last_good_gump_time", 0.0) or 0.0)
    no_gumps = _safe_int(_RUNTIME_DIAG.get("no_gump_events", 0), 0)
    if no_gumps < int(CONNECTION_SUSPECT_MIN_NO_GUMP_EVENTS):
        return
    if last_good > 0.0 and (now - last_good) < float(CONNECTION_SUSPECT_IDLE_S):
        return
    last_log = float(_RUNTIME_DIAG.get("last_suspect_log_time", 0.0) or 0.0)
    if (now - last_log) < float(CONNECTION_SUSPECT_LOG_GAP_S):
        return
    _RUNTIME_DIAG["last_suspect_log_time"] = now
    _maybe_log_journal_disconnect_suspect()

    context = {
        "reason": _safe_str(reason),
        "seconds_since_last_good_gump": 0.0 if last_good <= 0.0 else round(now - last_good, 3),
        "no_gump_events": int(no_gumps),
        "connection": _connection_health_snapshot(),
    }
    if isinstance(extra, dict):
        context["extra"] = copy.deepcopy(extra)
    _diag("error", "connection_suspect_timeout", context)
    _emit_action_dump("connection_suspect_timeout", {"reason": _safe_str(reason)})


def _maybe_log_stop_requested_transition():
    """Log when StopRequested changes from false to true."""
    current = False
    try:
        current = bool(getattr(API, "StopRequested", False))
    except Exception:
        current = False
    previous = bool(_RUNTIME_DIAG.get("last_stop_requested", False))
    if current and not previous:
        snapshot = _connection_health_snapshot()
        disconnect_like = (
            (not bool(snapshot.get("player_exists", True)))
            or (snapshot.get("player_hits") is None)
            or (snapshot.get("player_hits_max") is None)
            or (_safe_int(snapshot.get("disconnected_event_count", 0), 0) > 0)
        )
        _RUNTIME_DIAG["host_stop_transition_seen"] = True
        _RUNTIME_DIAG["host_stop_transition_utc"] = _utc_now_iso()
        _RUNTIME_DIAG["host_stop_disconnect_suspected"] = bool(disconnect_like)
        _diag(
            "warn",
            "host_stop_requested_transition",
            {
                "disconnect_like": bool(disconnect_like),
                "connection": snapshot,
            },
        )
        _emit_action_dump("host_stop_requested_transition")
    _RUNTIME_DIAG["last_stop_requested"] = bool(current)


def _stop_reason_from_request():
    """Resolve stop reason for StopRequested transitions."""
    if (
        bool(_RUNTIME_DIAG.get("host_stop_transition_seen", False))
        and bool(_RUNTIME_DIAG.get("host_stop_disconnect_suspected", False))
        and (not bool(_ABORT_CACHE.get("value", False)))
    ):
        return "disconnect_suspected"
    return "stop_requested"


def _append_diag_line(record):
    """Write one JSON-line diagnostic record to disk."""
    if not bool(_DIAG_LOG_STATE.get("enabled", False)):
        return
    path = _safe_str(_DIAG_LOG_STATE.get("path", "")).strip()
    if not path:
        return
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False, default=_json_default))
            handle.write("\n")
    except Exception:
        # Diagnostic logging must never interrupt mapping.
        pass


def _clear_diag_log_file(path):
    """Clear diagnostic log file so each script start has fresh records."""
    full = _safe_str(path).strip()
    if not full:
        return
    try:
        folder = os.path.dirname(full)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(full, "w", encoding="utf-8") as handle:
            handle.write("")
    except Exception:
        pass


def _configure_diag_log(path, session_id):
    """Configure persistent diagnostic log output for this run."""
    _DIAG_LOG_STATE["enabled"] = bool(ENABLE_PERSISTENT_DIAG_LOG)
    _DIAG_LOG_STATE["path"] = _safe_str(path).strip()
    _DIAG_LOG_STATE["session_id"] = _safe_str(session_id).strip()
    _DIAG_LOG_STATE["sequence"] = 0
    if not bool(_DIAG_LOG_STATE.get("enabled", False)):
        return
    if not _safe_str(_DIAG_LOG_STATE.get("path", "")).strip():
        _DIAG_LOG_STATE["enabled"] = False
        return
    _clear_diag_log_file(_safe_str(_DIAG_LOG_STATE.get("path", "")))
    header = {
        "time_utc": _utc_now_iso(),
        "level": "info",
        "message": "diag_log_configured",
        "sequence": 0,
        "session_id": _safe_str(_DIAG_LOG_STATE.get("session_id", "")),
        "context": {"path": _safe_str(_DIAG_LOG_STATE.get("path", ""))},
    }
    _append_diag_line(header)


def _action_state_snapshot(throttle_state=None, include_open_ids=True):
    """Capture queue/cooldown state for diagnostics around API actions."""
    snapshot = {
        "global_cooldown_active": False,
        "use_item_queue_active": False,
        "move_queue_active": False,
        "throttle_backoff": 0,
        "no_response_streak": 0,
        "open_gump_count": 0,
        "open_gump_ids": [],
    }
    try:
        snapshot["global_cooldown_active"] = bool(API.IsGlobalCooldownActive())
    except Exception:
        pass
    try:
        snapshot["use_item_queue_active"] = bool(API.IsProcessingUseItemQueue())
    except Exception:
        pass
    try:
        snapshot["move_queue_active"] = bool(API.IsProcessingMoveQueue())
    except Exception:
        pass
    if isinstance(throttle_state, dict):
        snapshot["throttle_backoff"] = _safe_int(throttle_state.get("backoff", 0), 0)
        snapshot["no_response_streak"] = _safe_int(throttle_state.get("no_response_streak", 0), 0)
    if include_open_ids:
        ids = _open_ids()
        snapshot["open_gump_ids"] = ids
        snapshot["open_gump_count"] = len(ids)
    else:
        snapshot["open_gump_ids"] = []
        snapshot["open_gump_count"] = 0
    return snapshot


def _connection_health_snapshot():
    """Capture best-effort connection health details for diagnostics."""
    _scan_journal_disconnect_markers()
    data = {
        "player_exists": False,
        "player_serial": 0,
        "player_name": "",
        "player_hits": None,
        "player_hits_max": None,
        "player_is_dead": None,
        "profile_server": "",
        "profile_character": "",
        "stop_requested_flag": False,
        "abort_flag": False,
        "event_registered": bool(_CONNECTION_DIAG.get("events_registered", False)),
        "last_event": _safe_str(_CONNECTION_DIAG.get("last_event", "")),
        "last_event_utc": _safe_str(_CONNECTION_DIAG.get("last_event_utc", "")),
        "connected_event_count": _safe_int(_CONNECTION_DIAG.get("connected_event_count", 0), 0),
        "disconnected_event_count": _safe_int(_CONNECTION_DIAG.get("disconnected_event_count", 0), 0),
        "journal_last_text": _safe_str(_RUNTIME_DIAG.get("journal_last_text", "")),
        "journal_last_match": _safe_str(_RUNTIME_DIAG.get("journal_last_match", "")),
        "journal_match_count": _safe_int(_RUNTIME_DIAG.get("journal_match_count", 0), 0),
    }
    try:
        player = getattr(API, "Player", None)
    except Exception:
        player = None
    if player is not None:
        data["player_exists"] = True
        try:
            data["player_serial"] = _safe_int(getattr(player, "Serial", 0), 0)
        except Exception:
            pass
        try:
            data["player_name"] = _safe_str(getattr(player, "Name", ""))
        except Exception:
            pass
        try:
            data["player_hits"] = _safe_opt_int(getattr(player, "Hits", None))
            data["player_hits_max"] = _safe_opt_int(getattr(player, "HitsMax", None))
        except Exception:
            pass
        try:
            data["player_is_dead"] = bool(getattr(player, "IsDead", False))
        except Exception:
            pass
    try:
        profile = getattr(API, "Profile", None)
    except Exception:
        profile = None
    if profile is not None:
        try:
            data["profile_server"] = _safe_str(getattr(profile, "ServerName", ""))
            data["profile_character"] = _safe_str(getattr(profile, "CharacterName", ""))
        except Exception:
            pass
    try:
        data["stop_requested_flag"] = bool(getattr(API, "StopRequested", False))
    except Exception:
        data["stop_requested_flag"] = False
    data["abort_flag"] = bool(_ABORT_CACHE.get("value", False))
    return data


def _on_connected_event(*args):
    """Record server connected event from API.Events."""
    _CONNECTION_DIAG["last_event"] = "connected"
    _CONNECTION_DIAG["last_event_utc"] = _utc_now_iso()
    _CONNECTION_DIAG["connected_event_count"] = _safe_int(_CONNECTION_DIAG.get("connected_event_count", 0), 0) + 1
    _diag("info", "connection_event_connected", {"args_count": len(args), "connection": _connection_health_snapshot()})


def _on_disconnected_event(*args):
    """Record server disconnected event from API.Events."""
    _CONNECTION_DIAG["last_event"] = "disconnected"
    _CONNECTION_DIAG["last_event_utc"] = _utc_now_iso()
    _CONNECTION_DIAG["disconnected_event_count"] = _safe_int(_CONNECTION_DIAG.get("disconnected_event_count", 0), 0) + 1
    _diag("error", "connection_event_disconnected", {"args_count": len(args), "connection": _connection_health_snapshot()})


def _register_connection_event_hooks():
    """Attach connection event hooks once per script run."""
    if bool(_CONNECTION_DIAG.get("events_registered", False)):
        return
    try:
        events = getattr(API, "Events", None)
        if events is None:
            _CONNECTION_DIAG["event_hook_error"] = "events_missing"
            return
        if hasattr(events, "OnConnected"):
            events.OnConnected(_on_connected_event)
        if hasattr(events, "OnDisconnected"):
            events.OnDisconnected(_on_disconnected_event)
        _CONNECTION_DIAG["events_registered"] = True
        _diag("info", "connection_event_hooks_registered", {"connection": _connection_health_snapshot()})
    except Exception as ex:
        _CONNECTION_DIAG["event_hook_error"] = _safe_str(ex)
        _diag("warn", "connection_event_hooks_failed", {"error": _safe_str(ex)})


def _diag(level, message, context=None):
    """Append structured diagnostic record."""
    _DIAG_LOG_STATE["sequence"] = _safe_int(_DIAG_LOG_STATE.get("sequence", 0), 0) + 1
    record = {
        "time_utc": _utc_now_iso(),
        "sequence": _safe_int(_DIAG_LOG_STATE.get("sequence", 0), 0),
        "session_id": _safe_str(_DIAG_LOG_STATE.get("session_id", "")),
        "level": _safe_str(level),
        "message": _safe_str(message),
        "context": context if isinstance(context, dict) else {},
    }
    _record_action(record.get("message", ""), record.get("level", ""), record.get("context", {}))
    RUN_DIAGNOSTICS.append(record)
    _append_diag_line(record)


def _abort_flag_set():
    """Read optional persistent abort flag."""
    now = time.time()
    if (now - float(_ABORT_CACHE.get("last_check", 0.0))) < float(ABORT_POLL_S):
        return bool(_ABORT_CACHE.get("value", False))
    raw = "0"
    try:
        raw = API.GetPersistentVar(ABORT_FLAG_KEY, "0", API.PersistentVar.Char)
    except Exception:
        raw = "0"
    value = _safe_str(raw).strip().lower() in ("1", "true", "yes", "stop")
    _ABORT_CACHE["last_check"] = now
    _ABORT_CACHE["value"] = bool(value)
    return bool(value)


def _stop_requested():
    """Return true when script should stop."""
    _maybe_log_stop_requested_transition()
    try:
        if bool(getattr(API, "StopRequested", False)):
            return True
    except Exception:
        pass
    return _abort_flag_set()


def _has_target_cursor():
    """Return true when the server target cursor is active."""
    try:
        return bool(API.HasTarget())
    except Exception:
        return False


def _cancel_target_cursor():
    """Attempt to cancel target cursor safely."""
    try:
        API.CancelTarget()
    except Exception:
        return False
    _pump(0.05)
    return not _has_target_cursor()


def _wait_for_target_cursor(timeout_s):
    """Wait briefly for a server target cursor to appear."""
    try:
        return bool(API.WaitForTarget("any", float(timeout_s)))
    except Exception:
        return False


def _cancel_target_prompt(journal_prompt_detected=False):
    """Cancel target prompt, including journal-only prompts without active cursor."""
    # For journal-driven prompts we still send CancelTarget because some shards
    # require this even when HasTarget() is false at polling time.
    try:
        API.CancelTarget()
    except Exception:
        return False

    _pump(0.05)

    if bool(journal_prompt_detected):
        _wait_for_target_cursor(float(TARGET_PROMPT_CANCEL_WAIT_S))
        try:
            API.CancelTarget()
        except Exception:
            pass
        _pump(0.05)

    return not _has_target_cursor()


def _pump(seconds):
    """Pause while processing callbacks."""
    remain = max(0.0, float(seconds or 0.0))
    while remain > 0.0:
        if _stop_requested():
            return
        step = min(0.10, remain)
        try:
            API.ProcessCallbacks()
        except Exception:
            pass
        try:
            API.Pause(step)
        except Exception:
            pass
        remain -= step


def _default_config():
    """Return default persisted config."""
    return {
        "last_root_target_serial": 0,
        "last_export_folder": "",
        "last_shard_profile": "",
        "last_character_name": "",
        "manual_server_name": "",
    }


def _load_config():
    """Load persisted config."""
    cfg = _default_config()
    raw = ""
    try:
        raw = API.GetPersistentVar(PERSIST_KEY, "", API.PersistentVar.Char)
    except Exception:
        raw = ""
    text = _safe_str(raw).strip()
    if not text:
        return cfg
    try:
        loaded = json.loads(text)
    except Exception:
        _diag("warn", "config_parse_failed")
        return cfg
    if not isinstance(loaded, dict):
        return cfg
    for key in cfg.keys():
        if key in loaded:
            cfg[key] = loaded.get(key)
    cfg["last_root_target_serial"] = _safe_int(cfg.get("last_root_target_serial", 0), 0)
    cfg["last_export_folder"] = _safe_str(cfg.get("last_export_folder", "")).strip()
    cfg["manual_server_name"] = _safe_str(cfg.get("manual_server_name", "")).strip()
    return cfg


def _save_config(config):
    """Save persisted config."""
    payload = _default_config()
    if isinstance(config, dict):
        payload.update(config)
    payload["last_root_target_serial"] = _safe_int(payload.get("last_root_target_serial", 0), 0)
    payload["last_export_folder"] = _safe_str(payload.get("last_export_folder", "")).strip()
    payload["manual_server_name"] = _safe_str(payload.get("manual_server_name", "")).strip()
    try:
        API.SavePersistentVar(PERSIST_KEY, json.dumps(payload, sort_keys=True), API.PersistentVar.Char)
    except Exception:
        _diag("warn", "config_save_failed")


def _load_persistent_json(key, default_obj):
    """Load a JSON object from persistent vars."""
    raw = ""
    try:
        raw = API.GetPersistentVar(_safe_str(key), "", API.PersistentVar.Char)
    except Exception:
        raw = ""
    text = _safe_str(raw).strip()
    if not text:
        return copy.deepcopy(default_obj)
    try:
        loaded = json.loads(text)
    except Exception:
        return copy.deepcopy(default_obj)
    if not isinstance(loaded, dict):
        return copy.deepcopy(default_obj)
    return loaded


def _save_persistent_json(key, payload):
    """Save a JSON object to persistent vars."""
    try:
        API.SavePersistentVar(_safe_str(key), json.dumps(payload or {}, sort_keys=True), API.PersistentVar.Char)
        return True
    except Exception:
        return False


def _default_resume_state():
    """Return default resume metadata payload."""
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "session_id": "",
        "status": "",
        "checkpoint_json_path": "",
        "checkpoint_txt_path": "",
        "checkpoint_items_pipe_path": "",
        "checkpoint_materials_pipe_path": "",
        "diagnostic_log_path": "",
        "final_json_path": "",
        "final_txt_path": "",
        "final_items_pipe_path": "",
        "final_materials_pipe_path": "",
        "root_target_serial": 0,
        "profile": {"server_name": "", "character_name": ""},
        "updated_at_utc": "",
    }


def _load_resume_state():
    """Load active resume metadata."""
    state = _default_resume_state()
    loaded = _load_persistent_json(RESUME_KEY, state)
    if not isinstance(loaded, dict):
        return state
    state.update(loaded)
    state["session_id"] = _safe_str(state.get("session_id", "")).strip()
    state["status"] = _safe_str(state.get("status", "")).strip().lower()
    state["checkpoint_json_path"] = _safe_str(state.get("checkpoint_json_path", "")).strip()
    state["checkpoint_txt_path"] = _safe_str(state.get("checkpoint_txt_path", "")).strip()
    state["checkpoint_items_pipe_path"] = _safe_str(state.get("checkpoint_items_pipe_path", "")).strip()
    state["checkpoint_materials_pipe_path"] = _safe_str(state.get("checkpoint_materials_pipe_path", "")).strip()
    state["diagnostic_log_path"] = _safe_str(state.get("diagnostic_log_path", "")).strip()
    state["final_json_path"] = _safe_str(state.get("final_json_path", "")).strip()
    state["final_txt_path"] = _safe_str(state.get("final_txt_path", "")).strip()
    state["final_items_pipe_path"] = _safe_str(state.get("final_items_pipe_path", "")).strip()
    state["final_materials_pipe_path"] = _safe_str(state.get("final_materials_pipe_path", "")).strip()
    state["root_target_serial"] = _safe_int(state.get("root_target_serial", 0), 0)
    if not isinstance(state.get("profile"), dict):
        state["profile"] = {"server_name": "", "character_name": ""}
    state["profile"]["server_name"] = _safe_str(state["profile"].get("server_name", "")).strip()
    state["profile"]["character_name"] = _safe_str(state["profile"].get("character_name", "")).strip()
    state["updated_at_utc"] = _safe_str(state.get("updated_at_utc", "")).strip()
    return state


def _save_resume_state(state):
    """Persist resume metadata."""
    payload = _default_resume_state()
    if isinstance(state, dict):
        payload.update(state)
    payload["schema_version"] = CHECKPOINT_SCHEMA_VERSION
    payload["session_id"] = _safe_str(payload.get("session_id", "")).strip()
    payload["status"] = _safe_str(payload.get("status", "")).strip().lower()
    payload["checkpoint_json_path"] = _safe_str(payload.get("checkpoint_json_path", "")).strip()
    payload["checkpoint_txt_path"] = _safe_str(payload.get("checkpoint_txt_path", "")).strip()
    payload["checkpoint_items_pipe_path"] = _safe_str(payload.get("checkpoint_items_pipe_path", "")).strip()
    payload["checkpoint_materials_pipe_path"] = _safe_str(payload.get("checkpoint_materials_pipe_path", "")).strip()
    payload["diagnostic_log_path"] = _safe_str(payload.get("diagnostic_log_path", "")).strip()
    payload["final_json_path"] = _safe_str(payload.get("final_json_path", "")).strip()
    payload["final_txt_path"] = _safe_str(payload.get("final_txt_path", "")).strip()
    payload["final_items_pipe_path"] = _safe_str(payload.get("final_items_pipe_path", "")).strip()
    payload["final_materials_pipe_path"] = _safe_str(payload.get("final_materials_pipe_path", "")).strip()
    payload["root_target_serial"] = _safe_int(payload.get("root_target_serial", 0), 0)
    if not isinstance(payload.get("profile"), dict):
        payload["profile"] = {"server_name": "", "character_name": ""}
    payload["profile"] = {
        "server_name": _safe_str(payload["profile"].get("server_name", "")).strip(),
        "character_name": _safe_str(payload["profile"].get("character_name", "")).strip(),
    }
    payload["updated_at_utc"] = _utc_now_iso()
    return _save_persistent_json(RESUME_KEY, payload)


def _clear_resume_state():
    """Clear active resume metadata."""
    try:
        API.SavePersistentVar(RESUME_KEY, "", API.PersistentVar.Char)
    except Exception:
        pass


def _delete_file_if_exists(path):
    """Delete a file path if present and return status token."""
    full = _safe_str(path).strip()
    if not full:
        return "empty"
    try:
        if not os.path.exists(full):
            return "missing"
    except Exception:
        return "missing"
    try:
        os.remove(full)
        return "deleted"
    except Exception as ex:
        _diag("warn", "cache_clear_file_delete_failed", {"path": full, "error": _safe_str(ex)})
        return "failed"


def _clear_cached_resume_artifacts(resume_state):
    """Delete cached checkpoint artifacts referenced by resume metadata."""
    state = resume_state if isinstance(resume_state, dict) else {}
    unique_paths = []
    seen = set()
    for key in (
        "checkpoint_json_path",
        "checkpoint_txt_path",
        "checkpoint_items_pipe_path",
        "checkpoint_materials_pipe_path",
        "diagnostic_log_path",
    ):
        path = _safe_str(state.get(key, "")).strip()
        if not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)

    deleted = 0
    missing = 0
    failed = 0
    for path in unique_paths:
        status = _delete_file_if_exists(path)
        if status == "deleted":
            deleted += 1
        elif status in ("missing", "empty"):
            missing += 1
        elif status == "failed":
            failed += 1

    _diag(
        "info" if failed == 0 else "warn",
        "cache_clear_summary",
        {"deleted": int(deleted), "missing": int(missing), "failed": int(failed), "path_count": len(unique_paths)},
    )
    return {"deleted": int(deleted), "missing": int(missing), "failed": int(failed), "path_count": len(unique_paths)}


def _read_json_file(path):
    """Read JSON file and return object or None."""
    full = _safe_str(path).strip()
    if not full:
        return None
    if not os.path.exists(full):
        return None
    try:
        with io.open(full, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write_json_atomic(path, payload):
    """Write JSON atomically so checkpoints stay valid."""
    full = _safe_str(path).strip()
    if not full:
        return False
    folder = os.path.dirname(full)
    tmp_path = full + ".tmp"
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        os.replace(tmp_path, full)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def _write_text_atomic(path, text):
    """Write text atomically for live TXT checkpoints."""
    full = _safe_str(path).strip()
    if not full:
        return False
    folder = os.path.dirname(full)
    tmp_path = full + ".tmp"
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(_safe_str(text))
        os.replace(tmp_path, full)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def normalize_packet_gump_text(raw_text):
    """Normalize PacketGumpText for hashing/parsing."""
    text = _safe_str(raw_text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def scan_top_level_blocks(normalized_text):
    """Scan top-level brace blocks with string awareness."""
    blocks = []
    errors = []
    text = _safe_str(normalized_text)
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for idx in range(len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if ch == "}":
            if depth <= 0:
                errors.append({"stage": "block_scan", "message": "unexpected_close", "offset": idx})
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                end = idx + 1
                blocks.append(
                    {
                        "index": len(blocks),
                        "start": start,
                        "end": end,
                        "inner_start": start + 1,
                        "inner_end": idx,
                        "raw": text[start:end],
                        "text": text[start + 1:idx],
                    }
                )
                start = -1

    if depth != 0:
        errors.append({"stage": "block_scan", "message": "unbalanced_braces", "offset": len(text)})
    return blocks, errors


def _decode_string_token(raw_token):
    """Decode quoted string token value."""
    raw = _safe_str(raw_token)
    body = raw[1:-1] if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"' else raw
    body = body.replace(r"\\", "\\").replace(r"\"", '"')
    body = body.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
    return body


def _parse_numeric_token(raw_token, token_type):
    """Parse HEX/INT token into integer."""
    raw = _safe_str(raw_token).strip()
    if token_type == "INT":
        return int(raw)
    sign = 1
    text = raw
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    value = int(text, 16) if text.lower().startswith("0x") else int(text)
    return sign * value


def tokenize_block(block_info, token_start_index):
    """Tokenize one block using required ordered token regexes."""
    tokens = []
    errors = []
    text = _safe_str(block_info.get("text", ""))
    base_offset = _safe_int(block_info.get("inner_start", 0), 0)
    block_index = _safe_int(block_info.get("index", 0), 0)

    pos = 0
    token_index = int(token_start_index)
    while pos < len(text):
        matched = False
        for token_name, token_regex in TOKEN_RULES:
            m = token_regex.match(text, pos)
            if not m:
                continue
            raw = m.group(0)
            local_start = pos
            local_end = m.end()
            value = raw
            parse_error = None
            if token_name == "STRING":
                value = _decode_string_token(raw)
            elif token_name in ("INT", "HEX"):
                try:
                    value = _parse_numeric_token(raw, token_name)
                except Exception:
                    value = raw
                    parse_error = "numeric_parse_failed"
            elif token_name == "UNKNOWN":
                parse_error = "unknown_token"

            token = {
                "index": token_index,
                "block_index": block_index,
                "type": token_name,
                "raw": raw,
                "value": value,
                "start": base_offset + local_start,
                "end": base_offset + local_end,
                "offset_start": local_start,
                "offset_end": local_end,
            }
            tokens.append(token)

            if parse_error:
                errors.append(
                    {
                        "stage": "tokenize",
                        "message": parse_error,
                        "offset": token["start"],
                        "block_index": block_index,
                        "token_index": token_index,
                        "raw": raw,
                    }
                )
            pos = local_end
            token_index += 1
            matched = True
            break

        if not matched:
            errors.append({"stage": "tokenize", "message": "no_progress", "offset": base_offset + pos})
            pos += 1

    return tokens, errors


def build_node(block_info, block_tokens, node_index):
    """Build AST node with command and positional args."""
    errors = []
    filtered = [t for t in block_tokens if _safe_str(t.get("type", "")) != "WS"]
    if not filtered:
        return None, errors

    command_token = None
    command_pos = -1
    for idx, tok in enumerate(filtered):
        if _safe_str(tok.get("type", "")) == "IDENT":
            command_token = tok
            command_pos = idx
            break
    if command_token is None:
        errors.append({"stage": "node_build", "message": "command_missing", "offset": block_info.get("inner_start", 0)})
        return None, errors

    if command_pos != 0:
        errors.append({"stage": "node_build", "message": "command_not_first", "offset": command_token.get("start", 0)})

    args = []
    arg_token_indices = []
    for tok in filtered[command_pos + 1:]:
        tok_type = _safe_str(tok.get("type", ""))
        if tok_type in ("COMMA", "LBRACK", "RBRACK", "LPAREN", "RPAREN"):
            continue
        args.append(tok.get("value"))
        arg_token_indices.append(_safe_int(tok.get("index", 0), 0))

    return (
        {
            "index": int(node_index),
            "block_index": _safe_int(block_info.get("index", 0), 0),
            "command": _safe_str(command_token.get("value", "")).strip().lower(),
            "command_raw": _safe_str(command_token.get("raw", "")),
            "command_token_index": _safe_int(command_token.get("index", 0), 0),
            "args": args,
            "arg_token_indices": arg_token_indices,
            "span": {"start": _safe_int(block_info.get("start", 0), 0), "end": _safe_int(block_info.get("end", 0), 0)},
            "projection": {"known": False, "fields": {}},
        },
        errors,
    )


def _project_node(node):
    """Project node args into named fields via registry."""
    command = _safe_str(node.get("command", "")).strip().lower()
    entry = COMMAND_REGISTRY.get(command)
    if not entry:
        return {"known": False, "fields": {}}, False
    fields = {}
    arg_names = entry.get("arg_names", [])
    args = node.get("args", [])
    for idx in range(len(arg_names)):
        if idx < len(args):
            fields[arg_names[idx]] = args[idx]
    return {"known": True, "fields": fields}, True


def _extract_node_artifacts(node):
    """Extract button candidates and text references from node."""
    buttons = []
    texts = []
    command = _safe_str(node.get("command", "")).strip().lower()
    entry = COMMAND_REGISTRY.get(command)
    projection = node.get("projection", {}) if isinstance(node.get("projection", {}), dict) else {}
    fields = projection.get("fields", {}) if isinstance(projection.get("fields", {}), dict) else {}

    if entry:
        button_field = _safe_str(entry.get("button_field", "")).strip()
        if button_field:
            x = _safe_opt_int(fields.get(_safe_str(entry.get("x_field", "x"))))
            y = _safe_opt_int(fields.get(_safe_str(entry.get("y_field", "y"))))

            # PacketGumpText layouts appear with two observed argument orders:
            # 1) ... button_id, type, param
            # 2) ... type, param, button_id
            # Pick the second shape when the first implies impossible page/reply values.
            primary_bid = _safe_opt_int(fields.get("button_id"))
            primary_type = _safe_opt_int(fields.get("type"))
            primary_param = _safe_opt_int(fields.get("param"))

            bid = primary_bid
            button_type = primary_type
            button_param = primary_param

            alt_bid = _safe_opt_int(fields.get("param"))
            alt_type = _safe_opt_int(fields.get("button_id"))
            alt_param = _safe_opt_int(fields.get("type"))

            if command in ("button", "buttontileart") and alt_bid is not None:
                use_alt = False
                if (primary_bid is None or int(primary_bid) < 0) and int(alt_bid) > 0:
                    use_alt = True
                elif primary_bid == 0 and primary_type in (1, 2) and alt_type == 0:
                    use_alt = True
                elif (
                    primary_type == 0
                    and primary_bid in (0, 1)
                    and primary_param is not None
                    and int(primary_param) > 5
                    and int(alt_bid) > 1
                ):
                    use_alt = True
                if use_alt:
                    bid = alt_bid
                    button_type = alt_type
                    button_param = alt_param

            if bid is not None:
                keep_button = int(bid) > 0
                if not keep_button and int(bid) == 0 and button_type is not None and int(button_type) == 0:
                    keep_button = True
                if keep_button:
                    buttons.append(
                        {
                            "button_id": int(bid),
                            "button_type": _safe_opt_int(button_type),
                            "button_param": _safe_opt_int(button_param),
                            "layout_page": _safe_opt_int(node.get("layout_page")),
                            "x": x,
                            "y": y,
                            "source_command": command,
                            "node_index": _safe_int(node.get("index", 0), 0),
                            "arg_count": len(node.get("args", [])),
                        }
                    )

        text_idx_field = _safe_str(entry.get("text_index_field", "")).strip()
        if text_idx_field:
            idx = _safe_opt_int(fields.get(text_idx_field))
            if idx is not None:
                texts.append({"source_command": command, "node_index": _safe_int(node.get("index", 0), 0), "arg_index": None, "reference_type": "index", "text_index": int(idx), "inline_text": "", "x": _safe_opt_int(fields.get(_safe_str(entry.get("x_field", "x")))), "y": _safe_opt_int(fields.get(_safe_str(entry.get("y_field", "y"))))})

        text_value_field = _safe_str(entry.get("text_value_field", "")).strip()
        if text_value_field:
            value = fields.get(text_value_field)
            if isinstance(value, int):
                texts.append({"source_command": command, "node_index": _safe_int(node.get("index", 0), 0), "arg_index": None, "reference_type": "index", "text_index": int(value), "inline_text": "", "x": _safe_opt_int(fields.get(_safe_str(entry.get("x_field", "x")))), "y": _safe_opt_int(fields.get(_safe_str(entry.get("y_field", "y"))))})
            elif isinstance(value, str) and _safe_str(value).strip():
                texts.append({"source_command": command, "node_index": _safe_int(node.get("index", 0), 0), "arg_index": None, "reference_type": "inline", "text_index": None, "inline_text": _safe_str(value).strip(), "x": _safe_opt_int(fields.get(_safe_str(entry.get("x_field", "x")))), "y": _safe_opt_int(fields.get(_safe_str(entry.get("y_field", "y"))))})

    for arg_index, value in enumerate(node.get("args", [])):
        if isinstance(value, str) and _safe_str(value).strip():
            texts.append({"source_command": command, "node_index": _safe_int(node.get("index", 0), 0), "arg_index": int(arg_index), "reference_type": "inline", "text_index": None, "inline_text": _safe_str(value).strip(), "x": None, "y": None})

    return buttons, texts


def _dedupe_buttons(buttons):
    """Dedupe and sort button candidates."""
    seen = set()
    out = []
    for item in buttons:
        if not isinstance(item, dict):
            continue
        bid = _safe_int(item.get("button_id", -1), -1)
        button_type = _safe_opt_int(item.get("button_type"))
        button_param = _safe_opt_int(item.get("button_param"))
        layout_page = _safe_opt_int(item.get("layout_page"))
        if bid < 0:
            continue
        if bid == 0 and button_type != 0:
            continue
        key = (
            bid,
            _safe_opt_int(item.get("x")),
            _safe_opt_int(item.get("y")),
            _safe_str(item.get("source_command", "")).strip().lower(),
            _safe_int(item.get("node_index", -1), -1),
            button_type,
            button_param,
            layout_page,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "button_id": bid,
                "button_type": key[5],
                "button_param": key[6],
                "layout_page": key[7],
                "x": key[1],
                "y": key[2],
                "source_command": key[3],
                "node_index": key[4],
                "arg_count": _safe_int(item.get("arg_count", 0), 0),
            }
        )
    out.sort(
        key=lambda x: (
            _safe_int(x.get("button_id", 0), 0),
            -1 if x.get("button_type") is None else _safe_int(x.get("button_type"), 0),
            -1 if x.get("layout_page") is None else _safe_int(x.get("layout_page"), 0),
            -1 if x.get("x") is None else _safe_int(x.get("x"), 0),
            -1 if x.get("y") is None else _safe_int(x.get("y"), 0),
            _safe_str(x.get("source_command", "")),
        )
    )
    return out


def _dedupe_text_refs(text_refs):
    """Dedupe and sort text references."""
    seen = set()
    out = []
    for item in text_refs:
        if not isinstance(item, dict):
            continue
        key = (_safe_str(item.get("source_command", "")).strip().lower(), _safe_int(item.get("node_index", -1), -1), item.get("arg_index"), _safe_str(item.get("reference_type", "")).strip().lower(), item.get("text_index"), _safe_str(item.get("inline_text", "")), _safe_opt_int(item.get("x")), _safe_opt_int(item.get("y")))
        if key in seen:
            continue
        seen.add(key)
        out.append({"source_command": key[0], "node_index": key[1], "arg_index": key[2], "reference_type": key[3], "text_index": key[4], "inline_text": key[5], "x": key[6], "y": key[7]})
    out.sort(key=lambda x: (_safe_int(x.get("node_index", -1), -1), _safe_str(x.get("source_command", "")), _safe_str(x.get("reference_type", "")), -1 if x.get("text_index") is None else _safe_int(x.get("text_index"), 0), _safe_str(x.get("inline_text", ""))))
    return out


def _parse_line_token_value(raw_token):
    """Parse one line token into numeric or decoded string value."""
    text = _safe_str(raw_token)
    if not text:
        return ""
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return _decode_string_token(text)
    if re.fullmatch(RE_HEX, text):
        return _parse_numeric_token(text, "HEX")
    if re.fullmatch(RE_INT, text):
        return _parse_numeric_token(text, "INT")
    return text


def _build_line_nodes(normalized_text):
    """Build parser nodes from line-based PacketGumpText layouts."""
    nodes = []
    errors = []
    line_offset = 0
    for line_number, raw_line in enumerate(_safe_str(normalized_text).split("\n"), 1):
        source_line = _safe_str(raw_line).replace("\x00", "")
        stripped = source_line.strip()
        if not stripped:
            line_offset += len(source_line) + 1
            continue

        token_strings = LINE_TOKEN_RULE.findall(stripped)
        if not token_strings:
            line_offset += len(source_line) + 1
            continue

        command_raw = _safe_str(token_strings[0]).strip()
        command = command_raw.lower()
        if not command:
            line_offset += len(source_line) + 1
            continue

        args = []
        for tok in token_strings[1:]:
            try:
                args.append(_parse_line_token_value(tok))
            except Exception:
                args.append(_safe_str(tok))

        node = {
            "index": len(nodes),
            "block_index": -1,
            "command": command,
            "command_raw": command_raw,
            "command_token_index": -1,
            "args": args,
            "arg_token_indices": [],
            "span": {"start": int(line_offset), "end": int(line_offset + len(source_line))},
            "projection": {"known": False, "fields": {}},
            "line_number": int(line_number),
        }
        projection, _ = _project_node(node)
        node["projection"] = projection
        nodes.append(node)
        line_offset += len(source_line) + 1
    return nodes, errors


def _annotate_nodes_with_layout_pages(nodes):
    """Annotate nodes with current layout page inferred from `page` commands."""
    page_number = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        command = _safe_str(node.get("command", "")).strip().lower()
        args = node.get("args", []) or []
        if command == "page":
            next_page = _safe_opt_int(args[0] if args else None)
            if next_page is not None and int(next_page) >= 0:
                page_number = int(next_page)
        node["layout_page"] = int(page_number)
    return nodes


def parse_packet_gump_text(raw_packet_text):
    """Parse PacketGumpText and return required parser schema payload."""
    raw = _safe_str(raw_packet_text)
    normalized = normalize_packet_gump_text(raw)
    layout_hash = _sha1_text(normalized)

    blocks, block_errors = scan_top_level_blocks(normalized)
    tokens = []
    nodes = []
    errors = list(block_errors)
    unknown_map = {}
    button_candidates = []
    text_references = []

    token_index = 0
    tokens_by_block = {}
    for block in blocks:
        block_tokens, token_errors = tokenize_block(block, token_index)
        token_index += len(block_tokens)
        tokens.extend(block_tokens)
        errors.extend(token_errors)
        tokens_by_block[_safe_int(block.get("index", 0), 0)] = block_tokens

    if blocks:
        node_index = 0
        for block in blocks:
            bi = _safe_int(block.get("index", 0), 0)
            node, node_errors = build_node(block, tokens_by_block.get(bi, []), node_index)
            errors.extend(node_errors)
            if node is None:
                continue
            projection, _ = _project_node(node)
            node["projection"] = projection
            nodes.append(node)
            node_index += 1
    else:
        line_nodes, line_errors = _build_line_nodes(normalized)
        errors.extend(line_errors)
        nodes.extend(line_nodes)

    nodes = _annotate_nodes_with_layout_pages(nodes)

    for node in nodes:
        command = _safe_str(node.get("command", "")).strip().lower()
        if command not in COMMAND_REGISTRY:
            if command not in unknown_map:
                unknown_map[command] = {"command": command, "count": 0, "node_indices": []}
            unknown_map[command]["count"] += 1
            unknown_map[command]["node_indices"].append(_safe_int(node.get("index", 0), 0))

        node_buttons, node_texts = _extract_node_artifacts(node)
        button_candidates.extend(node_buttons)
        text_references.extend(node_texts)

    unknown_commands = []
    for key in sorted(unknown_map.keys()):
        entry = unknown_map[key]
        unknown_commands.append({"command": _safe_str(entry.get("command", "")), "count": _safe_int(entry.get("count", 0), 0), "node_indices": sorted([_safe_int(x, 0) for x in (entry.get("node_indices", []) or [])])})

    button_candidates = _dedupe_buttons(button_candidates)
    text_references = _dedupe_text_refs(text_references)
    errors.sort(key=lambda x: (_safe_int(x.get("offset", 0), 0), _safe_str(x.get("stage", "")), _safe_str(x.get("message", ""))))

    stats = {
        "raw_length": len(raw),
        "normalized_length": len(normalized),
        "block_count": len(blocks),
        "token_count": len(tokens),
        "node_count": len(nodes),
        "text_reference_count": len(text_references),
        "button_candidate_count": len(button_candidates),
        "unknown_command_count": len(unknown_commands),
        "error_count": len(errors),
    }

    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "raw": raw,
        "normalized": normalized,
        "layout_hash": layout_hash,
        "blocks": blocks,
        "tokens": tokens,
        "nodes": nodes,
        "text_references": text_references,
        "button_candidates": button_candidates,
        "unknown_commands": unknown_commands,
        "errors": errors,
        "stats": stats,
    }

def _profile_context():
    """Return profile context dictionary."""
    server_name = "unknown_shard"
    character_name = "unknown_character"
    try:
        profile = getattr(API, "Profile", None)
        if profile:
            server_name = _safe_str(getattr(profile, "ServerName", "")).strip() or server_name
            character_name = _safe_str(getattr(profile, "CharacterName", "")).strip() or character_name
    except Exception:
        pass
    try:
        if character_name == "unknown_character":
            player = getattr(API, "Player", None)
            if player:
                character_name = _safe_str(getattr(player, "Name", "")).strip() or character_name
    except Exception:
        pass
    return {"server_name": server_name, "character_name": character_name}


def _prompt_server_name(default_server_name):
    """Show startup gump for manual server name entry."""
    default_value = _safe_str(default_server_name).strip()
    if not default_value or default_value.lower() == "unknown_shard":
        default_value = ""

    state = {"done": False, "accepted": False, "value": default_value, "clear_cache": False}
    panel = None
    server_box = None
    clear_cache_checkbox = None

    try:
        panel = API.CreateGump(True, True, False)
        panel.SetRect(130, 130, 420, 196)

        bg = API.CreateGumpColorBox(0.80, "#1B1B1B")
        bg.SetRect(0, 0, 420, 196)
        panel.Add(bg)

        title = API.CreateGumpTTFLabel("Gump Mapper Setup", 16, "#FFFFFF", "alagard", "center", 420)
        title.SetPos(0, 16)
        panel.Add(title)

        prompt = API.CreateGumpTTFLabel("Server name for this mapping run:", 12, "#FFFFFF", "alagard", "left", 380)
        prompt.SetPos(20, 52)
        panel.Add(prompt)

        server_box = API.CreateGumpTextBox(default_value, 380, 22, False)
        server_box.SetPos(20, 74)
        panel.Add(server_box)

        clear_cache_checkbox = API.CreateGumpCheckbox("Clear cached checkpoint data before start", 0, False)
        clear_cache_checkbox.SetPos(20, 103)
        panel.Add(clear_cache_checkbox)

        ok_btn = API.CreateSimpleButton("Start Mapping", 110, 22)
        ok_btn.SetPos(220, 140)
        panel.Add(ok_btn)

        cancel_btn = API.CreateSimpleButton("Cancel", 80, 22)
        cancel_btn.SetPos(340, 140)
        panel.Add(cancel_btn)

        def _accept():
            text = _safe_str(getattr(server_box, "Text", "")).strip()
            if not text:
                _sys("Server name is required to continue.", WARN_HUE)
                return
            clear_cache_selected = False
            try:
                clear_cache_selected = bool(getattr(clear_cache_checkbox, "IsChecked", False))
            except Exception:
                clear_cache_selected = False
            if not clear_cache_selected:
                try:
                    clear_cache_selected = bool(clear_cache_checkbox.GetIsChecked())
                except Exception:
                    clear_cache_selected = False
            state["value"] = text
            state["accepted"] = True
            state["clear_cache"] = bool(clear_cache_selected)
            state["done"] = True
            try:
                panel.Dispose()
            except Exception:
                pass

        def _cancel():
            state["done"] = True
            state["accepted"] = False
            try:
                panel.Dispose()
            except Exception:
                pass

        def _closed():
            state["done"] = True

        API.AddControlOnClick(ok_btn, _accept)
        API.AddControlOnClick(cancel_btn, _cancel)
        API.AddControlOnDisposed(panel, _closed)
        API.AddGump(panel)
    except Exception as ex:
        _diag("warn", "server_prompt_gump_failed", {"error": _safe_str(ex)})
        return default_value, False, False

    while not bool(state.get("done", False)):
        if _stop_requested():
            break
        _pump(0.10)

    try:
        if panel is not None:
            panel.Dispose()
    except Exception:
        pass
    return (
        _safe_str(state.get("value", "")).strip(),
        bool(state.get("accepted", False)),
        bool(state.get("clear_cache", False)),
    )


def _resolve_profile_server_name(config, profile):
    """Resolve run server name via startup gump input."""
    if not isinstance(profile, dict):
        profile = {"server_name": "unknown_shard", "character_name": "unknown_character"}

    default_server = _safe_str(config.get("manual_server_name", "") if isinstance(config, dict) else "").strip()
    if not default_server:
        default_server = _safe_str(profile.get("server_name", "")).strip()
    if (not default_server) or default_server.lower() == "unknown_shard":
        default_server = _safe_str(config.get("last_shard_profile", "") if isinstance(config, dict) else "").strip()

    _sys("Enter server name for this mapping run.", DEFAULT_HUE)
    entered_server, accepted, clear_cache_requested = _prompt_server_name(default_server)
    if not accepted:
        return None, False

    resolved = copy.deepcopy(profile)
    resolved["server_name"] = _safe_str(entered_server).strip()
    if isinstance(config, dict):
        config["manual_server_name"] = _safe_str(entered_server).strip()
    _diag(
        "info",
        "server_name_selected",
        {"server_name": _safe_str(entered_server), "clear_cache_requested": bool(clear_cache_requested)},
    )
    return resolved, bool(clear_cache_requested)


def _reset_progress_gump_state():
    """Clear in-memory control references for the progress gump."""
    _PROGRESS_GUMP["panel"] = None
    _PROGRESS_GUMP["server_label"] = None
    _PROGRESS_GUMP["root_label"] = None
    _PROGRESS_GUMP["status_label"] = None
    _PROGRESS_GUMP["counts_label"] = None
    _PROGRESS_GUMP["queue_label"] = None
    _PROGRESS_GUMP["stop_label"] = None
    _PROGRESS_GUMP["last_render_key"] = ""


def _set_ui_text(control, text):
    """Set control text using API-supported methods."""
    if control is None:
        return
    value = _safe_str(text)
    try:
        control.SetText(value)
        return
    except Exception:
        pass
    try:
        control.Text = value
    except Exception:
        pass


def _on_progress_gump_disposed():
    """Track progress gump closure."""
    _reset_progress_gump_state()


def _dispose_progress_gump():
    """Dispose progress gump safely when stopping or restarting."""
    panel = _PROGRESS_GUMP.get("panel")
    if panel is None:
        _reset_progress_gump_state()
        return
    try:
        panel.Dispose()
    except Exception:
        pass
    _reset_progress_gump_state()


def _render_progress_gump(
    status_text,
    stop_reason,
    gump_count,
    edge_count,
    button_attempts,
    interaction_count,
    queue_length,
):
    """Render live traversal progress into the startup progress gump."""
    if _PROGRESS_GUMP.get("panel") is None:
        return

    gumps = max(0, _safe_int(gump_count, 0))
    edges = max(0, _safe_int(edge_count, 0))
    attempts = max(0, _safe_int(button_attempts, 0))
    interactions = max(0, _safe_int(interaction_count, 0))
    queued = max(0, _safe_int(queue_length, 0))
    status_value = _safe_str(status_text).strip().replace("_", " ") or "mapping"
    stop_value = _safe_str(stop_reason).strip().replace("_", " ") or "running"

    render_key = "{0}|{1}|{2}|{3}|{4}|{5}|{6}".format(
        status_value,
        stop_value,
        gumps,
        edges,
        attempts,
        interactions,
        queued,
    )
    if render_key == _safe_str(_PROGRESS_GUMP.get("last_render_key", "")):
        return
    _PROGRESS_GUMP["last_render_key"] = render_key

    _set_ui_text(_PROGRESS_GUMP.get("status_label"), "Status: {0}".format(status_value))
    _set_ui_text(
        _PROGRESS_GUMP.get("counts_label"),
        "Gumps: {0} (cap {1}) | Edges: {2} (cap {3})".format(
            gumps,
            int(MAX_TOTAL_CAPTURES),
            edges,
            int(MAX_TOTAL_EDGES),
        ),
    )
    _set_ui_text(
        _PROGRESS_GUMP.get("queue_label"),
        "Queue: {0} | Interactions: {1} | Attempts: {2}".format(
            queued,
            interactions,
            attempts,
        ),
    )
    _set_ui_text(_PROGRESS_GUMP.get("stop_label"), "Stop reason: {0}".format(stop_value))


def _update_progress_gump_from_checkpoint(run_state, button_attempts, interaction_keys, queue, stop_reason):
    """Update the live progress gump from checkpoint commit state."""
    if not isinstance(run_state, dict):
        run_state = {}
    gump_count = len(run_state.get("order", []) or [])
    edge_count = len(run_state.get("edges", []) or [])
    interaction_count = len(interaction_keys or [])
    queue_length = len(queue or [])
    _render_progress_gump(
        "mapping",
        stop_reason,
        gump_count,
        edge_count,
        button_attempts,
        interaction_count,
        queue_length,
    )


def _update_progress_gump_from_stats(stats, stop_reason, status_text, queue_length=0):
    """Update the live progress gump from manifest stats."""
    if not isinstance(stats, dict):
        stats = {}
    _render_progress_gump(
        status_text,
        stop_reason,
        _safe_int(stats.get("total_gumps", 0), 0),
        _safe_int(stats.get("total_edges", 0), 0),
        _safe_int(stats.get("button_attempts", 0), 0),
        _safe_int(stats.get("unique_interactions", 0), 0),
        _safe_int(queue_length, 0),
    )


def _create_progress_gump(profile, root_serial, session_id):
    """Create startup progress gump that updates live during traversal."""
    _dispose_progress_gump()
    _diag(
        "trace",
        "progress_gump_create_start",
        {
            "session_id": _safe_str(session_id),
            "root_target_serial": _safe_int(root_serial, 0),
            "profile": copy.deepcopy(profile) if isinstance(profile, dict) else {},
        },
    )

    if not isinstance(profile, dict):
        profile = {"server_name": "unknown_shard", "character_name": "unknown_character"}

    try:
        panel = API.CreateGump(True, True, True)
        panel.SetRect(int(PROGRESS_GUMP_X), int(PROGRESS_GUMP_Y), int(PROGRESS_GUMP_W), int(PROGRESS_GUMP_H))

        bg = API.CreateGumpColorBox(0.80, "#1B1B1B")
        bg.SetRect(0, 0, int(PROGRESS_GUMP_W), int(PROGRESS_GUMP_H))
        panel.Add(bg)

        title = API.CreateGumpTTFLabel("Gump Mapper Live Progress", 15, "#FFFFFF", "alagard", "center", int(PROGRESS_GUMP_W))
        title.SetPos(0, 12)
        panel.Add(title)

        server_label = API.CreateGumpTTFLabel(
            "Server: {0} | Character: {1}".format(
                _safe_str(profile.get("server_name", "unknown_shard")),
                _safe_str(profile.get("character_name", "unknown_character")),
            ),
            11,
            "#FFFFFF",
            "alagard",
            "left",
            int(PROGRESS_GUMP_W - 32),
        )
        server_label.SetPos(16, 40)
        panel.Add(server_label)

        root_label = API.CreateGumpTTFLabel(
            "Root: 0x{0:08X} | Session: {1}".format(
                _safe_int(root_serial, 0),
                _safe_str(session_id),
            ),
            11,
            "#DDDDDD",
            "alagard",
            "left",
            int(PROGRESS_GUMP_W - 32),
        )
        root_label.SetPos(16, 58)
        panel.Add(root_label)

        status_label = API.CreateGumpTTFLabel("Status: initializing", 11, "#D9F4FF", "alagard", "left", int(PROGRESS_GUMP_W - 32))
        status_label.SetPos(16, 86)
        panel.Add(status_label)

        counts_label = API.CreateGumpTTFLabel("", 11, "#FFFFFF", "alagard", "left", int(PROGRESS_GUMP_W - 32))
        counts_label.SetPos(16, 106)
        panel.Add(counts_label)

        queue_label = API.CreateGumpTTFLabel("", 11, "#FFFFFF", "alagard", "left", int(PROGRESS_GUMP_W - 32))
        queue_label.SetPos(16, 126)
        panel.Add(queue_label)

        stop_label = API.CreateGumpTTFLabel("", 11, "#FFFFFF", "alagard", "left", int(PROGRESS_GUMP_W - 32))
        stop_label.SetPos(16, 146)
        panel.Add(stop_label)

        API.AddControlOnDisposed(panel, _on_progress_gump_disposed)
        API.AddGump(panel)

        _PROGRESS_GUMP["panel"] = panel
        _PROGRESS_GUMP["server_label"] = server_label
        _PROGRESS_GUMP["root_label"] = root_label
        _PROGRESS_GUMP["status_label"] = status_label
        _PROGRESS_GUMP["counts_label"] = counts_label
        _PROGRESS_GUMP["queue_label"] = queue_label
        _PROGRESS_GUMP["stop_label"] = stop_label
        _PROGRESS_GUMP["last_render_key"] = ""

        _update_progress_gump_from_stats({}, "", "waiting_for_traversal_start")
        _diag(
            "info",
            "progress_gump_create_success",
            {"session_id": _safe_str(session_id)},
        )
        return True
    except Exception as ex:
        _diag("warn", "progress_gump_create_failed", {"error": _safe_str(ex)})
        _dispose_progress_gump()
        return False


def _resolve_root_path():
    """Resolve base path for export defaults."""
    script_path = _safe_str(getattr(API, "ScriptPath", "")).strip()
    if script_path:
        base = script_path if os.path.isdir(script_path) else os.path.dirname(script_path)
    else:
        try:
            base = os.path.dirname(__file__)
        except Exception:
            base = os.getcwd()

    base = os.path.normpath(base)
    tail = _safe_str(os.path.basename(base)).lower()
    if tail in ("resources", "utilities", "skills"):
        base = os.path.dirname(base)
    if _safe_str(os.path.basename(base)).lower() == "scripts":
        base = os.path.dirname(base)
    return os.path.normpath(base)


def _export_dir(config):
    """Resolve export directory from config or defaults."""
    if isinstance(config, dict):
        persisted = _safe_str(config.get("last_export_folder", "")).strip()
        if persisted:
            return os.path.normpath(persisted)
    return os.path.join(_resolve_root_path(), DEFAULT_EXPORT_SUBDIR)


def _request_target(timeout_s):
    """Request target and return serial or 0."""
    if _stop_requested():
        return 0
    try:
        return _safe_int(API.RequestTarget(float(timeout_s)), 0)
    except Exception:
        return 0


def _select_root_serial(config):
    """Ask for root target and allow saved serial reuse."""
    saved = _safe_int(config.get("last_root_target_serial", 0) if isinstance(config, dict) else 0, 0)
    if saved > 0:
        _sys("Target root object. Cancel to reuse 0x{0:08X}.".format(saved), DEFAULT_HUE)
    else:
        _sys("Target root object now.", DEFAULT_HUE)
    selected = _request_target(ROOT_TARGET_TIMEOUT_S)
    if selected > 0:
        return selected
    if saved > 0:
        _sys("Using saved root serial 0x{0:08X}.".format(saved), DEFAULT_HUE)
        return saved
    return 0


def _gump_id(gump_obj):
    """Extract gump ID from runtime object."""
    if gump_obj is None:
        return 0
    if isinstance(gump_obj, int):
        return int(gump_obj)
    for attr in ("ID", "Id", "GumpID", "GumpId", "ServerSerial", "Serial"):
        try:
            value = getattr(gump_obj, attr, None)
        except Exception:
            value = None
        if value is None:
            continue
        parsed = _safe_int(value, 0)
        if parsed != 0:
            return int(parsed)
    return 0


def _all_gumps():
    """Return list of open gump objects."""
    try:
        return list(API.GetAllGumps() or [])
    except Exception:
        return []


def _gump_contents(gump_id):
    """Return visible gump text for ID."""
    gid = _safe_int(gump_id, 0)
    try:
        if gid > 0:
            return _safe_str(API.GetGumpContents(int(gid)) or "")
        return _safe_str(API.GetGumpContents() or "")
    except Exception:
        return ""


def _runtime_current_page(gump_obj):
    """Best-effort runtime current page number for an open gump."""
    if gump_obj is None:
        return None
    roots = [gump_obj]
    try:
        inner = getattr(gump_obj, "Gump", None)
        if inner is not None:
            roots.append(inner)
    except Exception:
        pass
    for root in roots:
        for page_attr in ("CurrentPage", "Page", "PageNumber"):
            try:
                page_value = _safe_opt_int(getattr(root, page_attr, None))
            except Exception:
                page_value = None
            if page_value is not None and int(page_value) >= 0:
                return int(page_value)
    return None


def _ui_button_candidates(gump_obj):
    """Best-effort runtime UI button extraction."""
    out = []
    if gump_obj is None:
        return out

    roots = [gump_obj]
    try:
        inner = getattr(gump_obj, "Gump", None)
        if inner is not None:
            roots.append(inner)
    except Exception:
        pass

    for root in roots:
        current_page = None
        for page_attr in ("CurrentPage", "Page", "PageNumber"):
            try:
                page_value = _safe_opt_int(getattr(root, page_attr, None))
            except Exception:
                page_value = None
            if page_value is not None and int(page_value) >= 0:
                current_page = int(page_value)
                break

        for attr in ("Buttons", "Children", "Controls", "ControlCollection", "Items"):
            try:
                controls = list(getattr(root, attr, None) or [])
            except Exception:
                controls = []
            for ctrl in controls:
                control_page = None
                is_visible = True
                try:
                    visible_attr = getattr(ctrl, "Visible", None)
                except Exception:
                    visible_attr = None
                if visible_attr is not None:
                    try:
                        is_visible = bool(visible_attr)
                    except Exception:
                        is_visible = True
                try:
                    if hasattr(ctrl, "IsVisible"):
                        visible_call = ctrl.IsVisible()
                        if visible_call is not None:
                            is_visible = bool(visible_call)
                except Exception:
                    pass
                if not bool(is_visible):
                    continue

                try:
                    enabled_attr = getattr(ctrl, "Enabled", None)
                except Exception:
                    enabled_attr = None
                if enabled_attr is not None:
                    try:
                        if not bool(enabled_attr):
                            continue
                    except Exception:
                        pass

                if current_page is not None and int(current_page) > 0:
                    for page_attr in ("Page", "PageNumber", "GumpPage"):
                        try:
                            page_value = _safe_opt_int(getattr(ctrl, page_attr, None))
                        except Exception:
                            page_value = None
                        if page_value is not None and int(page_value) >= 0:
                            control_page = int(page_value)
                            break
                    if control_page is not None and int(control_page) not in (0, int(current_page)):
                        continue

                try:
                    bid = _safe_opt_int(getattr(ctrl, "ButtonID", None))
                except Exception:
                    bid = None
                if bid is None or int(bid) <= 0:
                    continue
                x = None
                y = None
                try:
                    if hasattr(ctrl, "GetX"):
                        x = _safe_opt_int(ctrl.GetX())
                except Exception:
                    pass
                try:
                    if hasattr(ctrl, "GetY"):
                        y = _safe_opt_int(ctrl.GetY())
                except Exception:
                    pass
                if x is None:
                    x = _safe_opt_int(getattr(ctrl, "X", None))
                if y is None:
                    y = _safe_opt_int(getattr(ctrl, "Y", None))
                button_type = _safe_opt_int(getattr(ctrl, "Type", None))
                button_param = _safe_opt_int(getattr(ctrl, "Param", None))
                out.append(
                    {
                        "button_id": int(bid),
                        "button_type": button_type,
                        "button_param": button_param,
                        "layout_page": control_page if control_page is not None else current_page,
                        "x": x,
                        "y": y,
                        "source_command": "ui_button",
                        "node_index": -1,
                        "arg_count": 0,
                    }
                )
    return _dedupe_buttons(out)


def _split_visible_lines(raw_text):
    """Split GetGumpContents text into non-empty lines."""
    text = _safe_str(raw_text).replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        if "|" in line:
            for chunk in line.split("|"):
                part = _safe_str(chunk).strip()
                if part:
                    lines.append(part)
        else:
            part = _safe_str(line).strip()
            if part:
                lines.append(part)
    return lines


def _resolve_text_label(text_ref, visible_lines):
    """Resolve text label for a parser text reference."""
    if not isinstance(text_ref, dict):
        return ""
    if _safe_str(text_ref.get("reference_type", "")).lower() == "inline":
        return _safe_str(text_ref.get("inline_text", "")).strip()
    idx = _safe_opt_int(text_ref.get("text_index"))
    if idx is None:
        return ""
    if idx >= 0 and idx < len(visible_lines):
        return _safe_str(visible_lines[idx]).strip()
    return "text_index:{0}".format(int(idx))


def _infer_button_labels(buttons, text_refs, visible_lines):
    """Attach inferred label text to each button candidate."""
    anchors = []
    for ref in text_refs:
        label = _resolve_text_label(ref, visible_lines)
        label = _safe_str(label).strip()
        if not label:
            continue
        anchors.append({"text": label, "x": _safe_opt_int(ref.get("x")), "y": _safe_opt_int(ref.get("y"))})

    for btn in buttons:
        bx = _safe_opt_int(btn.get("x"))
        by = _safe_opt_int(btn.get("y"))
        best = ""
        best_score = None
        for anchor in anchors:
            text = _safe_str(anchor.get("text", "")).strip()
            if not text:
                continue
            ax = _safe_opt_int(anchor.get("x"))
            ay = _safe_opt_int(anchor.get("y"))
            if bx is None or by is None or ax is None or ay is None:
                score = 10 ** 9
            else:
                score = abs(int(bx) - int(ax)) + abs(int(by) - int(ay))
            if best_score is None or score < best_score:
                best_score = score
                best = text
        btn["inferred_label"] = best
    return buttons


def capture_gump_snapshot(gump_obj):
    """Capture one gump snapshot with parser output."""
    gid = _gump_id(gump_obj)
    runtime = gump_obj
    if gid > 0:
        try:
            fetched = API.GetGump(int(gid))
            if fetched is not None:
                runtime = fetched
        except Exception:
            pass

    try:
        packet_raw = _safe_str(getattr(runtime, "PacketGumpText", "") or "")
    except Exception:
        packet_raw = ""

    parser = parse_packet_gump_text(packet_raw)
    visible_raw = _gump_contents(gid)
    visible_lines = _split_visible_lines(visible_raw)
    buttons = _dedupe_buttons((parser.get("button_candidates", []) if isinstance(parser, dict) else []) + _ui_button_candidates(runtime))
    text_refs = parser.get("text_references", []) if isinstance(parser, dict) else []
    buttons = _infer_button_labels(buttons, text_refs, visible_lines)
    runtime_page = _runtime_current_page(runtime)
    page_buttons = []
    for button in buttons:
        if not isinstance(button, dict):
            continue
        if _safe_int(button.get("button_type", -1), -1) == 0:
            page_buttons.append(copy.deepcopy(button))

    text_hash = _sha1_text(" ".join(visible_lines).lower())
    layout_hash = _safe_str(parser.get("layout_hash", ""))

    return {
        "captured_at_utc": _utc_now_iso(),
        "gump_id": int(gid),
        "layout_hash": layout_hash,
        "text_hash": text_hash,
        "state_key": "{0}|{1}".format(layout_hash, text_hash),
        "title": _safe_str(visible_lines[0] if visible_lines else ""),
        "packet_gump_text_raw": packet_raw,
        "visible_text_raw": visible_raw,
        "visible_text_lines": visible_lines,
        "runtime_page": runtime_page,
        "buttons_discovered": buttons,
        "page_buttons_discovered": page_buttons,
        "button_ids": sorted(list(set([_safe_int(x.get("button_id", 0), 0) for x in buttons if isinstance(x, dict) and _safe_int(x.get("button_id", 0), 0) > 0]))),
        "parser_output": parser,
        "traversal_diagnostics": [],
    }


def _capture_open_gumps():
    """Capture snapshots for all open gumps."""
    snapshots = []
    for gump in sorted(_all_gumps(), key=lambda g: (_gump_id(g), _safe_str(type(g)))):
        if _stop_requested():
            break
        try:
            snapshots.append(capture_gump_snapshot(gump))
        except Exception as ex:
            _diag("warn", "capture_open_gump_failed", {"error": _safe_str(ex)})
    return snapshots


def _open_ids():
    """Return sorted open gump IDs."""
    return sorted(list(set([_gump_id(g) for g in _all_gumps() if _gump_id(g) != 0])))


def _action_busy():
    """Return true when cooldown/queues are active."""
    busy = False
    try:
        if bool(API.IsGlobalCooldownActive()):
            busy = True
    except Exception:
        pass
    try:
        if bool(API.IsProcessingUseItemQueue()):
            busy = True
    except Exception:
        pass
    try:
        if bool(API.IsProcessingMoveQueue()):
            busy = True
    except Exception:
        pass
    return bool(busy)


def _wait_action_slot(throttle_state, timeout_s=QUEUE_WAIT_S):
    """Wait until safe to send use/click action."""
    start = time.time()
    _diag(
        "trace",
        "action_slot_wait_start",
        {
            "timeout_s": float(timeout_s),
            "throttle_pause_s": _throttle_pause_seconds(throttle_state),
            "state": _action_state_snapshot(throttle_state, include_open_ids=False),
        },
    )
    loops = 0
    while True:
        if _stop_requested():
            _diag("warn", "action_slot_wait_stop_requested", {"connection": _connection_health_snapshot()})
            return False
        if not _action_busy():
            _diag(
                "trace",
                "action_slot_wait_ready",
                {
                    "elapsed_s": round(time.time() - start, 3),
                    "loops": int(loops),
                    "state": _action_state_snapshot(throttle_state, include_open_ids=False),
                },
            )
            return True
        if (time.time() - start) >= float(timeout_s):
            _diag(
                "warn",
                "action_slot_wait_timeout",
                {
                    "elapsed_s": round(time.time() - start, 3),
                    "loops": int(loops),
                    "state": _action_state_snapshot(throttle_state, include_open_ids=False),
                    "connection": _connection_health_snapshot(),
                },
            )
            return False
        loops += 1
        _pump(min(0.25, max(0.05, _throttle_pause_seconds(throttle_state))))


def _throttle_pause_seconds(throttle_state):
    """Return computed backoff pause seconds."""
    level = max(0, min(int(MAX_BACKOFF), _safe_int(throttle_state.get("backoff", 0), 0)))
    delay = float(BASE_PAUSE_S) * (2.0 ** level)
    if delay > float(MAX_BACKOFF_S):
        delay = float(MAX_BACKOFF_S)
    if delay < 0.2:
        delay = 0.2
    return float(delay)


def _throttle_pause(throttle_state):
    """Apply post-action throttle pause."""
    _pump(_throttle_pause_seconds(throttle_state))


def _throttle_update(throttle_state, outcome):
    """Update backoff from click outcome."""
    key = _safe_str(outcome).strip().lower()
    level = _safe_int(throttle_state.get("backoff", 0), 0)
    if key in ("no_response", "same_layout", "reply_failed", "path_reopen_failed"):
        level = min(level + 1, int(MAX_BACKOFF))
    else:
        level = max(level - 1, 0)
    throttle_state["backoff"] = level
    if key in ("no_response", "reply_failed", "path_reopen_failed"):
        throttle_state["no_response_streak"] = _safe_int(throttle_state.get("no_response_streak", 0), 0) + 1
    else:
        throttle_state["no_response_streak"] = 0


def _open_root(root_serial, throttle_state, recovery_state=None, expected_state_key=""):
    """Use root serial and capture initial gumps with recovery guardrails."""
    serial = _safe_int(root_serial, 0)
    if serial <= 0:
        _diag("warn", "open_root_invalid_serial", {"root_serial": int(serial)})
        return None, []
    if isinstance(recovery_state, dict):
        now = time.time()
        last = float(recovery_state.get("last_root_use_time", 0.0) or 0.0)
        min_gap = float(MIN_ROOT_REOPEN_GAP_S)
        if last > 0.0 and (now - last) < min_gap:
            wait_s = max(0.0, min_gap - (now - last))
            _diag(
                "trace",
                "open_root_rate_limit_wait",
                {"wait_s": round(wait_s, 3), "min_gap_s": float(min_gap)},
            )
            _pump(wait_s)

    pre_ids = set(_open_ids())
    _diag(
        "trace",
        "open_root_start",
        {
            "root_serial": int(serial),
            "pre_open_ids": sorted(list(pre_ids)),
            "state": _action_state_snapshot(throttle_state, include_open_ids=False),
        },
    )
    if not _wait_action_slot(throttle_state, QUEUE_WAIT_S):
        _diag("warn", "open_root_no_action_slot", {"root_serial": int(serial)})
        return None, []

    _scan_journal_disconnect_markers()
    target_cursor_open = _has_target_cursor()
    journal_target_prompt, journal_last_text = _journal_indicates_target_prompt()
    if target_cursor_open or journal_target_prompt:
        cancelled = bool(_cancel_target_prompt(journal_prompt_detected=journal_target_prompt))
        still_open = _has_target_cursor()
        _diag(
            "warn",
            "open_root_target_prompt_precheck",
            {
                "root_serial": int(serial),
                "target_cursor_open": bool(target_cursor_open),
                "journal_target_prompt": bool(journal_target_prompt),
                "journal_last_text": _safe_str(journal_last_text),
                "target_cancelled": bool(cancelled),
                "target_still_open": bool(still_open),
            },
        )
        if still_open:
            return None, []
    try:
        if isinstance(recovery_state, dict):
            recovery_state["last_root_use_time"] = float(time.time())
        API.UseObject(int(serial))
        _diag("trace", "open_root_use_object_sent", {"root_serial": int(serial)})
    except Exception as ex:
        _diag("error", "open_root_use_object_failed", {"root_serial": int(serial), "error": _safe_str(ex)})
        return None, []
    _throttle_pause(throttle_state)

    start = time.time()
    wait_hit = False
    snapshots = []
    while (time.time() - start) < float(ROOT_WAIT_S):
        if _stop_requested():
            _diag("warn", "open_root_stop_requested")
            return None, []
        try:
            if bool(API.WaitForGump(0, POST_POLL_S)):
                wait_hit = True
                snapshots = _capture_open_gumps()
                if snapshots:
                    break
        except Exception:
            pass
        _pump(POST_POLL_S)

    if not snapshots:
        _pump(ROOT_SETTLE_S)
        snapshots = _capture_open_gumps()
    _diag(
        "trace",
        "open_root_capture_result",
        {
            "wait_hit": bool(wait_hit),
            "elapsed_s": round(time.time() - start, 3),
            "snapshot_count": len(snapshots),
            "post_open_ids": _open_ids(),
        },
    )
    if not snapshots:
        _mark_no_gump_interaction()
        if isinstance(recovery_state, dict):
            recovery_state["consecutive_root_open_failures"] = _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0) + 1
            recovery_state["consecutive_no_open_gumps"] = _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0) + 1
        _diag(
            "warn",
            "open_root_no_snapshots",
            {
                "connection": _connection_health_snapshot(),
                "recovery": {
                    "consecutive_root_open_failures": _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0) if isinstance(recovery_state, dict) else 0,
                    "consecutive_no_open_gumps": _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0) if isinstance(recovery_state, dict) else 0,
                },
            },
        )
        _maybe_log_connection_suspect(
            "open_root_no_snapshots",
            {"root_serial": int(serial), "expected_state_key": _safe_str(expected_state_key)},
        )
        return None, []

    _mark_good_gump_interaction()
    if isinstance(recovery_state, dict):
        recovery_state["consecutive_root_open_failures"] = 0
        recovery_state["consecutive_no_open_gumps"] = 0

    preferred = [s for s in snapshots if _safe_int(s.get("gump_id", 0), 0) not in pre_ids and _safe_int(s.get("gump_id", 0), 0) != 0]
    source = preferred if preferred else snapshots
    source = sorted(source, key=lambda s: (_safe_int(s.get("gump_id", 0), 0), _safe_str(s.get("layout_hash", "")), _safe_str(s.get("text_hash", ""))))

    selected = None
    expected = _safe_str(expected_state_key).strip()
    if expected:
        for candidate in source:
            if _safe_str(candidate.get("state_key", "")) == expected:
                selected = candidate
                break
        if selected is None:
            for candidate in snapshots:
                if _safe_str(candidate.get("state_key", "")) == expected:
                    selected = candidate
                    break
    if selected is None:
        selected = source[0] if source else None

    _diag(
        "trace",
        "open_root_selected",
        {
            "selected_state_key": _safe_str(selected.get("state_key", "")) if isinstance(selected, dict) else "",
            "selected_gump_id": _safe_int(selected.get("gump_id", 0), 0) if isinstance(selected, dict) else 0,
            "snapshot_count": len(snapshots),
            "expected_state_key": _safe_str(expected_state_key),
        },
    )
    return selected, snapshots


def _reply(button_id, gump_id):
    """Send ReplyGump for button/gump pair."""
    bid = _safe_int(button_id, 0)
    gid = _safe_int(gump_id, 0)
    if bid <= 0:
        _diag("warn", "reply_invalid_button", {"button_id": int(bid), "gump_id": int(gid)})
        return False
    _diag("trace", "reply_send", {"button_id": int(bid), "gump_id": int(gid)})
    try:
        if gid > 0:
            API.ReplyGump(int(bid), int(gid))
        else:
            API.ReplyGump(int(bid))
        _diag("trace", "reply_sent", {"button_id": int(bid), "gump_id": int(gid)})
        return True
    except Exception as ex:
        _diag("error", "reply_failed", {"button_id": int(bid), "gump_id": int(gid), "error": _safe_str(ex)})
        return False

def _click_and_capture(parent_snapshot, button_id, throttle_state):
    """Click a button and capture resulting gumps."""
    result = {
        "result_kind": "",
        "button_id": _safe_int(button_id, 0),
        "pre_state_keys": [],
        "pre_ids": [],
        "post_snapshots": [],
        "notes": "",
    }
    _diag(
        "trace",
        "click_capture_start",
        {
            "button_id": int(result["button_id"]),
            "parent_state_key": _safe_str(parent_snapshot.get("state_key", "")) if isinstance(parent_snapshot, dict) else "",
            "parent_gump_id": _safe_int(parent_snapshot.get("gump_id", 0), 0) if isinstance(parent_snapshot, dict) else 0,
            "state": _action_state_snapshot(throttle_state, include_open_ids=True),
        },
    )
    if _stop_requested():
        result["result_kind"] = "stop_requested"
        _diag("warn", "click_capture_stop_requested", {"button_id": int(result["button_id"])})
        return result
    if not _wait_action_slot(throttle_state, QUEUE_WAIT_S):
        result["result_kind"] = "no_action_slot"
        _diag("warn", "click_capture_no_action_slot", {"button_id": int(result["button_id"])})
        return result

    pre = _capture_open_gumps()
    pre_keys = [_safe_str(s.get("state_key", "")) for s in pre]
    pre_ids = sorted(list(set([_safe_int(s.get("gump_id", 0), 0) for s in pre])))
    result["pre_state_keys"] = pre_keys
    result["pre_ids"] = pre_ids
    _diag(
        "trace",
        "click_capture_pre_snapshot",
        {
            "button_id": int(result["button_id"]),
            "pre_ids": pre_ids,
            "pre_state_count": len(pre_keys),
        },
    )

    if not _reply(button_id, _safe_int(parent_snapshot.get("gump_id", 0), 0)):
        result["result_kind"] = "reply_failed"
        result["notes"] = "reply_failed"
        _diag("warn", "click_capture_reply_failed", {"button_id": int(result["button_id"])})
        return result

    _throttle_pause(throttle_state)

    start = time.time()
    while (time.time() - start) < float(CLICK_WAIT_S):
        if _stop_requested():
            _diag("warn", "click_capture_stop_during_wait", {"button_id": int(result["button_id"])})
            break
        if _open_ids() != pre_ids:
            _pump(0.1)
            break
        _pump(POST_POLL_S)

    post = _capture_open_gumps()
    result["post_snapshots"] = post
    if not post:
        _scan_journal_disconnect_markers()
        target_cursor_open = _has_target_cursor()
        journal_target_prompt, journal_last_text = _journal_indicates_target_prompt()
        saw_target_cursor = bool(target_cursor_open)
        if (not saw_target_cursor) and bool(journal_target_prompt):
            saw_target_cursor = bool(_wait_for_target_cursor(float(TARGET_PROMPT_CANCEL_WAIT_S))) or bool(_has_target_cursor())
        if saw_target_cursor:
            canceled = False
            if bool(AUTO_CANCEL_TARGET_CURSOR):
                canceled = bool(_cancel_target_prompt(journal_prompt_detected=journal_target_prompt))
            result["result_kind"] = "opened_target_cursor"
            result["notes"] = "target_cursor_opened" if target_cursor_open else "journal_target_prompt_detected"
            _diag(
                "warn",
                "click_capture_target_cursor_opened",
                {
                    "button_id": int(result["button_id"]),
                    "pre_ids": pre_ids,
                    "journal_last_text": _safe_str(journal_last_text),
                    "journal_target_prompt": bool(journal_target_prompt),
                    "auto_cancel_enabled": bool(AUTO_CANCEL_TARGET_CURSOR),
                    "target_cursor_open": bool(target_cursor_open),
                    "target_cursor_confirmed": bool(saw_target_cursor),
                    "target_cancelled": bool(canceled),
                    "connection": _connection_health_snapshot(),
                },
            )
            _mark_good_gump_interaction()
            return result

        result["result_kind"] = "no_response"
        _mark_no_gump_interaction()
        _diag(
            "warn",
            "click_capture_no_response",
            {
                "button_id": int(result["button_id"]),
                "pre_ids": pre_ids,
                "post_ids": _open_ids(),
                "state": _action_state_snapshot(throttle_state, include_open_ids=False),
                "connection": _connection_health_snapshot(),
            },
        )
        _maybe_log_connection_suspect(
            "click_capture_no_response",
            {"button_id": int(result["button_id"]), "parent_gump_id": _safe_int(parent_snapshot.get("gump_id", 0), 0) if isinstance(parent_snapshot, dict) else 0},
        )
        return result

    _mark_good_gump_interaction()
    pre_set = set(pre_keys)
    saw_new = False
    for snap in post:
        if _safe_str(snap.get("state_key", "")) not in pre_set:
            saw_new = True
            break
    result["result_kind"] = "opened_or_changed" if saw_new else "same_layout"
    _diag(
        "trace",
        "click_capture_result",
        {
            "button_id": int(result["button_id"]),
            "result_kind": _safe_str(result.get("result_kind", "")),
            "post_count": len(post),
            "post_ids": sorted(list(set([_safe_int(s.get("gump_id", 0), 0) for s in post]))),
            "state": _action_state_snapshot(throttle_state, include_open_ids=False),
        },
    )
    return result


def _select_children(post_snapshots, pre_state_keys, parent_state_key):
    """Select child snapshots for edge creation."""
    if not post_snapshots:
        return []

    pre = set(pre_state_keys or [])
    new_children = [s for s in post_snapshots if _safe_str(s.get("state_key", "")) not in pre]
    if new_children:
        chosen = new_children
    else:
        non_parent = [s for s in post_snapshots if _safe_str(s.get("state_key", "")) != _safe_str(parent_state_key)]
        chosen = non_parent if non_parent else [post_snapshots[0]]

    chosen = sorted(chosen, key=lambda s: (_safe_str(s.get("state_key", "")), _safe_int(s.get("gump_id", 0), 0)))
    return chosen[: int(MAX_CHILDREN_PER_CLICK)]


def _select_snapshot_by_state(snapshots, expected_state_key):
    """Pick snapshot matching expected state key, else first sorted."""
    expected = _safe_str(expected_state_key)
    if expected:
        for snap in snapshots:
            if _safe_str(snap.get("state_key", "")) == expected:
                return snap
    ordered = sorted(snapshots, key=lambda s: (_safe_str(s.get("state_key", "")), _safe_int(s.get("gump_id", 0), 0)))
    return ordered[0] if ordered else None


def _button_entries(capture_record, button_id):
    """Return all discovered button entries for a capture/button pair."""
    if not isinstance(capture_record, dict):
        return []
    bid = _safe_int(button_id, 0)
    if bid < 0:
        return []
    out = []
    for btn in capture_record.get("buttons_discovered", []) or []:
        if not isinstance(btn, dict):
            continue
        if _safe_int(btn.get("button_id", -1), -1) != bid:
            continue
        out.append(btn)
    return out


def _button_has_runtime_entry(capture_record, button_id):
    """Return True when button has runtime UI control backing."""
    for btn in _button_entries(capture_record, button_id):
        if _safe_str(btn.get("source_command", "")).strip().lower() == "ui_button":
            return True
    return False


def _button_has_parser_entry(capture_record, button_id):
    """Return True when button exists in parser layout commands."""
    for btn in _button_entries(capture_record, button_id):
        if _safe_str(btn.get("source_command", "")).strip().lower() != "ui_button":
            return True
    return False


def _button_parser_pages(capture_record, button_id):
    """Return sorted parser layout pages for a given button ID."""
    pages = set()
    for btn in _button_entries(capture_record, button_id):
        if _safe_str(btn.get("source_command", "")).strip().lower() == "ui_button":
            continue
        page = _safe_opt_int(btn.get("layout_page"))
        if page is not None and int(page) >= 0:
            pages.add(int(page))
    return sorted(list(pages))


def _button_is_parser_only(capture_record, button_id):
    """Return True when a button is parser-only and absent from runtime controls."""
    return _button_has_parser_entry(capture_record, button_id) and (not _button_has_runtime_entry(capture_record, button_id))


def _button_is_page_control(capture_record, button_id):
    """Return True when any discovered entry marks this button as page control."""
    for btn in _button_entries(capture_record, button_id):
        button_type = _safe_opt_int(btn.get("button_type"))
        if button_type is not None and int(button_type) == 0:
            return True
    return False


def _button_inferred_label(capture_record, button_id):
    """Return inferred button label for a capture/button pair."""
    if not isinstance(capture_record, dict):
        return ""
    for btn in capture_record.get("buttons_discovered", []) or []:
        if not isinstance(btn, dict):
            continue
        if _safe_int(btn.get("button_id", 0), 0) != _safe_int(button_id, 0):
            continue
        return _safe_str(btn.get("inferred_label", "")).strip()
    return ""


def _button_position(capture_record, button_id):
    """Return (x, y) for a capture/button pair when available."""
    if not isinstance(capture_record, dict):
        return None, None
    bid = _safe_int(button_id, 0)
    for btn in capture_record.get("buttons_discovered", []) or []:
        if not isinstance(btn, dict):
            continue
        if _safe_int(btn.get("button_id", 0), 0) != bid:
            continue
        return _safe_opt_int(btn.get("x")), _safe_opt_int(btn.get("y"))
    return None, None


def _capture_normalized_text(capture_record):
    """Return normalized text for role/skip detection from capture fields."""
    if not isinstance(capture_record, dict):
        return ""
    raw = _safe_str(capture_record.get("visible_text_raw", ""))
    if not raw:
        raw = _safe_str(capture_record.get("title", ""))
    if not raw:
        lines = capture_record.get("visible_text_lines", [])
        if isinstance(lines, list):
            raw = " ".join([_safe_str(x) for x in lines])
    return _normalize_gump_text(raw).lower()


def _blacksmith_menu_button_role(capture_record, button_id):
    """Classify Blacksmith menu button role using stable control anchors."""
    if not isinstance(capture_record, dict):
        return ""
    normalized = _capture_normalized_text(capture_record)
    if "blacksmithing menu" not in normalized:
        return ""

    x, y = _button_position(capture_record, button_id)
    if x is None or y is None:
        return ""

    bid = _safe_int(button_id, 0)

    # Left column category list (includes lower entries like Throwing/Miscellaneous).
    if x <= 40 and y >= 80 and y <= 280:
        return "category"
    # Lower-left material roots observed on Blacksmith menu.
    if x <= 40 and y >= 350 and y <= 395 and bid in (7, 147):
        return "material_root"
    # Right column "details" buttons for row entries.
    if x >= 460 and x <= 520 and y >= 60 and y <= 240:
        return "item_detail"
    # Middle column "make" buttons for row entries.
    if x >= 210 and x <= 250 and y >= 60 and y <= 240:
        return "item_make"
    # Selection-pane page controls are in the upper-right list footer row.
    if x >= 200 and x <= 430 and y >= 250 and y <= 285:
        return "item_page_nav"
    # Lower utility controls (repair/mark/enhance/alter/quest/make last/smelt/exit/cancel).
    if (x <= 40 and y >= 320 and y <= 430) or (x >= 240 and x <= 340 and y >= 330 and y <= 460):
        return "utility"
    if x <= 170 and y >= 430 and y <= 460:
        return "utility"
    # Defensive skip for frequently problematic utility-style IDs.
    if bid in (47, 227):
        return "utility"
    return "ignore"


def _infer_visible_item_page_group(capture_record):
    """Infer fallback item-page group from traversal path when parser page data is absent."""
    if not isinstance(capture_record, dict):
        return 0
    path_buttons = [_safe_int(x, 0) for x in (capture_record.get("path_button_ids", []) or []) if _safe_int(x, 0) > 0]
    if not path_buttons:
        return 0

    # Page transitions should come from explicit page controls, not utility replies.
    # Keep fallback group stable at 0 unless traversal paths carry explicit page state.
    group = 0
    for bid in path_buttons:
        button_id = int(bid)
        if (button_id % 20) == 1:
            group = 0
    return int(group)


def _item_button_page_group(button_id):
    """Return page group for item make/detail buttons, or -1 when not applicable."""
    bid = _safe_int(button_id, 0)
    if bid <= 0:
        return -1
    mod = int(bid % 20)
    if mod == 2:
        return max(0, int((int(bid) - 2) // 200))
    if mod == 3:
        return max(0, int((int(bid) - 3) // 200))
    return -1


def _filter_traversal_button_ids(capture_record, button_ids):
    """Filter traversal buttons to intended Blacksmith actions."""
    if not isinstance(capture_record, dict):
        return button_ids

    normalized = _capture_normalized_text(capture_record)
    if "blacksmithing menu" not in normalized:
        return button_ids

    runtime_page = _safe_opt_int(capture_record.get("runtime_page"))
    filtered = []
    seen = set()
    parser_only_skipped = 0
    page_control_skipped = 0
    runtime_missing_skipped = 0
    parser_page_mismatch_skipped = 0
    for raw in button_ids:
        bid = _safe_int(raw, 0)
        if bid <= 0:
            continue

        if _button_is_parser_only(capture_record, bid):
            parser_only_skipped += 1
            continue
        if _button_is_page_control(capture_record, bid):
            page_control_skipped += 1
            continue
        if not _button_has_runtime_entry(capture_record, bid):
            runtime_missing_skipped += 1
            continue

        role = _blacksmith_menu_button_role(capture_record, bid)
        if role not in ("category", "item_detail", "material_root"):
            continue
        if role == "item_detail":
            parser_pages = _button_parser_pages(capture_record, bid)
            use_parser_page = runtime_page is not None and int(runtime_page) > 0 and bool(parser_pages)
            if use_parser_page:
                if int(runtime_page) not in parser_pages and 0 not in parser_pages:
                    parser_page_mismatch_skipped += 1
                    continue
        if bid in seen:
            continue
        seen.add(bid)
        filtered.append(int(bid))

    if (
        parser_only_skipped > 0
        or page_control_skipped > 0
        or runtime_missing_skipped > 0
        or parser_page_mismatch_skipped > 0
    ):
        _diag(
            "trace",
            "traversal_off_page_buttons_filtered",
            {
                "capture_id": _safe_str(capture_record.get("capture_id", "")),
                "runtime_page": runtime_page,
                "parser_only_skipped": int(parser_only_skipped),
                "page_control_skipped": int(page_control_skipped),
                "runtime_missing_skipped": int(runtime_missing_skipped),
                "parser_page_mismatch_skipped": int(parser_page_mismatch_skipped),
            },
        )

    return sorted(filtered)


def _should_skip_utility_button(capture_record, button_id):
    """Skip known high-risk utility buttons that open target prompts."""
    bid = _safe_int(button_id, 0)
    if bid <= 0:
        return False

    role = _blacksmith_menu_button_role(capture_record, bid)
    if role:
        return role in ("item_make", "ignore", "utility")

    label = _button_inferred_label(capture_record, bid).lower()
    if label:
        for keyword in UTILITY_BUTTON_KEYWORDS:
            if keyword in label:
                return True

    normalized = _capture_normalized_text(capture_record)
    if not normalized:
        return False
    if "blacksmithing menu" not in normalized:
        return False

    # Coordinate-free fallback only when runtime positions are unavailable.
    if (bid % 20) != int(UTILITY_BUTTON_MODULO):
        return False
    if "repair item" in normalized or "enhance item" in normalized or "smelt item" in normalized or "prompt for mark" in normalized or "alter item" in normalized:
        return True
    return False


def _find_open_snapshot_for_capture(capture_record):
    """Return matching open snapshot for capture state/seen IDs, else None."""
    if not isinstance(capture_record, dict):
        return None

    target_state = _safe_str(capture_record.get("state_key", "")).strip()
    seen_ids = sorted(
        list(
            set(
                [
                    _safe_int(x, 0)
                    for x in (capture_record.get("seen_gump_ids", []) or [])
                    if _safe_int(x, 0) > 0
                ]
            )
        )
    )
    open_snaps = _capture_open_gumps()
    if not open_snaps:
        return None

    if target_state:
        for snap in open_snaps:
            if _safe_str(snap.get("state_key", "")) == target_state:
                return snap
        # Safety: avoid reusing a same-ID gump when state differs; this can click
        # hidden/off-page controls from the wrong menu state.
        if seen_ids:
            for snap in open_snaps:
                if _safe_int(snap.get("gump_id", 0), 0) in seen_ids:
                    _diag(
                        "trace",
                        "recovery_reuse_open_snapshot_state_mismatch",
                        {
                            "capture_id": _safe_str(capture_record.get("capture_id", "")),
                            "expected_state_key": _safe_str(target_state),
                            "found_state_key": _safe_str(snap.get("state_key", "")),
                            "gump_id": _safe_int(snap.get("gump_id", 0), 0),
                        },
                    )
                    break
        return None

    if seen_ids:
        for snap in open_snaps:
            if _safe_int(snap.get("gump_id", 0), 0) in seen_ids:
                return snap

    return None


def _open_path(root_serial, path_steps, throttle_state, expected_root_state, recovery_state=None):
    """Re-open root and replay path for recovery."""
    _diag(
        "trace",
        "open_path_start",
        {
            "root_serial": _safe_int(root_serial, 0),
            "path_length": len(path_steps or []),
            "expected_root_state": _safe_str(expected_root_state),
        },
    )
    root_snapshot, _ = _open_root(
        root_serial,
        throttle_state,
        recovery_state=recovery_state,
        expected_state_key=expected_root_state,
    )
    if root_snapshot is None:
        _diag("warn", "open_path_root_open_failed", {"connection": _connection_health_snapshot()})
        _maybe_log_connection_suspect(
            "open_path_root_open_failed",
            {"root_serial": _safe_int(root_serial, 0), "path_length": len(path_steps or [])},
        )
        return None
    if expected_root_state and _safe_str(root_snapshot.get("state_key", "")) != _safe_str(expected_root_state):
        _diag(
            "warn",
            "root_state_changed",
            {
                "expected_root_state": _safe_str(expected_root_state),
                "actual_root_state": _safe_str(root_snapshot.get("state_key", "")),
            },
        )

    current = root_snapshot
    for step_index, step in enumerate(path_steps):
        if _stop_requested():
            _diag("warn", "open_path_stop_requested", {"step_index": int(step_index)})
            return None
        button_id = _safe_int(step.get("button_id", 0), 0)
        if button_id <= 0:
            _diag("warn", "open_path_invalid_button", {"step_index": int(step_index), "button_id": int(button_id)})
            return None
        _diag(
            "trace",
            "open_path_step_click",
            {
                "step_index": int(step_index),
                "button_id": int(button_id),
                "expected_state_key": _safe_str(step.get("expected_state_key", "")),
                "current_state_key": _safe_str(current.get("state_key", "")),
            },
        )
        click_result = _click_and_capture(current, button_id, throttle_state)
        post = click_result.get("post_snapshots", [])
        if not post:
            _diag(
                "warn",
                "open_path_step_no_post",
                {
                    "step_index": int(step_index),
                    "button_id": int(button_id),
                    "result_kind": _safe_str(click_result.get("result_kind", "")),
                },
            )
            return None
        current = _select_snapshot_by_state(post, _safe_str(step.get("expected_state_key", "")))
        if current is None:
            _diag(
                "warn",
                "open_path_step_select_failed",
                {
                    "step_index": int(step_index),
                    "button_id": int(button_id),
                    "expected_state_key": _safe_str(step.get("expected_state_key", "")),
                },
            )
            return None
        expected_step_state = _safe_str(step.get("expected_state_key", "")).strip()
        selected_state = _safe_str(current.get("state_key", "")).strip()
        if expected_step_state and selected_state != expected_step_state:
            _diag(
                "warn",
                "open_path_step_state_mismatch",
                {
                    "step_index": int(step_index),
                    "button_id": int(button_id),
                    "expected_state_key": _safe_str(expected_step_state),
                    "selected_state_key": _safe_str(selected_state),
                },
            )
            return None
    _diag("trace", "open_path_success", {"path_length": len(path_steps or []), "state_key": _safe_str(current.get("state_key", ""))})
    return current


def _new_run_state():
    """Create mutable traversal run state."""
    return {
        "by_state": {},
        "by_id": {},
        "order": [],
        "next_capture_index": 1,
        "edges": [],
        "next_edge_index": 1,
        "layout_counts": {},
    }


def _capture_diag(record, message):
    """Append traversal diagnostic to capture record."""
    if not isinstance(record, dict):
        return
    lines = record.get("traversal_diagnostics", []) or []
    lines.append("[{0}] {1}".format(_utc_now_iso(), _safe_str(message)))
    record["traversal_diagnostics"] = lines


def _set_path(record, path_steps):
    """Set shortest known path metadata for capture."""
    if not isinstance(record, dict):
        return False
    current = record.get("path_steps", []) or []
    if current and len(current) <= len(path_steps or []):
        return False
    record["path_steps"] = copy.deepcopy(path_steps or [])
    record["path_button_ids"] = [_safe_int(s.get("button_id", 0), 0) for s in record["path_steps"]]
    record["depth"] = len(record["path_steps"])
    return True


def _register_capture(run_state, snapshot):
    """Register or reuse capture by state key."""
    key = _safe_str(snapshot.get("state_key", ""))
    if not key:
        return "", False

    if key in run_state.get("by_state", {}):
        capture_id = _safe_str(run_state["by_state"][key])
        existing = run_state.get("by_id", {}).get(capture_id)
        if isinstance(existing, dict):
            gid = _safe_int(snapshot.get("gump_id", 0), 0)
            seen = existing.get("seen_gump_ids", []) or []
            if gid != 0 and gid not in seen:
                seen.append(gid)
                existing["seen_gump_ids"] = sorted(list(set([_safe_int(x, 0) for x in seen])))
            existing["last_seen_utc"] = _utc_now_iso()
        return capture_id, False

    idx = _safe_int(run_state.get("next_capture_index", 1), 1)
    run_state["next_capture_index"] = idx + 1
    capture_id = "g{0:04d}".format(idx)
    record = copy.deepcopy(snapshot)
    record["capture_id"] = capture_id
    record["capture_index"] = idx
    record["path_steps"] = []
    record["path_button_ids"] = []
    record["depth"] = 0
    record["incoming_edges"] = []
    record["outgoing_edges"] = []
    record["parent_capture_ids"] = []
    record["first_seen_utc"] = _utc_now_iso()
    record["last_seen_utc"] = _utc_now_iso()
    gid = _safe_int(record.get("gump_id", 0), 0)
    record["seen_gump_ids"] = [gid] if gid != 0 else []

    run_state["by_state"][key] = capture_id
    run_state["by_id"][capture_id] = record
    run_state["order"].append(capture_id)

    lhash = _safe_str(record.get("layout_hash", ""))
    run_state["layout_counts"][lhash] = _safe_int(run_state["layout_counts"].get(lhash, 0), 0) + 1
    return capture_id, True


def _edge_add(run_state, parent_id, button_id, child_id, result_kind, notes):
    """Add parent->child edge record and update capture links."""
    edge_idx = _safe_int(run_state.get("next_edge_index", 1), 1)
    run_state["next_edge_index"] = edge_idx + 1
    edge_id = "e{0:05d}".format(edge_idx)

    parent = run_state.get("by_id", {}).get(_safe_str(parent_id), {})
    child = run_state.get("by_id", {}).get(_safe_str(child_id), {}) if _safe_str(child_id) else {}

    edge = {
        "edge_id": edge_id,
        "edge_index": edge_idx,
        "time_utc": _utc_now_iso(),
        "parent_capture_id": _safe_str(parent_id),
        "parent_layout_hash": _safe_str(parent.get("layout_hash", "")),
        "button_id": _safe_int(button_id, 0),
        "child_capture_id": _safe_str(child_id),
        "child_layout_hash": _safe_str(child.get("layout_hash", "")),
        "result_kind": _safe_str(result_kind),
        "notes": _safe_str(notes),
    }
    run_state["edges"].append(edge)

    if isinstance(parent, dict):
        outgoing = parent.get("outgoing_edges", []) or []
        outgoing.append(edge_id)
        parent["outgoing_edges"] = sorted(list(set(outgoing)))
    if _safe_str(child_id) and isinstance(child, dict):
        incoming = child.get("incoming_edges", []) or []
        incoming.append(edge_id)
        child["incoming_edges"] = sorted(list(set(incoming)))
    return edge_id


def _snapshot_manifest(manifest_template, run_state, button_attempts, interaction_count, stop_reason, finished):
    """Build manifest snapshot from current traversal state."""
    manifest = copy.deepcopy(manifest_template or {})
    stats = manifest.get("stats", {}) if isinstance(manifest.get("stats", {}), dict) else {}
    stats["total_gumps"] = len(run_state.get("order", []))
    stats["total_edges"] = len(run_state.get("edges", []))
    stats["button_attempts"] = int(button_attempts)
    stats["unique_interactions"] = int(interaction_count)
    stats["diagnostic_count"] = len(RUN_DIAGNOSTICS)
    manifest["stats"] = stats

    if finished:
        manifest["finished_at_utc"] = _utc_now_iso()

    if _safe_str(stop_reason).strip():
        manifest["stop_reason"] = _safe_str(stop_reason)
    else:
        manifest["stop_reason"] = "completed" if finished else "running"

    root_id = _safe_str(manifest.get("root_capture_id", ""))
    root_record = run_state.get("by_id", {}).get(root_id)
    if isinstance(root_record, dict):
        manifest["root_layout_hash"] = _safe_str(root_record.get("layout_hash", ""))
    return manifest


def _snapshot_gumps(run_state):
    """Return deterministic gump record list from runtime state."""
    out = []
    for capture_id in run_state.get("order", []):
        rec = run_state.get("by_id", {}).get(capture_id)
        if not isinstance(rec, dict):
            continue
        clone = copy.deepcopy(rec)
        clone["incoming_edges"] = sorted(list(set(clone.get("incoming_edges", []) or [])))
        clone["outgoing_edges"] = sorted(list(set(clone.get("outgoing_edges", []) or [])))
        clone["parent_capture_ids"] = sorted(list(set(clone.get("parent_capture_ids", []) or [])))
        out.append(clone)
    return out


def _snapshot_edges(run_state):
    """Return deterministic edge record list from runtime state."""
    return sorted(copy.deepcopy(run_state.get("edges", []) or []), key=lambda e: _safe_int(e.get("edge_index", 0), 0))


def _build_run_payload_snapshot(manifest_template, run_state, button_attempts, interaction_count, stop_reason, finished):
    """Build run payload snapshot for live checkpoint or final export."""
    manifest = _snapshot_manifest(
        manifest_template,
        run_state,
        button_attempts,
        interaction_count,
        stop_reason,
        finished=bool(finished),
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "manifest": manifest,
        "gumps": _snapshot_gumps(run_state),
        "edges": _snapshot_edges(run_state),
        "diagnostics": copy.deepcopy(RUN_DIAGNOSTICS),
    }


def _commit_live_checkpoint(
    live_state,
    manifest_template,
    run_state,
    button_attempts,
    interaction_keys,
    queue,
    throttle,
    stop_reason,
):
    """Write real-time JSON/TXT checkpoint files for crash-safe recovery."""
    if not isinstance(live_state, dict):
        return False
    if not bool(live_state.get("enabled", False)):
        return False

    _diag(
        "trace",
        "checkpoint_commit_start",
        {
            "queue_length": len(queue or []),
            "interaction_count": len(interaction_keys or []),
            "button_attempts": int(button_attempts),
            "stop_reason": _safe_str(stop_reason),
        },
    )

    run_payload = _build_run_payload_snapshot(
        manifest_template,
        run_state,
        button_attempts,
        len(interaction_keys or []),
        stop_reason,
        finished=False,
    )
    progress = {
        "queue": list(queue or []),
        "interaction_keys": sorted(list(set([_safe_str(x) for x in (interaction_keys or []) if _safe_str(x)]))),
        "button_attempts": int(button_attempts),
        "throttle": copy.deepcopy(throttle or {}),
        "stop_reason": _safe_str(stop_reason),
    }
    checkpoint_payload = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "updated_at_utc": _utc_now_iso(),
        "session_id": _safe_str(live_state.get("session_id", "")),
        "root_target_serial": _safe_int(live_state.get("root_target_serial", 0), 0),
        "profile": copy.deepcopy(live_state.get("profile", {})) if isinstance(live_state.get("profile"), dict) else {},
        "progress": progress,
        "run_payload": run_payload,
    }

    json_ok = _write_json_atomic(_safe_str(live_state.get("live_json_path", "")), checkpoint_payload)

    txt_output = _txt_report(run_payload)
    txt_output += "\n\nLIVE CHECKPOINT\n"
    txt_output += "updated_at_utc={0}\n".format(_safe_str(checkpoint_payload.get("updated_at_utc", "")))
    txt_output += "session_id={0}\n".format(_safe_str(live_state.get("session_id", "")))
    txt_output += "queue_length={0}\n".format(len(progress.get("queue", [])))
    txt_output += "interaction_count={0}\n".format(len(progress.get("interaction_keys", [])))
    txt_ok = _write_text_atomic(_safe_str(live_state.get("live_txt_path", "")), txt_output)
    items_pipe_ok = _write_text_atomic(
        _safe_str(live_state.get("live_items_pipe_path", "")),
        _item_pipe_output_text(run_payload),
    )
    materials_pipe_ok = _write_text_atomic(
        _safe_str(live_state.get("live_materials_pipe_path", "")),
        _materials_pipe_output_text(run_payload),
    )

    resume_ok = _save_resume_state(
        {
            "session_id": _safe_str(live_state.get("session_id", "")),
            "status": "running",
            "checkpoint_json_path": _safe_str(live_state.get("live_json_path", "")),
            "checkpoint_txt_path": _safe_str(live_state.get("live_txt_path", "")),
            "checkpoint_items_pipe_path": _safe_str(live_state.get("live_items_pipe_path", "")),
            "checkpoint_materials_pipe_path": _safe_str(live_state.get("live_materials_pipe_path", "")),
            "diagnostic_log_path": _safe_str(live_state.get("diagnostic_log_path", "")),
            "final_json_path": _safe_str(live_state.get("final_json_path", "")),
            "final_txt_path": _safe_str(live_state.get("final_txt_path", "")),
            "final_items_pipe_path": _safe_str(live_state.get("final_items_pipe_path", "")),
            "final_materials_pipe_path": _safe_str(live_state.get("final_materials_pipe_path", "")),
            "root_target_serial": _safe_int(live_state.get("root_target_serial", 0), 0),
            "profile": copy.deepcopy(live_state.get("profile", {})) if isinstance(live_state.get("profile"), dict) else {},
        }
    )
    commit_ok = bool(json_ok and txt_ok and items_pipe_ok and materials_pipe_ok and resume_ok)
    _diag(
        "trace" if commit_ok else "warn",
        "checkpoint_commit_result",
        {
            "json_ok": bool(json_ok),
            "txt_ok": bool(txt_ok),
            "items_pipe_ok": bool(items_pipe_ok),
            "materials_pipe_ok": bool(materials_pipe_ok),
            "resume_ok": bool(resume_ok),
            "live_json_path": _safe_str(live_state.get("live_json_path", "")),
            "live_txt_path": _safe_str(live_state.get("live_txt_path", "")),
            "live_items_pipe_path": _safe_str(live_state.get("live_items_pipe_path", "")),
            "live_materials_pipe_path": _safe_str(live_state.get("live_materials_pipe_path", "")),
        },
    )
    _update_progress_gump_from_checkpoint(
        run_state,
        button_attempts,
        interaction_keys,
        queue,
        stop_reason,
    )
    return commit_ok


def _restore_resume_context(checkpoint_payload, expected_root_serial, profile):
    """Restore traversal context from a live checkpoint payload."""
    if not isinstance(checkpoint_payload, dict):
        return None

    run_payload = checkpoint_payload.get("run_payload", {})
    if not isinstance(run_payload, dict):
        return None
    manifest = run_payload.get("manifest", {})
    if not isinstance(manifest, dict):
        return None

    root_serial = _safe_int(manifest.get("root_target_serial", 0), 0)
    if root_serial <= 0:
        root_serial = _safe_int(expected_root_serial, 0)
    if root_serial <= 0:
        return None
    if _safe_int(expected_root_serial, 0) > 0 and root_serial != _safe_int(expected_root_serial, 0):
        return None

    expected_server = _safe_str(profile.get("server_name", "")).strip().lower()
    expected_char = _safe_str(profile.get("character_name", "")).strip().lower()
    got_server = _safe_str(manifest.get("profile", {}).get("server_name", "")).strip().lower()
    got_char = _safe_str(manifest.get("profile", {}).get("character_name", "")).strip().lower()
    if expected_server and got_server and expected_server != got_server:
        return None
    if expected_char and got_char and expected_char != got_char:
        return None

    run_state = _new_run_state()
    gumps = run_payload.get("gumps", [])
    if not isinstance(gumps, list):
        gumps = []

    order_pairs = []
    max_capture_index = 0
    for rec in gumps:
        if not isinstance(rec, dict):
            continue
        capture_id = _safe_str(rec.get("capture_id", "")).strip()
        if not capture_id:
            continue
        capture_index = _safe_int(rec.get("capture_index", 0), 0)
        if capture_index > max_capture_index:
            max_capture_index = capture_index
        run_state["by_id"][capture_id] = copy.deepcopy(rec)
        state_key = _safe_str(rec.get("state_key", "")).strip()
        if state_key:
            run_state["by_state"][state_key] = capture_id
        order_pairs.append((capture_index, capture_id))
        lhash = _safe_str(rec.get("layout_hash", ""))
        run_state["layout_counts"][lhash] = _safe_int(run_state["layout_counts"].get(lhash, 0), 0) + 1

    order_pairs.sort(key=lambda x: (int(x[0]), _safe_str(x[1])))
    run_state["order"] = [x[1] for x in order_pairs]
    run_state["next_capture_index"] = max_capture_index + 1

    edges = run_payload.get("edges", [])
    if not isinstance(edges, list):
        edges = []
    run_state["edges"] = sorted(copy.deepcopy(edges), key=lambda e: _safe_int(e.get("edge_index", 0), 0))
    max_edge = 0
    for edge in run_state["edges"]:
        max_edge = max(max_edge, _safe_int(edge.get("edge_index", 0), 0))
    run_state["next_edge_index"] = max_edge + 1

    progress = checkpoint_payload.get("progress", {})
    if not isinstance(progress, dict):
        progress = {}

    queue_raw = progress.get("queue", [])
    if not isinstance(queue_raw, list):
        queue_raw = []
    queue = [cid for cid in queue_raw if _safe_str(cid) in run_state.get("by_id", {})]
    if not queue:
        root_capture = _safe_str(manifest.get("root_capture_id", ""))
        if root_capture and root_capture in run_state.get("by_id", {}):
            queue = [root_capture]

    interaction_keys = set()
    keys_raw = progress.get("interaction_keys", [])
    if isinstance(keys_raw, list):
        for item in keys_raw:
            text = _safe_str(item).strip()
            if text:
                interaction_keys.add(text)

    throttle = progress.get("throttle", {})
    if not isinstance(throttle, dict):
        throttle = {"backoff": 0, "no_response_streak": 0}
    throttle.setdefault("backoff", 0)
    throttle.setdefault("no_response_streak", 0)

    button_attempts = _safe_int(progress.get("button_attempts", 0), 0)
    if button_attempts <= 0:
        button_attempts = _safe_int(manifest.get("stats", {}).get("button_attempts", 0), 0)

    root_capture_id = _safe_str(manifest.get("root_capture_id", ""))
    root_state_key = ""
    root_record = run_state.get("by_id", {}).get(root_capture_id)
    if isinstance(root_record, dict):
        root_state_key = _safe_str(root_record.get("state_key", ""))

    manifest_restored = copy.deepcopy(manifest)
    manifest_restored["finished_at_utc"] = ""
    manifest_restored["stop_reason"] = "running"

    return {
        "root_target_serial": int(root_serial),
        "manifest": manifest_restored,
        "run_state": run_state,
        "queue": list(queue),
        "interaction_keys": set(interaction_keys),
        "button_attempts": int(button_attempts),
        "throttle": throttle,
        "root_state_key": root_state_key,
    }


def traverse_gumps(root_serial, profile, live_state=None, resume_context=None):
    """Traverse gumps with BFS, live checkpoints, and resume recovery."""
    diag_path = ""
    if isinstance(live_state, dict):
        diag_path = _safe_str(live_state.get("diagnostic_log_path", "")).strip()
    default_manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "started_at_utc": _utc_now_iso(),
        "finished_at_utc": "",
        "run_id": "{0}_{1}".format(SCRIPT_NAME, _utc_now_compact()),
        "profile": {"server_name": _safe_str(profile.get("server_name", "unknown_shard")), "character_name": _safe_str(profile.get("character_name", "unknown_character"))},
        "root_target_serial": _safe_int(root_serial, 0),
        "diagnostic_log_path": _safe_str(diag_path),
        "root_capture_id": "",
        "root_layout_hash": "",
        "stop_reason": "",
        "limits": {
            "max_depth": int(MAX_DEPTH),
            "max_buttons_per_gump": int(MAX_BUTTONS_PER_GUMP),
            "max_total_captures": int(MAX_TOTAL_CAPTURES),
            "max_total_edges": int(MAX_TOTAL_EDGES),
            "max_repeated_identical_layouts": int(MAX_REPEAT_LAYOUTS),
            "max_no_response_streak": int(MAX_NO_RESPONSE),
            "max_consecutive_root_open_fails": int(MAX_CONSECUTIVE_ROOT_OPEN_FAILS),
            "max_consecutive_no_gump_states": int(MAX_CONSECUTIVE_NO_GUMP_STATES),
            "max_path_reopen_fails_per_capture": int(MAX_PATH_REOPEN_FAILS_PER_CAPTURE),
            "min_root_reopen_gap_s": float(MIN_ROOT_REOPEN_GAP_S),
        },
        "stats": {"total_gumps": 0, "total_edges": 0, "button_attempts": 0, "unique_interactions": 0, "diagnostic_count": 0},
    }

    manifest = copy.deepcopy(default_manifest)
    run_state = _new_run_state()
    throttle = {"backoff": 0, "no_response_streak": 0}
    recovery_state = {
        "last_root_use_time": 0.0,
        "consecutive_root_open_failures": 0,
        "consecutive_no_open_gumps": 0,
        "path_reopen_failures_by_capture": {},
    }
    interaction_keys = set()
    button_attempts = 0
    stop_reason = ""
    root_state_key = ""
    queue = deque([])

    resume_active = isinstance(resume_context, dict) and isinstance(resume_context.get("run_state"), dict)
    if resume_active:
        run_state = copy.deepcopy(resume_context.get("run_state", _new_run_state()))
        throttle = copy.deepcopy(resume_context.get("throttle", {"backoff": 0, "no_response_streak": 0}))
        throttle.setdefault("backoff", 0)
        throttle.setdefault("no_response_streak", 0)
        interaction_keys = set([_safe_str(x) for x in (resume_context.get("interaction_keys", set()) or []) if _safe_str(x)])
        button_attempts = _safe_int(resume_context.get("button_attempts", 0), 0)
        root_state_key = _safe_str(resume_context.get("root_state_key", "")).strip()
        for cid in resume_context.get("queue", []) or []:
            capture_id = _safe_str(cid).strip()
            if capture_id and capture_id in run_state.get("by_id", {}):
                queue.append(capture_id)

        loaded_manifest = resume_context.get("manifest", {})
        if isinstance(loaded_manifest, dict):
            manifest.update(copy.deepcopy(loaded_manifest))
        if not isinstance(manifest.get("limits"), dict):
            manifest["limits"] = copy.deepcopy(default_manifest.get("limits", {}))
        if not isinstance(manifest.get("stats"), dict):
            manifest["stats"] = copy.deepcopy(default_manifest.get("stats", {}))
        if not manifest.get("started_at_utc"):
            manifest["started_at_utc"] = _utc_now_iso()
        if not manifest.get("run_id"):
            manifest["run_id"] = "{0}_{1}".format(SCRIPT_NAME, _utc_now_compact())
        if not queue:
            root_capture_id = _safe_str(manifest.get("root_capture_id", "")).strip()
            if root_capture_id and root_capture_id in run_state.get("by_id", {}):
                queue.append(root_capture_id)

    manifest["profile"] = {
        "server_name": _safe_str(profile.get("server_name", "unknown_shard")),
        "character_name": _safe_str(profile.get("character_name", "unknown_character")),
    }
    manifest["root_target_serial"] = _safe_int(root_serial, 0)
    if diag_path:
        manifest["diagnostic_log_path"] = _safe_str(diag_path)
    _diag(
        "info",
        "traversal_start",
        {
            "root_target_serial": _safe_int(root_serial, 0),
            "resume_active": bool(resume_active),
            "existing_capture_count": len(run_state.get("order", [])),
            "queue_length": len(queue),
            "interaction_count": len(interaction_keys),
            "button_attempts": int(button_attempts),
            "recovery": {
                "consecutive_root_open_failures": _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0),
                "consecutive_no_open_gumps": _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0),
            },
        },
    )

    # Fresh start path if no valid resume context was supplied.
    if not resume_active or not run_state.get("order", []):
        run_state = _new_run_state()
        throttle = {"backoff": 0, "no_response_streak": 0}
        recovery_state = {
            "last_root_use_time": 0.0,
            "consecutive_root_open_failures": 0,
            "consecutive_no_open_gumps": 0,
            "path_reopen_failures_by_capture": {},
        }
        interaction_keys = set()
        button_attempts = 0
        stop_reason = ""
        root_state_key = ""
        queue = deque([])

        root_snapshot, _ = _open_root(root_serial, throttle, recovery_state=recovery_state)
        if root_snapshot is None:
            stop_reason = "root_open_failed"
            _diag("error", "traversal_root_open_failed", {"root_serial": _safe_int(root_serial, 0)})
        else:
            root_id, _ = _register_capture(run_state, root_snapshot)
            root_record = run_state.get("by_id", {}).get(root_id)
            _set_path(root_record, [])
            manifest["root_capture_id"] = root_id
            manifest["root_layout_hash"] = _safe_str(root_record.get("layout_hash", "")) if isinstance(root_record, dict) else ""
            root_state_key = _safe_str(root_record.get("state_key", "")) if isinstance(root_record, dict) else ""
            queue.append(root_id)
            _diag(
                "info",
                "traversal_root_captured",
                {
                    "root_capture_id": _safe_str(root_id),
                    "root_state_key": _safe_str(root_state_key),
                    "root_gump_id": _safe_int(root_snapshot.get("gump_id", 0), 0),
                },
            )

    _commit_live_checkpoint(
        live_state,
        manifest,
        run_state,
        button_attempts,
        interaction_keys,
        list(queue),
        throttle,
        stop_reason,
    )

    while queue:
        if _stop_requested():
            stop_reason = _stop_reason_from_request()
            _diag("warn", "traversal_stop_requested", {"resolved_stop_reason": _safe_str(stop_reason)})
            break
        if len(run_state.get("order", [])) >= int(MAX_TOTAL_CAPTURES):
            stop_reason = "max_total_captures"
            _diag("warn", "traversal_limit_hit", {"limit": "max_total_captures", "count": len(run_state.get("order", []))})
            break
        if len(run_state.get("edges", [])) >= int(MAX_TOTAL_EDGES):
            stop_reason = "max_total_edges"
            _diag("warn", "traversal_limit_hit", {"limit": "max_total_edges", "count": len(run_state.get("edges", []))})
            break

        current_id = queue.popleft()
        current = run_state.get("by_id", {}).get(current_id)
        if not isinstance(current, dict):
            continue
        _diag(
            "trace",
            "traversal_pop_capture",
            {
                "capture_id": _safe_str(current_id),
                "depth": _safe_int(current.get("depth", 0), 0),
                "button_count": len(current.get("button_ids", []) or []),
                "queue_length_after_pop": len(queue),
                "state_key": _safe_str(current.get("state_key", "")),
            },
        )
        if _safe_int(current.get("depth", 0), 0) >= int(MAX_DEPTH):
            _diag(
                "trace",
                "traversal_skip_depth_limit",
                {
                    "capture_id": _safe_str(current_id),
                    "depth": _safe_int(current.get("depth", 0), 0),
                    "max_depth": int(MAX_DEPTH),
                },
            )
            continue

        button_ids = sorted(
            list(
                set(
                    [
                        _safe_int(x, 0)
                        for x in (current.get("button_ids", []) or [])
                        if _safe_int(x, 0) > 0
                    ]
                )
            )
        )
        original_button_count = len(button_ids)
        button_ids = _filter_traversal_button_ids(current, button_ids)
        if len(button_ids) != original_button_count:
            _diag(
                "trace",
                "traversal_buttons_filtered",
                {
                    "capture_id": _safe_str(current_id),
                    "original_count": int(original_button_count),
                    "kept_count": len(button_ids),
                },
            )
        if len(button_ids) > int(MAX_BUTTONS_PER_GUMP):
            button_ids = button_ids[: int(MAX_BUTTONS_PER_GUMP)]
            _capture_diag(current, "button_list_truncated")
            _diag(
                "warn",
                "traversal_buttons_truncated",
                {
                    "capture_id": _safe_str(current_id),
                    "original_count": len(current.get("button_ids", []) or []),
                    "kept_count": len(button_ids),
                },
            )

        capture_fail_map = recovery_state.get("path_reopen_failures_by_capture", {})
        if not isinstance(capture_fail_map, dict):
            capture_fail_map = {}
            recovery_state["path_reopen_failures_by_capture"] = capture_fail_map
        capture_key = _safe_str(current_id)
        if capture_key not in capture_fail_map:
            capture_fail_map[capture_key] = 0

        for button_id in button_ids:
            if _stop_requested():
                stop_reason = _stop_reason_from_request()
                _diag(
                    "warn",
                    "traversal_stop_requested_during_buttons",
                    {"capture_id": _safe_str(current_id), "resolved_stop_reason": _safe_str(stop_reason)},
                )
                break
            if len(run_state.get("edges", [])) >= int(MAX_TOTAL_EDGES):
                stop_reason = "max_total_edges"
                _diag("warn", "traversal_limit_hit", {"limit": "max_total_edges", "count": len(run_state.get("edges", []))})
                break

            interaction_key = "{0}|{1}|{2}".format(
                _safe_str(current.get("layout_hash", "")),
                int(button_id),
                _safe_str(current.get("text_hash", "")),
            )
            if interaction_key in interaction_keys:
                _diag(
                    "trace",
                    "traversal_skip_interaction_seen",
                    {"capture_id": _safe_str(current_id), "button_id": int(button_id)},
                )
                continue
            if _should_skip_utility_button(current, button_id):
                interaction_keys.add(interaction_key)
                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    "skipped_utility_button",
                    "target_prompt_risk",
                )
                _capture_diag(current, "utility_button_skipped_{0}".format(int(button_id)))
                _diag(
                    "info",
                    "traversal_skip_utility_button",
                    {"capture_id": _safe_str(current_id), "button_id": int(button_id)},
                )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                continue
            interaction_keys.add(interaction_key)
            button_attempts += 1
            _diag(
                "trace",
                "traversal_button_attempt",
                {
                    "capture_id": _safe_str(current_id),
                    "button_id": int(button_id),
                    "button_attempts": int(button_attempts),
                    "queue_length": len(queue),
                    "edge_count": len(run_state.get("edges", [])),
                    "action_state": _action_state_snapshot(throttle, include_open_ids=False),
                },
            )

            live_parent = _find_open_snapshot_for_capture(current)
            if live_parent is not None:
                _diag(
                    "trace",
                    "recovery_reuse_open_snapshot_success",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "gump_id": _safe_int(live_parent.get("gump_id", 0), 0),
                        "state_key": _safe_str(live_parent.get("state_key", "")),
                    },
                )
            else:
                _diag(
                    "trace",
                    "recovery_reuse_open_snapshot_miss",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "path_length": len(current.get("path_steps", []) or []),
                    },
                )
                live_parent = _open_path(
                    root_serial,
                    current.get("path_steps", []) or [],
                    throttle,
                    root_state_key,
                    recovery_state=recovery_state,
                )
            if live_parent is None:
                _capture_diag(current, "path_reopen_failed_before_button_{0}".format(int(button_id)))
                _edge_add(run_state, current_id, button_id, "", "path_reopen_failed", "could_not_reopen_parent")
                _throttle_update(throttle, "path_reopen_failed")
                capture_fail_map[capture_key] = _safe_int(capture_fail_map.get(capture_key, 0), 0) + 1
                _diag(
                    "warn",
                    "traversal_path_reopen_failed",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "capture_failures": _safe_int(capture_fail_map.get(capture_key, 0), 0),
                        "consecutive_root_open_failures": _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0),
                        "consecutive_no_open_gumps": _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0),
                        "connection": _connection_health_snapshot(),
                    },
                )
                if _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0) >= int(MAX_CONSECUTIVE_ROOT_OPEN_FAILS):
                    stop_reason = "root_unavailable_recovery_abort"
                    _diag(
                        "error",
                        "traversal_recovery_circuit_breaker",
                        {
                            "reason": "consecutive_root_open_failures",
                            "count": _safe_int(recovery_state.get("consecutive_root_open_failures", 0), 0),
                            "limit": int(MAX_CONSECUTIVE_ROOT_OPEN_FAILS),
                            "connection": _connection_health_snapshot(),
                        },
                    )
                elif _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0) >= int(MAX_CONSECUTIVE_NO_GUMP_STATES):
                    stop_reason = "root_unavailable_recovery_abort"
                    _diag(
                        "error",
                        "traversal_recovery_circuit_breaker",
                        {
                            "reason": "consecutive_no_open_gumps",
                            "count": _safe_int(recovery_state.get("consecutive_no_open_gumps", 0), 0),
                            "limit": int(MAX_CONSECUTIVE_NO_GUMP_STATES),
                            "connection": _connection_health_snapshot(),
                        },
                    )
                elif _safe_int(capture_fail_map.get(capture_key, 0), 0) >= int(MAX_PATH_REOPEN_FAILS_PER_CAPTURE):
                    _diag(
                        "warn",
                        "traversal_skip_capture_due_to_path_failures",
                        {
                            "capture_id": _safe_str(current_id),
                            "count": _safe_int(capture_fail_map.get(capture_key, 0), 0),
                            "limit": int(MAX_PATH_REOPEN_FAILS_PER_CAPTURE),
                        },
                    )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                if stop_reason:
                    break
                if _safe_int(capture_fail_map.get(capture_key, 0), 0) >= int(MAX_PATH_REOPEN_FAILS_PER_CAPTURE):
                    break
                continue

            capture_fail_map[capture_key] = 0

            # Re-validate against the live parent snapshot before any reply.
            # The queued capture can go stale when root/menu state changes.
            if not _button_has_runtime_entry(live_parent, button_id):
                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    "skipped_stale_not_in_live_parent",
                    "runtime_button_missing_in_live_parent",
                )
                _capture_diag(current, "stale_button_not_in_live_parent_{0}".format(int(button_id)))
                _diag(
                    "warn",
                    "traversal_skip_stale_button_not_in_live_parent",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "expected_state_key": _safe_str(current.get("state_key", "")),
                        "live_parent_state_key": _safe_str(live_parent.get("state_key", "")),
                        "live_parent_gump_id": _safe_int(live_parent.get("gump_id", 0), 0),
                    },
                )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                continue

            if _button_is_parser_only(live_parent, button_id):
                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    "skipped_parser_only_button",
                    "live_parent_parser_only",
                )
                _capture_diag(current, "parser_only_button_skipped_live_parent_{0}".format(int(button_id)))
                _diag(
                    "trace",
                    "traversal_skip_parser_only_button_live_parent",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "live_parent_state_key": _safe_str(live_parent.get("state_key", "")),
                    },
                )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                continue

            if _button_is_page_control(live_parent, button_id):
                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    "skipped_page_button",
                    "page_control_map_only",
                )
                _capture_diag(current, "page_button_skipped_live_parent_{0}".format(int(button_id)))
                _diag(
                    "trace",
                    "traversal_skip_page_button_live_parent",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "live_parent_state_key": _safe_str(live_parent.get("state_key", "")),
                    },
                )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                continue

            if _should_skip_utility_button(live_parent, button_id):
                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    "skipped_utility_button",
                    "target_prompt_risk_live_parent",
                )
                _capture_diag(current, "utility_button_skipped_live_parent_{0}".format(int(button_id)))
                _diag(
                    "info",
                    "traversal_skip_utility_button_live_parent",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "live_parent_state_key": _safe_str(live_parent.get("state_key", "")),
                    },
                )
                _commit_live_checkpoint(
                    live_state,
                    manifest,
                    run_state,
                    button_attempts,
                    interaction_keys,
                    list(queue),
                    throttle,
                    stop_reason,
                )
                continue

            click_result = _click_and_capture(live_parent, button_id, throttle)
            post = click_result.get("post_snapshots", [])
            if not post:
                if _safe_str(click_result.get("result_kind", "")) == "opened_target_cursor":
                    _edge_add(
                        run_state,
                        current_id,
                        button_id,
                        "",
                        "opened_target_cursor",
                        _safe_str(click_result.get("notes", "target_cursor_opened")),
                    )
                    _capture_diag(current, "target_cursor_opened_on_button_{0}".format(int(button_id)))
                    _throttle_update(throttle, "same_layout")
                    _pump(POST_POLL_S)
                    _diag(
                        "warn",
                        "traversal_target_cursor_result",
                        {
                            "capture_id": _safe_str(current_id),
                            "button_id": int(button_id),
                            "notes": _safe_str(click_result.get("notes", "")),
                        },
                    )
                    _commit_live_checkpoint(
                        live_state,
                        manifest,
                        run_state,
                        button_attempts,
                        interaction_keys,
                        list(queue),
                        throttle,
                        stop_reason,
                    )
                    continue

                _edge_add(
                    run_state,
                    current_id,
                    button_id,
                    "",
                    _safe_str(click_result.get("result_kind", "no_response")),
                    _safe_str(click_result.get("notes", "")),
                )
                _throttle_update(throttle, "no_response")
                _diag(
                    "warn",
                    "traversal_click_no_post",
                    {
                        "capture_id": _safe_str(current_id),
                        "button_id": int(button_id),
                        "result_kind": _safe_str(click_result.get("result_kind", "")),
                        "throttle": {
                            "backoff": _safe_int(throttle.get("backoff", 0), 0),
                            "no_response_streak": _safe_int(throttle.get("no_response_streak", 0), 0),
                        },
                    },
                )
            else:
                children = _select_children(
                    post,
                    click_result.get("pre_state_keys", []),
                    _safe_str(current.get("state_key", "")),
                )
                if not children:
                    _edge_add(run_state, current_id, button_id, "", "no_child_detected", "post_click_candidates_empty")
                    _throttle_update(throttle, "no_response")
                    _diag(
                        "warn",
                        "traversal_no_children_selected",
                        {"capture_id": _safe_str(current_id), "button_id": int(button_id), "post_count": len(post)},
                    )
                else:
                    saw_only_same = True
                    for child_snapshot in children:
                        child_state_key = _safe_str(child_snapshot.get("state_key", ""))
                        child_id, is_new = _register_capture(run_state, child_snapshot)
                        child = run_state.get("by_id", {}).get(child_id)
                        if not isinstance(child, dict):
                            continue

                        child_path = copy.deepcopy(current.get("path_steps", []) or [])
                        child_path.append({"button_id": int(button_id), "expected_state_key": child_state_key})
                        _set_path(child, child_path)

                        parents = child.get("parent_capture_ids", []) or []
                        if current_id not in parents:
                            parents.append(current_id)
                        child["parent_capture_ids"] = sorted(list(set(parents)))

                        same_layout = child_state_key == _safe_str(current.get("state_key", ""))
                        label = ""
                        for btn in current.get("buttons_discovered", []) or []:
                            if _safe_int(btn.get("button_id", 0), 0) == int(button_id):
                                label = _safe_str(btn.get("inferred_label", "")).strip()
                                break
                        _edge_add(
                            run_state,
                            current_id,
                            button_id,
                            child_id,
                            "same_layout" if same_layout else "opened_child",
                            "label={0}".format(label) if label else "",
                        )
                        if not same_layout:
                            saw_only_same = False

                        if is_new and _safe_int(child.get("depth", 0), 0) <= int(MAX_DEPTH):
                            queue.append(child_id)
                            _diag(
                                "trace",
                                "traversal_enqueue_child",
                                {
                                    "parent_capture_id": _safe_str(current_id),
                                    "child_capture_id": _safe_str(child_id),
                                    "button_id": int(button_id),
                                    "depth": _safe_int(child.get("depth", 0), 0),
                                    "queue_length": len(queue),
                                    "same_layout": bool(same_layout),
                                },
                            )

                        if is_new and _safe_int(run_state.get("layout_counts", {}).get(_safe_str(child.get("layout_hash", "")), 0), 0) > int(MAX_REPEAT_LAYOUTS):
                            stop_reason = "max_repeated_identical_layouts"
                            _diag(
                                "warn",
                                "traversal_limit_hit",
                                {
                                    "limit": "max_repeated_identical_layouts",
                                    "layout_hash": _safe_str(child.get("layout_hash", "")),
                                },
                            )
                            break

                    if stop_reason:
                        break
                    _throttle_update(throttle, "same_layout" if saw_only_same else "success")
                    _diag(
                        "trace",
                        "traversal_button_result",
                        {
                            "capture_id": _safe_str(current_id),
                            "button_id": int(button_id),
                            "child_count": len(children),
                            "saw_only_same": bool(saw_only_same),
                            "throttle": {
                                "backoff": _safe_int(throttle.get("backoff", 0), 0),
                                "no_response_streak": _safe_int(throttle.get("no_response_streak", 0), 0),
                            },
                        },
                    )

            _commit_live_checkpoint(
                live_state,
                manifest,
                run_state,
                button_attempts,
                interaction_keys,
                list(queue),
                throttle,
                stop_reason,
            )

            if _safe_int(throttle.get("no_response_streak", 0), 0) >= int(MAX_NO_RESPONSE):
                stop_reason = "max_no_response_streak"
                _diag(
                    "warn",
                    "traversal_limit_hit",
                    {"limit": "max_no_response_streak", "count": _safe_int(throttle.get("no_response_streak", 0), 0)},
                )
                break

        if stop_reason:
            break

    _commit_live_checkpoint(
        live_state,
        manifest,
        run_state,
        button_attempts,
        interaction_keys,
        list(queue),
        throttle,
        stop_reason,
    )
    _diag(
        "info",
        "traversal_finished",
        {
            "stop_reason": _safe_str(stop_reason) if _safe_str(stop_reason).strip() else "completed",
            "total_gumps": len(run_state.get("order", [])),
            "total_edges": len(run_state.get("edges", [])),
            "button_attempts": int(button_attempts),
            "interaction_count": len(interaction_keys),
            "connection": _connection_health_snapshot(),
        },
    )
    return _build_run_payload_snapshot(
        manifest,
        run_state,
        button_attempts,
        len(interaction_keys),
        stop_reason,
        finished=True,
    )


def _sanitize_token(value, fallback):
    """Return filename-safe token."""
    token = _safe_str(value).strip() or _safe_str(fallback).strip() or "unknown"
    token = re.sub(r"\s+", "_", token)
    token = re.sub(r"[^A-Za-z0-9_\-\.]+", "", token)
    token = token.strip("._-")
    return token if token else (_safe_str(fallback).strip() or "unknown")


def _export_paths(export_dir, profile, root_hash):
    """Build deterministic JSON/TXT export paths."""
    folder = os.path.normpath(_safe_str(export_dir).strip() or _export_dir({}))
    shard = _sanitize_token(profile.get("server_name", "unknown_shard"), "unknown_shard")
    character = _sanitize_token(profile.get("character_name", "unknown_character"), "unknown_character")
    root = _sanitize_token(_safe_str(root_hash)[:12], "nohash")
    stamp = _utc_now_compact()
    base = "gump_map_{0}_{1}_{2}_{3}".format(stamp, shard, character, root)
    live_base = base + LIVE_FILE_SUFFIX
    return {
        "folder": folder,
        "json": os.path.join(folder, base + ".json"),
        "txt": os.path.join(folder, base + ".txt"),
        "items_pipe": os.path.join(folder, base + "_items_pipe.txt"),
        "materials_pipe": os.path.join(folder, base + "_materials_pipe.txt"),
        "live_json": os.path.join(folder, live_base + ".json"),
        "live_txt": os.path.join(folder, live_base + ".txt"),
        "live_items_pipe": os.path.join(folder, live_base + "_items_pipe.txt"),
        "live_materials_pipe": os.path.join(folder, live_base + "_materials_pipe.txt"),
        "diag_log": os.path.join(folder, live_base + DIAG_LOG_EXTENSION),
        "base_name": base,
    }


def _derive_diag_path_from_live_json(live_json_path):
    """Derive a diagnostic log path from the live JSON checkpoint path."""
    path = _safe_str(live_json_path).strip()
    if not path:
        return ""
    if path.lower().endswith(".json"):
        return path[:-5] + DIAG_LOG_EXTENSION
    return path + DIAG_LOG_EXTENSION


def _pipe_field(value):
    """Normalize value for pipe-delimited output columns."""
    text = _safe_str(value).replace("\r", " ").replace("\n", " ")
    text = text.replace("|", "/")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_gump_text(text):
    """Normalize gump text by removing tags and compressing whitespace."""
    cleaned = re.sub(r"<[^>]*>", " ", _safe_str(text))
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_profession_name(run_payload):
    """Infer profession from root gump title text."""
    if not isinstance(run_payload, dict):
        return "UNKNOWN"
    manifest = run_payload.get("manifest", {})
    gumps = run_payload.get("gumps", [])
    if not isinstance(manifest, dict) or not isinstance(gumps, list):
        return "UNKNOWN"

    root_capture_id = _safe_str(manifest.get("root_capture_id", "")).strip()
    root_record = None
    for rec in gumps:
        if not isinstance(rec, dict):
            continue
        if _safe_str(rec.get("capture_id", "")).strip() == root_capture_id:
            root_record = rec
            break
    if not isinstance(root_record, dict):
        return "UNKNOWN"

    raw = _safe_str(root_record.get("title", "")) or _safe_str(root_record.get("visible_text_raw", ""))
    cleaned = _normalize_gump_text(raw)
    match = re.search(r"\b([A-Za-z][A-Za-z ]{1,40})\s+menu\b", cleaned, re.IGNORECASE)
    if not match:
        return "UNKNOWN"
    return _pipe_field(match.group(1)).title() or "UNKNOWN"


def _find_path_button(path_buttons, modulo_value):
    """Return the last button in path matching modulo pattern."""
    for bid in reversed(path_buttons):
        button = _safe_int(bid, 0)
        if button > 0 and (button % 20) == int(modulo_value):
            return int(button)
    return 0


def _extract_item_name_from_detail(detail_text):
    """Extract item name from normalized item-detail text."""
    text = _normalize_gump_text(detail_text)
    if not text:
        return ""

    def _clean_name(raw_name):
        cleaned = _pipe_field(raw_name)
        if not cleaned:
            return ""
        stop_patterns = [
            r"\bMakes as many as possible at once\b.*$",
            r"\bSuccess Chance:.*$",
            r"\bThis item may hold\b.*$",
            r"\bNow make number\b.*$",
            r"\bBlacksmithing\s+\d+(?:\.\d+)?\b.*$",
            r"\bCarpentry\s+\d+(?:\.\d+)?\b.*$",
            r"\bTailoring\s+\d+(?:\.\d+)?\b.*$",
            r"\bTinkering\s+\d+(?:\.\d+)?\b.*$",
            r"\bAlchemy\s+\d+(?:\.\d+)?\b.*$",
        ]
        for pattern in stop_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:,")
        return cleaned

    patterns = [
        r"\bBACK\s+(.+?)\s+Makes as many as possible at once\b",
        r"\bBACK\s+(.+?)\s+This item may hold\b",
        r"\bBACK\s+(.+?)\s+Success Chance:",
        r"\bBACK\s+(.+?)\s+[A-Za-z ]+\s+\d+(?:\.\d+)?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        name = _clean_name(match.group(1))
        if name:
            return name
    return ""


def _extract_resource_costs_from_detail(detail_text):
    """Extract material costs text from normalized item-detail text."""
    text = _normalize_gump_text(detail_text)
    if not text:
        return "UNKNOWN"

    resource_keywords = (
        "ingot",
        "board",
        "cloth",
        "leather",
        "hide",
        "log",
        "scale",
        "feather",
        "shaft",
        "gem",
        "ruby",
        "emerald",
        "sapphire",
        "diamond",
        "amethyst",
        "citrine",
        "tourmaline",
        "topaz",
        "amber",
        "bottle",
        "bone",
    )
    costs = []
    seen = set()

    name_qty = re.compile(r"\b([A-Za-z][A-Za-z'()\-]*(?:\s+[A-Za-z][A-Za-z'()\-]*){0,3})\s+(\d+)\b")
    for match in name_qty.finditer(text):
        name = _pipe_field(match.group(1))
        qty = _safe_int(match.group(2), 0)
        if qty <= 0:
            continue
        if not any(key in name.lower() for key in resource_keywords):
            continue
        row = "{0} {1}".format(int(qty), name)
        low = row.lower()
        if low in seen:
            continue
        seen.add(low)
        costs.append(row)

    qty_name = re.compile(r"\b(\d+)\s+([A-Za-z][A-Za-z'()\-]*(?:\s+[A-Za-z][A-Za-z'()\-]*){0,3})\b")
    for match in qty_name.finditer(text):
        qty = _safe_int(match.group(1), 0)
        name = _pipe_field(match.group(2))
        if qty <= 0:
            continue
        prefix_text = text[:int(match.start())].strip()
        prev_word = ""
        if prefix_text:
            prev_word = _safe_str(prefix_text.split(" ")[-1]).strip().lower()
        if prev_word and any(key in prev_word for key in resource_keywords):
            continue
        if not any(key in name.lower() for key in resource_keywords):
            continue
        row = "{0} {1}".format(int(qty), name)
        low = row.lower()
        if low in seen:
            continue
        seen.add(low)
        costs.append(row)

    if costs:
        return ", ".join(costs)
    return "UNKNOWN"


def _category_phrase_tokens(text):
    """Return tokens from the category phrase area in a gump title."""
    cleaned = _normalize_gump_text(text)
    tokens = re.findall(r"[A-Za-z][A-Za-z'()\-]*", cleaned)
    if not tokens:
        return []
    start = 0
    for idx in range(len(tokens) - 1):
        if tokens[idx].lower() == "last" and tokens[idx + 1].lower() == "ten":
            start = idx + 2
            break
    return tokens[start:]


def _extract_blacksmith_category_names_from_text(text):
    """Extract known Blacksmith category names in the order they appear on-screen."""
    normalized = _normalize_gump_text(text)
    if not normalized:
        return []

    lowered = normalized.lower()
    matches = []
    for name in BLACKSMITH_CATEGORY_NAME_ORDER:
        idx = lowered.find(name.lower())
        if idx >= 0:
            matches.append((int(idx), _pipe_field(name)))
    if not matches:
        return []

    matches.sort(key=lambda x: x[0])
    ordered = []
    seen = set()
    for _, label in matches:
        key = _safe_str(label).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(label)
    return ordered


def _build_category_label_map(run_payload):
    """Build best-effort category label map keyed by category button ID."""
    mapping = {}
    if not isinstance(run_payload, dict):
        return mapping
    manifest = run_payload.get("manifest", {})
    gumps = run_payload.get("gumps", [])
    if not isinstance(manifest, dict) or not isinstance(gumps, list):
        return mapping

    skip_phrases = set([
        "blacksmithing",
        "menu",
        "categories",
        "selections",
        "notices",
        "exit",
        "cancel",
        "make",
        "repair",
        "item",
        "prompt",
        "for",
        "mark",
        "enhance",
        "alter",
        "quest",
        "non",
        "completed",
        "smelt",
        "last",
        "ten",
        "next",
        "prev",
        "page",
        "back",
        "now",
        "number",
        "max",
        "success",
        "chance",
        "exceptional",
        "this",
        "you",
        "do",
        "not",
        "color",
        "materials",
        "other",
        "universal",
        "barding",
        "deed",
    ])

    ordered = sorted(gumps, key=lambda x: _safe_int(x.get("capture_index", 0), 0))
    root_capture_id = _safe_str(manifest.get("root_capture_id", "")).strip()
    root_record = None
    for rec in ordered:
        if _safe_str(rec.get("capture_id", "")).strip() == root_capture_id:
            root_record = rec
            break
    if not isinstance(root_record, dict):
        return mapping

    category_buttons = []
    for button in (root_record.get("buttons_discovered", []) or []):
        if not isinstance(button, dict):
            continue
        bid = _safe_int(button.get("button_id", 0), 0)
        if bid <= 0:
            continue
        x = _safe_opt_int(button.get("x"))
        y = _safe_opt_int(button.get("y"))
        if x is None or y is None:
            continue
        if x <= 40 and y >= 80 and y <= 280:
            category_buttons.append((int(y), int(bid)))
    category_button_ids = []
    for _, bid in sorted(category_buttons, key=lambda x: (x[0], x[1])):
        button_id = int(bid)
        if button_id in category_button_ids:
            continue
        category_button_ids.append(button_id)
    if not category_button_ids:
        fallback_ids = sorted(
            list(
                set(
                    [
                        _safe_int(button.get("button_id", 0), 0)
                        for button in (root_record.get("buttons_discovered", []) or [])
                        if isinstance(button, dict) and _safe_int(button.get("button_id", 0), 0) > 0 and (_safe_int(button.get("button_id", 0), 0) % 20) == 1
                    ]
                )
            )
        )
        category_button_ids = [int(x) for x in fallback_ids] if fallback_ids else [1, 21, 41, 61, 81, 101, 121]

    root_text = _safe_str(root_record.get("visible_text_raw", "")) or _safe_str(root_record.get("title", ""))
    ordered_names = _extract_blacksmith_category_names_from_text(root_text)
    root_tokens = _category_phrase_tokens(root_text)
    known_pairs = set(
        [
            "metal armor",
            "leather armor",
            "cloth armor",
            "bone armor",
            "wood armor",
            "plate armor",
            "studded armor",
            "animal barding",
        ]
    )
    if not ordered_names:
        ordered_names = []
        idx = 0
        while idx < len(root_tokens) and len(ordered_names) < len(category_button_ids):
            token = _safe_str(root_tokens[idx]).strip()
            if not token:
                idx += 1
                continue
            if token.lower() in skip_phrases:
                idx += 1
                continue
            if not token[:1].isupper():
                idx += 1
                continue

            choose = _pipe_field(token)
            if idx + 1 < len(root_tokens):
                token2 = _safe_str(root_tokens[idx + 1]).strip()
                if token2 and token2[:1].isupper():
                    pair = _pipe_field(token + " " + token2)
                    if pair.lower() in known_pairs:
                        choose = pair
                        idx += 1

            if choose:
                if choose.lower() not in [x.lower() for x in ordered_names]:
                    ordered_names.append(choose)
            idx += 1

    for idx_name, button_id in enumerate(category_button_ids):
        if idx_name < len(ordered_names):
            mapping[int(button_id)] = _pipe_field(ordered_names[idx_name])
        else:
            mapping[int(button_id)] = "CATEGORY_BUTTON_{0}".format(int(button_id))

    for rec in ordered:
        if not isinstance(rec, dict):
            continue
        buttons = rec.get("buttons_discovered", [])
        if not isinstance(buttons, list):
            continue
        for button in buttons:
            if not isinstance(button, dict):
                continue
            bid = _safe_int(button.get("button_id", 0), 0)
            if bid <= 0 or (bid % 20) != 1:
                continue
            label = _pipe_field(button.get("inferred_label", ""))
            if not label or label.lower() in skip_phrases:
                continue
            if int(bid) not in mapping:
                mapping[int(bid)] = label

    return mapping


def _build_item_pipe_rows(run_payload):
    """Build one deterministic output row per crafted item detail gump."""
    rows = []
    if not isinstance(run_payload, dict):
        return rows
    manifest = run_payload.get("manifest", {})
    gumps = run_payload.get("gumps", [])
    edges = run_payload.get("edges", [])
    if not isinstance(manifest, dict) or not isinstance(gumps, list):
        return rows
    if not isinstance(edges, list):
        edges = []

    server = _pipe_field(manifest.get("profile", {}).get("server_name", "")) or "unknown_shard"
    profession = _extract_profession_name(run_payload)
    category_labels = _build_category_label_map(run_payload)

    def _category_from_path(path_buttons):
        ids = [_safe_int(x, 0) for x in (path_buttons or []) if _safe_int(x, 0) > 0]
        for bid in reversed(ids):
            if (int(bid) % 20) != 1:
                continue
            if category_labels and int(bid) not in category_labels:
                continue
            return int(bid)
        return 0

    ordered = sorted(gumps, key=lambda x: _safe_int(x.get("capture_index", 0), 0))
    capture_by_id = {}
    for rec in ordered:
        if not isinstance(rec, dict):
            continue
        capture_id = _safe_str(rec.get("capture_id", "")).strip()
        if capture_id:
            capture_by_id[capture_id] = rec

    incoming_by_child = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        child_id = _safe_str(edge.get("child_capture_id", "")).strip()
        if not child_id:
            continue
        group = incoming_by_child.get(child_id)
        if group is None:
            group = []
            incoming_by_child[child_id] = group
        group.append(edge)

    seen_keys = set()
    for rec in ordered:
        if not isinstance(rec, dict):
            continue

        path_buttons = [_safe_int(x, 0) for x in (rec.get("path_button_ids", []) or []) if _safe_int(x, 0) > 0]
        if not path_buttons:
            continue

        detail_button_id = _find_path_button(path_buttons, 3)
        if detail_button_id <= 0:
            continue

        detail_text = _safe_str(rec.get("visible_text_raw", "")) or _safe_str(rec.get("title", ""))
        normalized = _normalize_gump_text(detail_text).lower()
        if "materials" not in normalized or "back" not in normalized:
            continue

        item_name = _extract_item_name_from_detail(detail_text)
        if not item_name:
            item_name = "UNKNOWN_ITEM_{0}".format(int(detail_button_id))
        normalized_item = _normalize_gump_text(item_name).lower()

        make_button_id = 0
        if int(detail_button_id) > 1 and (int(detail_button_id) % 20) == 3:
            make_button_id = int(detail_button_id) - 1
        if make_button_id <= 0:
            make_button_id = _find_path_button(path_buttons, 2)
        if make_button_id <= 0:
            make_button_id = int(detail_button_id)

        category_scores = {}
        category_from_detail_path = _category_from_path(path_buttons)
        if category_from_detail_path > 0:
            category_scores[int(category_from_detail_path)] = (2, len(path_buttons))

        capture_id = _safe_str(rec.get("capture_id", "")).strip()
        for edge in incoming_by_child.get(capture_id, []):
            if not isinstance(edge, dict):
                continue
            if _safe_int(edge.get("button_id", 0), 0) != int(detail_button_id):
                continue
            parent_id = _safe_str(edge.get("parent_capture_id", "")).strip()
            parent = capture_by_id.get(parent_id)
            if not isinstance(parent, dict):
                continue
            parent_path = [_safe_int(x, 0) for x in (parent.get("path_button_ids", []) or []) if _safe_int(x, 0) > 0]
            candidate_category = _category_from_path(parent_path)
            if candidate_category <= 0:
                continue
            parent_menu_text = _capture_normalized_text(parent)
            menu_matches_item = bool(parent_menu_text and normalized_item and normalized_item in parent_menu_text)
            score = (0 if menu_matches_item else 1, len(parent_path))
            existing = category_scores.get(int(candidate_category))
            if existing is None or score < existing:
                category_scores[int(candidate_category)] = score

        category_button_id = 0
        if category_scores:
            ordered_candidates = sorted(category_scores.items(), key=lambda pair: (pair[1][0], pair[1][1], pair[0]))
            category_button_id = int(ordered_candidates[0][0])
        if category_button_id <= 0 and detail_button_id > 2:
            inferred_button = int(detail_button_id) - 2
            if inferred_button > 0 and (inferred_button % 20) == 1:
                if (not category_labels) or (int(inferred_button) in category_labels):
                    category_button_id = int(inferred_button)

        if category_button_id > 0:
            category = _pipe_field(category_labels.get(category_button_id, "CATEGORY_BUTTON_{0}".format(int(category_button_id))))
            creation_path = "[{0},{1}]".format(int(category_button_id), int(make_button_id))
        else:
            category = "UNKNOWN"
            creation_path = "[-1,{0}]".format(int(make_button_id))

        resource_costs = _extract_resource_costs_from_detail(detail_text)
        key = "{0}|{1}|{2}".format(int(category_button_id), int(make_button_id), item_name.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        rows.append(
            {
                "server": server,
                "profession": profession,
                "category": category,
                "item_name": item_name,
                "creation_path": creation_path,
                "resource_costs": resource_costs,
                "_sort_category_button": int(category_button_id),
                "_sort_item_button": int(make_button_id),
            }
        )

    rows.sort(key=lambda r: (int(r.get("_sort_category_button", -1)), int(r.get("_sort_item_button", -1)), _safe_str(r.get("item_name", "")).lower()))
    return rows


def _item_pipe_output_text(run_payload, rows=None):
    """Build full pipe-delimited text output with header."""
    source_rows = rows if isinstance(rows, list) else _build_item_pipe_rows(run_payload)
    lines = ["Server|Profession|Category|Item Name|Creation Path|Resource Costs"]
    for row in source_rows:
        lines.append(
            "{0}|{1}|{2}|{3}|{4}|{5}".format(
                _pipe_field(row.get("server", "")),
                _pipe_field(row.get("profession", "")),
                _pipe_field(row.get("category", "")),
                _pipe_field(row.get("item_name", "")),
                _pipe_field(row.get("creation_path", "")),
                _pipe_field(row.get("resource_costs", "")),
            )
        )
    return "\n".join(lines) + "\n"


def export_items_pipe(run_payload, output_path):
    """Export one pipe-delimited row per item."""
    path = _safe_str(output_path).strip()
    if not path:
        _diag("warn", "item_pipe_export_skipped", {"reason": "empty_path"})
        return False

    _diag("info", "item_pipe_export_start", {"path": path})
    rows = _build_item_pipe_rows(run_payload)

    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(_item_pipe_output_text(run_payload, rows))
        _diag("info", "item_pipe_export_success", {"path": path, "row_count": len(rows)})
        return True
    except Exception as ex:
        _diag("error", "item_pipe_export_failed", {"path": path, "error": _safe_str(ex)})
        return False


def _capture_text_for_material_rows(capture_record):
    """Return best-effort text blob for material-name extraction."""
    if not isinstance(capture_record, dict):
        return ""
    text = _safe_str(capture_record.get("visible_text_raw", ""))
    if not text:
        text = _safe_str(capture_record.get("title", ""))
    if not text:
        lines = capture_record.get("visible_text_lines", [])
        if isinstance(lines, list):
            text = " ".join([_safe_str(x) for x in lines])
    return _normalize_gump_text(text)


def _normalize_material_candidate_name(value):
    """Normalize noisy material labels into canonical material names."""
    text = _pipe_field(value)
    if not text:
        return ""

    lowered = text.lower()
    prefixes = (
        "smelt item ",
        "item ",
        "not color ",
        "not colored ",
        "color ",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if lowered.startswith(prefix):
                text = _pipe_field(text[len(prefix):])
                lowered = text.lower()
                changed = True
                break

    if not text:
        return ""

    for allowed_name in BLACKSMITH_MATERIAL_NAME_WHITELIST:
        allowed_text = _pipe_field(allowed_name)
        if lowered == allowed_text.lower():
            return allowed_text

    return _pipe_field(text.title())


def _extract_material_names_from_text(capture_text):
    """Extract material labels from menu text that uses '(count)' markers."""
    text = _normalize_gump_text(capture_text)
    if not text:
        return []

    lowered = text.lower()
    if "blacksmithing menu" not in lowered:
        return []

    allowed = set([_safe_str(x).lower() for x in BLACKSMITH_MATERIAL_NAME_WHITELIST])
    blocked_tokens = (
        "completed",
        "smelt",
        "menu",
        "blacksmithing",
        "categories",
        "selections",
        "notices",
        "last ten",
        "next page",
        "prev page",
        "make last",
        "repair",
        "enhance",
        "alter",
        "quest",
        "exit",
        "cancel",
        "you haven't made",
    )

    out = []
    seen = set()
    for match in re.finditer(r"\b([A-Za-z][A-Za-z'()\-]*(?:\s+[A-Za-z][A-Za-z'()\-]*){0,3})\s*\((\d+)\)", text):
        candidate = _normalize_material_candidate_name(match.group(1))
        if not candidate:
            continue
        low = candidate.lower()
        if not low:
            continue
        if any(token in low for token in blocked_tokens):
            continue
        if low not in allowed and not low.endswith("scales"):
            continue
        cleaned = candidate.title()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _material_root_button_from_path(path_buttons):
    """Return material root button from path when known."""
    ids = [_safe_int(x, 0) for x in (path_buttons or []) if _safe_int(x, 0) > 0]
    for bid in reversed(ids):
        if int(bid) in (7, 147):
            return int(bid)
    return 0


def _material_option_buttons(capture_record):
    """Return stable upper-right material option button IDs ordered by row."""
    if not isinstance(capture_record, dict):
        return []
    grouped = {}
    for button in (capture_record.get("buttons_discovered", []) or []):
        if not isinstance(button, dict):
            continue
        bid = _safe_int(button.get("button_id", 0), 0)
        source = _safe_str(button.get("source_command", "")).strip().lower()
        x = _safe_opt_int(button.get("x"))
        y = _safe_opt_int(button.get("y"))
        if bid <= 0 or x is None or y is None:
            continue
        if source != "ui_button":
            continue
        # Material options render in the selections list (upper-right column).
        if x < 205 or x > 265 or y < 55 or y > 285:
            continue
        row = int(y)
        current = grouped.get(row)
        if current is None or int(bid) < int(current):
            grouped[row] = int(bid)
    if not grouped:
        return []
    return [int(grouped[row]) for row in sorted(grouped.keys())]


def _format_button_path(path_buttons):
    """Format path button list for pipe export."""
    ids = [_safe_int(x, 0) for x in (path_buttons or []) if _safe_int(x, 0) > 0]
    if not ids:
        return "[]"
    return "[{0}]".format(",".join([_safe_str(x) for x in ids]))


def _build_material_pipe_rows(run_payload):
    """Build one deterministic output row per discovered material option."""
    rows = []
    if not isinstance(run_payload, dict):
        return rows
    manifest = run_payload.get("manifest", {})
    gumps = run_payload.get("gumps", [])
    if not isinstance(manifest, dict) or not isinstance(gumps, list):
        return rows

    server = _pipe_field(manifest.get("profile", {}).get("server_name", "")) or "unknown_shard"
    profession = _extract_profession_name(run_payload)

    seen = set()
    ordered = sorted(gumps, key=lambda x: _safe_int(x.get("capture_index", 0), 0))
    for rec in ordered:
        if not isinstance(rec, dict):
            continue

        path_buttons = [_safe_int(x, 0) for x in (rec.get("path_button_ids", []) or []) if _safe_int(x, 0) > 0]
        material_root = _material_root_button_from_path(path_buttons)
        if material_root <= 0:
            continue

        capture_text = _capture_text_for_material_rows(rec)
        material_names = _extract_material_names_from_text(capture_text)
        if not material_names:
            continue
        if int(material_root) == 7:
            allowed_ingots = set([_safe_str(x).lower() for x in BLACKSMITH_INGOT_NAME_WHITELIST])
            material_names = [name for name in material_names if _safe_str(name).lower() in allowed_ingots]
        elif int(material_root) == 147:
            allowed_scales = set([_safe_str(x).lower() for x in BLACKSMITH_SCALE_NAME_WHITELIST])
            material_names = [name for name in material_names if _safe_str(name).lower() in allowed_scales]
        if not material_names:
            continue

        option_buttons = _material_option_buttons(rec)
        if not option_buttons:
            continue

        limit = min(len(material_names), len(option_buttons))
        for idx in range(limit):
            material_name = _safe_str(material_names[idx]).strip()
            option_button = _safe_int(option_buttons[idx], 0)
            if not material_name or option_button <= 0:
                continue
            button_path = _format_button_path([int(material_root), int(option_button)])
            key = "{0}|{1}".format(material_name.lower(), button_path)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "server": server,
                    "profession": profession,
                    "material_name": material_name,
                    "button_path": button_path,
                }
            )

    rows.sort(key=lambda r: (_safe_str(r.get("material_name", "")).lower(), _safe_str(r.get("button_path", ""))))
    return rows


def _materials_pipe_output_text(run_payload, rows=None):
    """Build full pipe-delimited text output for materials."""
    source_rows = rows if isinstance(rows, list) else _build_material_pipe_rows(run_payload)
    lines = ["Server|Profession|Material Name|Button Path"]
    for row in source_rows:
        lines.append(
            "{0}|{1}|{2}|{3}".format(
                _pipe_field(row.get("server", "")),
                _pipe_field(row.get("profession", "")),
                _pipe_field(row.get("material_name", "")),
                _pipe_field(row.get("button_path", "")),
            )
        )
    return "\n".join(lines) + "\n"


def export_materials_pipe(run_payload, output_path):
    """Export one pipe-delimited row per discovered material option."""
    path = _safe_str(output_path).strip()
    if not path:
        _diag("warn", "materials_pipe_export_skipped", {"reason": "empty_path"})
        return False

    _diag("info", "materials_pipe_export_start", {"path": path})
    rows = _build_material_pipe_rows(run_payload)

    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(_materials_pipe_output_text(run_payload, rows))
        _diag("info", "materials_pipe_export_success", {"path": path, "row_count": len(rows)})
        return True
    except Exception as ex:
        _diag("error", "materials_pipe_export_failed", {"path": path, "error": _safe_str(ex)})
        return False


def export_json(run_payload, output_path):
    """Export machine-readable JSON."""
    path = _safe_str(output_path).strip()
    if not path:
        return False
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(run_payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        return True
    except Exception as ex:
        _diag("error", "json_export_failed", {"path": path, "error": _safe_str(ex)})
        return False


def _tree_lines(run_payload):
    """Build text tree view of gump transitions."""
    lines = []
    manifest = run_payload.get("manifest", {}) if isinstance(run_payload, dict) else {}
    gumps = run_payload.get("gumps", []) if isinstance(run_payload, dict) else []
    edges = run_payload.get("edges", []) if isinstance(run_payload, dict) else []

    by_id = {}
    for rec in gumps:
        if isinstance(rec, dict):
            by_id[_safe_str(rec.get("capture_id", ""))] = rec

    children = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        parent_id = _safe_str(edge.get("parent_capture_id", ""))
        if not parent_id:
            continue
        if parent_id not in children:
            children[parent_id] = []
        children[parent_id].append(edge)

    for parent_id in children.keys():
        children[parent_id] = sorted(children[parent_id], key=lambda e: (_safe_int(e.get("button_id", 0), 0), _safe_str(e.get("child_capture_id", "")), _safe_str(e.get("result_kind", ""))))

    root_id = _safe_str(manifest.get("root_capture_id", ""))
    if not root_id:
        return ["(no root)"]

    queue = deque([(root_id, 0)])
    seen = set()
    while queue:
        cid, depth = queue.popleft()
        if cid in seen:
            continue
        seen.add(cid)
        rec = by_id.get(cid, {})
        lines.append("{0}{1} depth={2} hash={3} title={4}".format("  " * int(depth), cid, _safe_int(rec.get("depth", depth), depth), _safe_str(rec.get("layout_hash", ""))[:12], _safe_str(rec.get("title", ""))))
        for edge in children.get(cid, []):
            bid = _safe_int(edge.get("button_id", 0), 0)
            child_id = _safe_str(edge.get("child_capture_id", ""))
            kind = _safe_str(edge.get("result_kind", ""))
            lines.append("{0}  -- button {1} ({2}) --> {3}".format("  " * int(depth), int(bid), kind, child_id if child_id else "<none>"))
            if child_id and child_id not in seen:
                queue.append((child_id, int(depth) + 1))
    return lines


def _txt_report(run_payload):
    """Build human-readable TXT report."""
    manifest = run_payload.get("manifest", {}) if isinstance(run_payload, dict) else {}
    stats = manifest.get("stats", {}) if isinstance(manifest, dict) else {}
    gumps = run_payload.get("gumps", []) if isinstance(run_payload, dict) else []

    lines = []
    lines.append("Gump Mapper Report")
    lines.append("Run ID: {0}".format(_safe_str(manifest.get("run_id", ""))))
    lines.append("Started: {0}".format(_safe_str(manifest.get("started_at_utc", ""))))
    lines.append("Finished: {0}".format(_safe_str(manifest.get("finished_at_utc", ""))))
    lines.append("Server: {0}".format(_safe_str(manifest.get("profile", {}).get("server_name", ""))))
    lines.append("Character: {0}".format(_safe_str(manifest.get("profile", {}).get("character_name", ""))))
    lines.append("Root Serial: 0x{0:08X}".format(_safe_int(manifest.get("root_target_serial", 0), 0)))
    lines.append("Root Capture: {0}".format(_safe_str(manifest.get("root_capture_id", ""))))
    lines.append("Root Hash: {0}".format(_safe_str(manifest.get("root_layout_hash", ""))))
    lines.append("Diagnostic Log: {0}".format(_safe_str(manifest.get("diagnostic_log_path", ""))))
    lines.append("Stop Reason: {0}".format(_safe_str(manifest.get("stop_reason", ""))))
    lines.append("")
    lines.append("Stats")
    lines.append("- Total gumps: {0}".format(_safe_int(stats.get("total_gumps", 0), 0)))
    lines.append("- Total edges: {0}".format(_safe_int(stats.get("total_edges", 0), 0)))
    lines.append("- Button attempts: {0}".format(_safe_int(stats.get("button_attempts", 0), 0)))
    lines.append("- Unique interactions: {0}".format(_safe_int(stats.get("unique_interactions", 0), 0)))
    lines.append("")
    lines.append("Transition Tree")
    lines.extend(_tree_lines(run_payload))
    lines.append("")

    for rec in sorted(gumps, key=lambda x: _safe_int(x.get("capture_index", 0), 0)):
        lines.append("=" * 72)
        lines.append("{0} | gump_id={1} | depth={2}".format(_safe_str(rec.get("capture_id", "")), _safe_int(rec.get("gump_id", 0), 0), _safe_int(rec.get("depth", 0), 0)))
        lines.append("layout_hash={0}".format(_safe_str(rec.get("layout_hash", ""))))
        lines.append("text_hash={0}".format(_safe_str(rec.get("text_hash", ""))))
        lines.append("title={0}".format(_safe_str(rec.get("title", ""))))
        lines.append("parents={0}".format(rec.get("parent_capture_ids", [])))
        lines.append("path_buttons={0}".format(rec.get("path_button_ids", [])))
        lines.append("")

        lines.append("Visible Text")
        vlines = rec.get("visible_text_lines", []) or []
        if vlines:
            for idx, line in enumerate(vlines):
                lines.append("  [{0}] {1}".format(int(idx), _safe_str(line)))
        else:
            lines.append("  (none)")
        lines.append("")

        lines.append("Buttons")
        buttons = rec.get("buttons_discovered", []) or []
        if buttons:
            for b in buttons:
                lines.append("  button_id={0} x={1} y={2} source={3} label={4}".format(_safe_int(b.get("button_id", 0), 0), "?" if b.get("x") is None else _safe_int(b.get("x"), 0), "?" if b.get("y") is None else _safe_int(b.get("y"), 0), _safe_str(b.get("source_command", "")), _safe_str(b.get("inferred_label", ""))))
        else:
            lines.append("  (none)")

        parser = rec.get("parser_output", {}) if isinstance(rec, dict) else {}
        pstats = parser.get("stats", {}) if isinstance(parser, dict) else {}
        lines.append("Parser stats: blocks={0} tokens={1} nodes={2} errors={3} unknown={4}".format(_safe_int(pstats.get("block_count", 0), 0), _safe_int(pstats.get("token_count", 0), 0), _safe_int(pstats.get("node_count", 0), 0), _safe_int(pstats.get("error_count", 0), 0), _safe_int(pstats.get("unknown_command_count", 0), 0)))

    return "\n".join(lines)


def export_txt(run_payload, output_path):
    """Export human-readable TXT report."""
    path = _safe_str(output_path).strip()
    if not path:
        return False
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(_txt_report(run_payload))
        return True
    except Exception as ex:
        _diag("error", "txt_export_failed", {"path": path, "error": _safe_str(ex)})
        return False


def _confirm_export(paths):
    """Request operator confirmation before writing files."""
    if not REQUIRE_SAVE_CONFIRMATION:
        _diag(
            "trace",
            "main_export_auto_confirmed",
            {
                "json_path": _safe_str(paths.get("json", "")),
                "txt_path": _safe_str(paths.get("txt", "")),
                "items_pipe_path": _safe_str(paths.get("items_pipe", "")),
                "materials_pipe_path": _safe_str(paths.get("materials_pipe", "")),
            },
        )
        return True
    _sys("Ready to export gump map.", DEFAULT_HUE)
    _sys("JSON: {0}".format(_safe_str(paths.get("json", ""))), DEFAULT_HUE)
    _sys("TXT : {0}".format(_safe_str(paths.get("txt", ""))), DEFAULT_HUE)
    _sys("ITEM: {0}".format(_safe_str(paths.get("items_pipe", ""))), DEFAULT_HUE)
    _sys("MAT : {0}".format(_safe_str(paths.get("materials_pipe", ""))), DEFAULT_HUE)
    _sys("Target any object to confirm save. Cancel to skip.", DEFAULT_HUE)
    return _request_target(15.0) > 0


def main():
    """Run full gump mapper workflow."""
    RUN_DIAGNOSTICS[:] = []
    _ABORT_CACHE["last_check"] = 0.0
    _ABORT_CACHE["value"] = False
    _DIAG_LOG_STATE["enabled"] = False
    _DIAG_LOG_STATE["path"] = ""
    _DIAG_LOG_STATE["session_id"] = ""
    _DIAG_LOG_STATE["sequence"] = 0
    _CONNECTION_DIAG["events_registered"] = False
    _CONNECTION_DIAG["last_event"] = ""
    _CONNECTION_DIAG["last_event_utc"] = ""
    _CONNECTION_DIAG["connected_event_count"] = 0
    _CONNECTION_DIAG["disconnected_event_count"] = 0
    _CONNECTION_DIAG["event_hook_error"] = ""
    _RUNTIME_DIAG["last_good_gump_time"] = float(time.time())
    _RUNTIME_DIAG["no_gump_events"] = 0
    _RUNTIME_DIAG["last_suspect_log_time"] = 0.0
    _RUNTIME_DIAG["last_journal_scan_time"] = 0.0
    _RUNTIME_DIAG["journal_last_text"] = ""
    _RUNTIME_DIAG["journal_last_match"] = ""
    _RUNTIME_DIAG["journal_match_count"] = 0
    _RUNTIME_DIAG["journal_last_logged_match"] = ""
    _RUNTIME_DIAG["last_stop_requested"] = False
    _RUNTIME_DIAG["host_stop_transition_seen"] = False
    _RUNTIME_DIAG["host_stop_transition_utc"] = ""
    _RUNTIME_DIAG["host_stop_disconnect_suspected"] = False
    _RUNTIME_DIAG["action_ring"] = deque([], int(ACTION_RING_MAX))
    _dispose_progress_gump()

    _sys("GumpMapper loaded.", DEFAULT_HUE)
    _sys("Set persistent var '{0}' to 1 to request stop.".format(ABORT_FLAG_KEY), DEFAULT_HUE)

    if _stop_requested():
        _sys("Stop requested before start.", WARN_HUE)
        return

    config = _load_config()
    profile = _profile_context()
    resolved_profile, clear_cache_requested = _resolve_profile_server_name(config, profile)
    if not isinstance(resolved_profile, dict):
        _sys("Server name entry canceled. Stopping.", WARN_HUE)
        _diag("warn", "server_name_prompt_canceled")
        return
    profile = resolved_profile
    _save_config(config)
    export_dir = _export_dir(config)
    resume_state = _load_resume_state()
    if clear_cache_requested:
        _sys("Clearing cached checkpoint data before run.", DEFAULT_HUE)
        _diag("info", "main_cache_clear_requested", {"profile": copy.deepcopy(profile)})
        _clear_cached_resume_artifacts(resume_state)
        _clear_resume_state()
        resume_state = _default_resume_state()

    resume_context = None
    root_serial = 0
    session_id = ""
    live_json_path = ""
    live_txt_path = ""
    live_items_pipe_path = ""
    live_materials_pipe_path = ""
    diag_log_path = ""
    final_json_hint = ""
    final_txt_hint = ""
    final_items_pipe_hint = ""
    final_materials_pipe_hint = ""

    has_checkpoint = (
        _safe_str(resume_state.get("status", "")).strip().lower() == "running"
        and _safe_str(resume_state.get("checkpoint_json_path", "")).strip()
        and os.path.exists(_safe_str(resume_state.get("checkpoint_json_path", "")).strip())
    )
    if has_checkpoint:
        checkpoint_profile = resume_state.get("profile", {}) if isinstance(resume_state.get("profile"), dict) else {}
        same_server = _safe_str(checkpoint_profile.get("server_name", "")).strip().lower() == _safe_str(profile.get("server_name", "")).strip().lower()
        same_char = _safe_str(checkpoint_profile.get("character_name", "")).strip().lower() == _safe_str(profile.get("character_name", "")).strip().lower()
        if same_server and same_char:
            _sys("Found resumable GumpMapper session.", DEFAULT_HUE)
            _sys("Target any object to resume. Cancel target to start a new session.", DEFAULT_HUE)
            if _request_target(15.0) > 0:
                checkpoint_payload = _read_json_file(_safe_str(resume_state.get("checkpoint_json_path", "")).strip())
                resume_context = _restore_resume_context(
                    checkpoint_payload,
                    _safe_int(resume_state.get("root_target_serial", 0), 0),
                    profile,
                )
                if resume_context is None:
                    _sys("Resume checkpoint is invalid. Starting a new session.", WARN_HUE)
                    _clear_resume_state()
                else:
                    root_serial = _safe_int(resume_context.get("root_target_serial", 0), 0)
                    session_id = _safe_str(resume_state.get("session_id", "")).strip() or "{0}_{1}".format(SCRIPT_NAME, _utc_now_compact())
                    live_json_path = _safe_str(resume_state.get("checkpoint_json_path", "")).strip()
                    live_txt_path = _safe_str(resume_state.get("checkpoint_txt_path", "")).strip()
                    live_items_pipe_path = _safe_str(resume_state.get("checkpoint_items_pipe_path", "")).strip()
                    live_materials_pipe_path = _safe_str(resume_state.get("checkpoint_materials_pipe_path", "")).strip()
                    diag_log_path = _safe_str(resume_state.get("diagnostic_log_path", "")).strip()
                    final_json_hint = _safe_str(resume_state.get("final_json_path", "")).strip()
                    final_txt_hint = _safe_str(resume_state.get("final_txt_path", "")).strip()
                    final_items_pipe_hint = _safe_str(resume_state.get("final_items_pipe_path", "")).strip()
                    final_materials_pipe_hint = _safe_str(resume_state.get("final_materials_pipe_path", "")).strip()
                    _sys("Resuming previous mapping session.", DEFAULT_HUE)
            else:
                _sys("Starting new session and ignoring previous checkpoint.", DEFAULT_HUE)
                _clear_resume_state()
        else:
            _sys("Found checkpoint for a different profile. Starting new session.", WARN_HUE)
            _clear_resume_state()

    if root_serial <= 0:
        root_serial = _select_root_serial(config)
    if root_serial <= 0:
        _sys("No root serial selected. Stopping.", WARN_HUE)
        return

    if not session_id:
        session_id = "{0}_{1}".format(SCRIPT_NAME, _utc_now_compact())
    if not live_json_path or not live_txt_path or not live_items_pipe_path or not live_materials_pipe_path:
        provisional_paths = _export_paths(export_dir, profile, session_id[-8:])
        live_json_path = _safe_str(provisional_paths.get("live_json", ""))
        live_txt_path = _safe_str(provisional_paths.get("live_txt", ""))
        live_items_pipe_path = _safe_str(provisional_paths.get("live_items_pipe", ""))
        live_materials_pipe_path = _safe_str(provisional_paths.get("live_materials_pipe", ""))
        diag_log_path = _safe_str(provisional_paths.get("diag_log", ""))
        final_json_hint = _safe_str(provisional_paths.get("json", ""))
        final_txt_hint = _safe_str(provisional_paths.get("txt", ""))
        final_items_pipe_hint = _safe_str(provisional_paths.get("items_pipe", ""))
        final_materials_pipe_hint = _safe_str(provisional_paths.get("materials_pipe", ""))
    if not diag_log_path:
        diag_log_path = _derive_diag_path_from_live_json(live_json_path)
    if not live_items_pipe_path:
        if _safe_str(live_txt_path).strip().lower().endswith(".txt"):
            live_items_pipe_path = _safe_str(live_txt_path)[:-4] + "_items_pipe.txt"
        else:
            live_items_pipe_path = _safe_str(live_txt_path) + "_items_pipe.txt"
    if not live_materials_pipe_path:
        if _safe_str(live_txt_path).strip().lower().endswith(".txt"):
            live_materials_pipe_path = _safe_str(live_txt_path)[:-4] + "_materials_pipe.txt"
        else:
            live_materials_pipe_path = _safe_str(live_txt_path) + "_materials_pipe.txt"
    if not final_items_pipe_hint:
        if _safe_str(final_txt_hint).strip().lower().endswith(".txt"):
            final_items_pipe_hint = _safe_str(final_txt_hint)[:-4] + "_items_pipe.txt"
        else:
            final_items_pipe_hint = _safe_str(final_txt_hint) + "_items_pipe.txt"
    if not final_materials_pipe_hint:
        if _safe_str(final_txt_hint).strip().lower().endswith(".txt"):
            final_materials_pipe_hint = _safe_str(final_txt_hint)[:-4] + "_materials_pipe.txt"
        else:
            final_materials_pipe_hint = _safe_str(final_txt_hint) + "_materials_pipe.txt"

    _create_progress_gump(profile, root_serial, session_id)
    _update_progress_gump_from_stats({}, "", "initializing")

    _configure_diag_log(diag_log_path, session_id)
    _register_connection_event_hooks()
    _diag(
        "info",
        "main_session_start",
        {
            "session_id": _safe_str(session_id),
            "resume_mode": bool(resume_context is not None),
            "profile": copy.deepcopy(profile),
            "root_target_serial": int(root_serial),
            "live_json_path": _safe_str(live_json_path),
            "live_txt_path": _safe_str(live_txt_path),
            "diag_log_path": _safe_str(diag_log_path),
            "connection": _connection_health_snapshot(),
        },
    )

    live_state = {
        "enabled": True,
        "session_id": session_id,
        "live_json_path": live_json_path,
        "live_txt_path": live_txt_path,
        "live_items_pipe_path": live_items_pipe_path,
        "live_materials_pipe_path": live_materials_pipe_path,
        "diagnostic_log_path": diag_log_path,
        "final_json_path": final_json_hint,
        "final_txt_path": final_txt_hint,
        "final_items_pipe_path": final_items_pipe_hint,
        "final_materials_pipe_path": final_materials_pipe_hint,
        "profile": copy.deepcopy(profile),
        "root_target_serial": int(root_serial),
    }
    _save_resume_state(
        {
            "session_id": session_id,
            "status": "running",
            "checkpoint_json_path": live_json_path,
            "checkpoint_txt_path": live_txt_path,
            "checkpoint_items_pipe_path": live_items_pipe_path,
            "checkpoint_materials_pipe_path": live_materials_pipe_path,
            "diagnostic_log_path": diag_log_path,
            "final_json_path": final_json_hint,
            "final_txt_path": final_txt_hint,
            "final_items_pipe_path": final_items_pipe_hint,
            "final_materials_pipe_path": final_materials_pipe_hint,
            "root_target_serial": int(root_serial),
            "profile": copy.deepcopy(profile),
        }
    )

    _sys("Live JSON checkpoint: {0}".format(_safe_str(live_json_path)), DEFAULT_HUE)
    _sys("Live TXT checkpoint: {0}".format(_safe_str(live_txt_path)), DEFAULT_HUE)
    _sys("Live ITEM checkpoint: {0}".format(_safe_str(live_items_pipe_path)), DEFAULT_HUE)
    _sys("Live MAT checkpoint: {0}".format(_safe_str(live_materials_pipe_path)), DEFAULT_HUE)
    _sys("Diagnostic log: {0}".format(_safe_str(diag_log_path)), DEFAULT_HUE)

    config["last_root_target_serial"] = int(root_serial)
    config["last_shard_profile"] = _safe_str(profile.get("server_name", ""))
    config["last_character_name"] = _safe_str(profile.get("character_name", ""))
    _save_config(config)

    run_payload = traverse_gumps(root_serial, profile, live_state=live_state, resume_context=resume_context)
    manifest = run_payload.get("manifest", {}) if isinstance(run_payload, dict) else {}
    stats = manifest.get("stats", {}) if isinstance(manifest, dict) else {}
    _diag(
        "info",
        "main_traversal_complete",
        {
            "stop_reason": _safe_str(manifest.get("stop_reason", "")),
            "stats": copy.deepcopy(stats),
        },
    )
    _update_progress_gump_from_stats(stats, _safe_str(manifest.get("stop_reason", "")), "traversal_complete")

    _sys("GumpMapper summary: gumps={0}, edges={1}, button_attempts={2}".format(_safe_int(stats.get("total_gumps", 0), 0), _safe_int(stats.get("total_edges", 0), 0), _safe_int(stats.get("button_attempts", 0), 0)), DEFAULT_HUE)
    _sys("Stop reason: {0}".format(_safe_str(manifest.get("stop_reason", "completed"))), DEFAULT_HUE)

    stop_reason_text = _safe_str(manifest.get("stop_reason", "")).strip().lower()
    if stop_reason_text == "disconnect_suspected":
        _sys("Disconnect suspected during traversal. Skipping final export.", WARN_HUE)
        _diag(
            "warn",
            "main_export_skipped_disconnect_suspected",
            {"stop_reason": _safe_str(manifest.get("stop_reason", ""))},
        )
        _dispose_progress_gump()
        return

    if _safe_int(stats.get("total_gumps", 0), 0) <= 0:
        _sys("No gumps captured. Nothing to export.", WARN_HUE)
        _dispose_progress_gump()
        return

    paths = _export_paths(export_dir, profile, _safe_str(manifest.get("root_layout_hash", "")))
    _update_progress_gump_from_stats(stats, _safe_str(manifest.get("stop_reason", "")), "export_pending")
    if not _confirm_export(paths):
        _sys("Export canceled by operator.", WARN_HUE)
        _diag("warn", "main_export_canceled")
        _update_progress_gump_from_stats(stats, _safe_str(manifest.get("stop_reason", "")), "export_canceled")
        if _safe_str(manifest.get("stop_reason", "")).strip().lower() == "completed":
            _clear_resume_state()
        _dispose_progress_gump()
        return

    _update_progress_gump_from_stats(stats, _safe_str(manifest.get("stop_reason", "")), "exporting")
    ok_json = export_json(run_payload, _safe_str(paths.get("json", "")))
    ok_txt = export_txt(run_payload, _safe_str(paths.get("txt", "")))
    ok_items = export_items_pipe(run_payload, _safe_str(paths.get("items_pipe", "")))
    ok_materials = export_materials_pipe(run_payload, _safe_str(paths.get("materials_pipe", "")))
    _diag(
        "info"
        if (ok_json and ok_txt and ok_items and ok_materials and _safe_str(manifest.get("stop_reason", "")).strip().lower() == "completed")
        else "warn",
        "main_export_result",
        {
            "ok_json": bool(ok_json),
            "ok_txt": bool(ok_txt),
            "ok_items_pipe": bool(ok_items),
            "ok_materials_pipe": bool(ok_materials),
            "json_path": _safe_str(paths.get("json", "")),
            "txt_path": _safe_str(paths.get("txt", "")),
            "items_pipe_path": _safe_str(paths.get("items_pipe", "")),
            "materials_pipe_path": _safe_str(paths.get("materials_pipe", "")),
        },
    )

    if ok_json and ok_txt and ok_items and ok_materials:
        config["last_export_folder"] = _safe_str(paths.get("folder", ""))
        _save_config(config)
        if stop_reason_text == "completed":
            _sys("Export complete.", GOOD_HUE)
        else:
            _sys(
                "Partial export complete. Traversal stopped early: {0}".format(
                    _safe_str(manifest.get("stop_reason", "unknown"))
                ),
                WARN_HUE,
            )
        _sys(_safe_str(paths.get("json", "")), GOOD_HUE)
        _sys(_safe_str(paths.get("txt", "")), GOOD_HUE)
        _sys(_safe_str(paths.get("items_pipe", "")), GOOD_HUE)
        _sys(_safe_str(paths.get("materials_pipe", "")), GOOD_HUE)
        _update_progress_gump_from_stats(
            stats,
            _safe_str(manifest.get("stop_reason", "")),
            "export_complete" if stop_reason_text == "completed" else "export_partial",
        )
        if stop_reason_text == "completed":
            _clear_resume_state()
        else:
            _save_resume_state(
                {
                    "session_id": session_id,
                    "status": "running",
                    "checkpoint_json_path": _safe_str(live_json_path),
                    "checkpoint_txt_path": _safe_str(live_txt_path),
                    "checkpoint_items_pipe_path": _safe_str(live_items_pipe_path),
                    "checkpoint_materials_pipe_path": _safe_str(live_materials_pipe_path),
                    "diagnostic_log_path": _safe_str(diag_log_path),
                    "final_json_path": _safe_str(paths.get("json", "")),
                    "final_txt_path": _safe_str(paths.get("txt", "")),
                    "final_items_pipe_path": _safe_str(paths.get("items_pipe", "")),
                    "final_materials_pipe_path": _safe_str(paths.get("materials_pipe", "")),
                    "root_target_serial": int(root_serial),
                    "profile": copy.deepcopy(profile),
                }
            )
    else:
        _sys("Export failed. Check diagnostics.", WARN_HUE)
        _update_progress_gump_from_stats(stats, _safe_str(manifest.get("stop_reason", "")), "export_failed")
        _save_resume_state(
            {
                "session_id": session_id,
                "status": "running",
                "checkpoint_json_path": _safe_str(live_json_path),
                "checkpoint_txt_path": _safe_str(live_txt_path),
                "checkpoint_items_pipe_path": _safe_str(live_items_pipe_path),
                "checkpoint_materials_pipe_path": _safe_str(live_materials_pipe_path),
                "diagnostic_log_path": _safe_str(diag_log_path),
                "final_json_path": _safe_str(paths.get("json", "")),
                "final_txt_path": _safe_str(paths.get("txt", "")),
                "final_items_pipe_path": _safe_str(paths.get("items_pipe", "")),
                "final_materials_pipe_path": _safe_str(paths.get("materials_pipe", "")),
                "root_target_serial": int(root_serial),
                "profile": copy.deepcopy(profile),
            }
        )
    _dispose_progress_gump()


def _should_autostart_main():
    """Return true for supported script runner entrypoint names."""
    module_name = _safe_str(globals().get("__name__", ""))
    if module_name in ("__main__", "<module>"):
        return True
    return module_name.endswith(".GumpMapper") or module_name.endswith("GumpMapper")


if _should_autostart_main():
    main()

