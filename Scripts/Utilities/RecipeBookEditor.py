import API
import json
import ast
import os
import re
import sys
import sqlite3
import traceback

"""
RecipeBookEditor

Shared manual recipe editor for split recipe/key-map files.
Supports single or multi-material recipes.

`materials` format (semicolon-separated):
- material
- material:item_id
- material:item_id:min_in_pack:pull_amount

Example:
board;feather
ingot:0x1BF2:60:400;gem:0x0F26:10:80;super_gem:0x1234:10:80
"""

REQUEST_KEY = "recipe_editor_request"
RESULT_KEY = "recipe_editor_result"
DEBUG_LOG_FILE = "RecipeBookEditor.debug.log"
LOGS_DIR = r"F:\Games\Ultima_Online\Clients\TazUO\TazUO\LegionScripts\Logs"
SQLITE_CONNECT_TIMEOUT_S = 2.5
SQLITE_BUSY_TIMEOUT_MS = 2500

SERVER_OPTIONS = ["OSI", "UOAlive", "Sosaria Reforged", "InsaneUO"]
DEFAULT_SERVER = "UOAlive"
RECIPE_TYPE_OPTIONS = ["bod", "training"]
RECIPE_TYPE_LABELS = ["BOD", "Training"]
EDITOR_MODE_OPTIONS = ["bind_deed", "recipe_builder"]
EDITOR_MODE_LABELS = ["Bind Deed", "Recipe Builder"]
PROFESSION_OPTIONS = ["Blacksmith", "Tailor", "Carpentry", "Tinker", "Bowcraft", "Alchemy", "Inscription", "Cooking"]
MATERIAL_BASE_OPTIONS = ["ingot", "cloth", "leather", "board", "feather", "scale", "gem", "super_gem"]
EDITOR_BG_GUMP_ART_ID = 271
MATERIAL_KEY_DEFAULT_OPTIONS = ["ingot_iron", "cloth", "leather", "board", "feather"]
MATERIAL_KEY_ADD_LABEL = "Add New..."
RESOURCE_NONE_LABEL = "<none>"
RESOURCE_SLOT_COUNT = 5
ITEM_NONE_LABEL = "<none>"
CATEGORY_ALL_LABEL = "<all>"
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
PROFESSION_ALIASES_BY_CANONICAL = {
    "Blacksmith": ["Blacksmith", "Blacksmithing", "Blacksmithy"],
    "Tailor": ["Tailor", "Tailoring"],
    "Carpentry": ["Carpentry", "Carpenter"],
    "Tinker": ["Tinker", "Tinkering"],
    "Bowcraft": ["Bowcraft", "Bowcraft and Fletching", "Bowcraft/Fletching", "Fletching", "Bowyer"],
    "Alchemy": ["Alchemy", "Alchemist"],
    "Inscription": ["Inscription", "Scribing", "Scribe"],
    "Cooking": ["Cooking", "Cook"],
}

EDITOR_GUMP = None
EDITOR_INPUTS = {}
REQUEST_NONCE = 0
EDITOR_LAST_TYPE_IDX = -1
EDITOR_LAST_MATERIAL_KEY_IDX = -1
EDITOR_LAST_PROFESSION_IDX = -1
EDITOR_LAST_MODE_IDX = -1
EDITOR_LAST_SERVER_IDX = -1
EDITOR_LAST_CATEGORY_IDX = -1
EDITOR_LAST_ITEM_IDX = -1
SCRIPT_EXIT_REQUESTED = False

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
        RECIPE_STORE.set_base_dir(_project_root_dir or _util_dir)
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
        logs_dir = LOGS_DIR
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, DEBUG_LOG_FILE)
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
    if not n:
        return ""
    for canonical, aliases in PROFESSION_ALIASES_BY_CANONICAL.items():
        for alias in aliases:
            if str(alias or "").strip().lower() == n:
                return str(canonical)
    return ""


def _profession_aliases_for_query(name):
    canonical = _normalize_profession_name(name)
    out = []
    if canonical and canonical in PROFESSION_ALIASES_BY_CANONICAL:
        out.extend(list(PROFESSION_ALIASES_BY_CANONICAL.get(canonical, [])))
    raw = str(name or "").strip()
    if raw:
        out.append(raw)
    deduped = []
    seen = set()
    for val in out:
        t = str(val or "").strip()
        if not t:
            continue
        lk = t.lower()
        if lk in seen:
            continue
        seen.add(lk)
        deduped.append(t)
    return deduped


def _find_profession_option_index(options, preferred):
    opts = list(options or [])
    if not opts:
        return -1
    wanted_canon = _normalize_profession_name(preferred)
    wanted_raw = str(preferred or "").strip().lower()
    if wanted_raw:
        for i, opt in enumerate(opts):
            if str(opt or "").strip().lower() == wanted_raw:
                return int(i)
    if wanted_canon:
        for i, opt in enumerate(opts):
            if _normalize_profession_name(opt) == wanted_canon:
                return int(i)
    return -1


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
        item_id = _parse_item_id(parts[2]) if len(parts) > 2 else 0
        entry = {"material": mat, "per_item": int(qty)}
        if int(item_id) > 0:
            entry["item_id"] = int(item_id)
        out.append(entry)
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
        item_id = _parse_item_id(r.get("item_id", 0))
        if mat and qty > 0:
            if int(item_id) > 0:
                parts.append(f"{mat}:{qty}:0x{int(item_id):X}")
            else:
                parts.append(f"{mat}:{qty}")
    return ";".join(parts)


def _db_candidate_paths():
    if RECIPE_STORE is None:
        return []
    try:
        p = str(RECIPE_STORE._db_path() or "").strip()
    except Exception:
        p = ""
    if not p:
        return []
    return [os.path.normpath(p)]


def _load_resource_name_options():
    candidates = _db_candidate_paths()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if _has_columns(conn, "resource_catalog", ["resource_name"]):
                cur.execute(
                    """
                    SELECT resource_name
                    FROM resource_catalog
                    WHERE trim(coalesce(resource_name, '')) <> ''
                    ORDER BY resource_name COLLATE NOCASE
                    """
                )
                rows = cur.fetchall()
                out = [str(r["resource_name"] or "").strip() for r in rows if str(r["resource_name"] or "").strip()]
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


