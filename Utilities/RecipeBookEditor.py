import API
import json
import ast
import os
import re
import sys
import sqlite3

"""
RecipeBookEditor

Shared manual recipe editor for split recipe/key-map files.
Supports single or multi-material recipes.

`materials` format (semicolon-separated):
- material
- material:item_id
- material:item_id:min_in_pack:pull_amount
- material:item_id:min_in_pack:pull_amount:hue

Example:
board;feather
ingot:0x1BF2:60:400:0;gem:0x0F26:10:80;super_gem:0x1234:10:80
"""

REQUEST_KEY = "recipe_editor_request"
RESULT_KEY = "recipe_editor_result"
DEBUG_LOG_FILE = "RecipeBookEditor.debug.log"

SERVER_OPTIONS = ["OSI", "UOAlive", "Sosaria Reforged", "InsaneUO"]
DEFAULT_SERVER = "UOAlive"
RECIPE_TYPE_OPTIONS = ["bod", "training"]
RECIPE_TYPE_LABELS = ["BOD", "Training"]
EDITOR_MODE_OPTIONS = ["bind_deed", "recipe_builder"]
EDITOR_MODE_LABELS = ["Bind Deed", "Recipe Builder"]
PROFESSION_OPTIONS = ["Blacksmith", "Tailor", "Carpentry", "Tinker", "Bowcraft"]
MATERIAL_BASE_OPTIONS = ["ingot", "cloth", "leather", "board", "feather", "scale", "gem", "super_gem"]
EDITOR_BG_GUMP_ART_ID = 271
MATERIAL_KEY_DEFAULT_OPTIONS = ["ingot_iron", "cloth", "leather", "board", "feather"]
MATERIAL_KEY_ADD_LABEL = "Add New..."
RESOURCE_NONE_LABEL = "<none>"
RESOURCE_SLOT_COUNT = 5
ITEM_NONE_LABEL = "<none>"
RESOURCE_FALLBACK_OPTIONS = [
    "Ingot",
    "Board",
    "Feather",
    "Ruby",
    "Diamond",
    "Sapphire",
    "Citrine",
    "Tourmaline",
    "Amber",
    "Star Sapphire",
    "Amethyst",
    "Emerald",
    "Dark Sapphire",
    "Turquoise",
    "Perfect Emerald",
    "Ecru Citrine",
    "Fire Ruby",
    "Leather",
    "Cloth",
    "Blank Scroll",
    "Nox Crystal",
    "Spider Silk",
    "Mandrake",
]
MATERIAL_KEY_OPTIONS_BY_PROFESSION = {
    "Blacksmith": [
        "ingot_iron",
        "ingot_dull_copper",
        "ingot_shadow_iron",
        "ingot_copper",
        "ingot_bronze",
        "ingot_gold",
        "ingot_agapite",
        "ingot_verite",
        "ingot_valorite",
        "scale_red",
        "scale_yellow",
        "scale_black",
        "scale_green",
        "scale_white",
        "scale_blue",
    ],
    "Tailor": ["cloth", "leather"],
    "Carpentry": ["board"],
    "Tinker": [
        "ingot_iron",
        "ingot_dull_copper",
        "ingot_shadow_iron",
        "ingot_copper",
        "ingot_bronze",
        "ingot_gold",
        "ingot_agapite",
        "ingot_verite",
        "ingot_valorite",
    ],
    "Bowcraft": ["board", "feather"],
}
MATERIAL_BUTTONS_BY_KEY = {
    "Blacksmith": {
        "ingot_iron": [7, 6],
        "ingot_dull_copper": [7, 26],
        "ingot_shadow_iron": [7, 46],
        "ingot_copper": [7, 66],
        "ingot_bronze": [7, 86],
        "ingot_gold": [7, 106],
        "ingot_agapite": [7, 126],
        "ingot_verite": [7, 146],
        "ingot_valorite": [7, 166],
        "scale_red": [147, 6],
        "scale_yellow": [147, 26],
        "scale_black": [147, 46],
        "scale_green": [147, 66],
        "scale_white": [147, 86],
        "scale_blue": [147, 106],
    },
}

EDITOR_GUMP = None
EDITOR_INPUTS = {}
REQUEST_NONCE = 0
EDITOR_LAST_TYPE_IDX = -1
EDITOR_LAST_MATERIAL_KEY_IDX = -1
EDITOR_LAST_PROFESSION_IDX = -1
EDITOR_LAST_MODE_IDX = -1
SCRIPT_EXIT_REQUESTED = False

RECIPE_STORE = None
_script_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
_util_dir = _script_dir
if os.path.basename(str(_util_dir or "")).lower() != "utilities":
    _cand = os.path.join(_script_dir, "Utilities")
    if os.path.isdir(_cand):
        _util_dir = _cand
if _util_dir and _util_dir not in sys.path:
    sys.path.insert(0, _util_dir)
try:
    import RecipeStore as RECIPE_STORE
    try:
        RECIPE_STORE.set_base_dir(_util_dir)
    except Exception:
        pass
except Exception:
    RECIPE_STORE = None


def _say(msg, hue=17):
    API.SysMsg(msg, hue)


