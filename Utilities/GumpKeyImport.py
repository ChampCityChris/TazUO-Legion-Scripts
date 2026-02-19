import API
import json
import os
import sys

"""
GumpKeyImport

Reads `GumpKeyMapper.review.json` and imports APPROVED entries only
into `craftables.db` key maps via RecipeStore.
"""

REVIEW_FILE = "GumpKeyMapper.review.json"

RECIPE_STORE = None
_base = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
if _base and _base not in sys.path:
    sys.path.append(_base)
try:
    import RecipeStore as RECIPE_STORE
except Exception:
    RECIPE_STORE = None


def _say(msg, hue=88):
    try:
        API.SysMsg(str(msg or ""), hue)
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


def _normalize_server(server):
    s = str(server or "").strip()
    if not s:
        return "UOAlive"
    return s


def _int_list(v, limit=0):
    out = []
    for x in (v or []):
        try:
            n = int(x)
        except Exception:
            continue
        if n > 0:
            out.append(n)
            if int(limit or 0) > 0 and len(out) >= int(limit):
                break
    return out


def _review_path():
    return os.path.join(_base, REVIEW_FILE)


def _load_review():
    path = _review_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _iter_review_docs(raw):
    if isinstance(raw, list):
        for d in raw:
            if isinstance(d, dict):
                yield d
    elif isinstance(raw, dict):
        yield raw


def _import_doc(km, doc):
    meta = doc.get("metadata", {}) if isinstance(doc, dict) else {}
    server = _normalize_server(meta.get("server", "UOAlive"))
    profession = _normalize_profession(meta.get("profession", ""))
    if not profession:
        return 0, 0, ["Missing/invalid profession in metadata."]

    if server not in km or not isinstance(km.get(server), dict):
        km[server] = {}
    if profession not in km[server] or not isinstance(km[server].get(profession), dict):
        km[server][profession] = {"material_keys": {}, "item_keys": {}}
    node = km[server][profession]
    if "material_keys" not in node or not isinstance(node.get("material_keys"), dict):
        node["material_keys"] = {}
    if "item_keys" not in node or not isinstance(node.get("item_keys"), dict):
        node["item_keys"] = {}

    props = doc.get("proposals", {}) if isinstance(doc, dict) else {}
    mat_rows = props.get("material_keys", []) if isinstance(props, dict) else []
    item_rows = props.get("item_keys", []) if isinstance(props, dict) else []
    mat_added = 0
    item_added = 0
    errs = []

    for r in (mat_rows or []):
        if not isinstance(r, dict):
            continue
        if not bool(r.get("approved", False)):
            continue
        mk = str(r.get("material_key", "") or "").strip().lower()
        material = str(r.get("material", "") or "").strip().lower()
        mbtns = _int_list(r.get("material_buttons", []), 2)
        if not mk or not material:
            errs.append(f"Skipped material_key row with missing key/material: {r}")
            continue
        node["material_keys"][mk] = {
            "material": material,
            "material_buttons": mbtns,
        }
        mat_added += 1

    for r in (item_rows or []):
        if not isinstance(r, dict):
            continue
        if not bool(r.get("approved", False)):
            continue
        ik = str(r.get("item_key", "") or "").strip().lower()
        name = str(r.get("name", "") or "").strip()
        buttons = _int_list(r.get("buttons", []), 2)
        default_mk = str(r.get("default_material_key", "") or "").strip().lower()
        resources = r.get("resources", [])
        if not isinstance(resources, list):
            resources = []
        item_id = 0
        try:
            item_id = int(r.get("item_id", 0) or 0)
        except Exception:
            item_id = 0
        if not ik or not name or not buttons:
            errs.append(f"Skipped item_key row with missing key/name/buttons: {r}")
            continue
        node["item_keys"][ik] = {
            "name": name,
            "item_id": item_id,
            "buttons": buttons,
            "default_material_key": default_mk,
            "resources": resources,
        }
        item_added += 1

    return mat_added, item_added, errs


def _run():
    if RECIPE_STORE is None:
        _say("Import: RecipeStore module unavailable.", 33)
        return
    raw = _load_review()
    if raw is None:
        _say(f"Import: review file not found/invalid: {_review_path()}", 33)
        return

    try:
        RECIPE_STORE.init_store()
        km = RECIPE_STORE.load_key_maps() or {}
    except Exception as ex:
        _say(f"Import: failed to initialize/load DB key maps: {ex}", 33)
        return

    total_mat = 0
    total_item = 0
    all_errs = []
    docs = list(_iter_review_docs(raw))
    if not docs:
        _say("Import: no review documents found.", 33)
        return

    for d in docs:
        m, i, errs = _import_doc(km, d)
        total_mat += int(m or 0)
        total_item += int(i or 0)
        all_errs.extend(errs or [])

    try:
        ok = bool(RECIPE_STORE.save_key_maps(km))
    except Exception as ex:
        _say(f"Import: save_key_maps failed: {ex}", 33)
        return

    if not ok:
        _say("Import: key map save returned false.", 33)
        return

    _say(f"Import: approved material_keys imported={total_mat}, item_keys imported={total_item}")
    if all_errs:
        _say(f"Import: warnings={len(all_errs)} (see first warning in debug):", 33)
        _say(str(all_errs[0]), 33)
    try:
        hs = RECIPE_STORE.health_summary()
        _say(
            "Import: DB totals "
            f"material_keys={int(hs.get('material_keys_total', 0) or 0)} "
            f"item_keys={int(hs.get('item_keys_total', 0) or 0)}"
        )
    except Exception:
        pass


_run()

