import API
import json
import ast
import os
import re
import sys

"""
Crafter Trainer

Features:
- Gump-based multi-skill crafting trainer with per-skill target caps.
- Trains skills in gump order (top to bottom) and stops each at its cap.
- Tinkering is first (can be used to craft tools for other skills).
- Includes Blacksmithing training steps from BlackSmithTrainer.

Setup:
1) Enter target caps for the skills you want to train.
2) Press Start; the script will train each skill in order.
3) When prompted, target required containers (stock/salvage) for Blacksmithing.
"""

# === GUMP ===
GUMP_X = 420
GUMP_Y = 260
GUMP_W = 430
ROW_H = 24

CRAFT_SKILLS = [
    "Tinkering",
    "Blacksmithy",
    "Tailoring",
    "Carpentry",
    "Imbuing",
    "Alchemy",
    "Inscription",
    "Bowcraft/Fletching",
    "Cooking",
]

FREE_SKILLS = {"Bowcraft/Fletching", "Cooking"}

SKILL_CAPS = {name: 0.0 for name in CRAFT_SKILLS}
TEXT_INPUTS = {}
RUNNING = False
CONTROL_GUMP = None
CONTROL_BUTTON = None
USE_TOOL_CRAFTING = False
DATA_KEY = "crafter_trainer_config"
SERVER_OPTIONS = ["OSI", "UOAlive", "Sosaria Reforged", "InsaneUO"]
DEFAULT_SERVER = "UOAlive"
SELECTED_SERVER = DEFAULT_SERVER
RECIPE_TYPE_TRAINING = "training"
RECIPE_EDITOR_REQUEST_KEY = "recipe_editor_request"
RECIPE_EDITOR_SCRIPT_CANDIDATES = [
    "RecipeBookEditor.py",
    "RecipeBookEditor",
    "Utilities/RecipeBookEditor.py",
    "Utilities\\RecipeBookEditor.py",
]
RECIPE_EDITOR_FILE_CANDIDATES = [
    os.path.join("Utilities", "RecipeBookEditor.py"),
    "RecipeBookEditor.py",
]
RECIPE_EDITOR_NONCE = 0
RECIPE_EDITOR_RESULT_KEY = "recipe_editor_result"

RECIPE_STORE = None
try:
    _this_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
except Exception:
    _this_dir = os.getcwd()
_util_dir = os.path.normpath(os.path.join(_this_dir, "..", "Utilities"))
if _util_dir and _util_dir not in sys.path:
    sys.path.append(_util_dir)
try:
    import RecipeStore as RECIPE_STORE
except Exception:
    RECIPE_STORE = None

# === BLACKSMITH SETTINGS (copied from BlackSmithTrainer) ===
SKILL_TARGET = 120.0  # Default max skill target.

INGOT_ID = 0x1BF2
IRON_INGOT_HUE = 0
MIN_INGOTS_IN_PACK = 50
RESTOCK_AMOUNT = 300

RESTOCK_TOOLS = True
BLACKSMITH_TOOL_IDS = [0x0FBB]  # Tongs

PAUSE_DRAG = 600
PAUSE_GUMP_CLICK = 300
PAUSE_AFTER_CRAFT = 250
CRAFT_TIMEOUT_MS = 5000
OPEN_MENU_TIMEOUT_S = 15
GUMP_POLL_MS = 200

STATUS_HUE = 17
WARN_HUE = 33
BACKPACK_ITEM_THRESHOLD = 125
ALLOW_KEEP_GRAPHICS = [
    0x1BF2,  # Ingots
    0x1766,  # Cloth
    0x0E21,  # Bandages
    0x1081,  # Leather
    0x0F9F,  # Scissors
    0x0FBB,  # Tongs
]

SALVAGE_CONTEXT_INDEX = 2

BLACKSMITH_GUMP_ANCHORS = [
    "BLACKSMITHING MENU",
    "BLACKSMITHING",
    "BLACKSMITH",
]
BLACKSMITH_GUMP_ID = 0xD466EA9C
TINKER_GUMP_ANCHORS = [
    "TINKERING MENU",
    "TINKERING",
    "TINKER",
]
TAILOR_GUMP_ANCHORS = [
    "TAILORING MENU",
    "TAILORING",
    "TAILOR",
]
CARPENTRY_GUMP_ANCHORS = [
    "CARPENTRY MENU",
    "CARPENTRY",
    "CARPENTER",
]
BOWCRAFT_GUMP_ANCHORS = [
    "BOWCRAFT",
    "FLETCHING",
    "BOWYER",
]

GUMP_FAIL_TEXTS = [
    "you fail",
    "not enough",
    "you don't have",
    "you do not have",
    "insufficient",
    "must be near",
]

SWAP_WINDOW = 0.2
CHANGEOVER_PAUSE_MS = 600
POST_OPEN_PAUSE_MS = 150

STOCK_SERIAL = 0
SALVAGE_SERIAL = 0
TRASH_SERIAL = 0

# === TINKERING SETTINGS ===
TINKER_TOOL_GRAPHICS = [0x1EB8]  # Tinker's tools (UOAlive).
TINKER_GUMP_ID = 0xD466EA9C  # Tinkering gump id (UOAlive).
TINKER_BTN_TOOLS = 41  # Tools category button.
TINKER_BTN_TINKER_TOOL = 62  # Tinker tool button.
TINKER_BTN_TONGS = 242  # Tongs button.
TINKER_BTN_SEWING_KIT = [41, 122]  # Sewing kit buttons (page/category, item).
TINKER_BTN_SCISSORS = [41, 2]  # Scissors buttons (page/category, item).
TINKER_BTN_DOVETAIL_SAW = [41, 162]  # Dovetail saw buttons (page/category, item).

# === TAILORING SETTINGS ===
TAILOR_TOOL_GRAPHICS = [0x0F9D]  # Sewing kit.
TAILOR_GUMP_ID = 0xD466EA9C
CLOTH_ID = 0x1766
BOLT_OF_CLOTH_IDS = [0x0F97, 0x0F95, 0x0F96]
LEATHER_ID = 0x1081
MIN_CLOTH_IN_PACK = 20
MIN_LEATHER_IN_PACK = 20
RESTOCK_CLOTH_AMOUNT = 300
RESTOCK_LEATHER_AMOUNT = 200
TAILOR_CRAFT_SETTLE_MS = 1200

# === CARPENTRY SETTINGS ===
CARPENTRY_TOOL_GRAPHICS = [0x1028, 0x102C, 0x1034, 0x1035]  # Common carpentry tools.
CARPENTRY_GUMP_ID = 0xD466EA9C
BOARD_ID = 0x1BD7
MIN_BOARDS_IN_PACK = 30
RESTOCK_BOARDS_AMOUNT = 400
CARPENTRY_CRAFT_SETTLE_MS = 1200

# === BOWCRAFT/FLETCHING SETTINGS ===
BOWCRAFT_TOOL_GRAPHICS = [0x1022]  # Fletcher's tools.
BOWCRAFT_GUMP_ID = 0xD466EA9C
FEATHER_ID = 0x1BD1
MIN_FEATHERS_IN_PACK = 20
RESTOCK_FEATHERS_AMOUNT = 300
BOWCRAFT_CRAFT_SETTLE_MS = 1200

# === INSCRIPTION SETTINGS ===
SCRIBE_PEN_ID = 0x0FBF
BLANK_SCROLL_ID = 0x0EF3
INSCRIPTION_REAGENTS = [0x0F86, 0x0F7B, 0x0F8C, 0x0F88, 0x0F7A, 0x0F85, 0x0F84]
INSCRIPTION_SCROLL_PULL = 30
INSCRIPTION_SCROLL_MIN = 5
INSCRIPTION_REAGENT_PULL = 30
INSCRIPTION_REAGENT_MIN = 5
INSCRIPTION_CRAFT_PAUSE_MS = 2000

# Mirrors InscriptTrainer ranges/buttons.
INSCRIPTION_STEPS = [
    {"start_at": 30.0, "name": "Recall", "page_button": 8, "spell_button": 107, "mana": 15},
    {"start_at": 55.0, "name": "Blade Spirit", "page_button": 15, "spell_button": 2, "mana": 15},
    {"start_at": 65.0, "name": "Energy Bolt", "page_button": 15, "spell_button": 65, "mana": 20},
    {"start_at": 80.0, "name": "Gate Travel", "page_button": 22, "spell_button": 23, "mana": 40},
    {"start_at": 94.0, "name": "Resurrection", "page_button": 22, "spell_button": 72, "mana": 50},
]

# Training craft steps are sourced exclusively from `Utilities/recipes.json`
# using `recipe_type=training`, selected `server`, and profession tags.
#
# Skill progression windows are defined in-script (server-specific) and then resolved
# against recipe-book craft metadata (buttons/item ids/material).
TRAINING_PLANS_BY_SERVER = {
    "UOAlive": {
        "Blacksmithy": [
            {"start_at": 40.0, "end_at": 45.0, "name": "Mace", "material_key": "ingot_iron"},
            {"start_at": 45.0, "end_at": 50.0, "name": "Maul", "material_key": "ingot_iron"},
            {"start_at": 50.0, "end_at": 55.0, "name": "Cutlass", "material_key": "ingot_iron"},
            {"start_at": 55.0, "end_at": 59.5, "name": "Katana", "material_key": "ingot_iron"},
            {"start_at": 59.5, "end_at": 70.5, "name": "Scimitar", "material_key": "ingot_iron"},
            {"start_at": 70.5, "end_at": 106.4, "name": "Platemail Gorget", "material_key": "ingot_iron"},
            {"start_at": 106.4, "end_at": 108.9, "name": "Platemail Gloves", "material_key": "ingot_iron"},
            {"start_at": 108.9, "end_at": 116.3, "name": "Platemail Arms", "material_key": "ingot_iron"},
            {"start_at": 116.3, "end_at": 118.8, "name": "Platemail Legs", "material_key": "ingot_iron"},
            {"start_at": 118.8, "end_at": 120.0, "name": "Platemail Tunic", "material_key": "ingot_iron"},
        ],
        "Tinkering": [
            {"start_at": 0.0, "end_at": 30.0, "action": "npc_training", "message": "Train from a Tinker NPC"},
            {"start_at": 30.0, "end_at": 45.0, "name": "Lockpick", "material_key": "ingot_iron"},
            {"start_at": 45.0, "end_at": 60.0, "name": "Scissors", "material_key": "ingot_iron"},
            {"start_at": 60.0, "end_at": 75.0, "name": "Gears", "material_key": "ingot_iron"},
            {"start_at": 75.0, "end_at": 90.0, "name": "Ring", "material_key": "ingot_iron"},
            {"start_at": 90.0, "end_at": 100.0, "name": "Spyglass", "material_key": "ingot_iron"},
            {
                "start_at": 100.0, "end_at": 120.0, "material_key": "ingot_iron",
                "any_of": [
                    "Brilliant Amber Bracelet",
                    "Fire Ruby Bracelet",
                    "Dark Sapphire Bracelet",
                    "White Pearl Bracelet",
                    "Ecru Citrine Bracelet",
                    "Blue Diamond Bracelet",
                    "Perfect Emerald Ring",
                    "Turquoise Ring",
                ],
            },
        ],
        "Tailoring": [
            {"start_at": 0.0, "end_at": 29.0, "action": "npc_training", "message": "Purchase skill gains from an NPC Tailor"},
            {"start_at": 29.0, "end_at": 35.0, "name": "Short Pants", "material_key": "cloth"},
            {"start_at": 35.0, "end_at": 41.4, "name": "Fur Capes", "material_key": "cloth"},
            {"start_at": 41.4, "end_at": 50.0, "name": "Cloaks", "material_key": "cloth"},
            {"start_at": 50.0, "end_at": 54.0, "name": "Fur Boots", "material_key": "cloth"},
            {"start_at": 54.0, "end_at": 65.0, "name": "Robes", "material_key": "cloth"},
            {"start_at": 65.0, "end_at": 72.0, "name": "Kasa", "material_key": "cloth"},
            {"start_at": 72.0, "end_at": 78.0, "name": "Ninja Tabi", "material_key": "cloth"},
            {"start_at": 78.0, "end_at": 110.0, "name": "Oil Cloth", "material_key": "cloth"},
            {"start_at": 110.0, "end_at": 115.0, "name": "Elven Shirt", "material_key": "cloth"},
            {"start_at": 115.0, "end_at": 120.0, "name": "Studded Hiro Sode", "material_key": "leather"},
        ],
        "Carpentry": [
            {"start_at": 0.0, "end_at": 30.0, "action": "npc_training", "message": "Train directly from a Carpenter NPC"},
            {"start_at": 30.0, "end_at": 48.0, "name": "Medium Crate", "material_key": "board"},
            {"start_at": 48.0, "end_at": 53.0, "name": "Large Crate", "material_key": "board"},
            {"start_at": 53.0, "end_at": 60.0, "name": "Wooden Shield", "material_key": "board"},
            {"start_at": 60.0, "end_at": 74.0, "name": "Fukiya", "material_key": "board"},
            {"start_at": 74.0, "end_at": 79.0, "name": "Quarter Staff", "material_key": "board"},
            {"start_at": 79.0, "end_at": 82.0, "name": "Gnarled Staff", "material_key": "board"},
            {"start_at": 82.0, "end_at": 96.0, "name": "Black Staff", "material_key": "board"},
            {"start_at": 96.0, "end_at": 120.0, "name": "Wild Staff", "material_key": "board"},
        ],
        "Bowcraft/Fletching": [
            {"start_at": 0.0, "end_at": 30.0, "action": "npc_training", "message": "Train from a Bowyer NPC"},
            {
                "start_at": 30.0, "end_at": 35.0, "name": "Shaft",
                "material_key": "board",
                "materials": [{"material": "board"}, {"material": "feather"}],
            },
            {"start_at": 35.0, "end_at": 55.0, "name": "Simple Bow", "material_key": "board"},
            {"start_at": 55.0, "end_at": 60.0, "name": "Fukiya Dart", "material_key": "board"},
            {"start_at": 60.0, "end_at": 70.0, "name": "Bow", "material_key": "board"},
            {"start_at": 70.0, "end_at": 80.0, "name": "Composite Bow", "material_key": "board"},
            {"start_at": 80.0, "end_at": 90.0, "name": "Heavy Crossbow", "material_key": "board"},
            {"start_at": 90.0, "end_at": 100.0, "name": "Repeating Crossbow", "material_key": "board"},
        ],
    },
}