def _load_resource_item_id_map():
    candidates = _db_candidate_paths()
    seen = set()
    out = {}
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if _has_columns(conn, "resource_catalog", ["resource_name"]):
                cols = _table_columns(conn, "resource_catalog")
                iid_expr = "game_item_id" if "game_item_id" in cols else "0 AS game_item_id"
                cur.execute(
                    "SELECT resource_name, "
                    + str(iid_expr)
                    + " FROM resource_catalog WHERE trim(coalesce(resource_name,'')) <> ''"
                )
                rows = cur.fetchall()
                for row in rows:
                    name = str(row["resource_name"] or "").strip().lower()
                    if not name:
                        continue
                    try:
                        iid = int(row["game_item_id"] or 0)
                    except Exception:
                        iid = 0
                    if iid > 0:
                        out[name] = int(iid)
                break
        except Exception:
            out = {}
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return out


def _save_resource_item_id_mappings(resources):
    mapped = {}
    for rr in _normalize_resource_rows(resources):
        mat = str(rr.get("material", "") or "").strip().lower()
        iid = _parse_item_id(rr.get("item_id", 0))
        if mat and int(iid) > 0:
            mapped[mat] = int(iid)
    if not mapped:
        return True

    candidates = _db_candidate_paths()
    seen = set()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if _has_columns(conn, "resource_catalog", ["resource_name"]):
                cols = _table_columns(conn, "resource_catalog")
                if "game_item_id" in cols:
                    names = list(mapped.keys())
                    placeholders = ",".join(["?"] * len(names))
                    cur.execute(
                        "SELECT lower(resource_name) AS resource_name_key, coalesce(game_item_id, 0) AS game_item_id "
                        "FROM resource_catalog WHERE lower(resource_name) IN (" + placeholders + ")",
                        tuple(names),
                    )
                    existing = {}
                    for row in (cur.fetchall() or []):
                        key = str(row["resource_name_key"] or "").strip().lower()
                        if not key:
                            continue
                        try:
                            existing[key] = int(row["game_item_id"] or 0)
                        except Exception:
                            existing[key] = 0

                    changed = {}
                    for mat, iid in mapped.items():
                        if int(existing.get(mat, 0)) != int(iid):
                            changed[mat] = int(iid)

                    if not changed:
                        _write_debug_log("Resource item-id mappings unchanged; skipping save db={0}".format(str(t)))
                        return True

                    for mat, iid in changed.items():
                        cur.execute("INSERT OR IGNORE INTO resource_catalog(resource_name) VALUES (?)", (mat,))
                        cur.execute(
                            "UPDATE resource_catalog SET game_item_id=? WHERE lower(resource_name)=lower(?)",
                            (int(iid), mat),
                        )
                    conn.commit()
                    _write_debug_log(
                        "Saved resource item-id mappings: count={0} db={1}".format(int(len(changed)), str(t))
                    )
                    return True
        except Exception as ex:
            _write_debug_log("Resource item-id mapping save failed db={0} err={1}".format(str(t), str(ex)))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return False


def _table_columns(conn, table_name):
    out = set()
    try:
        cur = conn.execute("PRAGMA table_info(" + str(table_name) + ")")
        for row in (cur.fetchall() or []):
            try:
                out.add(str(row[1] or "").strip().lower())
            except Exception:
                pass
    except Exception:
        return set()
    return out


def _has_columns(conn, table_name, names):
    cols = _table_columns(conn, table_name)
    if not cols:
        return False
    for nm in (names or []):
        key = str(nm or "").strip().lower()
        if key and key not in cols:
            return False
    return True


def _prof_where_clause_and_params(profession):
    aliases = _profession_aliases_for_query(profession)
    if not aliases:
        return "", []
    placeholders = ",".join(["?"] * len(aliases))
    clause = " AND lower(coalesce(cp.profession_name,'')) IN (" + placeholders + ")"
    params = [str(x or "").strip().lower() for x in aliases if str(x or "").strip()]
    return clause, params


def _dedupe_str_list(values):
    seen = set()
    out = []
    for val in list(values or []):
        t = str(val or "").strip()
        if not t:
            continue
        lk = t.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(t)
    return out


