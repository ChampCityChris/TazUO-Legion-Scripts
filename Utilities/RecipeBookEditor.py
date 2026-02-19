import API
import json
import ast
import os
import re
import sys

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

RECIPE_STORE = None
_util_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
if _util_dir and _util_dir not in sys.path:
    sys.path.append(_util_dir)
try:
    import RecipeStore as RECIPE_STORE
except Exception:
    RECIPE_STORE = None


def _say(msg, hue=17):
    API.SysMsg(msg, hue)


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
        return bool(RECIPE_STORE.save_recipes(list(rows or [])))
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
        return bool(RECIPE_STORE.save_key_maps(dict(key_maps or {})))
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
    raw = API.GetPersistentVar(key, "", API.PersistentVar.Char)
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
        API.SavePersistentVar(key, json.dumps(obj or {}), API.PersistentVar.Char)
    except Exception:
        pass


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
    # Prefer gump art background when available; fallback to color box.
    try:
        pic = API.CreateGumpPic(int(EDITOR_BG_GUMP_ART_ID))
        try:
            pic.SetPos(0, 0)
        except Exception:
            pass
        try:
            # Some API builds allow sizing image controls.
            pic.SetRect(0, 0, int(w), int(h))
        except Exception:
            pass
        g.Add(pic)
        return
    except Exception:
        pass
    bg = API.CreateGumpColorBox(0.8, "#1B1B1B")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)


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
    global EDITOR_GUMP, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX, EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX
    if EDITOR_GUMP:
        try:
            EDITOR_GUMP.Dispose()
        except Exception:
            pass
    EDITOR_GUMP = None
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
    out["name"] = str((f.get("name").Text if f.get("name") else "") or "")
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
    out["resources_text"] = str((f.get("resources_text").Text if f.get("resources_text") else "") or "")
    out["start_at"] = str((f.get("start_at").Text if f.get("start_at") else "") or "")
    out["stop_at"] = str((f.get("stop_at").Text if f.get("stop_at") else "") or "")
    return out


def _save_and_exit():
    global EDITOR_INPUTS
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

    name = str((f.get("name").Text if f.get("name") else "") or "").strip()
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
        _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "saved", "editor_mode": editor_mode, "key_maps_saved": True})
        _close_editor()
        return

    # bind_deed mode: prefer key-map values when present.
    item_map = _get_item_key_map(SERVER_OPTIONS[srv_idx], PROFESSION_OPTIONS[prof_idx], name)
    if item_map:
        map_buttons = [int(x) for x in (item_map.get("buttons", []) or []) if int(x) > 0][:2]
        if map_buttons:
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

    if not _upsert_recipe(row):
        _say("Failed to save recipe.", 33)
        return
    _say(f"Recipe saved: {row['recipe_type']} {row['profession']} {row['name']} ({row['server']})")
    _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "saved", "recipe": row, "editor_mode": editor_mode})
    _close_editor()


def _cancel_and_exit():
    _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "cancel"})
    _close_editor()


def _prefill_from_request():
    global REQUEST_NONCE
    req = _get_persistent_json(REQUEST_KEY) or {}
    payload = req.get("payload", {}) if isinstance(req, dict) else {}
    REQUEST_NONCE = int(req.get("nonce", 0) or 0) if isinstance(req, dict) else 0
    return payload if isinstance(payload, dict) else {}