# === GUMP HELPERS ===

def _pause_ms(ms):
    API.Pause(ms / 1000.0)


def _say(msg, hue=STATUS_HUE):
    API.SysMsg(msg, hue)


def _parse_cap(text):
    try:
        return float(text)
    except Exception:
        return 0.0


def _display_skill_name(name):
    if name in FREE_SKILLS:
        return f"{name} (free)"
    return name


def _normalize_server_name(value):
    v = str(value or "").strip().lower()
    for s in SERVER_OPTIONS:
        if s.lower() == v:
            return s
    return DEFAULT_SERVER


def _normalize_profession_name(name):
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


def _normalize_material_base(material, profession=""):
    m = str(material or "").strip().lower()
    if m in ("boards", "board"):
        return "board"
    if m in ("cloth", "leather", "ingot", "feather", "feathers"):
        if m == "feathers":
            return "feather"
        return m
    p = _normalize_profession_name(profession)
    if p in ("Blacksmith", "Tinker"):
        return "ingot"
    if p == "Carpentry":
        return "board"
    if p == "Tailor":
        return "cloth"
    if p == "Bowcraft":
        return "board"
    return "ingot"


def _material_key_from_base(base):
    b = str(base or "").strip().lower()
    if b == "cloth":
        return "cloth"
    if b == "leather":
        return "leather"
    if b == "board":
        return "board"
    if b == "feather":
        return "feather"
    return "ingot_iron"


def _parse_int_list(text):
    return [int(x) for x in re.findall(r"\d+", str(text or ""))]


def _parse_number(text, default=0.0):
    try:
        return float(str(text or "").strip())
    except Exception:
        return float(default)


def _normalize_material_requirements(raw, fallback_material="", fallback_profession=""):
    out = []
    src = raw if isinstance(raw, list) else []
    for ent in src:
        if isinstance(ent, dict):
            base = _normalize_material_base(ent.get("material", ""), fallback_profession)
            mk = str(ent.get("material_key", "") or _material_key_from_base(base)).strip()
            out.append({
                "material": base,
                "material_key": mk,
                "item_id": int(ent.get("item_id", 0) or 0),
                "min_in_pack": int(ent.get("min_in_pack", 0) or 0),
                "pull_amount": int(ent.get("pull_amount", 0) or 0),
                "hue": ent.get("hue", None),
            })
        else:
            base = _normalize_material_base(str(ent or ""), fallback_profession)
            out.append({
                "material": base,
                "material_key": _material_key_from_base(base),
                "item_id": 0,
                "min_in_pack": 0,
                "pull_amount": 0,
                "hue": None,
            })
    if not out:
        base = _normalize_material_base(fallback_material or "", fallback_profession)
        out.append({
            "material": base,
            "material_key": _material_key_from_base(base),
            "item_id": 0,
            "min_in_pack": 0,
            "pull_amount": 0,
            "hue": None,
        })
    return out


def _load_recipe_book_raw():
    if RECIPE_STORE is None:
        return []
    try:
        return list(RECIPE_STORE.load_recipes() or [])
    except Exception:
        pass
    return []


def _save_recipe_book_raw(rows):
    if RECIPE_STORE is None:
        _say("Recipe DB unavailable.", WARN_HUE)
        return False
    try:
        return bool(RECIPE_STORE.save_recipes(list(rows or [])))
    except Exception as ex:
        _say(f"Recipe DB write failed: {ex}", WARN_HUE)
        return False


def _set_persistent_json(key, obj):
    try:
        API.SavePersistentVar(str(key), json.dumps(obj or {}), API.PersistentVar.Char)
    except Exception:
        pass


def _launch_shared_recipe_editor(payload=None):
    global RECIPE_EDITOR_NONCE
    RECIPE_EDITOR_NONCE += 1
    req = {
        "nonce": int(RECIPE_EDITOR_NONCE),
        "caller": "CrafterTrainer",
        "payload": dict(payload or {}),
    }
    _set_persistent_json(RECIPE_EDITOR_REQUEST_KEY, req)
    launched = False
    for script_name in RECIPE_EDITOR_SCRIPT_CANDIDATES:
        try:
            API.PlayScript(str(script_name))
            ack_wait = 0.0
            while ack_wait < 1.2:
                _pause_ms(100)
                ack_wait += 0.1
                raw = API.GetPersistentVar(RECIPE_EDITOR_RESULT_KEY, "", API.PersistentVar.Char)
                if not raw:
                    continue
                try:
                    res = json.loads(raw)
                except Exception:
                    try:
                        res = ast.literal_eval(raw)
                    except Exception:
                        res = {}
                try:
                    if int(res.get("nonce", 0) or 0) != int(RECIPE_EDITOR_NONCE):
                        continue
                except Exception:
                    continue
                if str(res.get("status", "") or "").strip().lower() == "opened":
                    launched = True
                    break
            if launched:
                break
        except Exception:
            continue
    if not launched:
        try:
            base = os.path.dirname(__file__)
        except Exception:
            base = os.getcwd()
        for rel in RECIPE_EDITOR_FILE_CANDIDATES:
            p = os.path.normpath(os.path.join(base, "..", rel))
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    code = f.read()
                local_ctx = {"API": API, "__file__": p, "__name__": "__main__"}
                exec(compile(code, p, "exec"), local_ctx, local_ctx)
                raw = API.GetPersistentVar(RECIPE_EDITOR_RESULT_KEY, "", API.PersistentVar.Char)
                if raw:
                    try:
                        res = json.loads(raw)
                    except Exception:
                        try:
                            res = ast.literal_eval(raw)
                        except Exception:
                            res = {}
                    if int(res.get("nonce", 0) or 0) == int(RECIPE_EDITOR_NONCE):
                        launched = True
                        break
            except Exception:
                continue
    if not launched:
        _say("Could not launch RecipeBookEditor.py (check script path/name in Script Manager).", WARN_HUE)


def _normalize_training_recipe_entry(r):
    if not isinstance(r, dict):
        return None
    name = str(r.get("name", "") or "").strip()
    prof = _normalize_profession_name(r.get("profession", ""))
    if not name or not prof:
        return None
    buttons = [int(x) for x in (r.get("buttons", []) or []) if int(x) > 0]
    if not buttons:
        return None
    base = _normalize_material_base(r.get("material", ""), prof)
    materials = _normalize_material_requirements(r.get("materials", []), base, prof)
    return {
        "name": name,
        "profession": prof,
        "item_id": int(r.get("item_id", 0) or 0),
        "buttons": buttons,
        "material": base,
        "material_key": str(r.get("material_key", "") or _material_key_from_base(base)),
        "materials": materials,
        "material_buttons": [int(x) for x in (r.get("material_buttons", []) or []) if int(x) > 0],
        "recipe_type": RECIPE_TYPE_TRAINING,
        "server": _normalize_server_name(r.get("server", SELECTED_SERVER)),
        "start_at": float(r.get("start_at", 0.0) or 0.0),
        "stop_at": float(r.get("stop_at", r.get("end_at", 0.0)) or 0.0),
    }


def _recipe_row_matches(a, b):
    return (
        str(a.get("recipe_type", "")).lower() == str(b.get("recipe_type", "")).lower()
        and _normalize_server_name(a.get("server", DEFAULT_SERVER)) == _normalize_server_name(b.get("server", DEFAULT_SERVER))
        and _normalize_profession_name(a.get("profession", "")) == _normalize_profession_name(b.get("profession", ""))
        and str(a.get("name", "")).strip().lower() == str(b.get("name", "")).strip().lower()
        and str(a.get("material_key", "")).strip().lower() == str(b.get("material_key", "")).strip().lower()
    )


def _upsert_shared_recipe(row):
    norm = _normalize_training_recipe_entry(row)
    if not norm:
        return False
    all_rows = _load_recipe_book_raw()
    replaced = False
    for i, r in enumerate(all_rows):
        if _recipe_row_matches(r, norm):
            all_rows[i] = dict(r, **norm)
            replaced = True
            break
    if not replaced:
        all_rows.append(norm)
    return _save_recipe_book_raw(all_rows)


def _skill_to_profession(skill_name):
    m = {
        "Blacksmithy": "Blacksmith",
        "Tailoring": "Tailor",
        "Carpentry": "Carpentry",
        "Tinkering": "Tinker",
        "Bowcraft/Fletching": "Bowcraft",
    }
    return m.get(str(skill_name or ""), "")


def _training_steps_from_recipe_book(skill_name):
    prof = _skill_to_profession(skill_name)
    if not prof:
        return []
    rows = _load_recipe_book_raw()
    out = []
    for r in rows:
        if str(r.get("recipe_type", "")).strip().lower() != RECIPE_TYPE_TRAINING:
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
            continue
        if _normalize_profession_name(r.get("profession", "")) != prof:
            continue
        n = _normalize_training_recipe_entry(r)
        if not n:
            continue
        out.append({
            "start_at": float(n.get("start_at", 0.0) or 0.0),
            "stop_at": float(n.get("stop_at", 0.0) or 0.0),
            "name": str(n.get("name", "")),
            "item_id": int(n.get("item_id", 0) or 0),
            "material": str(n.get("material", "ingot") or "ingot"),
            "materials": _normalize_material_requirements(
                n.get("materials", []),
                str(n.get("material", "ingot") or "ingot"),
                prof
            ),
            "buttons": [int(x) for x in (n.get("buttons", []) or []) if int(x) > 0],
        })
    return _normalize_steps(out) if out else []