def _write_debug_log(msg):
    try:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(_util_dir, DEBUG_LOG_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write("[{0}] {1}\n".format(ts, str(msg)))
    except Exception:
        pass


def _parse_int_list(text):
    return [int(x) for x in re.findall(r"\d+", str(text or ""))]


def _parse_item_id(text):
    t = str(text or "").strip().lower()
    if not t:
        return 0
    if t.startswith("0x"):
        try:
            return int(t, 16)
        except Exception:
            return 0
    try:
        return int(t)
    except Exception:
        return 0


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


def _material_key_from_base(base):
    b = str(base or "").strip().lower()
    if b == "cloth":
        return "cloth"
    if b == "leather":
        return "leather"
    if b == "board":
        return "board"
    if b in ("feather", "feathers"):
        return "feather"
    return "ingot_iron"


def _material_base_from_key(key, fallback="ingot"):
    k = str(key or "").strip().lower()
    if k in ("cloth", "leather", "board", "feather"):
        return k
    if k in ("feathers",):
        return "feather"
    if k.startswith("ingot"):
        return "ingot"
    return str(fallback or "ingot").strip().lower() or "ingot"


def _normalize_item_key_name(name):
    n = str(name or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"[^a-z0-9 '\-]", "", n)
    return n.strip()


def _parse_resources_text(text):
    out = []
    for chunk in [x.strip() for x in str(text or "").split(";") if str(x or "").strip()]:
        parts = [p.strip() for p in chunk.split(":")]
        if not parts:
            continue
        mat = str(parts[0] or "").strip().lower()
        if not mat:
            continue
        qty = 0
        if len(parts) > 1:
            try:
                qty = int(parts[1])
            except Exception:
                qty = 0
        if qty <= 0:
            continue
        out.append({"material": mat, "per_item": int(qty)})
    return out


def _resources_to_text(resources):
    if not isinstance(resources, list):
        return ""
    parts = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        mat = str(r.get("material", "") or "").strip().lower()
        qty = int(r.get("per_item", 0) or 0)
        if mat and qty > 0:
            parts.append(f"{mat}:{qty}")
    return ";".join(parts)


def _load_resource_name_options():
    candidates = []
    try:
        candidates.append(os.path.join(_util_dir, "craftables.db"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(_script_dir, "craftables.db"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(os.getcwd(), "craftables.db"))
    except Exception:
        pass
    seen = set()
    out = []
    for p in candidates:
        t = str(p or "").strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        if not os.path.exists(t):
            continue
        conn = None
        try:
            conn = sqlite3.connect(t, timeout=0.35)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=350")
            cur.execute(
                """
                SELECT name
                FROM resources
                WHERE trim(coalesce(name, '')) <> ''
                ORDER BY name COLLATE NOCASE
                """
            )
            rows = cur.fetchall()
            out = [str(r["name"] or "").strip() for r in rows if str(r["name"] or "").strip()]
            if out:
                break
        except Exception:
            out = []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    if not out:
        out = list(RESOURCE_FALLBACK_OPTIONS)
    seen_names = set()
    deduped = []
    for n in out:
        t = str(n or "").strip()
        if not t:
            continue
        lk = t.lower()
        if lk in seen_names:
            continue
        seen_names.add(lk)
        deduped.append(t)
    return deduped


def _resource_option_index(options, name):
    target = str(name or "").strip().lower()
    if not target:
        return -1
    for i, opt in enumerate(list(options or [])):
        if str(opt or "").strip().lower() == target:
            return int(i)
    return -1


def _load_item_name_options(server, profession):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    prof = _normalize_profession_name(profession or "")
    if not prof:
        return []

    candidates = []
    try:
        candidates.append(os.path.join(_util_dir, "craftables.db"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(_script_dir, "craftables.db"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(os.getcwd(), "craftables.db"))
    except Exception:
        pass

    seen_paths = set()
    out = []
    for p in candidates:
        t = str(p or "").strip()
        if not t:
            continue
        lk = t.lower()
        if lk in seen_paths:
            continue
        seen_paths.add(lk)
        if not os.path.exists(t):
            continue
        conn = None
        try:
            conn = sqlite3.connect(t, timeout=0.35)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=350")
            cur.execute(
                """
                SELECT name
                FROM item_keys
                WHERE lower(coalesce(server,''))=lower(?)
                  AND lower(coalesce(profession,''))=lower(?)
                  AND trim(coalesce(name,''))<>''
                ORDER BY name COLLATE NOCASE
                """,
                (srv, prof),
            )
            rows = cur.fetchall()
            out = [str(r["name"] or "").strip() for r in rows if str(r["name"] or "").strip()]
            if out:
                break
        except Exception:
            out = []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    if not out:
        # Fallback to key-map cache if DB lookup is unavailable.
        try:
            km = _get_key_maps()
            node = km.get(srv, {}).get(prof, {}) if isinstance(km, dict) else {}
            ik = node.get("item_keys", {}) if isinstance(node, dict) else {}
            if isinstance(ik, dict):
                for ent in ik.values():
                    nm = str((ent or {}).get("name", "") if isinstance(ent, dict) else "").strip()
                    if nm:
                        out.append(nm)
        except Exception:
            pass

    seen_names = set()
    deduped = []
    for n in out:
        t = str(n or "").strip()
        if not t:
            continue
        k = t.lower()
        if k in seen_names:
            continue
        seen_names.add(k)
        deduped.append(t)
    return deduped


def _selected_item_name_from_inputs(inputs):
    f = inputs or {}
    dd = f.get("name")
    opts = list(f.get("name_options", []) or [])
    idx = -1
    try:
        idx = int(dd.GetSelectedIndex()) if dd else -1
    except Exception:
        idx = -1
    if 0 <= idx < len(opts):
        val = str(opts[idx] or "").strip()
        if val.lower() == str(ITEM_NONE_LABEL).lower():
            return ""
        return val
    try:
        return str((dd.Text if dd else "") or "").strip()
    except Exception:
        return ""


def _normalize_resource_rows(resources):
    out = []
    for r in list(resources or []):
        if not isinstance(r, dict):
            continue
        mat = str(r.get("material", "") or "").strip().lower()
        try:
            qty = int(r.get("per_item", 0) or 0)
        except Exception:
            qty = 0
        if not mat or qty <= 0:
            continue
        out.append({"material": mat, "per_item": int(qty)})
        if len(out) >= int(RESOURCE_SLOT_COUNT):
            break
    return out


def _collect_resource_rows_from_controls(inputs):
    out = []
    for row in list((inputs or {}).get("resource_rows", []) or []):
        if not isinstance(row, dict):
            continue
        dd = row.get("resource")
        qty_tb = row.get("qty")
        opts = list(row.get("options", []) or [])
        idx = -1
        try:
            idx = int(dd.GetSelectedIndex()) if dd else -1
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(opts):
            continue
        name = str(opts[idx] or "").strip()
        if not name or name.lower() == str(RESOURCE_NONE_LABEL).strip().lower():
            continue
        qty_text = str((qty_tb.Text if qty_tb else "") or "").strip()
        qty = 0
        try:
            qty = int(qty_text)
        except Exception:
            qty = 0
        if qty <= 0:
            continue
        out.append({"material": name.lower(), "per_item": int(qty)})
        if len(out) >= int(RESOURCE_SLOT_COUNT):
            break
    return out


def _read_recipe_book():
    if RECIPE_STORE is None:
        return []
    try:
        return list(RECIPE_STORE.load_recipes() or [])
    except Exception as ex:
        _say(f"Recipe DB read failed: {ex}", 33)
        return []


def _write_recipe_book(rows):
    if RECIPE_STORE is None:
        _say("Recipe DB unavailable.", 33)
        return False
    try:
        ok = bool(RECIPE_STORE.save_recipes(list(rows or [])))
        if not ok:
            err = ""
            try:
                err = str(RECIPE_STORE.last_init_error() or "")
            except Exception:
                err = ""
            if err:
                _say(f"Recipe DB write blocked: {err}", 33)
        return ok
    except Exception as ex:
        _say(f"Recipe DB write failed: {ex}", 33)
        return False


def _normalize_recipe_entry(r):
    if not isinstance(r, dict):
        return None
    name = str(r.get("name", "") or "").strip()
    prof = _normalize_profession_name(r.get("profession", ""))
    if not name or not prof:
        return None
    buttons = [int(x) for x in (r.get("buttons", []) or []) if int(x) > 0]
    if not buttons:
        return None
    material = str(r.get("material", "ingot") or "ingot").strip().lower()
    mk = str(r.get("material_key", "") or "").strip().lower()
    if not mk:
        mk = _material_key_from_base(material)
    row = {
        "name": name,
        "profession": prof,
        "item_id": int(r.get("item_id", 0) or 0),
        "buttons": buttons,
        "material": material,
        "material_key": mk,
        "materials": list(r.get("materials", []) or []),
        "material_buttons": [int(x) for x in (r.get("material_buttons", []) or []) if int(x) > 0],
        "deed_key": str(r.get("deed_key", "") or "").strip(),
        "recipe_type": str(r.get("recipe_type", "bod") or "bod").strip().lower(),
        "server": _normalize_server_name(r.get("server", DEFAULT_SERVER)),
    }
    if "start_at" in r:
        try:
            row["start_at"] = float(r.get("start_at", 0.0) or 0.0)
        except Exception:
            row["start_at"] = 0.0
    if "stop_at" in r:
        try:
            row["stop_at"] = float(r.get("stop_at", 0.0) or 0.0)
        except Exception:
            row["stop_at"] = 0.0
    return row


def _row_key(r):
    return (
        str(r.get("recipe_type", "")).lower(),
        _normalize_server_name(r.get("server", DEFAULT_SERVER)),
        _normalize_profession_name(r.get("profession", "")),
        str(r.get("name", "")).strip().lower(),
        str(r.get("material_key", "")).strip().lower(),
    )


def _get_key_maps():
    if RECIPE_STORE is None:
        return {}
    try:
        km = RECIPE_STORE.load_key_maps() or {}
        return dict(km) if isinstance(km, dict) else {}
    except Exception as ex:
        _say(f"Key-map DB read failed: {ex}", 33)
        return {}


def _set_key_maps(key_maps):
    if RECIPE_STORE is None:
        _say("Key-map DB unavailable.", 33)
        return False
    try:
        ok = bool(RECIPE_STORE.save_key_maps(dict(key_maps or {})))
        if not ok:
            err = ""
            try:
                err = str(RECIPE_STORE.last_init_error() or "")
            except Exception:
                err = ""
            if err:
                _say(f"Key-map DB write blocked: {err}", 33)
        return ok
    except Exception as ex:
        _say(f"Key-map DB write failed: {ex}", 33)
        return False


def _key_map_prof_node(server, profession, create=False):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    prof = _normalize_profession_name(profession)
    if not prof:
        return None
    km = _get_key_maps()
    if create:
        if srv not in km or not isinstance(km.get(srv), dict):
            km[srv] = {}
        if prof not in km[srv] or not isinstance(km[srv].get(prof), dict):
            km[srv][prof] = {}
        node = km[srv][prof]
        if "material_keys" not in node or not isinstance(node.get("material_keys"), dict):
            node["material_keys"] = {}
        if "item_keys" not in node or not isinstance(node.get("item_keys"), dict):
            node["item_keys"] = {}
        return km, node, srv, prof
    if not isinstance(km.get(srv), dict):
        return None
    node = km[srv].get(prof)
    if not isinstance(node, dict):
        return None
    if not isinstance(node.get("material_keys"), dict):
        node["material_keys"] = {}
    if not isinstance(node.get("item_keys"), dict):
        node["item_keys"] = {}
    return km, node, srv, prof


def _get_material_key_map(server, profession, material_key):
    mk = str(material_key or "").strip().lower()
    if not mk:
        return None
    data = _key_map_prof_node(server, profession, create=False)
    if not data:
        return None
    _, node, _, _ = data
    val = node.get("material_keys", {}).get(mk)
    return dict(val) if isinstance(val, dict) else None


def _get_item_key_map(server, profession, item_name):
    nk = _normalize_item_key_name(item_name)
    if not nk:
        return None
    data = _key_map_prof_node(server, profession, create=False)
    if not data:
        return None
    _, node, _, _ = data
    val = node.get("item_keys", {}).get(nk)
    return dict(val) if isinstance(val, dict) else None


def _upsert_key_maps(server, profession, item_name, item_id, buttons, material, material_key, material_buttons, resources=None, category=None):
    data = _key_map_prof_node(server, profession, create=True)
    if not data:
        return False
    km, node, _, _ = data
    mk = str(material_key or "").strip().lower()
    base = str(material or _material_base_from_key(mk, "ingot") or "ingot").strip().lower()
    mbtns = [int(x) for x in (material_buttons or []) if int(x) > 0][:2]
    if mk:
        node["material_keys"][mk] = {
            "material": base,
            "material_buttons": mbtns,
        }

    nk = _normalize_item_key_name(item_name)
    ibtns = [int(x) for x in (buttons or []) if int(x) > 0][:2]
    if nk:
        node["item_keys"][nk] = {
            "name": str(item_name or "").strip(),
            "item_id": int(item_id or 0),
            "buttons": ibtns,
            "default_material_key": mk,
            "category": str(category or "").strip(),
            "resources": list(resources or []),
        }
    return _set_key_maps(km)


def _upsert_recipe(row):
    norm = _normalize_recipe_entry(row)
    if not norm:
        return False
    rows = _read_recipe_book()
    key = _row_key(norm)
    replaced = False
    for i, r in enumerate(rows):
        rn = _normalize_recipe_entry(r)
        if not rn:
            continue
        if _row_key(rn) == key:
            rows[i] = dict(rn, **norm)
            replaced = True
            break
    if not replaced:
        rows.append(norm)
    return _write_recipe_book(rows)


def _get_persistent_json(key):
    raw = ""
    try:
        raw = API.GetPersistentVar(str(key), "", API.PersistentVar.Char)
    except Exception:
        try:
            raw = API.GetPersistentVar(str(key), "")
        except Exception:
            raw = ""
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
    payload = json.dumps(obj or {})
    try:
        API.SavePersistentVar(str(key), payload, API.PersistentVar.Char)
        return True
    except Exception as ex1:
        try:
            API.SavePersistentVar(str(key), payload)
            _write_debug_log("Persistent write fallback succeeded key={0} err={1}".format(str(key), str(ex1)))
            return True
        except Exception as ex2:
            _write_debug_log(
                "Persistent write failed key={0} err1={1} err2={2}".format(str(key), str(ex1), str(ex2))
            )
            return False


def _parse_materials_text(text):
    out = []
    chunks = [x.strip() for x in str(text or "").split(";") if str(x or "").strip()]
    for c in chunks:
        parts = [p.strip() for p in c.split(":")]
        if not parts:
            continue
        material = str(parts[0] or "").strip().lower()
        if not material:
            continue
        ent = {
            "material": material,
            "item_id": _parse_item_id(parts[1]) if len(parts) > 1 else 0,
            "min_in_pack": int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0,
            "pull_amount": int(parts[3]) if len(parts) > 3 and str(parts[3]).isdigit() else 0,
            "hue": None,
        }
        if len(parts) > 4:
            hue_text = str(parts[4] or "").strip()
            if hue_text:
                try:
                    ent["hue"] = int(hue_text, 16) if hue_text.lower().startswith("0x") else int(hue_text)
                except Exception:
                    ent["hue"] = None
        out.append(ent)
    return out


def _materials_to_text(materials):
    if not isinstance(materials, list):
        return ""
    parts = []
    for m in materials:
        if not isinstance(m, dict):
            continue
        base = str(m.get("material", "") or "").strip()
        if not base:
            continue
        item_id = int(m.get("item_id", 0) or 0)
        min_in_pack = int(m.get("min_in_pack", 0) or 0)
        pull_amount = int(m.get("pull_amount", 0) or 0)
        hue = m.get("hue", None)
        seg = [base]
        if item_id > 0 or min_in_pack > 0 or pull_amount > 0 or hue is not None:
            seg.append(f"0x{int(item_id):X}" if item_id > 0 else "0")
        if min_in_pack > 0 or pull_amount > 0 or hue is not None:
            seg.append(str(min_in_pack))
        if pull_amount > 0 or hue is not None:
            seg.append(str(pull_amount))
        if hue is not None:
            try:
                seg.append(str(int(hue)))
            except Exception:
                seg.append(str(hue))
        parts.append(":".join(seg))
    return ";".join(parts)


def _tooltip_lines(text):
    lines = []
    for ln in str(text or "").splitlines():
        t = str(ln or "").strip()
        if t:
            lines.append(t)
    return lines


def _add_editor_background(g, w, h):
    # Match the viewer visual language.
    bg = API.CreateGumpColorBox(0.78, "#111923")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)
    panel = API.CreateGumpColorBox(0.40, "#1B2A3A")
    panel.SetRect(8, 8, w - 16, h - 16)
    g.Add(panel)


def _collect_material_key_options(profession=""):
    prof = _normalize_profession_name(profession)
    keys = set()
    if prof:
        for k in MATERIAL_KEY_OPTIONS_BY_PROFESSION.get(prof, []):
            t = str(k or "").strip().lower()
            if t:
                keys.add(t)
    for r in _read_recipe_book():
        try:
            if prof and _normalize_profession_name(r.get("profession", "")) != prof:
                continue
            mk = str(r.get("material_key", "") or "").strip().lower()
        except Exception:
            mk = ""
        if mk:
            keys.add(mk)
    # Include mapped material keys from key_maps (all servers).
    km = _get_key_maps()
    if prof and isinstance(km, dict):
        for srv_node in km.values():
            if not isinstance(srv_node, dict):
                continue
            pnode = srv_node.get(prof, {})
            if not isinstance(pnode, dict):
                continue
            mats = pnode.get("material_keys", {})
            if not isinstance(mats, dict):
                continue
            for k in mats.keys():
                t = str(k or "").strip().lower()
                if t:
                    keys.add(t)
    return sorted(list(keys))


def _find_material_buttons_for_key(profession, material_key, server=""):
    prof = _normalize_profession_name(profession)
    mk = str(material_key or "").strip().lower()
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    if not prof or not mk:
        return []
    km = _get_material_key_map(srv, prof, mk)
    if km:
        mb = [int(x) for x in (km.get("material_buttons", []) or []) if int(x) > 0]
        if mb:
            return mb[:2]
    for r in _read_recipe_book():
        rn = _normalize_recipe_entry(r)
        if not rn:
            continue
        if str(rn.get("profession", "") or "") != prof:
            continue
        if _normalize_server_name(rn.get("server", DEFAULT_SERVER)) != srv:
            continue
        if str(rn.get("material_key", "") or "").strip().lower() != mk:
            continue
        mb = [int(x) for x in (rn.get("material_buttons", []) or []) if int(x) > 0]
        if mb:
            return mb[:2]
    by_prof = MATERIAL_BUTTONS_BY_KEY.get(prof, {})
    fallback = [int(x) for x in (by_prof.get(mk, []) or []) if int(x) > 0]
    if fallback:
        return fallback[:2]
    return []


def _close_editor():
    global EDITOR_GUMP, EDITOR_INPUTS, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX, EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX
    if EDITOR_GUMP:
        try:
            EDITOR_GUMP.Dispose()
        except Exception:
            pass
    EDITOR_GUMP = None
    EDITOR_INPUTS = {}
    EDITOR_LAST_TYPE_IDX = -1
    EDITOR_LAST_MATERIAL_KEY_IDX = -1
    EDITOR_LAST_PROFESSION_IDX = -1
    EDITOR_LAST_MODE_IDX = -1


def _capture_editor_state():
    f = EDITOR_INPUTS or {}
    out = {}
    try:
        dd_mode = f.get("editor_mode")
        midx = int(dd_mode.GetSelectedIndex()) if dd_mode else 0
    except Exception:
        midx = 0
    if midx < 0 or midx >= len(EDITOR_MODE_OPTIONS):
        midx = 0
    out["editor_mode"] = EDITOR_MODE_OPTIONS[midx]
    try:
        dd = f.get("recipe_type")
        idx = int(dd.GetSelectedIndex()) if dd else 0
    except Exception:
        idx = 0
    if idx < 0 or idx >= len(RECIPE_TYPE_OPTIONS):
        idx = 0
    out["recipe_type"] = RECIPE_TYPE_OPTIONS[idx]
    try:
        dd = f.get("server")
        sidx = int(dd.GetSelectedIndex()) if dd else 0
    except Exception:
        sidx = 0
    if sidx < 0 or sidx >= len(SERVER_OPTIONS):
        sidx = 0
    out["server"] = SERVER_OPTIONS[sidx]
    try:
        dd = f.get("profession")
        pidx = int(dd.GetSelectedIndex()) if dd else 0
    except Exception:
        pidx = 0
    if pidx < 0 or pidx >= len(PROFESSION_OPTIONS):
        pidx = 0
    out["profession"] = PROFESSION_OPTIONS[pidx]
    out["material"] = str(f.get("material_hidden", "ingot") or "ingot")
    out["name"] = _selected_item_name_from_inputs(f)
    out["buttons"] = [int(x) for x in _parse_int_list(
        "{0},{1}".format(
            str((f.get("button_1").Text if f.get("button_1") else "") or ""),
            str((f.get("button_2").Text if f.get("button_2") else "") or "")
        )
    )][:2]
    mk_idx = -1
    mk_dd = f.get("material_key")
    mk_opts = list(f.get("material_key_options", []) or [])
    try:
        mk_idx = int(mk_dd.GetSelectedIndex()) if mk_dd else -1
    except Exception:
        mk_idx = -1
    if 0 <= mk_idx < len(mk_opts):
        out["material_key"] = str(mk_opts[mk_idx] or "").strip().lower()
    else:
        out["material_key"] = ""
    out["material_key_new"] = str((f.get("material_key_new").Text if f.get("material_key_new") else "") or "")
    out["material_buttons"] = [int(x) for x in _parse_int_list(
        "{0},{1}".format(
            str((f.get("material_button_1").Text if f.get("material_button_1") else "") or ""),
            str((f.get("material_button_2").Text if f.get("material_button_2") else "") or "")
        )
    )][:2]
    out["materials"] = _parse_materials_text(str((f.get("materials").Text if f.get("materials") else "") or ""))
    out["deed_key"] = str((f.get("deed_key_hidden") if f.get("deed_key_hidden") else "") or "")
    out["deed_serial"] = int(f.get("deed_serial_hidden", 0) or 0)
    out["required"] = int(f.get("required_hidden", 0) or 0)
    out["filled"] = int(f.get("filled_hidden", 0) or 0)
    out["remaining"] = int(f.get("remaining_hidden", 0) or 0)
    out["exceptional"] = bool(f.get("exceptional_hidden", False))
    out["raw_text"] = str((f.get("raw_text_hidden") if f.get("raw_text_hidden") else "") or "")
    out["item_name"] = str((f.get("item_name_hidden") if f.get("item_name_hidden") else "") or "")
    out["resources"] = _collect_resource_rows_from_controls(f)
    out["resources_text"] = _resources_to_text(out.get("resources", []))
    out["start_at"] = str((f.get("start_at").Text if f.get("start_at") else "") or "")
    out["stop_at"] = str((f.get("stop_at").Text if f.get("stop_at") else "") or "")
    return out


def _save_and_exit():
    global EDITOR_INPUTS, SCRIPT_EXIT_REQUESTED
    f = EDITOR_INPUTS or {}
    mode_dd = f.get("editor_mode")
    prof_dd = f.get("profession")
    srv_dd = f.get("server")
    type_dd = f.get("recipe_type")
    mode_idx = int(mode_dd.GetSelectedIndex()) if mode_dd else 0
    prof_idx = int(prof_dd.GetSelectedIndex()) if prof_dd else 0
    srv_idx = int(srv_dd.GetSelectedIndex()) if srv_dd else 0
    type_idx = int(type_dd.GetSelectedIndex()) if type_dd else 0
    if mode_idx < 0 or mode_idx >= len(EDITOR_MODE_OPTIONS):
        mode_idx = 0
    if prof_idx < 0 or prof_idx >= len(PROFESSION_OPTIONS):
        prof_idx = 0
    if srv_idx < 0 or srv_idx >= len(SERVER_OPTIONS):
        srv_idx = 0
    if type_idx < 0 or type_idx >= len(RECIPE_TYPE_OPTIONS):
        type_idx = 0
    editor_mode = EDITOR_MODE_OPTIONS[mode_idx]

    name = _selected_item_name_from_inputs(f).strip()
    if not name:
        _say("Recipe name is required.", 33)
        return
    b1_text = str((f.get("button_1").Text if f.get("button_1") else "") or "").strip()
    b2_text = str((f.get("button_2").Text if f.get("button_2") else "") or "").strip()
    b1 = _parse_int_list(b1_text)
    b2 = _parse_int_list(b2_text)
    buttons = []
    if b1:
        buttons.append(int(b1[0]))
    if b2:
        buttons.append(int(b2[0]))
    user_entered_two_buttons = bool(len(buttons) >= 2)
    if not buttons:
        _say("Enter at least one crafting button id.", 33)
        return

    mk_text = ""
    mk_dd = f.get("material_key")
    mk_opts = list(f.get("material_key_options", []) or [])
    try:
        mk_idx = int(mk_dd.GetSelectedIndex()) if mk_dd else -1
    except Exception:
        mk_idx = -1
    if 0 <= mk_idx < len(mk_opts):
        selected_mk = str(mk_opts[mk_idx] or "").strip()
        if selected_mk == MATERIAL_KEY_ADD_LABEL:
            mk_text = str((f.get("material_key_new").Text if f.get("material_key_new") else "") or "").strip().lower()
        else:
            mk_text = selected_mk.strip().lower()
    if not mk_text:
        mk_text = _material_key_from_base(str(f.get("material_hidden", "ingot") or "ingot"))
    material = _material_base_from_key(mk_text, str(f.get("material_hidden", "ingot") or "ingot"))
    materials_text = str((f.get("materials").Text if f.get("materials") else "") or "").strip()
    materials = _parse_materials_text(materials_text)
    if not materials:
        materials = [{"material": material, "item_id": 0, "min_in_pack": 0, "pull_amount": 0, "hue": None}]
    resources = _collect_resource_rows_from_controls(f)
    if not resources:
        resources = _parse_resources_text(str((f.get("resources_text").Text if f.get("resources_text") else "") or ""))

    row = {
        "name": name,
        "profession": PROFESSION_OPTIONS[prof_idx],
        "item_id": 0,
        "buttons": [int(x) for x in buttons],
        "material": material,
        "material_key": mk_text,
        "materials": materials,
        "material_buttons": [int(x) for x in _parse_int_list(
            "{0},{1}".format(
                str((f.get("material_button_1").Text if f.get("material_button_1") else "") or ""),
                str((f.get("material_button_2").Text if f.get("material_button_2") else "") or "")
            )
        )][:2],
        "deed_key": (
            ""
            if editor_mode == "recipe_builder"
            else str((f.get("deed_key_hidden") if f.get("deed_key_hidden") else "") or "").strip()
        ),
        "recipe_type": RECIPE_TYPE_OPTIONS[type_idx],
        "server": SERVER_OPTIONS[srv_idx],
    }
    if RECIPE_TYPE_OPTIONS[type_idx] == "training":
        start_at_text = str((f.get("start_at").Text if f.get("start_at") else "") or "").strip()
        stop_at_text = str((f.get("stop_at").Text if f.get("stop_at") else "") or "").strip()
        if start_at_text:
            try:
                row["start_at"] = float(start_at_text)
            except Exception:
                row["start_at"] = 0.0
        if stop_at_text:
            try:
                row["stop_at"] = float(stop_at_text)
            except Exception:
                row["stop_at"] = 0.0

    if editor_mode == "recipe_builder":
        if not _upsert_key_maps(
            SERVER_OPTIONS[srv_idx],
            PROFESSION_OPTIONS[prof_idx],
            name,
            int(row.get("item_id", 0) or 0),
            list(row.get("buttons", []) or []),
            material,
            mk_text,
            list(row.get("material_buttons", []) or []),
            resources,
        ):
            _say("Failed to save key maps.", 33)
            return
        _say(f"Key maps saved: {PROFESSION_OPTIONS[prof_idx]} {name} ({SERVER_OPTIONS[srv_idx]})")
        ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "saved", "editor_mode": editor_mode, "key_maps_saved": True})
        _write_debug_log("Save ack (key_maps_saved) nonce={0} ok={1}".format(int(REQUEST_NONCE), bool(ok)))
        _close_editor()
        SCRIPT_EXIT_REQUESTED = True
        return

    # bind_deed mode: prefer key-map values when present.
    item_map = _get_item_key_map(SERVER_OPTIONS[srv_idx], PROFESSION_OPTIONS[prof_idx], name)
    if item_map:
        map_buttons = [int(x) for x in (item_map.get("buttons", []) or []) if int(x) > 0][:2]
        if map_buttons and not user_entered_two_buttons:
            row["buttons"] = map_buttons
        if int(row.get("item_id", 0) or 0) <= 0:
            row["item_id"] = int(item_map.get("item_id", 0) or 0)
        if not mk_text:
            row["material_key"] = str(item_map.get("default_material_key", "") or "").strip().lower()

    mat_map = _get_material_key_map(SERVER_OPTIONS[srv_idx], PROFESSION_OPTIONS[prof_idx], row.get("material_key", mk_text))
    if mat_map:
        map_mbtns = [int(x) for x in (mat_map.get("material_buttons", []) or []) if int(x) > 0][:2]
        if map_mbtns:
            row["material_buttons"] = map_mbtns
        row["material"] = str(mat_map.get("material", row.get("material", material)) or row.get("material", material)).strip().lower()

    # In bind_deed mode, keep key maps synchronized with the confirmed recipe path.
    existing_category = str(item_map.get("category", "") or "").strip() if isinstance(item_map, dict) else ""
    existing_resources = list(item_map.get("resources", []) or []) if isinstance(item_map, dict) else []
    resources_to_save = list(resources or []) if list(resources or []) else list(existing_resources or [])
    if not _upsert_key_maps(
        SERVER_OPTIONS[srv_idx],
        PROFESSION_OPTIONS[prof_idx],
        name,
        int(row.get("item_id", 0) or 0),
        list(row.get("buttons", []) or []),
        str(row.get("material", material) or material),
        str(row.get("material_key", mk_text) or mk_text),
        list(row.get("material_buttons", []) or []),
        resources_to_save,
        existing_category,
    ):
        _say("Failed to save key maps.", 33)
        return

    if not _upsert_recipe(row):
        _say("Failed to save recipe.", 33)
        return
    _say(f"Recipe saved: {row['recipe_type']} {row['profession']} {row['name']} ({row['server']})")
    ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "saved", "recipe": row, "editor_mode": editor_mode})
    _write_debug_log(
        "Save ack nonce={0} ok={1} name={2} profession={3}".format(
            int(REQUEST_NONCE), bool(ok), str(row.get("name", "") or ""), str(row.get("profession", "") or "")
        )
    )
    _close_editor()
    SCRIPT_EXIT_REQUESTED = True