def _open_editor(pre_override=None):
    global EDITOR_GUMP, EDITOR_INPUTS, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX, EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX
    _close_editor()
    pre = pre_override if isinstance(pre_override, dict) else _prefill_from_request()
    _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "opened"})
    g = API.CreateGump(True, True, False)
    w = 760
    h = 690
    g.SetRect(740, 180, w, h)
    _add_editor_background(g, w, h)

    title = API.CreateGumpTTFLabel("Recipe Book Editor", 15, "#000000", "alagard", "center", w)
    title.SetPos(0, 58)
    g.Add(title)

    y = 109
    x_off = 70
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

    l_mode = API.CreateGumpTTFLabel("Mode", 12, "#000000", "alagard", "left", 60)
    l_mode.SetPos(10 + x_off, y)
    g.Add(l_mode)
    d_mode = API.CreateDropDown(160, list(EDITOR_MODE_LABELS), mode_idx)
    d_mode.SetPos(60 + x_off, y - 2)
    g.Add(d_mode)

    y += 34
    l0 = API.CreateGumpTTFLabel("Type", 12, "#000000", "alagard", "left", 60)
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

    l0b = API.CreateGumpTTFLabel("Server", 12, "#000000", "alagard", "left", 70)
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
    l1 = API.CreateGumpTTFLabel("Profession", 12, "#000000", "alagard", "left", 90)
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
    l3 = API.CreateGumpTTFLabel("Item Name", 12, "#000000", "alagard", "left", 90)
    l3.SetPos(10 + x_off, y)
    g.Add(l3)
    t_name = API.CreateGumpTextBox(str(pre.get("name", pre.get("item_name", "")) or ""), 500, 18, False)
    t_name.SetPos(100 + x_off, y - 2)
    g.Add(t_name)

    t_resources = None
    if mode_text == "recipe_builder":
        y += 38
        l3b = API.CreateGumpTTFLabel("Resources per item (base:qty;...)", 12, "#000000", "alagard", "left", 260)
        l3b.SetPos(10 + x_off, y)
        g.Add(l3b)
        item_map_for_resources = _get_item_key_map(srv, prof, str(pre.get("name", pre.get("item_name", "")) or ""))
        resources_text = str(pre.get("resources_text", "") or "").strip()
        if not resources_text and isinstance(item_map_for_resources, dict):
            resources_text = _resources_to_text(item_map_for_resources.get("resources", []))
        t_resources = API.CreateGumpTextBox(resources_text, 300, 18, False)
        t_resources.SetPos(300 + x_off, y - 2)
        g.Add(t_resources)

    y += 38
    l4 = API.CreateGumpTTFLabel("Crafting Gump Button Combination", 12, "#000000", "alagard", "left", 220)
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
        l6 = API.CreateGumpTTFLabel("Training Starts At:", 12, "#000000", "alagard", "left", 120)
        l6.SetPos(10 + x_off, y)
        g.Add(l6)
        t_start = API.CreateGumpTextBox(str(pre.get("start_at", "") or ""), 80, 18, False)
        t_start.SetPos(130 + x_off, y - 2)
        g.Add(t_start)

        l6b = API.CreateGumpTTFLabel("Training Stops At:", 12, "#000000", "alagard", "left", 120)
        l6b.SetPos(250 + x_off, y)
        g.Add(l6b)
        t_stop = API.CreateGumpTextBox(str(pre.get("stop_at", "") or ""), 80, 18, False)
        t_stop.SetPos(370 + x_off, y - 2)
        g.Add(t_stop)

    y += 38
    l7 = API.CreateGumpTTFLabel("Material Key", 12, "#000000", "alagard", "left", 90)
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
        l7b = API.CreateGumpTTFLabel("New Material Key:", 12, "#000000", "alagard", "left", 120)
        l7b.SetPos(300 + x_off, y)
        g.Add(l7b)
        t_mk_new = API.CreateGumpTextBox(str(pre.get("material_key_new", mk_current) or ""), 190, 18, False)
        t_mk_new.SetPos(420 + x_off, y - 2)
        g.Add(t_mk_new)

    y += 38
    if mk_idx == len(mk_labels) - 1:
        y += 24

    l8 = API.CreateGumpTTFLabel("Crafting Gump Material Button Combination:", 12, "#000000", "alagard", "left", 360)
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
    save_bg = API.CreateGumpColorBox(0.55, "#000000")
    save_bg.SetRect(180 + x_off, y, 110, 20)
    g.Add(save_bg)
    save_btn = API.CreateSimpleButton("Save Recipe", 110, 20)
    save_btn.SetPos(180 + x_off, y)
    g.Add(save_btn)
    API.AddControlOnClick(save_btn, _save_and_exit)

    cancel_bg = API.CreateGumpColorBox(0.55, "#000000")
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
        "name": t_name,
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
        "resources_text": t_resources,
    }


def _main():
    if RECIPE_STORE is not None:
        try:
            RECIPE_STORE.init_store()
        except Exception as ex:
            _say(f"Recipe DB init failed: {ex}", 33)
    else:
        _say("Recipe DB module unavailable.", 33)
    _open_editor()
    while EDITOR_GUMP is not None:
        API.ProcessCallbacks()
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


_main()