def _build_recipe_lookup_for_skill(skill_name):
    prof = _skill_to_profession(skill_name)
    if not prof:
        return {}
    rows = _load_recipe_book_raw()
    lookup = {}
    for r in rows:
        if str(r.get("recipe_type", "")).strip().lower() != RECIPE_TYPE_TRAINING:
            continue
        if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != _normalize_server_name(SELECTED_SERVER):
            continue
        if _normalize_profession_name(r.get("profession", "")) != prof:
            continue
        n = _normalize_training_recipe_entry(r)
        if not n:
            continue
        key = (
            str(n.get("name", "")).strip().lower(),
            str(n.get("material_key", "") or _material_key_from_base(n.get("material", "ingot"))).strip().lower(),
        )
        lookup[key] = {
            "name": str(n.get("name", "")),
            "item_id": int(n.get("item_id", 0) or 0),
            "material": str(n.get("material", "ingot") or "ingot"),
            "material_key": str(n.get("material_key", "") or _material_key_from_base(n.get("material", "ingot"))),
            "materials": _normalize_material_requirements(
                n.get("materials", []),
                str(n.get("material", "ingot") or "ingot"),
                prof
            ),
            "buttons": [int(x) for x in (n.get("buttons", []) or []) if int(x) > 0],
        }
    return lookup


def _training_steps_from_in_script_plan(skill_name):
    server = _normalize_server_name(SELECTED_SERVER)
    plan = (TRAINING_PLANS_BY_SERVER.get(server, {}) or {}).get(str(skill_name), []) or []
    if not plan:
        return []
    recipe_lookup = _build_recipe_lookup_for_skill(skill_name)
    out = []
    missing = []
    for p in plan:
        action = str(p.get("action", "") or "").strip().lower()
        if action:
            out.append({
                "start_at": float(p.get("start_at", 0.0) or 0.0),
                "name": str(p.get("name", action)),
                "item_id": 0,
                "material": str(p.get("material", "cloth") or "cloth"),
                "materials": _normalize_material_requirements(
                    p.get("materials", []),
                    str(p.get("material", "cloth") or "cloth"),
                    _skill_to_profession(skill_name)
                ),
                "buttons": [int(x) for x in (p.get("buttons", []) or []) if int(x) > 0],
                "action": action,
                "message": str(p.get("message", "") or ""),
            })
            continue
        step_name = str(p.get("name", "") or "").strip()
        candidates = []
        any_of = p.get("any_of", []) or []
        if isinstance(any_of, list) and any_of:
            for nm in any_of:
                nms = str(nm or "").strip()
                if nms:
                    candidates.append(nms)
        elif step_name:
            candidates.append(step_name)
        material_key = str(p.get("material_key", "") or "ingot_iron").strip().lower()
        recipe = None
        chosen_name = step_name
        for nm in candidates:
            key = (nm.lower(), material_key)
            recipe = recipe_lookup.get(key)
            if recipe:
                chosen_name = nm
                break
        if not recipe:
            if candidates:
                missing.append(f"{'/'.join(candidates)} ({material_key})")
            else:
                missing.append(f"{step_name or 'unnamed'} ({material_key})")
            continue
        out.append({
            "start_at": float(p.get("start_at", 0.0) or 0.0),
            "name": str(recipe.get("name", chosen_name)),
            "item_id": int(recipe.get("item_id", 0) or 0),
            "material": str(recipe.get("material", "ingot") or "ingot"),
            "materials": _normalize_material_requirements(
                recipe.get("materials", []) or p.get("materials", []),
                str(recipe.get("material", "ingot") or "ingot"),
                _skill_to_profession(skill_name)
            ),
            "buttons": [int(x) for x in (recipe.get("buttons", []) or []) if int(x) > 0],
        })
    if missing:
        _say(
            f"Missing training recipes for {skill_name} on {server}: {', '.join(missing)}",
            WARN_HUE
        )
    return _normalize_steps(out) if out else []


def _resolve_training_steps(skill_name):
    # Runtime source of truth is the shared recipe book.
    # (In-script plans are retained only as historical data/migration reference.)
    return _training_steps_from_recipe_book(skill_name)


def _update_caps_from_gump():
    for name, box in TEXT_INPUTS.items():
        cap = _parse_cap(box.Text.strip() if box and box.Text else "")
        SKILL_CAPS[name] = cap


def _toggle_running():
    global RUNNING
    RUNNING = not RUNNING
    if CONTROL_BUTTON:
        CONTROL_BUTTON.Text = "Pause" if RUNNING else "Start"

def _toggle_tool_crafting():
    global USE_TOOL_CRAFTING
    USE_TOOL_CRAFTING = not USE_TOOL_CRAFTING
    _save_config()
    _rebuild_gump()


def _set_server(selected_index):
    global SELECTED_SERVER
    idx = int(selected_index)
    if idx < 0 or idx >= len(SERVER_OPTIONS):
        idx = 0
    SELECTED_SERVER = str(SERVER_OPTIONS[idx])
    _save_config()
    _rebuild_gump()


def _open_shared_recipe_editor_from_control():
    _launch_shared_recipe_editor({
        "recipe_type": RECIPE_TYPE_TRAINING,
        "server": str(SELECTED_SERVER or DEFAULT_SERVER),
        "profession": "Blacksmith",
        "material": "ingot",
        "material_key": "ingot_iron",
        "name": "",
        "buttons": "",
        "start_at": 0.0,
    })


def _set_stock():
    global STOCK_SERIAL
    API.SysMsg("Target resource container.")
    serial = API.RequestTarget()
    if serial:
        STOCK_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_stock():
    global STOCK_SERIAL
    STOCK_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_salvage():
    global SALVAGE_SERIAL
    API.SysMsg("Target salvage bag.")
    serial = API.RequestTarget()
    if serial:
        SALVAGE_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_salvage():
    global SALVAGE_SERIAL
    SALVAGE_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_trash():
    global TRASH_SERIAL
    API.SysMsg("Target trash container.")
    serial = API.RequestTarget()
    if serial:
        TRASH_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_trash():
    global TRASH_SERIAL
    TRASH_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _create_gump():
    global CONTROL_GUMP, CONTROL_BUTTON
    g = API.CreateGump(True, True, False)
    g.SetRect(GUMP_X, GUMP_Y, GUMP_W, 60 + len(CRAFT_SKILLS) * ROW_H + 130)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, GUMP_W, 60 + len(CRAFT_SKILLS) * ROW_H + 130)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("Crafting Trainer", 16, "#FFFFFF", "alagard", "center", GUMP_W)
    title.SetPos(0, 6)
    g.Add(title)

    y = 32
    for name in CRAFT_SKILLS:
        label = API.CreateGumpTTFLabel(_display_skill_name(name), 12, "#FFFFFF", "alagard", "left", 260)
        label.SetPos(10, y)
        g.Add(label)
        box = API.CreateGumpTextBox("", 80, 20, False)
        box.SetPos(320, y - 2)
        g.Add(box)
        TEXT_INPUTS[name] = box
        y += ROW_H

    # Tinkering containers
    stock_status = "Set" if STOCK_SERIAL else "Unset"
    stock_label = API.CreateGumpTTFLabel(f"Resource Stock: {stock_status}", 12, "#FFFFFF", "alagard", "left", 260)
    stock_label.SetPos(10, y)
    g.Add(stock_label)
    stock_btn = API.CreateSimpleButton("Set", 50, 18)
    stock_btn.SetPos(310, y - 2)
    g.Add(stock_btn)
    API.AddControlOnClick(stock_btn, _set_stock)
    stock_unset = API.CreateSimpleButton("Unset", 50, 18)
    stock_unset.SetPos(365, y - 2)
    g.Add(stock_unset)
    API.AddControlOnClick(stock_unset, _unset_stock)
    y += ROW_H

    salvage_status = "Set" if SALVAGE_SERIAL else "Unset"
    salvage_label = API.CreateGumpTTFLabel(f"Salvage Bag: {salvage_status}", 12, "#FFFFFF", "alagard", "left", 260)
    salvage_label.SetPos(10, y)
    g.Add(salvage_label)
    salvage_btn = API.CreateSimpleButton("Set", 50, 18)
    salvage_btn.SetPos(310, y - 2)
    g.Add(salvage_btn)
    API.AddControlOnClick(salvage_btn, _set_salvage)
    salvage_unset = API.CreateSimpleButton("Unset", 50, 18)
    salvage_unset.SetPos(365, y - 2)
    g.Add(salvage_unset)
    API.AddControlOnClick(salvage_unset, _unset_salvage)
    y += ROW_H

    trash_status = "Set" if TRASH_SERIAL else "Unset"
    trash_label = API.CreateGumpTTFLabel(f"Trash: {trash_status}", 12, "#FFFFFF", "alagard", "left", 260)
    trash_label.SetPos(10, y)
    g.Add(trash_label)
    trash_btn = API.CreateSimpleButton("Set", 50, 18)
    trash_btn.SetPos(310, y - 2)
    g.Add(trash_btn)
    API.AddControlOnClick(trash_btn, _set_trash)
    trash_unset = API.CreateSimpleButton("Unset", 50, 18)
    trash_unset.SetPos(365, y - 2)
    g.Add(trash_unset)
    API.AddControlOnClick(trash_unset, _unset_trash)
    y += ROW_H

    tool_label = API.CreateGumpTTFLabel(
        f"Auto Tools: {'On' if USE_TOOL_CRAFTING else 'Off'}", 12, "#FFFFFF", "alagard", "left", 260
    )
    tool_label.SetPos(10, y)
    g.Add(tool_label)
    tool_btn = API.CreateSimpleButton("Toggle", 60, 18)
    tool_btn.SetPos(355, y - 2)
    g.Add(tool_btn)
    API.AddControlOnClick(tool_btn, _toggle_tool_crafting)
    y += ROW_H

    srv_label = API.CreateGumpTTFLabel("Server", 12, "#FFFFFF", "alagard", "left", 80)
    srv_label.SetPos(10, y)
    g.Add(srv_label)
    srv_idx = 0
    try:
        srv_idx = SERVER_OPTIONS.index(str(SELECTED_SERVER or DEFAULT_SERVER))
    except Exception:
        srv_idx = 0
    srv_dd = API.CreateDropDown(170, list(SERVER_OPTIONS), srv_idx)
    srv_dd.SetPos(70, y - 2)
    g.Add(srv_dd)
    srv_dd.OnDropDownOptionSelected(_set_server)
    manual_btn = API.CreateSimpleButton("Manual Recipe", 100, 18)
    manual_btn.SetPos(250, y - 2)
    g.Add(manual_btn)
    API.AddControlOnClick(manual_btn, _open_shared_recipe_editor_from_control)
    y += ROW_H

    CONTROL_BUTTON = API.CreateSimpleButton("Start", 100, 20)
    CONTROL_BUTTON.SetPos(int(GUMP_W / 2) - 50, y + 4)
    g.Add(CONTROL_BUTTON)
    API.AddControlOnClick(CONTROL_BUTTON, _toggle_running)

    API.AddGump(g)
    CONTROL_GUMP = g


def _rebuild_gump():
    global CONTROL_GUMP
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
    _create_gump()