def _cancel_and_exit():
    global SCRIPT_EXIT_REQUESTED
    ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "cancel"})
    _write_debug_log("Cancel ack nonce={0} ok={1}".format(int(REQUEST_NONCE), bool(ok)))
    _close_editor()
    SCRIPT_EXIT_REQUESTED = True


def _prefill_from_request():
    global REQUEST_NONCE
    req = _get_persistent_json(REQUEST_KEY) or {}
    payload = req.get("payload", {}) if isinstance(req, dict) else {}
    REQUEST_NONCE = int(req.get("nonce", 0) or 0) if isinstance(req, dict) else 0
    _write_debug_log("Prefill request nonce={0} has_payload={1}".format(int(REQUEST_NONCE), bool(isinstance(payload, dict) and payload)))
    return payload if isinstance(payload, dict) else {}


def _open_editor(pre_override=None):
    global EDITOR_GUMP, EDITOR_INPUTS, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX, EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX, SCRIPT_EXIT_REQUESTED
    _close_editor()
    SCRIPT_EXIT_REQUESTED = False
    pre = pre_override if isinstance(pre_override, dict) else _prefill_from_request()
    ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "opened"})
    _write_debug_log("Open ack nonce={0} ok={1}".format(int(REQUEST_NONCE), bool(ok)))
    g = API.CreateGump(True, True, False)
    w = 760
    h = 720
    g.SetRect(560, 120, w, h)
    _add_editor_background(g, w, h)

    label_color = "#E7F0FA"
    title = API.CreateGumpTTFLabel("Recipe Book (Editor)", 16, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 12)
    g.Add(title)

    y = 46
    x_off = 24
    # Optional BOD context block (when launched from BODAssist learn mode).
    deed_serial = int(pre.get("deed_serial", 0) or 0)
    req = int(pre.get("required", 0) or 0)
    fill = int(pre.get("filled", 0) or 0)
    rem = int(pre.get("remaining", 0) or 0)
    exc = "Yes" if bool(pre.get("exceptional", False)) else "No"
    raw_text = str(pre.get("raw_text", "") or "")
    has_deed_context = bool(deed_serial or raw_text)
    mode_text = str(pre.get("editor_mode", "") or "").strip().lower()
    if mode_text not in EDITOR_MODE_OPTIONS:
        mode_text = "bind_deed" if has_deed_context else "recipe_builder"
    try:
        mode_idx = EDITOR_MODE_OPTIONS.index(mode_text)
    except Exception:
        mode_idx = 0

    if has_deed_context and mode_text == "bind_deed":
        tip_lines = _tooltip_lines(raw_text)[:14]
        max_chars = 0
        for ln in tip_lines:
            try:
                max_chars = max(max_chars, len(str(ln or "")))
            except Exception:
                pass
        # Approximate text width for alagard 11pt and keep panel compact.
        box_w = int(min(w - 40, max(220, (max_chars * 6) + 20)))
        box_x = int((w - box_w) / 2)
        header_h = 16
        hdr_bg = API.CreateGumpColorBox(0.90, "#2A2A2A")
        hdr_bg.SetRect(box_x, y, box_w, header_h)
        g.Add(hdr_bg)
        t0 = API.CreateGumpTTFLabel("Deed Tooltip:", 12, "#FFFFFF", "alagard", "center", box_w)
        t0.SetPos(box_x, y)
        g.Add(t0)
        y += header_h
        if tip_lines:
            box_h = int((len(tip_lines) * 14) + 12)
            box_y = int(y)
            tip_bg = API.CreateGumpColorBox(0.90, "#000000")
            tip_bg.SetRect(box_x, box_y, box_w, box_h)
            g.Add(tip_bg)
            line_y = box_y + 6
            for ln in tip_lines:
                tl = API.CreateGumpTTFLabel(str(ln or ""), 11, "#CCCCCC", "alagard", "center", box_w - 10)
                tl.SetPos(box_x + 5, line_y)
                g.Add(tl)
                line_y += 14
            y = box_y + box_h + 14
        else:
            y += 14

    l_mode = API.CreateGumpTTFLabel("Mode", 12, label_color, "alagard", "left", 60)
    l_mode.SetPos(10 + x_off, y)
    g.Add(l_mode)
    d_mode = API.CreateDropDown(160, list(EDITOR_MODE_LABELS), mode_idx)
    d_mode.SetPos(60 + x_off, y - 2)
    g.Add(d_mode)

    y += 34
    l0 = API.CreateGumpTTFLabel("Type", 12, label_color, "alagard", "left", 60)
    l0.SetPos(10 + x_off, y)
    g.Add(l0)
    type_idx = 0
    try:
        type_idx = RECIPE_TYPE_OPTIONS.index(str(pre.get("recipe_type", "bod") or "bod").lower())
    except Exception:
        type_idx = 0
    d0 = API.CreateDropDown(120, list(RECIPE_TYPE_LABELS), type_idx)
    d0.SetPos(60 + x_off, y - 2)
    g.Add(d0)

    l0b = API.CreateGumpTTFLabel("Server", 12, label_color, "alagard", "left", 70)
    l0b.SetPos(220 + x_off, y)
    g.Add(l0b)
    srv = _normalize_server_name(pre.get("server", DEFAULT_SERVER))
    try:
        srv_idx = SERVER_OPTIONS.index(srv)
    except Exception:
        srv_idx = 1
    d0b = API.CreateDropDown(160, list(SERVER_OPTIONS), srv_idx)
    d0b.SetPos(280 + x_off, y - 2)
    g.Add(d0b)

    y += 38
    l1 = API.CreateGumpTTFLabel("Profession", 12, label_color, "alagard", "left", 90)
    l1.SetPos(10 + x_off, y)
    g.Add(l1)
    prof = _normalize_profession_name(pre.get("profession", "Blacksmith")) or "Blacksmith"
    try:
        prof_idx = PROFESSION_OPTIONS.index(prof)
    except Exception:
        prof_idx = 0
    d1 = API.CreateDropDown(140, list(PROFESSION_OPTIONS), prof_idx)
    d1.SetPos(100 + x_off, y - 2)
    g.Add(d1)

    y += 38
    l3 = API.CreateGumpTTFLabel("Item Name", 12, label_color, "alagard", "left", 90)
    l3.SetPos(10 + x_off, y)
    g.Add(l3)
    current_item_name = str(pre.get("name", pre.get("item_name", "")) or "").strip()
    name_options = _load_item_name_options(srv, prof)
    if current_item_name and _resource_option_index(name_options, current_item_name) < 0:
        name_options.append(current_item_name)
    if not name_options:
        name_options = [str(ITEM_NONE_LABEL)]
    name_idx = _resource_option_index(name_options, current_item_name)
    if name_idx < 0:
        name_idx = 0
    d_name = API.CreateDropDown(500, list(name_options), int(name_idx))
    d_name.SetPos(100 + x_off, y - 2)
    g.Add(d_name)

    resource_rows = []
    y += 38
    l3b = API.CreateGumpTTFLabel("Item Resource Costs (max 5)", 12, label_color, "alagard", "left", 220)
    l3b.SetPos(10 + x_off, y)
    g.Add(l3b)
    item_name_for_resources = str(name_options[name_idx] if 0 <= int(name_idx) < len(name_options) else current_item_name).strip()
    if item_name_for_resources.lower() == str(ITEM_NONE_LABEL).lower():
        item_name_for_resources = ""
    item_map_for_resources = _get_item_key_map(srv, prof, item_name_for_resources)
    pre_resources = _normalize_resource_rows(pre.get("resources", []))
    if not pre_resources:
        pre_resources = _normalize_resource_rows(_parse_resources_text(str(pre.get("resources_text", "") or "").strip()))
    if not pre_resources and isinstance(item_map_for_resources, dict):
        pre_resources = _normalize_resource_rows(item_map_for_resources.get("resources", []))
    resource_options = _load_resource_name_options()
    resource_options = list(resource_options or [])
    if not resource_options:
        resource_options = list(RESOURCE_FALLBACK_OPTIONS)
    option_values = [str(RESOURCE_NONE_LABEL)]
    option_values.extend([str(x or "").strip() for x in resource_options if str(x or "").strip()])
    for rr in pre_resources:
        mat_name = str(rr.get("material", "") or "").strip()
        if mat_name and _resource_option_index(option_values, mat_name) < 0:
            option_values.append(mat_name)
    for idx_row in range(int(RESOURCE_SLOT_COUNT)):
        ry = y + 24 + (idx_row * 24)
        slot_lbl = API.CreateGumpTTFLabel(str(int(idx_row + 1)) + ".", 11, label_color, "alagard", "left", 16)
        slot_lbl.SetPos(10 + x_off, ry)
        g.Add(slot_lbl)
        selected_name = ""
        qty_text = ""
        if idx_row < len(pre_resources):
            selected_name = str(pre_resources[idx_row].get("material", "") or "").strip()
            try:
                qty_text = str(int(pre_resources[idx_row].get("per_item", 0) or 0))
            except Exception:
                qty_text = ""
        opt_idx = _resource_option_index(option_values, selected_name)
        if opt_idx < 0:
            opt_idx = 0
        dd_res = API.CreateDropDown(220, list(option_values), int(opt_idx))
        dd_res.SetPos(32 + x_off, ry - 2)
        g.Add(dd_res)
        t_qty = API.CreateGumpTextBox(str(qty_text or ""), 72, 18, False)
        t_qty.SetPos(264 + x_off, ry - 2)
        g.Add(t_qty)
        resource_rows.append({"resource": dd_res, "qty": t_qty, "options": list(option_values)})
    y += 24 + (int(RESOURCE_SLOT_COUNT) * 24) + 8

    y += 38
    l4 = API.CreateGumpTTFLabel("Crafting Gump Button Combination", 12, label_color, "alagard", "left", 220)
    l4.SetPos(10 + x_off, y)
    g.Add(l4)
    pre_buttons = pre.get("buttons", [])
    if isinstance(pre_buttons, list):
        p1 = str(int(pre_buttons[0])) if len(pre_buttons) > 0 else ""
        p2 = str(int(pre_buttons[1])) if len(pre_buttons) > 1 else ""
    else:
        parsed = _parse_int_list(str(pre_buttons or ""))
        p1 = str(int(parsed[0])) if len(parsed) > 0 else ""
        p2 = str(int(parsed[1])) if len(parsed) > 1 else ""
    t_btn1 = API.CreateGumpTextBox(p1, 72, 18, False)
    t_btn1.SetPos(250 + x_off, y - 2)
    g.Add(t_btn1)
    t_btn2 = API.CreateGumpTextBox(p2, 72, 18, False)
    t_btn2.SetPos(332 + x_off, y - 2)
    g.Add(t_btn2)

    t_start = None
    t_stop = None
    if RECIPE_TYPE_OPTIONS[type_idx] == "training":
        y += 38
        l6 = API.CreateGumpTTFLabel("Training Starts At:", 12, label_color, "alagard", "left", 120)
        l6.SetPos(10 + x_off, y)
        g.Add(l6)
        t_start = API.CreateGumpTextBox(str(pre.get("start_at", "") or ""), 80, 18, False)
        t_start.SetPos(130 + x_off, y - 2)
        g.Add(t_start)

        l6b = API.CreateGumpTTFLabel("Training Stops At:", 12, label_color, "alagard", "left", 120)
        l6b.SetPos(250 + x_off, y)
        g.Add(l6b)
        t_stop = API.CreateGumpTextBox(str(pre.get("stop_at", "") or ""), 80, 18, False)
        t_stop.SetPos(370 + x_off, y - 2)
        g.Add(t_stop)

    y += 38
    l7 = API.CreateGumpTTFLabel("Material Key", 12, label_color, "alagard", "left", 90)
    l7.SetPos(10 + x_off, y)
    g.Add(l7)
    mk_current = str(pre.get("material_key", "") or "").strip().lower()
    if not mk_current:
        mk_current = _material_key_from_base(str(pre.get("material", "ingot") or "ingot"))
    mk_options = _collect_material_key_options(prof)
    mk_labels = list(mk_options)
    mk_labels.append(MATERIAL_KEY_ADD_LABEL)
    mk_selected = str(pre.get("material_key", "") or "").strip().lower()
    mk_add_mode = (
        bool(str(pre.get("material_key_new", "") or "").strip())
        or mk_selected == str(MATERIAL_KEY_ADD_LABEL).strip().lower()
        or (mk_current and mk_current not in mk_options)
    )
    mk_idx = 0
    if mk_add_mode:
        mk_idx = len(mk_labels) - 1
    else:
        try:
            mk_idx = mk_labels.index(mk_current)
        except Exception:
            mk_idx = 0
    d_mk = API.CreateDropDown(190, mk_labels, mk_idx)
    d_mk.SetPos(100 + x_off, y - 2)
    g.Add(d_mk)
    t_mk_new = None
    if mk_idx == len(mk_labels) - 1:
        l7b = API.CreateGumpTTFLabel("New Material Key:", 12, label_color, "alagard", "left", 120)
        l7b.SetPos(300 + x_off, y)
        g.Add(l7b)
        t_mk_new = API.CreateGumpTextBox(str(pre.get("material_key_new", mk_current) or ""), 190, 18, False)
        t_mk_new.SetPos(420 + x_off, y - 2)
        g.Add(t_mk_new)

    y += 38
    if mk_idx == len(mk_labels) - 1:
        y += 24

    l8 = API.CreateGumpTTFLabel("Crafting Gump Material Button Combination:", 12, label_color, "alagard", "left", 360)
    l8.SetPos(10 + x_off, y)
    g.Add(l8)
    selected_mk = ""
    try:
        if 0 <= int(mk_idx) < len(mk_labels):
            selected_mk = str(mk_labels[int(mk_idx)] or "").strip().lower()
    except Exception:
        selected_mk = ""
    auto_mb = []
    if selected_mk and selected_mk != str(MATERIAL_KEY_ADD_LABEL).strip().lower():
        auto_mb = _find_material_buttons_for_key(prof, selected_mk, srv)
    if auto_mb:
        mb = list(auto_mb)
    elif selected_mk and selected_mk != str(MATERIAL_KEY_ADD_LABEL).strip().lower():
        mb = []
    else:
        mb = pre.get("material_buttons", [])
    if isinstance(mb, list):
        mb1 = str(int(mb[0])) if len(mb) > 0 else ""
        mb2 = str(int(mb[1])) if len(mb) > 1 else ""
    else:
        parsed_mb = _parse_int_list(str(mb or ""))
        mb1 = str(int(parsed_mb[0])) if len(parsed_mb) > 0 else ""
        mb2 = str(int(parsed_mb[1])) if len(parsed_mb) > 1 else ""
    t_mb1 = API.CreateGumpTextBox(mb1, 72, 18, False)
    t_mb1.SetPos(390 + x_off, y - 2)
    g.Add(t_mb1)
    t_mb2 = API.CreateGumpTextBox(mb2, 72, 18, False)
    t_mb2.SetPos(472 + x_off, y - 2)
    g.Add(t_mb2)

    y += 44
    save_bg = API.CreateGumpColorBox(0.55, "#1B2A3A")
    save_bg.SetRect(180 + x_off, y, 110, 20)
    g.Add(save_bg)
    save_btn = API.CreateSimpleButton("Save Recipe", 110, 20)
    save_btn.SetPos(180 + x_off, y)
    g.Add(save_btn)
    API.AddControlOnClick(save_btn, _save_and_exit)

    cancel_bg = API.CreateGumpColorBox(0.55, "#1B2A3A")
    cancel_bg.SetRect(300 + x_off, y, 80, 20)
    g.Add(cancel_bg)
    cancel_btn = API.CreateSimpleButton("Cancel", 80, 20)
    cancel_btn.SetPos(300 + x_off, y)
    g.Add(cancel_btn)
    API.AddControlOnClick(cancel_btn, _cancel_and_exit)

    API.AddGump(g)
    EDITOR_GUMP = g
    EDITOR_LAST_MODE_IDX = int(mode_idx)
    EDITOR_LAST_TYPE_IDX = int(type_idx)
    EDITOR_LAST_MATERIAL_KEY_IDX = int(mk_idx)
    EDITOR_LAST_PROFESSION_IDX = int(prof_idx)
    EDITOR_INPUTS = {
        "editor_mode": d_mode,
        "recipe_type": d0,
        "server": d0b,
        "profession": d1,
        "material_hidden": str(pre.get("material", "ingot") or "ingot"),
        "name": d_name,
        "name_options": list(name_options),
        "button_1": t_btn1,
        "button_2": t_btn2,
        "start_at": t_start,
        "stop_at": t_stop,
        "material_key": d_mk,
        "material_key_options": mk_labels,
        "material_key_new": t_mk_new,
        "material_button_1": t_mb1,
        "material_button_2": t_mb2,
        "deed_key_hidden": str(pre.get("deed_key", "") or ""),
        "deed_serial_hidden": int(pre.get("deed_serial", 0) or 0),
        "required_hidden": int(pre.get("required", 0) or 0),
        "filled_hidden": int(pre.get("filled", 0) or 0),
        "remaining_hidden": int(pre.get("remaining", 0) or 0),
        "exceptional_hidden": bool(pre.get("exceptional", False)),
        "raw_text_hidden": str(pre.get("raw_text", "") or ""),
        "item_name_hidden": str(pre.get("item_name", "") or ""),
        "resource_rows": resource_rows,
        "resources_text": None,  # legacy fallback path
    }