def _load_profession_name_options(server):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    candidates = _db_candidate_paths()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"]) and _has_columns(
                conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"]
            ) and _has_columns(conn, "game_servers", ["game_server_id", "server_name"]):
                cur.execute(
                    """
                    SELECT DISTINCT cp.profession_name
                    FROM crafting_professions cp
                    JOIN crafting_contexts cc ON cc.profession_id = cp.profession_id
                    JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                    WHERE lower(coalesce(gs.server_name,''))=lower(?)
                    ORDER BY cp.profession_name COLLATE NOCASE
                    """,
                    (srv,),
                )
                rows = cur.fetchall()
                out = [str(r["profession_name"] or "").strip() for r in rows if str(r["profession_name"] or "").strip()]
                if not out:
                    cur.execute(
                        """
                        SELECT profession_name
                        FROM crafting_professions
                        WHERE trim(coalesce(profession_name,'')) <> ''
                        ORDER BY profession_name COLLATE NOCASE
                        """
                    )
                    rows = cur.fetchall()
                    out = [str(r["profession_name"] or "").strip() for r in rows if str(r["profession_name"] or "").strip()]
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
        out = list(PROFESSION_OPTIONS)
    canonical_out = []
    seen = set()
    for nm in out:
        raw = str(nm or "").strip()
        if not raw:
            continue
        canon = _normalize_profession_name(raw) or raw
        key = str(canon or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        canonical_out.append(str(canon).strip())
    if not canonical_out:
        canonical_out = list(PROFESSION_OPTIONS)
    return _dedupe_str_list(canonical_out)


def _load_category_name_options(server, profession):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    candidates = _db_candidate_paths()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if _has_columns(conn, "craft_categories", ["category_name", "display_sequence", "context_id"]) and _has_columns(
                conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"]
            ) and _has_columns(conn, "game_servers", ["game_server_id", "server_name"]) and _has_columns(
                conn, "crafting_professions", ["profession_id", "profession_name"]
            ):
                prof_clause, prof_params = _prof_where_clause_and_params(profession)
                params = [srv]
                params.extend(prof_params)
                cur.execute(
                    """
                    SELECT DISTINCT cat.category_name, cat.display_sequence
                    FROM craft_categories cat
                    JOIN crafting_contexts cc ON cc.context_id = cat.context_id
                    JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                    JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                    WHERE lower(coalesce(gs.server_name,''))=lower(?)
                    """
                    + prof_clause
                    + """
                    AND trim(coalesce(cat.category_name,'')) <> ''
                    ORDER BY cat.display_sequence, cat.category_name COLLATE NOCASE
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
                out = [str(r["category_name"] or "").strip() for r in rows if str(r["category_name"] or "").strip()]
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
        try:
            km = _get_key_maps()
            prof = _normalize_profession_name(profession)
            node = km.get(srv, {}).get(prof, {}) if isinstance(km, dict) else {}
            ik = node.get("item_keys", {}) if isinstance(node, dict) else {}
            if isinstance(ik, dict):
                for ent in ik.values():
                    if not isinstance(ent, dict):
                        continue
                    cat = str(ent.get("category", "") or "").strip()
                    if cat:
                        out.append(cat)
        except Exception:
            pass
    return _dedupe_str_list(out)


def _load_item_name_options(server, profession, category=""):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    prof = _normalize_profession_name(profession or "")
    if not prof:
        return []
    category_text = str(category or "").strip()
    if category_text.lower() == str(CATEGORY_ALL_LABEL).lower():
        category_text = ""

    candidates = _db_candidate_paths()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))

            if _has_columns(conn, "craftable_items", ["craftable_item_id", "context_id", "item_display_name"]) and _has_columns(
                conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"]
            ) and _has_columns(conn, "game_servers", ["game_server_id", "server_name"]) and _has_columns(
                conn, "crafting_professions", ["profession_id", "profession_name"]
            ):
                prof_clause, prof_params = _prof_where_clause_and_params(profession)
                cat_clause = ""
                params = [srv]
                params.extend(prof_params)
                if category_text:
                    cat_clause = " AND lower(coalesce(cat.category_name,''))=lower(?)"
                    params.append(category_text)
                cur.execute(
                    """
                    SELECT ci.item_display_name
                    FROM craftable_items ci
                    JOIN crafting_contexts cc ON cc.context_id = ci.context_id
                    JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                    JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                    LEFT JOIN craft_categories cat ON cat.category_id = ci.category_id
                    WHERE lower(coalesce(gs.server_name,''))=lower(?)
                    """
                    + prof_clause
                    + cat_clause
                    + """
                    AND trim(coalesce(ci.item_display_name,''))<>'' 
                    ORDER BY ci.item_display_name COLLATE NOCASE
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
                out = [str(r["item_display_name"] or "").strip() for r in rows if str(r["item_display_name"] or "").strip()]
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
        seen_saved_paths = set()
        for p in candidates:
            t = str(p or "").strip()
            if not t:
                continue
            lk = t.lower()
            if lk in seen_saved_paths:
                continue
            seen_saved_paths.add(lk)
            if not os.path.exists(t):
                continue
            conn = None
            try:
                conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
                if _has_columns(conn, "saved_craft_recipes", ["context_id", "recipe_name"]) and _has_columns(
                    conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"]
                ) and _has_columns(conn, "game_servers", ["game_server_id", "server_name"]) and _has_columns(
                    conn, "crafting_professions", ["profession_id", "profession_name"]
                ):
                    prof_clause, prof_params = _prof_where_clause_and_params(profession)
                    params = [srv]
                    params.extend(prof_params)
                    cat_join = ""
                    cat_clause = ""
                    if category_text and _has_columns(conn, "craftable_items", ["craftable_item_id", "category_id"]) and _has_columns(
                        conn, "craft_categories", ["category_id", "category_name"]
                    ):
                        cat_join = """
                        LEFT JOIN craftable_items ci ON ci.craftable_item_id = sr.craftable_item_id
                        LEFT JOIN craft_categories cat ON cat.category_id = ci.category_id
                        """
                        cat_clause = " AND lower(coalesce(cat.category_name,''))=lower(?)"
                        params.append(category_text)
                    cur.execute(
                        """
                        SELECT DISTINCT sr.recipe_name
                        FROM saved_craft_recipes sr
                        JOIN crafting_contexts cc ON cc.context_id = sr.context_id
                        JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                        JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                        """
                        + cat_join
                        + """
                        WHERE lower(coalesce(gs.server_name,''))=lower(?)
                        """
                        + prof_clause
                        + cat_clause
                        + """
                        AND trim(coalesce(sr.recipe_name,''))<>'' 
                        ORDER BY sr.recipe_name COLLATE NOCASE
                        """,
                        tuple(params),
                    )
                    rows = cur.fetchall()
                    out = [str(r["recipe_name"] or "").strip() for r in rows if str(r["recipe_name"] or "").strip()]
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
                    cat = str((ent or {}).get("category", "") if isinstance(ent, dict) else "").strip()
                    if category_text and cat.lower() != category_text.lower():
                        continue
                    if nm:
                        out.append(nm)
        except Exception:
            pass

    return _dedupe_str_list(out)


def _load_item_catalog_entry(server, profession, item_name):
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    item = str(item_name or "").strip()
    if not item:
        return {}
    candidates = _db_candidate_paths()
    seen_paths = set()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if not (
                _has_columns(conn, "craftable_items", ["craftable_item_id", "context_id", "item_display_name"])
                and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
                and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
                and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
            ):
                continue
            prof_clause, prof_params = _prof_where_clause_and_params(profession)
            params = [srv]
            params.extend(prof_params)
            params.append(item)
            cur.execute(
                """
                SELECT ci.craftable_item_id, ci.game_item_id, ci.default_material_option_id,
                       coalesce(cat.category_name, '') AS category_name,
                       coalesce(cat.category_navigation_button_id, 0) AS category_navigation_button_id
                FROM craftable_items ci
                JOIN crafting_contexts cc ON cc.context_id = ci.context_id
                JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                LEFT JOIN craft_categories cat ON cat.category_id = ci.category_id
                WHERE lower(coalesce(gs.server_name,''))=lower(?)
                """
                + prof_clause
                + """
                  AND lower(coalesce(ci.item_display_name,''))=lower(?)
                ORDER BY ci.craftable_item_id
                LIMIT 1
                """,
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                continue

            item_id = int(row["craftable_item_id"] or 0)
            category_button = int(row["category_navigation_button_id"] or 0)
            buttons = []
            if category_button > 0:
                buttons.append(int(category_button))
            if _has_columns(conn, "craftable_item_navigation_steps", ["craftable_item_id", "step_number", "gump_button_id"]):
                cur.execute(
                    """
                    SELECT gump_button_id
                    FROM craftable_item_navigation_steps
                    WHERE craftable_item_id=?
                    ORDER BY step_number
                    """,
                    (int(item_id),),
                )
                for r_btn in (cur.fetchall() or []):
                    try:
                        b = int(r_btn["gump_button_id"] or 0)
                    except Exception:
                        b = 0
                    if b > 0:
                        if not buttons or int(buttons[-1]) != int(b):
                            buttons.append(int(b))

            resources = []
            if _has_columns(conn, "craftable_item_resource_requirements", ["craftable_item_id", "requirement_sequence", "resource_id", "quantity_per_item"]) and _has_columns(
                conn, "resource_catalog", ["resource_id", "resource_name"]
            ):
                resource_cols = _table_columns(conn, "resource_catalog")
                item_id_expr = "coalesce(rc.game_item_id, 0)" if "game_item_id" in resource_cols else "0"
                cur.execute(
                    """
                    SELECT rc.resource_name, cir.quantity_per_item, """
                    + str(item_id_expr)
                    + """
                    FROM craftable_item_resource_requirements cir
                    JOIN resource_catalog rc ON rc.resource_id = cir.resource_id
                    WHERE cir.craftable_item_id=?
                    ORDER BY cir.requirement_sequence
                    """,
                    (int(item_id),),
                )
                for rr in (cur.fetchall() or []):
                    mat = str(rr["resource_name"] or "").strip().lower()
                    try:
                        qty = int(rr["quantity_per_item"] or 0)
                    except Exception:
                        qty = 0
                    try:
                        item_id = int(rr[2] or 0)
                    except Exception:
                        item_id = 0
                    if mat and qty > 0:
                        entry = {"material": mat, "per_item": int(qty)}
                        if int(item_id) > 0:
                            entry["item_id"] = int(item_id)
                        resources.append(entry)

            default_material_key = ""
            declared_material = ""
            try:
                mo_id = int(row["default_material_option_id"] or 0)
            except Exception:
                mo_id = 0
            if mo_id > 0 and _has_columns(conn, "material_options", ["material_option_id", "material_option_key", "material_family_id"]):
                cur.execute(
                    """
                    SELECT mo.material_option_key, mf.family_code
                    FROM material_options mo
                    LEFT JOIN material_families mf ON mf.material_family_id = mo.material_family_id
                    WHERE mo.material_option_id=?
                    LIMIT 1
                    """,
                    (int(mo_id),),
                )
                mo_row = cur.fetchone()
                if mo_row:
                    default_material_key = str(mo_row["material_option_key"] or "").strip().lower()
                    declared_material = str(mo_row["family_code"] or "").strip().lower()

            return {
                "category": str(row["category_name"] or "").strip(),
                "buttons": [int(x) for x in buttons if int(x) > 0][:3],
                "item_id": int(row["game_item_id"] or 0),
                "resources": list(resources or []),
                "default_material_key": default_material_key,
                "material": declared_material,
            }
        except Exception:
            continue
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return {}


def _resource_option_index(options, name):
    target = str(name or "").strip().lower()
    if not target:
        return -1
    for i, opt in enumerate(list(options or [])):
        if str(opt or "").strip().lower() == target:
            return int(i)
    return -1


def _selected_dropdown_value(dd, options):
    opts = list(options or [])
    idx = -1
    try:
        idx = int(dd.GetSelectedIndex()) if dd else -1
    except Exception:
        idx = -1
    if 0 <= idx < len(opts):
        return str(opts[idx] or "").strip()
    try:
        return str((dd.Text if dd else "") or "").strip()
    except Exception:
        return ""


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
        item_id = _parse_item_id(r.get("item_id", 0))
        entry = {"material": mat, "per_item": int(qty)}
        if int(item_id) > 0:
            entry["item_id"] = int(item_id)
        out.append(entry)
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
        item_id_tb = row.get("item_id")
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
        item_id_text = str((item_id_tb.Text if item_id_tb else "") or "").strip()
        item_id = _parse_item_id(item_id_text)
        entry = {"material": name.lower(), "per_item": int(qty)}
        if int(item_id) > 0:
            entry["item_id"] = int(item_id)
        out.append(entry)
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
        }
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
        seg = [base]
        if item_id > 0 or min_in_pack > 0 or pull_amount > 0:
            seg.append(f"0x{int(item_id):X}" if item_id > 0 else "0")
        if min_in_pack > 0 or pull_amount > 0:
            seg.append(str(min_in_pack))
        if pull_amount > 0:
            seg.append(str(pull_amount))
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


def _collect_material_key_options(profession="", server=""):
    prof = _normalize_profession_name(profession)
    srv = _normalize_server_name(server or DEFAULT_SERVER)
    keys = set()
    # Include canonical material options from normalized craftables schema.
    candidates = _db_candidate_paths()
    seen_paths = set()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if not (
                _has_columns(conn, "material_options", ["material_option_id", "context_id", "material_option_key"])
                and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
                and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
                and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
            ):
                continue
            prof_clause, prof_params = _prof_where_clause_and_params(profession)
            params = [srv]
            params.extend(prof_params)
            cur.execute(
                """
                SELECT mo.material_option_key
                FROM material_options mo
                JOIN crafting_contexts cc ON cc.context_id = mo.context_id
                JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                WHERE lower(coalesce(gs.server_name,''))=lower(?)
                """
                + prof_clause
                + """
                  AND trim(coalesce(mo.material_option_key,'')) <> ''
                ORDER BY mo.material_option_key COLLATE NOCASE
                """,
                tuple(params),
            )
            for rr in (cur.fetchall() or []):
                mk = str(rr["material_option_key"] or "").strip().lower()
                if mk:
                    keys.add(mk)
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    # Include material keys already persisted with saved recipes.
    seen_saved_paths = set()
    for p in candidates:
        t = str(p or "").strip()
        if not t:
            continue
        lk = t.lower()
        if lk in seen_saved_paths:
            continue
        seen_saved_paths.add(lk)
        if not os.path.exists(t):
            continue
        conn = None
        try:
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if not (
                _has_columns(conn, "saved_craft_recipes", ["context_id", "selected_material_option_id", "declared_material_family_id"])
                and _has_columns(conn, "material_options", ["material_option_id", "material_option_key", "material_family_id"])
                and _has_columns(conn, "material_families", ["material_family_id", "family_code"])
                and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
                and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
                and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
            ):
                continue
            prof_clause, prof_params = _prof_where_clause_and_params(profession)
            params = [srv]
            params.extend(prof_params)
            cur.execute(
                """
                SELECT DISTINCT coalesce(mo.material_option_key, mf.family_code, '') AS material_key
                FROM saved_craft_recipes sr
                JOIN crafting_contexts cc ON cc.context_id = sr.context_id
                JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                LEFT JOIN material_options mo ON mo.material_option_id = sr.selected_material_option_id
                LEFT JOIN material_families mf ON mf.material_family_id = coalesce(sr.declared_material_family_id, mo.material_family_id)
                WHERE lower(coalesce(gs.server_name,''))=lower(?)
                """
                + prof_clause
                + """
                  AND trim(coalesce(mo.material_option_key, mf.family_code, '')) <> ''
                ORDER BY material_key COLLATE NOCASE
                """,
                tuple(params),
            )
            for rr in (cur.fetchall() or []):
                mk = str(rr["material_key"] or "").strip().lower()
                if mk:
                    keys.add(mk)
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    for r in _read_recipe_book():
        try:
            if prof and _normalize_profession_name(r.get("profession", "")) != prof:
                continue
            if _normalize_server_name(r.get("server", DEFAULT_SERVER)) != srv:
                continue
            mk = str(r.get("material_key", "") or "").strip().lower()
        except Exception:
            mk = ""
        if mk:
            keys.add(mk)
    # Include mapped material keys from key_maps for the selected server.
    km = _get_key_maps()
    if prof and isinstance(km, dict):
        srv_node = km.get(srv, {})
        if isinstance(srv_node, dict):
            pnode = srv_node.get(prof, {})
            if isinstance(pnode, dict):
                mats = pnode.get("material_keys", {})
                if isinstance(mats, dict):
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
    # Pull directly from normalized material option navigation if available.
    candidates = _db_candidate_paths()
    seen_paths = set()
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
            conn = sqlite3.connect(t, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
            if not (
                _has_columns(conn, "material_options", ["material_option_id", "context_id", "material_option_key"])
                and _has_columns(conn, "material_option_navigation_steps", ["material_option_id", "step_number", "gump_button_id"])
                and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
                and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
                and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
            ):
                continue
            prof_clause, prof_params = _prof_where_clause_and_params(profession)
            params = [srv]
            params.extend(prof_params)
            params.append(mk)
            cur.execute(
                """
                SELECT mons.gump_button_id
                FROM material_options mo
                JOIN material_option_navigation_steps mons ON mons.material_option_id = mo.material_option_id
                JOIN crafting_contexts cc ON cc.context_id = mo.context_id
                JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                WHERE lower(coalesce(gs.server_name,''))=lower(?)
                """
                + prof_clause
                + """
                  AND lower(coalesce(mo.material_option_key,''))=lower(?)
                ORDER BY mons.step_number
                """,
                tuple(params),
            )
            out = []
            for rr in (cur.fetchall() or []):
                try:
                    b = int(rr["gump_button_id"] or 0)
                except Exception:
                    b = 0
                if b > 0:
                    out.append(int(b))
                if len(out) >= 2:
                    break
            if out:
                return out
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
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
    global EDITOR_GUMP, EDITOR_INPUTS, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX
    global EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX, EDITOR_LAST_SERVER_IDX, EDITOR_LAST_CATEGORY_IDX
    global EDITOR_LAST_ITEM_IDX
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
    EDITOR_LAST_SERVER_IDX = -1
    EDITOR_LAST_CATEGORY_IDX = -1
    EDITOR_LAST_ITEM_IDX = -1


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
    prof_opts = list(f.get("profession_options", []) or [])
    if not prof_opts:
        prof_opts = list(PROFESSION_OPTIONS)
    out["profession"] = _selected_dropdown_value(f.get("profession"), prof_opts)
    cat_opts = list(f.get("category_options", []) or [])
    selected_category = _selected_dropdown_value(f.get("category"), cat_opts)
    if selected_category.lower() == str(CATEGORY_ALL_LABEL).lower():
        selected_category = ""
    out["category"] = selected_category
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
    srv_dd = f.get("server")
    type_dd = f.get("recipe_type")
    mode_idx = int(mode_dd.GetSelectedIndex()) if mode_dd else 0
    srv_idx = int(srv_dd.GetSelectedIndex()) if srv_dd else 0
    type_idx = int(type_dd.GetSelectedIndex()) if type_dd else 0
    prof_opts = list(f.get("profession_options", []) or [])
    if not prof_opts:
        prof_opts = list(PROFESSION_OPTIONS)
    raw_profession = _selected_dropdown_value(f.get("profession"), prof_opts)
    profession = _normalize_profession_name(raw_profession)
    if not profession:
        _say("Select a valid profession.", 33)
        return
    category_opts = list(f.get("category_options", []) or [])
    selected_category = _selected_dropdown_value(f.get("category"), category_opts)
    if selected_category.lower() == str(CATEGORY_ALL_LABEL).lower():
        selected_category = ""
    if mode_idx < 0 or mode_idx >= len(EDITOR_MODE_OPTIONS):
        mode_idx = 0
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
        materials = [{"material": material, "item_id": 0, "min_in_pack": 0, "pull_amount": 0}]
    resources = _collect_resource_rows_from_controls(f)
    if not resources:
        resources = _parse_resources_text(str((f.get("resources_text").Text if f.get("resources_text") else "") or ""))
    resources = _normalize_resource_rows(resources)
    catalog_defaults = _load_item_catalog_entry(SERVER_OPTIONS[srv_idx], raw_profession or profession, name)
    if not selected_category and isinstance(catalog_defaults, dict):
        selected_category = str(catalog_defaults.get("category", "") or "").strip()
    if not mk_text and isinstance(catalog_defaults, dict):
        mk_text = str(catalog_defaults.get("default_material_key", "") or "").strip().lower()
        if mk_text:
            material = _material_base_from_key(mk_text, material)
    if not resources and isinstance(catalog_defaults, dict):
        resources = _normalize_resource_rows(catalog_defaults.get("resources", []))

    row = {
        "name": name,
        "profession": profession,
        "item_id": int(catalog_defaults.get("item_id", 0) or 0) if isinstance(catalog_defaults, dict) else 0,
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
        existing_item_map = _get_item_key_map(SERVER_OPTIONS[srv_idx], profession, name)
        existing_resources = list(existing_item_map.get("resources", []) or []) if isinstance(existing_item_map, dict) else []
        resources_to_save = (
            list(resources or [])
            if list(resources or [])
            else _normalize_resource_rows(existing_resources)
        )
        if not resources_to_save:
            _say("Resources are required. Add at least one resource and per-item quantity.", 33)
            return
        if not _save_resource_item_id_mappings(resources_to_save):
            _say("Failed to save resource item-id mappings.", 33)
            return
        if not _upsert_key_maps(
            SERVER_OPTIONS[srv_idx],
            profession,
            name,
            int(row.get("item_id", 0) or 0),
            list(row.get("buttons", []) or []),
            material,
            mk_text,
            list(row.get("material_buttons", []) or []),
            resources_to_save,
            selected_category,
        ):
            _say("Failed to save key maps.", 33)
            return
        _say(f"Key maps saved: {profession} {name} ({SERVER_OPTIONS[srv_idx]})")
        ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "saved", "editor_mode": editor_mode, "key_maps_saved": True})
        _write_debug_log("Save ack (key_maps_saved) nonce={0} ok={1}".format(int(REQUEST_NONCE), bool(ok)))
        _close_editor()
        SCRIPT_EXIT_REQUESTED = True
        return

    # bind_deed mode: prefer key-map values when present.
    item_map = _get_item_key_map(SERVER_OPTIONS[srv_idx], profession, name)
    if item_map:
        map_buttons = [int(x) for x in (item_map.get("buttons", []) or []) if int(x) > 0][:2]
        if map_buttons and not user_entered_two_buttons:
            row["buttons"] = map_buttons
        if int(row.get("item_id", 0) or 0) <= 0:
            row["item_id"] = int(item_map.get("item_id", 0) or 0)
        if not mk_text:
            row["material_key"] = str(item_map.get("default_material_key", "") or "").strip().lower()

    mat_map = _get_material_key_map(SERVER_OPTIONS[srv_idx], profession, row.get("material_key", mk_text))
    if mat_map:
        map_mbtns = [int(x) for x in (mat_map.get("material_buttons", []) or []) if int(x) > 0][:2]
        if map_mbtns:
            row["material_buttons"] = map_mbtns
        row["material"] = str(mat_map.get("material", row.get("material", material)) or row.get("material", material)).strip().lower()

    # In bind_deed mode, keep key maps synchronized with the confirmed recipe path.
    existing_category = str(item_map.get("category", "") or "").strip() if isinstance(item_map, dict) else ""
    category_to_save = selected_category if selected_category else existing_category
    existing_resources = list(item_map.get("resources", []) or []) if isinstance(item_map, dict) else []
    resources_to_save = (
        list(resources or [])
        if list(resources or [])
        else _normalize_resource_rows(existing_resources)
    )
    if not resources_to_save:
        _say("Resources are required. Add at least one resource and per-item quantity.", 33)
        return
    if not _save_resource_item_id_mappings(resources_to_save):
        _say("Failed to save resource item-id mappings.", 33)
        return
    if not _upsert_key_maps(
        SERVER_OPTIONS[srv_idx],
        profession,
        name,
        int(row.get("item_id", 0) or 0),
        list(row.get("buttons", []) or []),
        str(row.get("material", material) or material),
        str(row.get("material_key", mk_text) or mk_text),
        list(row.get("material_buttons", []) or []),
        resources_to_save,
        category_to_save,
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
    global EDITOR_GUMP, EDITOR_INPUTS, EDITOR_LAST_TYPE_IDX, EDITOR_LAST_MATERIAL_KEY_IDX
    global EDITOR_LAST_PROFESSION_IDX, EDITOR_LAST_MODE_IDX, EDITOR_LAST_SERVER_IDX, EDITOR_LAST_CATEGORY_IDX
    global EDITOR_LAST_ITEM_IDX
    global SCRIPT_EXIT_REQUESTED
    _close_editor()
    SCRIPT_EXIT_REQUESTED = False
    pre = pre_override if isinstance(pre_override, dict) else _prefill_from_request()
    g = API.CreateGump(True, True, False)
    w = 760
    h = 720
    g.SetRect(560, 120, w, h)
    try:
        g.SetInScreen()
    except Exception:
        pass
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
    profession_options = _load_profession_name_options(srv)
    if not profession_options:
        profession_options = list(PROFESSION_OPTIONS)
    pre_profession = str(pre.get("profession", "Blacksmith") or "Blacksmith")
    prof_idx = _find_profession_option_index(profession_options, pre_profession)
    if prof_idx < 0:
        prof_idx = 0
    prof_display = str(profession_options[prof_idx] or "") if profession_options else "Blacksmith"
    prof = _normalize_profession_name(prof_display) or _normalize_profession_name(pre_profession) or "Blacksmith"
    d1 = API.CreateDropDown(180, list(profession_options), int(prof_idx))
    d1.SetPos(100 + x_off, y - 2)
    g.Add(d1)

    y += 38
    l2 = API.CreateGumpTTFLabel("Category", 12, label_color, "alagard", "left", 78)
    l2.SetPos(10 + x_off, y)
    g.Add(l2)
    current_item_name = str(pre.get("name", pre.get("item_name", "")) or "").strip()
    item_catalog = _load_item_catalog_entry(srv, prof_display, current_item_name) if current_item_name else {}
    preferred_category = str(pre.get("category", "") or "").strip()
    if not preferred_category and isinstance(item_catalog, dict):
        preferred_category = str(item_catalog.get("category", "") or "").strip()
    category_values = _load_category_name_options(srv, prof_display)
    category_options = [str(CATEGORY_ALL_LABEL)]
    category_options.extend(list(category_values or []))
    if preferred_category and _resource_option_index(category_options, preferred_category) < 0:
        category_options.append(preferred_category)
    category_options = _dedupe_str_list(category_options)
    cat_idx = _resource_option_index(category_options, preferred_category if preferred_category else CATEGORY_ALL_LABEL)
    if cat_idx < 0:
        cat_idx = 0
    d_cat = API.CreateDropDown(220, list(category_options), int(cat_idx))
    d_cat.SetPos(88 + x_off, y - 2)
    g.Add(d_cat)

    y += 38
    l3 = API.CreateGumpTTFLabel("Item Name", 12, label_color, "alagard", "left", 90)
    l3.SetPos(10 + x_off, y)
    g.Add(l3)
    selected_category = str(category_options[cat_idx] if 0 <= int(cat_idx) < len(category_options) else CATEGORY_ALL_LABEL)
    name_options = _load_item_name_options(srv, prof_display, selected_category)
    if current_item_name and _resource_option_index(name_options, current_item_name) < 0:
        name_options.append(current_item_name)
    name_options = _dedupe_str_list(name_options)
    if not name_options:
        name_options = [str(ITEM_NONE_LABEL)]
    name_idx = _resource_option_index(name_options, current_item_name)
    if name_idx < 0:
        name_idx = 0
    d_name = API.CreateDropDown(500, list(name_options), int(name_idx))
    d_name.SetPos(100 + x_off, y - 2)
    g.Add(d_name)

    item_name_for_defaults = str(name_options[name_idx] if 0 <= int(name_idx) < len(name_options) else current_item_name).strip()
    if item_name_for_defaults.lower() == str(ITEM_NONE_LABEL).lower():
        item_name_for_defaults = ""
    if item_name_for_defaults and (not item_catalog or _resource_option_index([current_item_name], item_name_for_defaults) < 0):
        item_catalog = _load_item_catalog_entry(srv, prof_display, item_name_for_defaults)

    item_map_for_defaults = _get_item_key_map(srv, prof, item_name_for_defaults)
    resource_rows = []
    y += 38
    l3b = API.CreateGumpTTFLabel("Item Resource Costs (max 5)", 12, label_color, "alagard", "left", 220)
    l3b.SetPos(10 + x_off, y)
    g.Add(l3b)
    pre_resources = _normalize_resource_rows(pre.get("resources", []))
    if not pre_resources:
        pre_resources = _normalize_resource_rows(_parse_resources_text(str(pre.get("resources_text", "") or "").strip()))
    if not pre_resources and isinstance(item_catalog, dict):
        pre_resources = _normalize_resource_rows(item_catalog.get("resources", []))
    if not pre_resources and isinstance(item_map_for_defaults, dict):
        pre_resources = _normalize_resource_rows(item_map_for_defaults.get("resources", []))
    resource_item_id_map = _load_resource_item_id_map()
    if pre_resources and isinstance(resource_item_id_map, dict) and resource_item_id_map:
        hydrated_resources = []
        for rr in pre_resources:
            if not isinstance(rr, dict):
                continue
            mat = str(rr.get("material", "") or "").strip().lower()
            try:
                qty = int(rr.get("per_item", 0) or 0)
            except Exception:
                qty = 0
            if not mat or qty <= 0:
                continue
            item_id = _parse_item_id(rr.get("item_id", 0))
            if int(item_id) <= 0:
                item_id = _parse_item_id(resource_item_id_map.get(mat, 0))
            entry = {"material": mat, "per_item": int(qty)}
            if int(item_id) > 0:
                entry["item_id"] = int(item_id)
            hydrated_resources.append(entry)
        pre_resources = list(hydrated_resources)
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
    qty_hdr = API.CreateGumpTTFLabel("Qty", 11, label_color, "alagard", "left", 32)
    qty_hdr.SetPos(264 + x_off, y + 4)
    g.Add(qty_hdr)
    item_id_hdr = API.CreateGumpTTFLabel("Item ID", 11, label_color, "alagard", "left", 64)
    item_id_hdr.SetPos(348 + x_off, y + 4)
    g.Add(item_id_hdr)
    for idx_row in range(int(RESOURCE_SLOT_COUNT)):
        ry = y + 24 + (idx_row * 24)
        slot_lbl = API.CreateGumpTTFLabel(str(int(idx_row + 1)) + ".", 11, label_color, "alagard", "left", 16)
        slot_lbl.SetPos(10 + x_off, ry)
        g.Add(slot_lbl)
        selected_name = ""
        qty_text = ""
        item_id_text = ""
        if idx_row < len(pre_resources):
            selected_name = str(pre_resources[idx_row].get("material", "") or "").strip()
            try:
                qty_text = str(int(pre_resources[idx_row].get("per_item", 0) or 0))
            except Exception:
                qty_text = ""
            item_id = _parse_item_id(pre_resources[idx_row].get("item_id", 0))
            if int(item_id) > 0:
                item_id_text = f"0x{int(item_id):X}"
        opt_idx = _resource_option_index(option_values, selected_name)
        if opt_idx < 0:
            opt_idx = 0
        dd_res = API.CreateDropDown(220, list(option_values), int(opt_idx))
        dd_res.SetPos(32 + x_off, ry - 2)
        g.Add(dd_res)
        t_qty = API.CreateGumpTextBox(str(qty_text or ""), 72, 18, False)
        t_qty.SetPos(264 + x_off, ry - 2)
        g.Add(t_qty)
        t_item_id = API.CreateGumpTextBox(str(item_id_text or ""), 98, 18, False)
        t_item_id.SetPos(348 + x_off, ry - 2)
        g.Add(t_item_id)
        resource_rows.append({"resource": dd_res, "qty": t_qty, "item_id": t_item_id, "options": list(option_values)})
    y += 24 + (int(RESOURCE_SLOT_COUNT) * 24) + 8

    y += 38
    l4 = API.CreateGumpTTFLabel("Crafting Gump Button Combination", 12, label_color, "alagard", "left", 220)
    l4.SetPos(10 + x_off, y)
    g.Add(l4)
    pre_buttons = pre.get("buttons", [])
    parsed_pre_buttons = []
    if isinstance(pre_buttons, list):
        for x in pre_buttons:
            try:
                b = int(x)
            except Exception:
                b = 0
            if b > 0:
                parsed_pre_buttons.append(int(b))
            if len(parsed_pre_buttons) >= 2:
                break
    else:
        parsed = _parse_int_list(str(pre_buttons or ""))
        parsed_pre_buttons = [int(x) for x in parsed if int(x) > 0][:2]
    if not parsed_pre_buttons and isinstance(item_catalog, dict):
        parsed_pre_buttons = [int(x) for x in (item_catalog.get("buttons", []) or []) if int(x) > 0][:2]
    if not parsed_pre_buttons and isinstance(item_map_for_defaults, dict):
        parsed_pre_buttons = [int(x) for x in (item_map_for_defaults.get("buttons", []) or []) if int(x) > 0][:2]
    p1 = str(int(parsed_pre_buttons[0])) if len(parsed_pre_buttons) > 0 else ""
    p2 = str(int(parsed_pre_buttons[1])) if len(parsed_pre_buttons) > 1 else ""
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
    base_material = str(pre.get("material", "") or "").strip().lower()
    if not base_material and isinstance(item_catalog, dict):
        base_material = str(item_catalog.get("material", "") or "").strip().lower()
    if not base_material:
        base_material = "ingot"
    mk_current = str(pre.get("material_key", "") or "").strip().lower()
    if not mk_current and isinstance(item_catalog, dict):
        mk_current = str(item_catalog.get("default_material_key", "") or "").strip().lower()
    if not mk_current:
        mk_current = _material_key_from_base(base_material)
    mk_options = _collect_material_key_options(prof, srv)
    mk_labels = list(mk_options)
    mk_labels.append(MATERIAL_KEY_ADD_LABEL)
    mk_selected = str(pre.get("material_key", mk_current) or "").strip().lower()
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
    EDITOR_LAST_SERVER_IDX = int(srv_idx)
    EDITOR_LAST_CATEGORY_IDX = int(cat_idx)
    EDITOR_LAST_ITEM_IDX = int(name_idx)
    EDITOR_INPUTS = {
        "editor_mode": d_mode,
        "recipe_type": d0,
        "server": d0b,
        "profession": d1,
        "profession_options": list(profession_options),
        "category": d_cat,
        "category_options": list(category_options),
        "material_hidden": str(base_material or "ingot"),
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
        "resources_text": None,
    }
    ok = _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "opened"})
    _write_debug_log("Open ack nonce={0} ok={1}".format(int(REQUEST_NONCE), bool(ok)))


def _main():
    global SCRIPT_EXIT_REQUESTED
    # Keep launch responsive; DB access is handled lazily by read/write helpers.
    try:
        _open_editor()
    except Exception:
        _write_debug_log("Open editor exception:\n{0}".format(traceback.format_exc()))
        _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "error", "error": "open_editor"})
        SCRIPT_EXIT_REQUESTED = True
    try:
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
                dd_server = f.get("server")
                dd_category = f.get("category")
                dd_item = f.get("name")
                current_mode_idx = int(dd_mode.GetSelectedIndex()) if dd_mode else -1
                current_type_idx = int(dd_type.GetSelectedIndex()) if dd_type else -1
                current_mk_idx = int(dd_mk.GetSelectedIndex()) if dd_mk else -1
                current_prof_idx = int(dd_prof.GetSelectedIndex()) if dd_prof else -1
                current_server_idx = int(dd_server.GetSelectedIndex()) if dd_server else -1
                current_category_idx = int(dd_category.GetSelectedIndex()) if dd_category else -1
                current_item_idx = int(dd_item.GetSelectedIndex()) if dd_item else -1
            except Exception:
                current_mode_idx = -1
                current_type_idx = -1
                current_mk_idx = -1
                current_prof_idx = -1
                current_server_idx = -1
                current_category_idx = -1
                current_item_idx = -1
            if current_mode_idx != -1 and current_mode_idx != int(EDITOR_LAST_MODE_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_type_idx != -1 and current_type_idx != int(EDITOR_LAST_TYPE_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_server_idx != -1 and current_server_idx != int(EDITOR_LAST_SERVER_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_prof_idx != -1 and current_prof_idx != int(EDITOR_LAST_PROFESSION_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_category_idx != -1 and current_category_idx != int(EDITOR_LAST_CATEGORY_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_item_idx != -1 and current_item_idx != int(EDITOR_LAST_ITEM_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            if current_mk_idx != -1 and current_mk_idx != int(EDITOR_LAST_MATERIAL_KEY_IDX):
                state = _capture_editor_state()
                _open_editor(state)
                continue
            API.Pause(0.1)
    except Exception:
        _write_debug_log("Main loop exception:\n{0}".format(traceback.format_exc()))
        _set_persistent_json(RESULT_KEY, {"nonce": REQUEST_NONCE, "status": "error", "error": "main_loop"})
        _close_editor()
        SCRIPT_EXIT_REQUESTED = True
    _write_debug_log("Main exit requested={0} gump_alive={1}".format(bool(SCRIPT_EXIT_REQUESTED), bool(EDITOR_GUMP is not None)))


_main()