def _default_config():
    return {
        "stock_serial": 0,
        "salvage_serial": 0,
        "trash_serial": 0,
        "use_tool_crafting": False,
        "selected_server": DEFAULT_SERVER,
    }


def _load_config():
    global STOCK_SERIAL, SALVAGE_SERIAL, TRASH_SERIAL, USE_TOOL_CRAFTING, SELECTED_SERVER
    if RECIPE_STORE is not None:
        try:
            RECIPE_STORE.init_store()
        except Exception as ex:
            _say(f"Recipe DB init failed: {ex}", WARN_HUE)
    raw = API.GetPersistentVar(DATA_KEY, "", API.PersistentVar.Char)
    if raw:
        try:
            try:
                data = json.loads(raw)
            except Exception:
                data = ast.literal_eval(raw)
            STOCK_SERIAL = int(data.get("stock_serial", 0) or 0)
            SALVAGE_SERIAL = int(data.get("salvage_serial", 0) or 0)
            TRASH_SERIAL = int(data.get("trash_serial", 0) or 0)
            USE_TOOL_CRAFTING = bool(data.get("use_tool_crafting", False))
            SELECTED_SERVER = _normalize_server_name(data.get("selected_server", DEFAULT_SERVER))
            return
        except Exception:
            pass
    data = _default_config()
    STOCK_SERIAL = data["stock_serial"]
    SALVAGE_SERIAL = data["salvage_serial"]
    TRASH_SERIAL = data["trash_serial"]
    USE_TOOL_CRAFTING = data["use_tool_crafting"]
    SELECTED_SERVER = _normalize_server_name(data.get("selected_server", DEFAULT_SERVER))


def _save_config():
    data = {
        "stock_serial": int(STOCK_SERIAL or 0),
        "salvage_serial": int(SALVAGE_SERIAL or 0),
        "trash_serial": int(TRASH_SERIAL or 0),
        "use_tool_crafting": bool(USE_TOOL_CRAFTING),
        "selected_server": str(SELECTED_SERVER or DEFAULT_SERVER),
    }
    API.SavePersistentVar(DATA_KEY, json.dumps(data), API.PersistentVar.Char)


def _pause_if_needed():
    while not RUNNING:
        API.ProcessCallbacks()
        API.Pause(0.1)


# === BLACKSMITH HELPERS ===

def _get_skill_value(name):
    skill = API.GetSkill(name)
    if not skill or skill.Value is None:
        return 0.0
    return float(skill.Value)


def _get_skill_cap(name):
    skill = API.GetSkill(name)
    if not skill or skill.Cap is None:
        return 0.0
    return float(skill.Cap)


def _gump_matches_anchors(gump_id, anchors):
    text = API.GetGumpContents(gump_id)
    if not text:
        return False
    lower = text.lower()
    for a in anchors:
        if a.lower() in lower:
            return True
    return False


def _find_gump_containing(anchors, preferred_id=0):
    probe_ids = []
    for gid in [preferred_id, BLACKSMITH_GUMP_ID, TINKER_GUMP_ID, TAILOR_GUMP_ID, CARPENTRY_GUMP_ID]:
        if gid and gid not in probe_ids:
            probe_ids.append(gid)
    for gid in probe_ids:
        if API.WaitForGump(gid, 0.1) and _gump_matches_anchors(gid, anchors):
            return gid
    return 0


def _wait_for_gump(anchors, timeout_s=OPEN_MENU_TIMEOUT_S, preferred_id=0):
    waited = 0.0
    while waited < timeout_s:
        gid = _find_gump_containing(anchors, preferred_id)
        if gid:
            return gid
        _pause_ms(GUMP_POLL_MS)
        waited += (GUMP_POLL_MS / 1000.0)
    return 0


def _find_first_in_container(container_serial, item_id, hue_filter=None):
    for it in _items_in(container_serial, recursive=True):
        if it.Graphic != item_id:
            continue
        if hue_filter is None or int(getattr(it, "Hue", -1)) == int(hue_filter):
            return it
    return None

def _find_first_in_container_multi(container_serial, item_ids):
    for item_id in item_ids:
        item = _find_first_in_container(container_serial, item_id)
        if item:
            return item
    return None


def _count_in(container_serial, item_id, hue_filter=None):
    items = API.ItemsInContainer(container_serial, True) or []
    total = 0
    for it in items:
        if it.Graphic != item_id:
            continue
        if hue_filter is not None and int(getattr(it, "Hue", -1)) != int(hue_filter):
            continue
        total += int(getattr(it, "Amount", 1))
    return total


def _items_in(container_serial, recursive=True):
    serial = container_serial
    if hasattr(container_serial, "Serial"):
        serial = container_serial.Serial
    return API.ItemsInContainer(serial, recursive) or []


def _backpack_item_count():
    try:
        total = 0
        queue = [API.Backpack]
        seen = set()
        while queue:
            current = queue.pop(0)
            serial = current.Serial if hasattr(current, "Serial") else current
            if not serial or serial in seen:
                continue
            seen.add(serial)
            items = API.ItemsInContainer(serial, False) or []
            total += len(items)
            for it in items:
                try:
                    if int(API.Contents(it.Serial)) > 0:
                        queue.append(it.Serial)
                except Exception:
                    continue
        return total
    except Exception:
        return len(_items_in(API.Backpack, recursive=True))


def _has_any_in_backpack(item_ids):
    for it in _items_in(API.Backpack):
        if it.Graphic in item_ids:
            return True
    return False


def _move_salvage_non_keep_to_trash():
    if not SALVAGE_SERIAL or not TRASH_SERIAL:
        return
    for it in _items_in(SALVAGE_SERIAL, True):
        if it.Graphic in ALLOW_KEEP_GRAPHICS:
            continue
        _pause_if_needed()
        API.ProcessCallbacks()
        API.MoveItem(it.Serial, TRASH_SERIAL, int(getattr(it, "Amount", 1)))
        _pause_ms(PAUSE_DRAG)


def _clear_crafted_items(item_ids):
    if not SALVAGE_SERIAL and not TRASH_SERIAL:
        return
    if SALVAGE_SERIAL:
        API.ContextMenu(SALVAGE_SERIAL, SALVAGE_CONTEXT_INDEX)
        _pause_ms(5000)
    while _has_any_in_backpack(item_ids):
        _pause_if_needed()
        API.ProcessCallbacks()
        itm = None
        for item_id in item_ids:
            itm = _find_first_in_container(API.Backpack, item_id)
            if itm:
                if hasattr(itm, "Container") and int(getattr(itm, "Container", 0)) in (SALVAGE_SERIAL, TRASH_SERIAL):
                    itm = None
                    continue
                if hasattr(itm, "ContainerSerial") and int(getattr(itm, "ContainerSerial", 0)) in (SALVAGE_SERIAL, TRASH_SERIAL):
                    itm = None
                    continue
                break
        if not itm:
            break
        moved = False
        if SALVAGE_SERIAL:
            moved = _move_to_salvage(itm.Graphic, SALVAGE_SERIAL)
        if not moved and TRASH_SERIAL:
            _move_to_salvage(itm.Graphic, TRASH_SERIAL)
        _pause_ms(PAUSE_DRAG)
    _move_salvage_non_keep_to_trash()


def _get_first_tool_serial():
    for tid in BLACKSMITH_TOOL_IDS:
        item = _find_first_in_container(API.Backpack, tid)
        if item:
            return item.Serial
    return 0


def _find_first_tool_in_stock(stock_serial):
    for tid in BLACKSMITH_TOOL_IDS:
        item = _find_first_in_container(stock_serial, tid)
        if item:
            return item
    return None


def _ensure_tool_or_exit(stock_serial):
    tool = _get_first_tool_serial()
    if tool:
        return tool
    if RESTOCK_TOOLS:
        stock_tool = _find_first_tool_in_stock(stock_serial)
        if stock_tool:
            API.MoveItem(stock_tool.Serial, API.Backpack, 1)
            _pause_ms(PAUSE_DRAG)
            tool = _get_first_tool_serial()
            if tool:
                return tool
    if USE_TOOL_CRAFTING:
        if not _ensure_tinker_tools():
            _say("Cannot craft blacksmith tool: no tinker's tools available.", WARN_HUE)
            return 0
        attempts = 0
        while attempts < 3:
            attempts += 1
            if _craft_blacksmith_tool_with_tinkering():
                _pause_ms(PAUSE_DRAG)
                tool = _get_first_tool_serial()
                if tool:
                    return tool
            _pause_ms(300)
    _say("No blacksmith tools available.", WARN_HUE)
    return 0


def _close_blacksmith_gump_if_open():
    gid = _find_gump_containing(BLACKSMITH_GUMP_ANCHORS, BLACKSMITH_GUMP_ID)
    if gid:
        API.CloseGump(gid)
        _pause_ms(150)


def _close_tinker_gump_if_open():
    gid = _find_gump_containing(TINKER_GUMP_ANCHORS, TINKER_GUMP_ID)
    if gid:
        API.CloseGump(gid)
        _pause_ms(150)


def _close_tailor_gump_if_open():
    gid = _find_gump_containing(TAILOR_GUMP_ANCHORS, TAILOR_GUMP_ID)
    if gid:
        API.CloseGump(gid)
        _pause_ms(150)


def _close_carpentry_gump_if_open():
    gid = _find_gump_containing(CARPENTRY_GUMP_ANCHORS, CARPENTRY_GUMP_ID)
    if gid:
        API.CloseGump(gid)
        _pause_ms(150)


def _close_bowcraft_gump_if_open():
    gid = _find_gump_containing(BOWCRAFT_GUMP_ANCHORS, BOWCRAFT_GUMP_ID)
    if gid:
        API.CloseGump(gid)
        _pause_ms(150)


def _get_first_tailor_tool_serial():
    for tid in TAILOR_TOOL_GRAPHICS:
        item = _find_first_in_container(API.Backpack, tid)
        if item:
            return item.Serial
    return 0


def _find_tailor_tool_in_stock(stock_serial):
    for tid in TAILOR_TOOL_GRAPHICS:
        item = _find_first_in_container(stock_serial, tid)
        if item:
            return item
    return None


def _ensure_tailor_tool_or_exit(stock_serial):
    tool = _get_first_tailor_tool_serial()
    if tool:
        return tool
    stock_tool = _find_tailor_tool_in_stock(stock_serial)
    if stock_tool:
        API.MoveItem(stock_tool.Serial, API.Backpack, 1)
        _pause_ms(PAUSE_DRAG)
        tool = _get_first_tailor_tool_serial()
        if tool:
            return tool
    if USE_TOOL_CRAFTING:
        if not _ensure_tinker_tools():
            _say("Cannot craft tailoring tool: no tinker's tools available.", WARN_HUE)
            return 0
        attempts = 0
        while attempts < 3:
            attempts += 1
            if _craft_tailor_tool_with_tinkering():
                _pause_ms(PAUSE_DRAG)
                tool = _get_first_tailor_tool_serial()
                if tool:
                    return tool
            _pause_ms(300)
    _say("No tailoring tools available.", WARN_HUE)
    return 0


def _get_first_carpentry_tool_serial():
    for tid in CARPENTRY_TOOL_GRAPHICS:
        item = _find_first_in_container(API.Backpack, tid)
        if item:
            return item.Serial
    return 0


def _find_carpentry_tool_in_stock(stock_serial):
    for tid in CARPENTRY_TOOL_GRAPHICS:
        item = _find_first_in_container(stock_serial, tid)
        if item:
            return item
    return None