def _main():
    global SCRIPT_EXIT_REQUESTED
    # Keep launch responsive; DB access is handled lazily by read/write helpers.
    _open_editor()
    while not SCRIPT_EXIT_REQUESTED and EDITOR_GUMP is not None:
        API.ProcessCallbacks()
        if SCRIPT_EXIT_REQUESTED or EDITOR_GUMP is None:
            break
        try:
            f = EDITOR_INPUTS or {}
            dd_mode = f.get("editor_mode")
            dd_type = f.get("recipe_type")
            dd_mk = f.get("material_key")
            dd_prof = f.get("profession")
            current_mode_idx = int(dd_mode.GetSelectedIndex()) if dd_mode else -1
            current_type_idx = int(dd_type.GetSelectedIndex()) if dd_type else -1
            current_mk_idx = int(dd_mk.GetSelectedIndex()) if dd_mk else -1
            current_prof_idx = int(dd_prof.GetSelectedIndex()) if dd_prof else -1
        except Exception:
            current_mode_idx = -1
            current_type_idx = -1
            current_mk_idx = -1
            current_prof_idx = -1
        if current_mode_idx != -1 and current_mode_idx != int(EDITOR_LAST_MODE_IDX):
            state = _capture_editor_state()
            _open_editor(state)
            continue
        if current_type_idx != -1 and current_type_idx != int(EDITOR_LAST_TYPE_IDX):
            state = _capture_editor_state()
            _open_editor(state)
            continue
        if current_prof_idx != -1 and current_prof_idx != int(EDITOR_LAST_PROFESSION_IDX):
            state = _capture_editor_state()
            _open_editor(state)
            continue
        if current_mk_idx != -1 and current_mk_idx != int(EDITOR_LAST_MATERIAL_KEY_IDX):
            state = _capture_editor_state()
            _open_editor(state)
            continue
        API.Pause(0.1)
    _write_debug_log("Main exit requested={0} gump_alive={1}".format(bool(SCRIPT_EXIT_REQUESTED), bool(EDITOR_GUMP is not None)))


_main()