def _ensure_carpentry_tool_or_exit(stock_serial):
    tool = _get_first_carpentry_tool_serial()
    if tool:
        return tool
    stock_tool = _find_carpentry_tool_in_stock(stock_serial)
    if stock_tool:
        API.MoveItem(stock_tool.Serial, API.Backpack, 1)
        _pause_ms(PAUSE_DRAG)
        tool = _get_first_carpentry_tool_serial()
        if tool:
            return tool
    if USE_TOOL_CRAFTING:
        if not _ensure_tinker_tools():
            _say("Cannot craft carpentry tool: no tinker's tools available.", WARN_HUE)
            return 0
        attempts = 0
        while attempts < 3:
            attempts += 1
            if _craft_carpentry_tool_with_tinkering():
                _pause_ms(PAUSE_DRAG)
                tool = _get_first_carpentry_tool_serial()
                if tool:
                    return tool
            _pause_ms(300)
    _say("No carpentry tools available.", WARN_HUE)
    return 0


def _get_first_bowcraft_tool_serial():
    for tid in BOWCRAFT_TOOL_GRAPHICS:
        item = _find_first_in_container(API.Backpack, tid)
        if item:
            return item.Serial
    return 0


def _find_bowcraft_tool_in_stock(stock_serial):
    for tid in BOWCRAFT_TOOL_GRAPHICS:
        item = _find_first_in_container(stock_serial, tid)
        if item:
            return item
    return None


def _ensure_bowcraft_tool_or_exit(stock_serial):
    tool = _get_first_bowcraft_tool_serial()
    if tool:
        return tool
    stock_tool = _find_bowcraft_tool_in_stock(stock_serial)
    if stock_tool:
        API.MoveItem(stock_tool.Serial, API.Backpack, 1)
        _pause_ms(PAUSE_DRAG)
        tool = _get_first_bowcraft_tool_serial()
        if tool:
            return tool
    _say("No bowcraft tools available.", WARN_HUE)
    return 0


def _open_tailor_menu(stock_serial):
    _close_blacksmith_gump_if_open()
    _close_tinker_gump_if_open()
    _close_carpentry_gump_if_open()
    _close_bowcraft_gump_if_open()
    tool = _ensure_tailor_tool_or_exit(stock_serial)
    if not tool:
        return 0
    API.UseObject(tool)
    gid = _wait_for_gump(TAILOR_GUMP_ANCHORS, timeout_s=3, preferred_id=TAILOR_GUMP_ID)
    if gid:
        return gid
    _say("Tailor gump not found.", WARN_HUE)
    return 0


def _open_carpentry_menu(stock_serial):
    _close_blacksmith_gump_if_open()
    _close_tinker_gump_if_open()
    _close_tailor_gump_if_open()
    _close_bowcraft_gump_if_open()
    tool = _ensure_carpentry_tool_or_exit(stock_serial)
    if not tool:
        return 0
    for _ in range(2):
        API.UseObject(tool)
        _pause_ms(POST_OPEN_PAUSE_MS)
        gid = _wait_for_gump(CARPENTRY_GUMP_ANCHORS, timeout_s=3, preferred_id=CARPENTRY_GUMP_ID)
        if gid:
            return gid
        # Some shards expose limited carpentry header text; fall back to known id.
        if CARPENTRY_GUMP_ID and API.WaitForGump(CARPENTRY_GUMP_ID, 0.5):
            return CARPENTRY_GUMP_ID
    _say("Carpentry gump not found.", WARN_HUE)
    return 0


def _open_bowcraft_menu(stock_serial):
    _close_blacksmith_gump_if_open()
    _close_tinker_gump_if_open()
    _close_tailor_gump_if_open()
    _close_carpentry_gump_if_open()
    tool = _ensure_bowcraft_tool_or_exit(stock_serial)
    if not tool:
        return 0
    for _ in range(2):
        API.UseObject(tool)
        _pause_ms(POST_OPEN_PAUSE_MS)
        gid = _wait_for_gump(BOWCRAFT_GUMP_ANCHORS, timeout_s=3, preferred_id=BOWCRAFT_GUMP_ID)
        if gid:
            return gid
        if BOWCRAFT_GUMP_ID and API.WaitForGump(BOWCRAFT_GUMP_ID, 0.5):
            return BOWCRAFT_GUMP_ID
    _say("Bowcraft gump not found.", WARN_HUE)
    return 0


def _craft_tailor_once(gump_id, step):
    buttons = step.get("buttons", []) or []
    if not buttons:
        _say(f"Tailor buttons not configured for: {step['name']}", WARN_HUE)
        return False
    if not gump_id or not _gump_matches_anchors(gump_id, TAILOR_GUMP_ANCHORS):
        gump_id = _wait_for_gump(TAILOR_GUMP_ANCHORS, timeout_s=2, preferred_id=TAILOR_GUMP_ID)
    if not gump_id:
        _say("Tailor gump validation failed.", WARN_HUE)
        return False
    for b in buttons:
        if not _gump_matches_anchors(gump_id, TAILOR_GUMP_ANCHORS):
            _say("Tailor gump changed unexpectedly.", WARN_HUE)
            return False
        API.ReplyGump(b, gump_id)
        _pause_ms(PAUSE_GUMP_CLICK)
    return True


def _craft_carpentry_once(gump_id, step):
    buttons = step.get("buttons", []) or []
    if not buttons:
        _say(f"Carpentry buttons not configured for: {step['name']}", WARN_HUE)
        return False
    if not gump_id:
        gump_id = _wait_for_gump(CARPENTRY_GUMP_ANCHORS, timeout_s=2, preferred_id=CARPENTRY_GUMP_ID)
    elif not _gump_matches_anchors(gump_id, CARPENTRY_GUMP_ANCHORS):
        if not (CARPENTRY_GUMP_ID and API.WaitForGump(CARPENTRY_GUMP_ID, 0.2)):
            gump_id = _wait_for_gump(CARPENTRY_GUMP_ANCHORS, timeout_s=2, preferred_id=CARPENTRY_GUMP_ID)
    if not gump_id:
        _say("Carpentry gump validation failed.", WARN_HUE)
        return False
    for b in buttons:
        if not _gump_matches_anchors(gump_id, CARPENTRY_GUMP_ANCHORS):
            if not (CARPENTRY_GUMP_ID and API.WaitForGump(CARPENTRY_GUMP_ID, 0.2)):
                _say("Carpentry gump changed unexpectedly.", WARN_HUE)
                return False
        if not API.WaitForGump(gump_id, 0.1):
            _say("Carpentry gump changed unexpectedly.", WARN_HUE)
            return False
        API.ReplyGump(b, gump_id)
        _pause_ms(PAUSE_GUMP_CLICK)
    return True


def _craft_bowcraft_once(gump_id, step):
    buttons = step.get("buttons", []) or []
    if not buttons:
        _say(f"Bowcraft buttons not configured for: {step['name']}", WARN_HUE)
        return False
    if not gump_id:
        gump_id = _wait_for_gump(BOWCRAFT_GUMP_ANCHORS, timeout_s=2, preferred_id=BOWCRAFT_GUMP_ID)
    elif not _gump_matches_anchors(gump_id, BOWCRAFT_GUMP_ANCHORS):
        if not API.WaitForGump(BOWCRAFT_GUMP_ID, 0.1):
            gump_id = _wait_for_gump(BOWCRAFT_GUMP_ANCHORS, timeout_s=2, preferred_id=BOWCRAFT_GUMP_ID)
    if not gump_id:
        _say("Bowcraft gump validation failed.", WARN_HUE)
        return False
    for b in buttons:
        if not _gump_matches_anchors(gump_id, BOWCRAFT_GUMP_ANCHORS):
            if not API.WaitForGump(BOWCRAFT_GUMP_ID, 0.1):
                _say("Bowcraft gump changed unexpectedly.", WARN_HUE)
                return False
        if not API.WaitForGump(gump_id, 0.1):
            _say("Bowcraft gump changed unexpectedly.", WARN_HUE)
            return False
        API.ReplyGump(b, gump_id)
        _pause_ms(PAUSE_GUMP_CLICK)
    return True


def _open_blacksmith_menu(stock_serial):
    _close_tinker_gump_if_open()
    _close_tailor_gump_if_open()
    _close_carpentry_gump_if_open()
    _close_bowcraft_gump_if_open()
    tool = _ensure_tool_or_exit(stock_serial)
    if not tool:
        return 0
    API.UseObject(tool)
    gid = _wait_for_gump(BLACKSMITH_GUMP_ANCHORS, preferred_id=BLACKSMITH_GUMP_ID)
    if gid == 0:
        tool = _ensure_tool_or_exit(stock_serial)
        if not tool:
            return 0
        API.UseObject(tool)
        gid = _wait_for_gump(BLACKSMITH_GUMP_ANCHORS, preferred_id=BLACKSMITH_GUMP_ID)
        if gid == 0:
            _say("Failed to open blacksmithing gump.", WARN_HUE)
            return 0
    return gid


def _reset_blacksmith_menu(stock_serial):
    _close_blacksmith_gump_if_open()
    _pause_ms(CHANGEOVER_PAUSE_MS)
    gid = _open_blacksmith_menu(stock_serial)
    _pause_ms(POST_OPEN_PAUSE_MS)
    return gid


def _restock_ingots(stock_serial):
    current = _count_in(API.Backpack, INGOT_ID, IRON_INGOT_HUE)
    if current >= MIN_INGOTS_IN_PACK:
        return current
    API.UseObject(stock_serial)
    _pause_ms(PAUSE_DRAG)
    items = API.ItemsInContainer(stock_serial, True) or []
    ing = None
    for item in items:
        if item.Graphic != INGOT_ID:
            continue
        if int(getattr(item, "Hue", -1)) != int(IRON_INGOT_HUE):
            continue
        ing = item
        break
    if not ing:
        _say("No ingots available.", WARN_HUE)
        return 0
    move_amt = min(RESTOCK_AMOUNT, int(getattr(ing, "Amount", 0)))
    API.MoveItem(ing.Serial, API.Backpack, move_amt)
    _pause_ms(PAUSE_DRAG)
    current = _count_in(API.Backpack, INGOT_ID, IRON_INGOT_HUE)
    if current < MIN_INGOTS_IN_PACK:
        _say("Ingot restock failed.", WARN_HUE)
        return 0
    return current


def _restock_resource(stock_serial, item_id, min_in_pack, restock_amount, hue_filter=None):
    current = _count_in(API.Backpack, item_id, hue_filter)
    if current >= min_in_pack:
        return current
    API.UseObject(stock_serial)
    _pause_ms(PAUSE_DRAG)
    items = API.ItemsInContainer(stock_serial, True) or []
    source = None
    for item in items:
        if item.Graphic != item_id:
            continue
        if hue_filter is not None and int(getattr(item, "Hue", -1)) != int(hue_filter):
            continue
        source = item
        break
    if not source:
        return 0
    move_amt = min(restock_amount, int(getattr(source, "Amount", 0)))
    API.MoveItem(source.Serial, API.Backpack, move_amt)
    _pause_ms(PAUSE_DRAG)
    return _count_in(API.Backpack, item_id, hue_filter)


def _cut_bolts_in_backpack():
    scissors = _find_first_in_container(API.Backpack, 0x0F9F)
    if not scissors:
        _say("No scissors in backpack to cut bolts.", WARN_HUE)
        return False
    cut_any = False
    for bolt_id in BOLT_OF_CLOTH_IDS:
        while True:
            bolt = _find_first_in_container(API.Backpack, bolt_id)
            if not bolt:
                break
            API.UseObject(scissors.Serial)
            if not API.WaitForTarget("any", 2):
                return cut_any
            API.Target(bolt.Serial)
            _pause_ms(PAUSE_DRAG)
            cut_any = True
    return cut_any


def _craft_scissors_with_tinkering():
    if STOCK_SERIAL:
        _restock_ingots(STOCK_SERIAL)
    gump_id = _open_tinker_menu()
    if not gump_id:
        _say("Tinker gump not found for scissors craft.", WARN_HUE)
        return False
    if not _craft_tinker_once(gump_id, TINKER_BTN_SCISSORS):
        return False
    _pause_ms(500)
    API.CloseGump(gump_id)
    API.CloseGump()
    return True


def _ensure_scissors_for_tailoring(stock_serial):
    scissors = _find_first_in_container(API.Backpack, 0x0F9F)
    if scissors:
        return True
    stock_scissors = _find_first_in_container(stock_serial, 0x0F9F)
    if stock_scissors:
        API.MoveItem(stock_scissors.Serial, API.Backpack, 1)
        _pause_ms(PAUSE_DRAG)
        return _find_first_in_container(API.Backpack, 0x0F9F) is not None
    if USE_TOOL_CRAFTING:
        if not _ensure_tinker_tools():
            return False
        attempts = 0
        while attempts < 3:
            attempts += 1
            if _craft_scissors_with_tinkering():
                if _find_first_in_container(API.Backpack, 0x0F9F):
                    return True
            _pause_ms(300)
    return False


def _restock_tailor_cloth(stock_serial):
    current = _count_in(API.Backpack, CLOTH_ID)
    if current >= MIN_CLOTH_IN_PACK:
        return current
    current = _restock_resource(stock_serial, CLOTH_ID, MIN_CLOTH_IN_PACK, RESTOCK_CLOTH_AMOUNT)
    if current >= MIN_CLOTH_IN_PACK:
        return current
    attempts = 0
    while current < MIN_CLOTH_IN_PACK and attempts < 6:
        attempts += 1
        bolt = _find_first_in_container_multi(stock_serial, BOLT_OF_CLOTH_IDS)
        if not bolt:
            break
        move_amt = min(6, int(getattr(bolt, "Amount", 1) or 1))
        API.MoveItem(bolt.Serial, API.Backpack, move_amt)
        _pause_ms(PAUSE_DRAG)
        if not _ensure_scissors_for_tailoring(stock_serial):
            _say("No scissors available to cut bolts.", WARN_HUE)
            break
        _cut_bolts_in_backpack()
        current = _count_in(API.Backpack, CLOTH_ID)
    return current


def _restock_boards(stock_serial):
    return _restock_resource(stock_serial, BOARD_ID, MIN_BOARDS_IN_PACK, RESTOCK_BOARDS_AMOUNT)


def _ensure_step_materials(stock_serial, step):
    mats = _normalize_material_requirements(
        step.get("materials", []),
        str(step.get("material", "ingot") or "ingot"),
        ""
    )
    for m in mats:
        base = str(m.get("material", "") or "").lower()
        item_id = int(m.get("item_id", 0) or 0)
        min_in_pack = int(m.get("min_in_pack", 0) or 0)
        pull_amount = int(m.get("pull_amount", 0) or 0)
        hue = m.get("hue", None)
        if base == "board":
            iid = item_id if item_id > 0 else BOARD_ID
            minimum = min_in_pack if min_in_pack > 0 else MIN_BOARDS_IN_PACK
            pull = pull_amount if pull_amount > 0 else RESTOCK_BOARDS_AMOUNT
            if _restock_resource(stock_serial, iid, minimum, pull, hue_filter=hue) < minimum:
                return False
            continue
        if base == "feather":
            iid = item_id if item_id > 0 else FEATHER_ID
            minimum = min_in_pack if min_in_pack > 0 else MIN_FEATHERS_IN_PACK
            pull = pull_amount if pull_amount > 0 else RESTOCK_FEATHERS_AMOUNT
            if _restock_resource(stock_serial, iid, minimum, pull, hue_filter=hue) < minimum:
                return False
            continue
        if base == "cloth":
            minimum = min_in_pack if min_in_pack > 0 else MIN_CLOTH_IN_PACK
            if _restock_tailor_cloth(stock_serial) < minimum:
                return False
            continue
        if base == "leather":
            iid = item_id if item_id > 0 else LEATHER_ID
            minimum = min_in_pack if min_in_pack > 0 else MIN_LEATHER_IN_PACK
            pull = pull_amount if pull_amount > 0 else RESTOCK_LEATHER_AMOUNT
            if _restock_resource(stock_serial, iid, minimum, pull, hue_filter=hue) < minimum:
                return False
            continue
        if base == "ingot":
            iid = item_id if item_id > 0 else INGOT_ID
            minimum = min_in_pack if min_in_pack > 0 else MIN_INGOTS_IN_PACK
            pull = pull_amount if pull_amount > 0 else RESTOCK_AMOUNT
            if _restock_resource(stock_serial, iid, minimum, pull, hue_filter=hue) < minimum:
                return False
            continue
        if item_id > 0:
            minimum = min_in_pack if min_in_pack > 0 else 10
            pull = pull_amount if pull_amount > 0 else max(50, minimum)
            if _restock_resource(stock_serial, item_id, minimum, pull, hue_filter=hue) < minimum:
                return False
            continue
    return True


def _ensure_item_in_backpack_from_stock(stock_serial, item_id, min_in_pack, pull_amount):
    if _count_in(API.Backpack, item_id) >= min_in_pack:
        return True
    if not stock_serial:
        return False
    item = _find_first_in_container(stock_serial, item_id)
    if not item:
        return False
    move_amt = min(int(getattr(item, "Amount", 1) or 1), int(pull_amount))
    API.MoveItem(item.Serial, API.Backpack, move_amt)
    _pause_ms(PAUSE_DRAG)
    return _count_in(API.Backpack, item_id) >= min_in_pack


def _ensure_inscription_reagents(stock_serial):
    for reg in INSCRIPTION_REAGENTS:
        if _count_in(API.Backpack, reg) >= INSCRIPTION_REAGENT_MIN:
            continue
        item = _find_first_in_container(stock_serial, reg)
        if not item:
            return False
        move_amt = min(int(getattr(item, "Amount", 1) or 1), int(INSCRIPTION_REAGENT_PULL))
        API.MoveItem(item.Serial, API.Backpack, move_amt)
        _pause_ms(PAUSE_DRAG)
        if _count_in(API.Backpack, reg) < INSCRIPTION_REAGENT_MIN:
            return False
    return True


def _check_and_regen_mana(threshold):
    if threshold is None:
        threshold = API.Player.ManaMax
    if API.Player.Mana >= threshold or API.Player.Mana >= API.Player.ManaMax:
        return
    while RUNNING and API.Player.Mana < threshold:
        API.ProcessCallbacks()
        if not API.BuffExists("Meditation"):
            API.UseSkill("Meditation")
        _pause_ms(1000)


def _open_inscription_gump(pen_serial):
    _close_blacksmith_gump_if_open()
    _close_tinker_gump_if_open()
    _close_tailor_gump_if_open()
    _close_carpentry_gump_if_open()
    _close_bowcraft_gump_if_open()
    API.UseObject(pen_serial)
    _pause_ms(1000)
    return API.WaitForGump(0, 3)


def _craft_inscription_selection(page_button, spell_button):
    API.ReplyGump(page_button)
    _pause_ms(1000)
    API.ReplyGump(spell_button)
    _pause_ms(1000)


def _craft_once(gump_id, buttons):
    if not gump_id or not _gump_matches_anchors(gump_id, BLACKSMITH_GUMP_ANCHORS):
        gump_id = _wait_for_gump(BLACKSMITH_GUMP_ANCHORS, timeout_s=2, preferred_id=BLACKSMITH_GUMP_ID)
    if not gump_id:
        _say("Blacksmith gump validation failed.", WARN_HUE)
        return False
    for b in buttons:
        if not _gump_matches_anchors(gump_id, BLACKSMITH_GUMP_ANCHORS):
            _say("Blacksmith gump changed unexpectedly.", WARN_HUE)
            return False
        API.ReplyGump(b, gump_id)
        _pause_ms(PAUSE_GUMP_CLICK)
    return True


def _craft_tinker_once(gump_id, buttons):
    if not buttons:
        return False
    if not gump_id or not _gump_matches_anchors(gump_id, TINKER_GUMP_ANCHORS):
        gump_id = _wait_for_gump(TINKER_GUMP_ANCHORS, timeout_s=2, preferred_id=TINKER_GUMP_ID)
    if not gump_id:
        _say("Tinker gump validation failed.", WARN_HUE)
        return False
    if len(buttons) == 1:
        if not _gump_matches_anchors(gump_id, TINKER_GUMP_ANCHORS):
            _say("Tinker gump changed unexpectedly.", WARN_HUE)
            return False
        API.ReplyGump(buttons[0], gump_id)
        _pause_ms(PAUSE_GUMP_CLICK)
        return True
    first, second = buttons[0], buttons[1]
    if not _gump_matches_anchors(gump_id, TINKER_GUMP_ANCHORS):
        _say("Tinker gump changed unexpectedly.", WARN_HUE)
        return False
    API.ReplyGump(first, gump_id)
    _wait_for_gump(TINKER_GUMP_ANCHORS, timeout_s=2, preferred_id=TINKER_GUMP_ID)
    _pause_ms(PAUSE_GUMP_CLICK)
    if not _gump_matches_anchors(gump_id, TINKER_GUMP_ANCHORS):
        _say("Tinker gump changed unexpectedly.", WARN_HUE)
        return False
    API.ReplyGump(second, gump_id)
    _pause_ms(PAUSE_GUMP_CLICK)
    return True

def _gump_has_text(gump_id, phrases):
    contents = API.GetGumpContents(gump_id)
    if not contents:
        return False
    lower = contents.lower()
    for p in phrases:
        if p in lower:
            return True
    return False


def _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline_expected):
    waited = 0
    step = 125
    while waited <= CRAFT_TIMEOUT_MS:
        if _count_in(API.Backpack, expected_item_id) > baseline_expected:
            return True
        if _gump_has_text(gump_id, GUMP_FAIL_TEXTS):
            return False
        _pause_ms(step)
        waited += step
    return False


def _move_to_salvage(item_id, salvage_serial):
    itm = _find_first_in_container(API.Backpack, item_id)
    if not itm:
        return False
    API.MoveItem(itm.Serial, salvage_serial, int(getattr(itm, "Amount", 1)))
    _pause_ms(PAUSE_DRAG)
    return True


def _smelt_salvage_bag(serial):
    API.ContextMenu(serial, SALVAGE_CONTEXT_INDEX)
    _pause_ms(250)


def _normalize_steps(steps):
    s = sorted(steps, key=lambda x: float(x["start_at"]))
    out = []
    seen = set()
    for step in s:
        key = float(step["start_at"])
        if key in seen:
            continue
        out.append(step)
        seen.add(key)
    return out


def _pick_step(skill, steps_sorted):
    chosen = steps_sorted[0]
    for step in steps_sorted:
        s_at = float(step.get("start_at", 0.0) or 0.0)
        e_at = float(step.get("stop_at", 0.0) or 0.0)
        if skill >= s_at and (e_at <= 0.0 or skill < e_at):
            return step
        if skill >= s_at:
            chosen = step
            continue
        break
    return chosen


def _near_any_swap(skill, swap_points):
    for t in swap_points:
        if abs(skill - t) <= SWAP_WINDOW:
            return True
    return False


# === TINKERING HELPERS ===

def _get_tinker_tool():
    for graphic in TINKER_TOOL_GRAPHICS:
        tool = API.FindType(graphic, API.Backpack)
        if tool:
            return tool
    return None

def _count_tinker_tools():
    items = API.ItemsInContainer(API.Backpack, True) or []
    return sum(1 for i in items if i.Graphic in TINKER_TOOL_GRAPHICS)

def _open_tinker_menu_for_tools():
    _close_blacksmith_gump_if_open()
    _close_tailor_gump_if_open()
    _close_carpentry_gump_if_open()
    _close_bowcraft_gump_if_open()
    tool = _get_tinker_tool()
    if not tool:
        return 0
    API.UseObject(tool.Serial)
    gid = _wait_for_gump(TINKER_GUMP_ANCHORS, timeout_s=3, preferred_id=TINKER_GUMP_ID)
    if not gid:
        return 0
    _pause_ms(250)
    API.ReplyGump(TINKER_BTN_TOOLS, gid)
    gid = _wait_for_gump(TINKER_GUMP_ANCHORS, timeout_s=3, preferred_id=TINKER_GUMP_ID)
    if not gid:
        return 0
    _pause_ms(250)
    return gid

def _craft_tinker_tool():
    if STOCK_SERIAL:
        _restock_ingots(STOCK_SERIAL)
    gump_id = _open_tinker_menu_for_tools()
    if not gump_id:
        _say("Tinker gump not found.", WARN_HUE)
        return False
    API.ReplyGump(TINKER_BTN_TINKER_TOOL, gump_id)
    _pause_ms(500)
    API.CloseGump(gump_id)
    API.CloseGump()
    return True

def _craft_blacksmith_tool_with_tinkering():
    if STOCK_SERIAL:
        _restock_ingots(STOCK_SERIAL)
    gump_id = _open_tinker_menu_for_tools()
    if not gump_id:
        _say("Tinker gump not found for blacksmith tool craft.", WARN_HUE)
        return False
    API.ReplyGump(TINKER_BTN_TONGS, gump_id)
    _pause_ms(500)
    API.CloseGump(gump_id)
    API.CloseGump()
    return True

def _craft_tailor_tool_with_tinkering():
    if STOCK_SERIAL:
        _restock_ingots(STOCK_SERIAL)
    gump_id = _open_tinker_menu()
    if not gump_id:
        _say("Tinker gump not found for tailoring tool craft.", WARN_HUE)
        return False
    if not _craft_tinker_once(gump_id, TINKER_BTN_SEWING_KIT):
        return False
    _pause_ms(500)
    API.CloseGump(gump_id)
    API.CloseGump()
    return True


def _craft_carpentry_tool_with_tinkering():
    if STOCK_SERIAL:
        _restock_ingots(STOCK_SERIAL)
    gump_id = _open_tinker_menu()
    if not gump_id:
        _say("Tinker gump not found for carpentry tool craft.", WARN_HUE)
        return False
    if not _craft_tinker_once(gump_id, TINKER_BTN_DOVETAIL_SAW):
        return False
    _pause_ms(500)
    API.CloseGump(gump_id)
    API.CloseGump()
    return True

def _ensure_tinker_tools():
    if STOCK_SERIAL == 0:
        _say("Resource stock not set. Pausing.", WARN_HUE)
        return False
    count = _count_tinker_tools()
    if count == 0:
        stock_tool = _find_first_in_container_multi(STOCK_SERIAL, TINKER_TOOL_GRAPHICS)
        if not stock_tool:
            _say("No tinker's tools available in stock.", WARN_HUE)
            return False
        API.MoveItem(stock_tool.Serial, API.Backpack, 1)
        _pause_ms(PAUSE_DRAG)
        count = _count_tinker_tools()
    if not USE_TOOL_CRAFTING:
        return True
    if count < 2:
        if STOCK_SERIAL:
            _restock_ingots(STOCK_SERIAL)
        if not _craft_tinker_tool():
            return False
    return True


def _open_tinker_menu():
    _close_blacksmith_gump_if_open()
    _close_tailor_gump_if_open()
    _close_carpentry_gump_if_open()
    _close_bowcraft_gump_if_open()
    tool = _get_tinker_tool()
    if not tool:
        _say("No tinker's tool in backpack.", WARN_HUE)
        return 0
    API.UseObject(tool.Serial)
    gid = _wait_for_gump(TINKER_GUMP_ANCHORS, timeout_s=3, preferred_id=TINKER_GUMP_ID)
    if gid:
        return gid
    _say("Tinker gump not found.", WARN_HUE)
    return 0


def _train_tinkering_to(cap):
    global STOCK_SERIAL
    if cap <= 0:
        return True
    if _get_skill_value("Tinkering") < 30.0:
        API.HeadMsg("Train from a Tinker NPC", API.Player, WARN_HUE)
        _say("Tinkering below 30.0. Train from a Tinker NPC.", WARN_HUE)
        return False
    if STOCK_SERIAL == 0:
        API.SysMsg("Target resource container (ingots).")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if STOCK_SERIAL == 0:
        _say("Stock chest not set. Pausing.", WARN_HUE)
        return False

    steps = _resolve_training_steps("Tinkering")
    if not steps:
        _say(f"No Tinkering training recipes for server '{SELECTED_SERVER}'.", WARN_HUE)
        return False
    swap_points = [float(s["start_at"]) for s in steps if float(s["start_at"]) > 0.0]
    last_step_name = ""

    while RUNNING and _get_skill_value("Tinkering") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break
        if not _ensure_tinker_tools():
            return False

        if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
            _clear_crafted_items([int(s.get("item_id", 0) or 0) for s in steps if int(s.get("item_id", 0) or 0) > 0])
            if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
                _say("Backpack full. Pausing.", WARN_HUE)
                return False

        stock = API.FindItem(STOCK_SERIAL)
        if not stock:
            _say("Tinkering stock invalid. Pausing.", WARN_HUE)
            return False

        API.UseObject(stock.Serial)
        _pause_ms(300)

        skill = _get_skill_value("Tinkering")
        step = _pick_step(skill, steps)
        if str(step.get("action", "")).strip().lower() == "npc_training":
            msg = str(step.get("message", "") or "Train from a Tinker NPC")
            API.HeadMsg(msg, API.Player, WARN_HUE)
            _say(msg, WARN_HUE)
            return False
        if not _ensure_step_materials(stock.Serial, step):
            _say("Missing tinkering materials.", WARN_HUE)
            return False

        gump_id = _open_tinker_menu()
        if gump_id == 0:
            return False

        if (last_step_name and step["name"] != last_step_name) or _near_any_swap(skill, swap_points):
            gump_id = _open_tinker_menu()

        last_step_name = step["name"]
        expected_item_id = int(step.get("item_id", 0) or 0)
        baseline = _count_in(API.Backpack, expected_item_id) if expected_item_id else 0

        if not _craft_tinker_once(gump_id, step["buttons"]):
            return False
        _say(f"Skill {skill:.1f} Making {step['name']}", STATUS_HUE)

        if expected_item_id:
            if _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline):
                moved = False
                if SALVAGE_SERIAL:
                    moved = _move_to_salvage(expected_item_id, SALVAGE_SERIAL)
                if not moved and TRASH_SERIAL:
                    _move_to_salvage(expected_item_id, TRASH_SERIAL)
        else:
            _pause_ms(PAUSE_AFTER_CRAFT)
        _pause_ms(PAUSE_AFTER_CRAFT)

    return True


def _train_blacksmithy_to(cap):
    global STOCK_SERIAL, SALVAGE_SERIAL
    if cap <= 0:
        return True
    if STOCK_SERIAL == 0:
        API.SysMsg("Target stock chest for Blacksmithing.")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if SALVAGE_SERIAL == 0:
        API.SysMsg("Target salvage bag for Blacksmithing.")
        serial = API.RequestTarget()
        if serial:
            SALVAGE_SERIAL = int(serial)

    steps = _resolve_training_steps("Blacksmithy")
    if not steps:
        _say(f"No Blacksmithy training recipes for server '{SELECTED_SERVER}'.", WARN_HUE)
        return False
    swap_points = [float(s["start_at"]) for s in steps if float(s["start_at"]) > 0.0]
    last_step_name = ""

    while RUNNING and _get_skill_value("Blacksmithy") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break
        if not STOCK_SERIAL or not SALVAGE_SERIAL:
            _say("Stock or Salvage not set. Pausing.", WARN_HUE)
            return False

        stock = API.FindItem(STOCK_SERIAL)
        salvage_bag = API.FindItem(SALVAGE_SERIAL)
        if not stock or not salvage_bag:
            _say("Stock or Salvage invalid. Pausing.", WARN_HUE)
            return False

        if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
            _clear_crafted_items([int(s.get("item_id", 0) or 0) for s in steps if int(s.get("item_id", 0) or 0) > 0])
            if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
                _say("Backpack full. Pausing.", WARN_HUE)
                return False

        API.UseObject(stock.Serial)
        _pause_ms(300)

        ingots = _restock_ingots(stock.Serial)
        if ingots == 0:
            return False

        skill = _get_skill_value("Blacksmithy")
        step = _pick_step(skill, steps)

        gump_id = _open_blacksmith_menu(stock.Serial)
        if gump_id == 0:
            return False

        if (last_step_name and step["name"] != last_step_name) or _near_any_swap(skill, swap_points):
            gump_id = _reset_blacksmith_menu(stock.Serial)

        last_step_name = step["name"]
        expected_item_id = step["item_id"]
        baseline = _count_in(API.Backpack, expected_item_id)

        if not _craft_once(gump_id, step["buttons"]):
            return False
        _say(f"Skill {skill:.1f} Making {step['name']}", STATUS_HUE)

        if _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline):
            moved = False
            if SALVAGE_SERIAL and _move_to_salvage(expected_item_id, SALVAGE_SERIAL):
                _smelt_salvage_bag(SALVAGE_SERIAL)
                moved = True
            if not moved and TRASH_SERIAL:
                _move_to_salvage(expected_item_id, TRASH_SERIAL)

        _pause_ms(PAUSE_AFTER_CRAFT)

    return True


def _train_tailoring_to(cap):
    global STOCK_SERIAL
    if cap <= 0:
        return True
    if _get_skill_value("Tailoring") < 29.0:
        API.HeadMsg("Purchase skill gains from an NPC Tailor", API.Player, WARN_HUE)
        _say("Tailoring below 29.0. Purchase skill gains from an NPC Tailor.", WARN_HUE)
        return False
    if STOCK_SERIAL == 0:
        API.SysMsg("Target stock chest for Tailoring.")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if STOCK_SERIAL == 0:
        _say("Tailoring stock not set. Pausing.", WARN_HUE)
        return False

    steps = _resolve_training_steps("Tailoring")
    if not steps:
        _say(f"No Tailoring training recipes for server '{SELECTED_SERVER}'.", WARN_HUE)
        return False
    swap_points = [float(s["start_at"]) for s in steps if float(s["start_at"]) > 0.0]
    last_step_name = ""

    while RUNNING and _get_skill_value("Tailoring") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break

        stock = API.FindItem(STOCK_SERIAL)
        if not stock:
            _say("Tailoring stock invalid. Pausing.", WARN_HUE)
            return False

        if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
            _clear_crafted_items([int(s.get("item_id", 0) or 0) for s in steps if int(s.get("item_id", 0) or 0) > 0])
            if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
                _say("Backpack full. Pausing.", WARN_HUE)
                return False

        skill = _get_skill_value("Tailoring")
        step = _pick_step(skill, steps)
        if str(step.get("action", "")).strip().lower() == "npc_training":
            msg = str(step.get("message", "") or "Purchase skill gains from an NPC Tailor")
            API.HeadMsg(msg, API.Player, WARN_HUE)
            _say(msg, WARN_HUE)
            return False
        material = (step.get("material") or "cloth").lower()
        if material == "leather":
            stocked = _restock_resource(stock.Serial, LEATHER_ID, MIN_LEATHER_IN_PACK, RESTOCK_LEATHER_AMOUNT)
            if stocked < MIN_LEATHER_IN_PACK:
                _say("Not enough leather for tailoring.", WARN_HUE)
                return False
        else:
            stocked = _restock_tailor_cloth(stock.Serial)
            if stocked < MIN_CLOTH_IN_PACK:
                _say("Not enough cloth for tailoring.", WARN_HUE)
                return False

        gump_id = _open_tailor_menu(stock.Serial)
        if gump_id == 0:
            return False

        if (last_step_name and step["name"] != last_step_name) or _near_any_swap(skill, swap_points):
            _close_tailor_gump_if_open()
            gump_id = _open_tailor_menu(stock.Serial)
            if gump_id == 0:
                return False

        last_step_name = step["name"]
        expected_item_id = int(step.get("item_id", 0) or 0)
        baseline = _count_in(API.Backpack, expected_item_id) if expected_item_id else 0

        if not _craft_tailor_once(gump_id, step):
            return False
        _say(f"Skill {skill:.1f} Making {step['name']}", STATUS_HUE)

        if expected_item_id:
            if _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline):
                moved = False
                if SALVAGE_SERIAL and _move_to_salvage(expected_item_id, SALVAGE_SERIAL):
                    _smelt_salvage_bag(SALVAGE_SERIAL)
                    moved = True
                if not moved and TRASH_SERIAL:
                    _move_to_salvage(expected_item_id, TRASH_SERIAL)
        else:
            _pause_ms(TAILOR_CRAFT_SETTLE_MS)

        _pause_ms(PAUSE_AFTER_CRAFT)

    return True


def _train_carpentry_to(cap):
    global STOCK_SERIAL
    if cap <= 0:
        return True
    if _get_skill_value("Carpentry") < 30.0:
        API.HeadMsg("Train directly from a Carpenter NPC", API.Player, WARN_HUE)
        _say("Carpentry below 30.0. Train directly from a Carpenter NPC.", WARN_HUE)
        return False
    if STOCK_SERIAL == 0:
        API.SysMsg("Target stock chest for Carpentry.")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if STOCK_SERIAL == 0:
        _say("Carpentry stock not set. Pausing.", WARN_HUE)
        return False

    steps = _resolve_training_steps("Carpentry")
    if not steps:
        _say(f"No Carpentry training recipes for server '{SELECTED_SERVER}'.", WARN_HUE)
        return False
    swap_points = [float(s["start_at"]) for s in steps if float(s["start_at"]) > 0.0]
    last_step_name = ""

    while RUNNING and _get_skill_value("Carpentry") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break

        stock = API.FindItem(STOCK_SERIAL)
        if not stock:
            _say("Carpentry stock invalid. Pausing.", WARN_HUE)
            return False

        if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
            _clear_crafted_items([int(s.get("item_id", 0) or 0) for s in steps if int(s.get("item_id", 0) or 0) > 0])
            if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
                _say("Backpack full. Pausing.", WARN_HUE)
                return False

        boards = _restock_boards(stock.Serial)
        if boards < MIN_BOARDS_IN_PACK:
            _say("Not enough boards for carpentry.", WARN_HUE)
            return False

        skill = _get_skill_value("Carpentry")
        step = _pick_step(skill, steps)
        if str(step.get("action", "")).strip().lower() == "npc_training":
            msg = str(step.get("message", "") or "Train directly from a Carpenter NPC")
            API.HeadMsg(msg, API.Player, WARN_HUE)
            _say(msg, WARN_HUE)
            return False

        gump_id = _open_carpentry_menu(stock.Serial)
        if gump_id == 0:
            return False

        if (last_step_name and step["name"] != last_step_name) or _near_any_swap(skill, swap_points):
            _close_carpentry_gump_if_open()
            gump_id = _open_carpentry_menu(stock.Serial)
            if gump_id == 0:
                return False

        last_step_name = step["name"]
        expected_item_id = int(step.get("item_id", 0) or 0)
        baseline = _count_in(API.Backpack, expected_item_id) if expected_item_id else 0

        if not _craft_carpentry_once(gump_id, step):
            return False
        _say(f"Skill {skill:.1f} Making {step['name']}", STATUS_HUE)

        if expected_item_id:
            if _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline):
                moved = False
                if SALVAGE_SERIAL and _move_to_salvage(expected_item_id, SALVAGE_SERIAL):
                    _smelt_salvage_bag(SALVAGE_SERIAL)
                    moved = True
                if moved:
                    _move_salvage_non_keep_to_trash()
                if not moved and TRASH_SERIAL:
                    _move_to_salvage(expected_item_id, TRASH_SERIAL)
        else:
            _pause_ms(CARPENTRY_CRAFT_SETTLE_MS)

        _pause_ms(PAUSE_AFTER_CRAFT)

    return True


def _train_bowcraft_to(cap):
    global STOCK_SERIAL
    if cap <= 0:
        return True
    if _get_skill_value("Bowcraft/Fletching") < 30.0:
        API.HeadMsg("Train from a Bowyer NPC", API.Player, WARN_HUE)
        _say("Bowcraft/Fletching below 30.0. Train from a Bowyer NPC.", WARN_HUE)
        return False
    if STOCK_SERIAL == 0:
        API.SysMsg("Target stock chest for Bowcraft/Fletching.")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if STOCK_SERIAL == 0:
        _say("Bowcraft/Fletching stock not set. Pausing.", WARN_HUE)
        return False

    steps = _resolve_training_steps("Bowcraft/Fletching")
    if not steps:
        _say(f"No Bowcraft/Fletching training recipes for server '{SELECTED_SERVER}'.", WARN_HUE)
        return False
    swap_points = [float(s["start_at"]) for s in steps if float(s["start_at"]) > 0.0]
    last_step_name = ""

    while RUNNING and _get_skill_value("Bowcraft/Fletching") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break

        stock = API.FindItem(STOCK_SERIAL)
        if not stock:
            _say("Bowcraft/Fletching stock invalid. Pausing.", WARN_HUE)
            return False

        if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
            _clear_crafted_items([int(s.get("item_id", 0) or 0) for s in steps if int(s.get("item_id", 0) or 0) > 0])
            if _backpack_item_count() >= BACKPACK_ITEM_THRESHOLD:
                _say("Backpack full. Pausing.", WARN_HUE)
                return False

        skill = _get_skill_value("Bowcraft/Fletching")
        step = _pick_step(skill, steps)
        if str(step.get("action", "")).strip().lower() == "npc_training":
            msg = str(step.get("message", "") or "Train from a Bowyer NPC")
            API.HeadMsg(msg, API.Player, WARN_HUE)
            _say(msg, WARN_HUE)
            return False

        if not _ensure_step_materials(stock.Serial, step):
            _say("Missing bowcraft materials (boards/feathers).", WARN_HUE)
            return False

        gump_id = _open_bowcraft_menu(stock.Serial)
        if gump_id == 0:
            return False

        if (last_step_name and step["name"] != last_step_name) or _near_any_swap(skill, swap_points):
            _close_bowcraft_gump_if_open()
            gump_id = _open_bowcraft_menu(stock.Serial)
            if gump_id == 0:
                return False

        last_step_name = step["name"]
        expected_item_id = int(step.get("item_id", 0) or 0)
        baseline = _count_in(API.Backpack, expected_item_id) if expected_item_id else 0

        if not _craft_bowcraft_once(gump_id, step):
            return False
        _say(f"Skill {skill:.1f} Making {step['name']}", STATUS_HUE)

        if expected_item_id:
            if _wait_for_expected_item_or_fail(gump_id, expected_item_id, baseline):
                moved = False
                if SALVAGE_SERIAL and _move_to_salvage(expected_item_id, SALVAGE_SERIAL):
                    _smelt_salvage_bag(SALVAGE_SERIAL)
                    moved = True
                if moved:
                    _move_salvage_non_keep_to_trash()
                if not moved and TRASH_SERIAL:
                    _move_to_salvage(expected_item_id, TRASH_SERIAL)
        else:
            _pause_ms(BOWCRAFT_CRAFT_SETTLE_MS)

        _pause_ms(PAUSE_AFTER_CRAFT)

    return True


def _train_inscription_to(cap):
    global STOCK_SERIAL
    if cap <= 0:
        return True
    if STOCK_SERIAL == 0:
        API.SysMsg("Target stock chest for Inscription.")
        serial = API.RequestTarget()
        if serial:
            STOCK_SERIAL = int(serial)
    if STOCK_SERIAL == 0:
        _say("Inscription stock not set. Pausing.", WARN_HUE)
        return False

    steps = _normalize_steps(INSCRIPTION_STEPS)

    while RUNNING and _get_skill_value("Inscribe") < cap:
        API.ProcessCallbacks()
        if not RUNNING:
            break

        stock = API.FindItem(STOCK_SERIAL)
        if not stock:
            _say("Inscription stock invalid. Pausing.", WARN_HUE)
            return False

        if not _ensure_item_in_backpack_from_stock(stock.Serial, SCRIBE_PEN_ID, 1, 1):
            _say("No pens available for inscription.", WARN_HUE)
            return False
        if not _ensure_item_in_backpack_from_stock(stock.Serial, BLANK_SCROLL_ID, INSCRIPTION_SCROLL_MIN, INSCRIPTION_SCROLL_PULL):
            _say("No blank scrolls available for inscription.", WARN_HUE)
            return False
        if not _ensure_inscription_reagents(stock.Serial):
            _say("Missing inscription reagents.", WARN_HUE)
            return False

        current_skill = _get_skill_value("Inscribe")
        skill_cap = _get_skill_cap("Inscribe")
        if skill_cap > 0 and current_skill >= skill_cap:
            _say("Inscribe is at skill cap. Pausing.", WARN_HUE)
            return False

        step = _pick_step(current_skill, steps)
        _check_and_regen_mana(step.get("mana"))

        pen = _find_first_in_container(API.Backpack, SCRIBE_PEN_ID)
        if not pen:
            _say("No pen in backpack.", WARN_HUE)
            return False

        if not _open_inscription_gump(pen.Serial):
            _say("Inscription gump not found, retrying...", WARN_HUE)
            _pause_ms(1000)
            continue

        _craft_inscription_selection(step["page_button"], step["spell_button"])
        _say(f"Skill {current_skill:.1f} Making {step['name']}", STATUS_HUE)
        _pause_ms(INSCRIPTION_CRAFT_PAUSE_MS)

    return True


# === MAIN LOOP ===

def _train_skill(name, cap):
    if cap <= 0:
        return True
    current = _get_skill_value(name)
    if current >= cap:
        return True
    if USE_TOOL_CRAFTING and name in ("Blacksmithy", "Tailoring", "Carpentry"):
        if not _ensure_tinker_tools():
            return False
    if name == "Blacksmithy":
        return _train_blacksmithy_to(cap)
    if name == "Tinkering":
        return _train_tinkering_to(cap)
    if name == "Carpentry":
        return _train_carpentry_to(cap)
    if name == "Inscription":
        return _train_inscription_to(cap)
    if name == "Tailoring":
        return _train_tailoring_to(cap)
    if name == "Bowcraft/Fletching":
        return _train_bowcraft_to(cap)
    API.SysMsg(f"{name} training not configured yet. Skipping.")
    return True


def _main():
    _create_gump()
    _load_config()
    _rebuild_gump()
    API.SysMsg(f"CrafterTrainer loaded. Server={SELECTED_SERVER}. Enter caps and press Start.")

    while True:
        API.ProcessCallbacks()
        _pause_if_needed()
        _update_caps_from_gump()

        for name in CRAFT_SKILLS:
            _update_caps_from_gump()
            cap = SKILL_CAPS.get(name, 0.0)
            if cap <= 0:
                continue
            if not RUNNING:
                break
            _train_skill(name, cap)
            if RUNNING and _get_skill_value(name) >= cap:
                _move_salvage_non_keep_to_trash()

        API.Pause(0.2)


_main()
