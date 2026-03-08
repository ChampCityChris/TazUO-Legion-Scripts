import json
import os
import sqlite3
import time

DB_FILE = "craftables.db"
DB_FOLDER = "Databases"
SCHEMA_VERSION = 9
BASE_DIR_OVERRIDE = ""
SQLITE_CONNECT_TIMEOUT_S = 0.35
SQLITE_BUSY_TIMEOUT_MS = 350
INIT_RETRY_COOLDOWN_S = 1.5
_INIT_OK = False
_INIT_NEXT_RETRY_AT = 0.0
_INIT_LAST_ERROR = ""
_DIAG_LOGGER = None
_READ_CONN = None
_READ_CONN_PATH = ""
# Manual validation checklist (schema v9):
# 1) Run init_store() and verify app_metadata.schema_version == 9.
# 2) Verify craft_categories queries succeed with context/category keys.
# 3) Run save_key_maps(...) and confirm caller logs contain no schema/insert errors.
RESOURCE_ITEM_ID_SEEDS = {
    "ingot": 0x1BF2,
    "board": 0x1BD7,
    "feather": 0x1BD1,
    "feathers": 0x1BD1,
    "cloth": 0x1766,
    "leather": 0x1081,
    "star sapphire": 0x0F0F,
    "emerald": 0x0F10,
    "sapphire": 0x0F11,
    "ruby": 0x0F13,
    "citrine": 0x0F15,
    "amethyst": 0x0F16,
    "tourmaline": 0x0F18,
    "amber": 0x0F25,
    "diamond": 0x0F26,
    "blank scroll": 0x0EF3,
    "mandrake": 0x0F86,
}


def set_diag_logger(logger):
    global _DIAG_LOGGER
    _DIAG_LOGGER = logger if callable(logger) else None


def _diag(msg):
    logger = _DIAG_LOGGER
    if logger is None:
        return
    try:
        logger(str(msg))
    except Exception:
        pass


def _base_dir():
    if BASE_DIR_OVERRIDE:
        return BASE_DIR_OVERRIDE
    try:
        return os.path.dirname(__file__)
    except Exception:
        try:
            spec = globals().get("__spec__", None)
            origin = getattr(spec, "origin", "") if spec is not None else ""
            if origin:
                return os.path.dirname(origin)
        except Exception:
            pass
        return os.getcwd()


def _normalize_abs_path(path):
    try:
        p = str(path or "").strip()
    except Exception:
        p = ""
    if not p:
        return ""
    try:
        return os.path.abspath(p)
    except Exception:
        return p


def _find_project_root(start_path):
    cur = _normalize_abs_path(start_path)
    prev = ""
    while cur and cur != prev:
        try:
            db_candidate = os.path.join(cur, DB_FOLDER, DB_FILE)
            if os.path.exists(db_candidate):
                return cur
        except Exception:
            pass
        prev = cur
        try:
            cur = os.path.dirname(cur)
        except Exception:
            break
    return ""


def set_base_dir(path):
    global BASE_DIR_OVERRIDE
    p = _normalize_abs_path(path)
    if not p:
        return
    root = _find_project_root(p)
    BASE_DIR_OVERRIDE = str(root or p)


def _db_path():
    _diag("_db_path: begin")
    roots = []
    # Prefer explicit caller override normalized to project root.
    override_root = _find_project_root(BASE_DIR_OVERRIDE) if BASE_DIR_OVERRIDE else ""
    if override_root:
        roots.append(override_root)
    # Then use module location discovery.
    module_root = _find_project_root(_normalize_abs_path(os.path.dirname(__file__)))
    if module_root:
        roots.append(module_root)

    base = _base_dir()
    base_abs = _normalize_abs_path(base)
    if base_abs:
        roots.append(base_abs)
        roots.append(os.path.dirname(base_abs))
        roots.append(os.path.dirname(os.path.dirname(base_abs)))

    seen = set()
    dedup_roots = []
    for r in roots:
        t = str(r or "").strip()
        if not t:
            continue
        k = os.path.normcase(os.path.normpath(t))
        if k in seen:
            continue
        seen.add(k)
        dedup_roots.append(t)

    for root in dedup_roots:
        p = os.path.join(root, DB_FOLDER, DB_FILE)
        _diag("_db_path: probe " + str(p))
        try:
            if os.path.exists(p):
                _diag("_db_path: selected existing " + str(p))
                return p
        except Exception:
            pass

    if dedup_roots:
        out = os.path.join(dedup_roots[0], DB_FOLDER, DB_FILE)
        _diag("_db_path: selected fallback " + str(out))
        return out
    out = os.path.join(str(base or ""), DB_FOLDER, DB_FILE)
    _diag("_db_path: selected base fallback " + str(out))
    return out


def _connect_raw(db_path):
    _diag("_connect_raw: sqlite connect begin path=" + str(db_path))
    conn = sqlite3.connect(db_path, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
    _diag("_connect_raw: sqlite connect complete")
    conn.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)) + ";")
    _diag("_connect_raw: busy_timeout set ms=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
    return conn


def _connect():
    db_path = _db_path()
    _diag("_connect: begin path=" + str(db_path))
    conn = _connect_raw(db_path)
    # Touch schema immediately so corruption/format errors surface here.
    _diag("_connect: pragma schema_version begin")
    cur = None
    try:
        cur = conn.execute("PRAGMA schema_version;")
        cur.fetchone()
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
    _diag("_connect: pragma schema_version complete")
    return conn


def _connect_read_cached():
    global _READ_CONN, _READ_CONN_PATH
    db_path = _db_path()
    cached = _READ_CONN
    if cached is not None and str(_READ_CONN_PATH or "") == str(db_path):
        try:
            cur = cached.execute("PRAGMA schema_version;")
            cur.fetchone()
            try:
                cur.close()
            except Exception:
                pass
            _diag("_connect_read_cached: reuse path=" + str(db_path))
            return cached
        except Exception:
            _READ_CONN = None
            _READ_CONN_PATH = ""
    _diag("_connect_read_cached: open path=" + str(db_path))
    conn = _connect_raw(db_path)
    try:
        conn.execute("PRAGMA query_only=ON;")
    except Exception:
        pass
    _READ_CONN = conn
    _READ_CONN_PATH = str(db_path)
    return conn


def _now_s():
    try:
        return float(time.time())
    except Exception:
        return 0.0


def try_init_store(force=False):
    global _INIT_OK, _INIT_NEXT_RETRY_AT, _INIT_LAST_ERROR
    _diag(
        "try_init_store: begin force={0} init_ok={1} next_retry_at={2}".format(
            bool(force), bool(_INIT_OK), float(_INIT_NEXT_RETRY_AT or 0.0)
        )
    )
    if _INIT_OK and not force:
        _diag("try_init_store: already initialized; skip")
        return True
    now = _now_s()
    if not force and now < float(_INIT_NEXT_RETRY_AT or 0.0):
        _diag("try_init_store: retry cooldown active")
        return False
    try:
        _diag("try_init_store: calling init_store")
        init_store()
        _INIT_OK = True
        _INIT_LAST_ERROR = ""
        _INIT_NEXT_RETRY_AT = 0.0
        _diag("try_init_store: success")
        return True
    except Exception as ex:
        _INIT_OK = False
        _INIT_LAST_ERROR = str(ex or "")
        _INIT_NEXT_RETRY_AT = now + float(INIT_RETRY_COOLDOWN_S)
        _diag("try_init_store: failed error=" + str(ex or ""))
        return False


def last_init_error():
    return str(_INIT_LAST_ERROR or "")


def _safe_json_loads(text, default):
    if not text:
        return default
    try:
        val = json.loads(text)
        return val
    except Exception:
        return default


def _safe_json_dumps(value, default):
    try:
        return json.dumps(value if value is not None else default)
    except Exception:
        return json.dumps(default)


def _fetchall(conn, query, params=()):
    cur = None
    try:
        cur = conn.execute(query, tuple(params or ()))
        return list(cur.fetchall() or [])
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass


def _as_int_list(value, limit=0):
    out = []
    for x in (value or []):
        try:
            n = int(x)
        except Exception:
            continue
        if n > 0:
            out.append(n)
            if int(limit or 0) > 0 and len(out) >= int(limit):
                break
    return out


def _as_list(value):
    return list(value) if isinstance(value, list) else []


def _as_str_list(value):
    out = []
    for x in (value or []):
        if isinstance(x, (dict, list)):
            s = _safe_json_dumps(x, {})
        else:
            s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _norm_resource_name(name):
    text = str(name or "").strip().lower()
    return " ".join(text.split())


def _canonical_profession_name(name):
    low = str(name or "").strip().lower()
    if low in ("blacksmith", "blacksmithy", "blacksmithing"):
        return "Blacksmith"
    if low in ("tailor", "tailoring"):
        return "Tailor"
    if low in ("carpentry", "carpenter"):
        return "Carpentry"
    if low in ("tinker", "tinkering"):
        return "Tinker"
    if low in ("bowcraft", "fletching", "bowcraft and fletching", "bowcraft/fletching", "bowyer"):
        return "Bowcraft"
    if low in ("alchemy", "alchemist"):
        return "Alchemy"
    if low in ("inscription", "scribe", "scribing"):
        return "Inscription"
    if low in ("cooking", "cook"):
        return "Cooking"
    return str(name or "").strip()


def _profession_lookup_candidates(name):
    raw = str(name or "").strip()
    low = raw.lower()
    out = []
    if low in ("blacksmith", "blacksmithy", "blacksmithing"):
        out.extend(["Blacksmithing", "Blacksmith", "Blacksmithy"])
    elif low in ("tailor", "tailoring"):
        out.extend(["Tailoring", "Tailor"])
    elif low in ("carpentry", "carpenter"):
        out.extend(["Carpentry", "Carpenter"])
    elif low in ("tinker", "tinkering"):
        out.extend(["Tinker", "Tinkering"])
    elif low in ("bowcraft", "fletching", "bowcraft and fletching", "bowcraft/fletching", "bowyer"):
        out.extend(["Bowcraft and Fletching", "Bowcraft", "Fletching", "Bowyer"])
    elif low in ("alchemy", "alchemist"):
        out.extend(["Alchemy", "Alchemist"])
    elif low in ("inscription", "scribe", "scribing"):
        out.extend(["Inscription", "Scribing", "Scribe"])
    elif low in ("cooking", "cook"):
        out.extend(["Cooking", "Cook"])
    if raw:
        out.append(raw)
    deduped = []
    seen = set()
    for val in out:
        t = str(val or "").strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(t)
    return deduped


def _is_valid_recipe_row(row):
    if not isinstance(row, dict):
        return False
    name = str(row.get("name", "") or "").strip()
    profession = str(row.get("profession", "") or "").strip()
    buttons = _as_int_list(row.get("buttons", []))
    return bool(name and profession and buttons)


def _table_columns(conn, table_name):
    out = set()
    cur = None
    try:
        cur = conn.execute("PRAGMA table_info(" + str(table_name) + ")")
        rows = cur.fetchall()
        for r in rows:
            try:
                out.add(str(r[1] or "").strip().lower())
            except Exception:
                pass
    except Exception:
        return set()
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
    return out


def _has_columns(conn, table_name, names):
    cols = _table_columns(conn, table_name)
    want = [str(x or "").strip().lower() for x in (names or []) if str(x or "").strip()]
    return bool(cols) and all(n in cols for n in want)


def _normalize_resource_rows(resources):
    out = []
    for r in (resources or []):
        if not isinstance(r, dict):
            continue
        mat = _norm_resource_name(r.get("material", ""))
        try:
            qty = int(r.get("per_item", 0) or 0)
        except Exception:
            qty = 0
        if mat and qty > 0:
            out.append({"material": mat, "per_item": int(qty)})
    return out


def _is_normalized_schema(conn):
    return (
        _has_columns(conn, "app_metadata", ["metadata_key", "metadata_value"])
        and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
        and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
        and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
        and _has_columns(conn, "material_options", ["material_option_id", "context_id", "material_option_key"])
        and _has_columns(conn, "craftable_items", ["craftable_item_id", "context_id", "item_key_slug"])
        and _has_columns(conn, "saved_craft_recipes", ["saved_recipe_id", "context_id", "recipe_type_code"])
    )


def _stored_schema_version(conn):
    if not _has_columns(conn, "app_metadata", ["metadata_key", "metadata_value"]):
        return 0
    cur = None
    try:
        cur = conn.execute(
            "SELECT metadata_value FROM app_metadata WHERE metadata_key='schema_version' LIMIT 1"
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass


def _schema_is_current(conn):
    if not _is_normalized_schema(conn):
        return False
    return int(_stored_schema_version(conn) or 0) == int(SCHEMA_VERSION)


def _ensure_schema_ready(conn):
    _diag("_ensure_schema_ready: check current schema/version")
    if _schema_is_current(conn):
        _diag("_ensure_schema_ready: schema current")
        return
    _diag("_ensure_schema_ready: schema not current; running _ensure_schema")
    _ensure_schema(conn)
    _diag("_ensure_schema_ready: schema ensure complete")


def _ensure_context_id(conn, server_id, profession_id):
    sid = int(server_id or 0)
    pid = int(profession_id or 0)
    if sid <= 0 or pid <= 0:
        return 0
    try:
        cur = conn.execute(
            """
            SELECT context_id
            FROM crafting_contexts
            WHERE game_server_id=? AND profession_id=?
            LIMIT 1
            """,
            (int(sid), int(pid)),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        conn.execute(
            "INSERT OR IGNORE INTO crafting_contexts(game_server_id, profession_id) VALUES (?, ?)",
            (int(sid), int(pid)),
        )
        cur = conn.execute(
            """
            SELECT context_id
            FROM crafting_contexts
            WHERE game_server_id=? AND profession_id=?
            LIMIT 1
            """,
            (int(sid), int(pid)),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _ensure_material_family_id(conn, material):
    code = _norm_resource_name(material)
    if not code:
        return 0
    try:
        cur = conn.execute(
            "SELECT material_family_id FROM material_families WHERE lower(family_code)=lower(?) LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        label = code.replace("_", " ").strip()
        if label:
            label = label[:1].upper() + label[1:]
        conn.execute(
            "INSERT INTO material_families(family_code, family_name) VALUES (?, ?)",
            (code, label or code),
        )
    except Exception:
        pass
    try:
        cur = conn.execute(
            "SELECT material_family_id FROM material_families WHERE lower(family_code)=lower(?) LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _lookup_material_option_id(conn, context_id, material_key):
    ctx = int(context_id or 0)
    mk = str(material_key or "").strip()
    if ctx <= 0 or not mk:
        return 0
    try:
        cur = conn.execute(
            """
            SELECT material_option_id
            FROM material_options
            WHERE context_id=? AND material_option_key=?
            LIMIT 1
            """,
            (int(ctx), mk),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _ensure_material_option_id(conn, context_id, material_key, material):
    ctx = int(context_id or 0)
    mk = str(material_key or "").strip()
    if ctx <= 0 or not mk:
        return 0
    mfid = int(_ensure_material_family_id(conn, material or "ingot") or 0)
    if mfid <= 0:
        return 0
    try:
        conn.execute(
            """
            INSERT INTO material_options(context_id, material_option_key, material_family_id)
            VALUES (?, ?, ?)
            ON CONFLICT(context_id, material_option_key) DO UPDATE
            SET material_family_id=excluded.material_family_id
            """,
            (int(ctx), mk, int(mfid)),
        )
    except Exception:
        pass
    return int(_lookup_material_option_id(conn, int(ctx), mk) or 0)


def _ensure_category_id(conn, context_id, category_name):
    ctx = int(context_id or 0)
    cat = str(category_name or "").strip()
    if ctx <= 0 or not cat:
        return 0
    try:
        cur = conn.execute(
            """
            SELECT category_id
            FROM craft_categories
            WHERE context_id=? AND category_name=?
            LIMIT 1
            """,
            (int(ctx), cat),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        cur = conn.execute(
            """
            SELECT coalesce(MAX(display_sequence), 0) + 1
            FROM craft_categories
            WHERE context_id=?
            """,
            (int(ctx),),
        )
        row = cur.fetchone()
        disp = int((row[0] if row else 1) or 1)
        conn.execute(
            """
            INSERT INTO craft_categories(context_id, category_name, display_sequence, category_navigation_button_id)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(context_id, category_name) DO NOTHING
            """,
            (int(ctx), cat, int(disp)),
        )
    except Exception:
        pass
    try:
        cur = conn.execute(
            """
            SELECT category_id
            FROM craft_categories
            WHERE context_id=? AND category_name=?
            LIMIT 1
            """,
            (int(ctx), cat),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _lookup_craftable_item_id(conn, context_id, item_key):
    ctx = int(context_id or 0)
    ik = str(item_key or "").strip()
    if ctx <= 0 or not ik:
        return 0
    try:
        cur = conn.execute(
            """
            SELECT craftable_item_id
            FROM craftable_items
            WHERE context_id=? AND item_key_slug=?
            LIMIT 1
            """,
            (int(ctx), ik),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _upsert_craftable_item(conn, context_id, item_key, name, item_id=0, category="", default_material_key=""):
    ctx = int(context_id or 0)
    ik = str(item_key or "").strip()
    nm = str(name or "").strip() or ik
    if ctx <= 0 or not ik:
        return 0
    cat_id = int(_ensure_category_id(conn, int(ctx), category) or 0) if str(category or "").strip() else None
    mo_id = (
        int(_lookup_material_option_id(conn, int(ctx), str(default_material_key or "").strip()) or 0)
        if str(default_material_key or "").strip()
        else 0
    )
    try:
        conn.execute(
            """
            INSERT INTO craftable_items(context_id, item_key_slug, item_display_name, game_item_id, category_id, default_material_option_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(context_id, item_key_slug) DO UPDATE SET
                item_display_name=excluded.item_display_name,
                game_item_id=excluded.game_item_id,
                category_id=excluded.category_id,
                default_material_option_id=excluded.default_material_option_id
            """,
            (
                int(ctx),
                ik,
                nm,
                None if int(item_id or 0) <= 0 else int(item_id),
                cat_id,
                None if mo_id <= 0 else int(mo_id),
            ),
        )
    except Exception:
        pass
    return int(_lookup_craftable_item_id(conn, int(ctx), ik) or 0)


def _parse_recipe_material_text(raw_material):
    text = str(raw_material or "").strip()
    out = {
        "material_name": _norm_resource_name(text),
        "item_id": 0,
        "min_in_pack": 0,
        "pull_amount": 0,
        "hue": None,
    }
    if not text:
        return out
    payload = None
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        out["material_name"] = _norm_resource_name(payload.get("material", "") or out["material_name"])
        try:
            out["item_id"] = int(payload.get("item_id", 0) or 0)
        except Exception:
            out["item_id"] = 0
        try:
            out["min_in_pack"] = int(payload.get("min_in_pack", 0) or 0)
        except Exception:
            out["min_in_pack"] = 0
        try:
            out["pull_amount"] = int(payload.get("pull_amount", 0) or 0)
        except Exception:
            out["pull_amount"] = 0
        hue = payload.get("hue", None)
        try:
            out["hue"] = int(hue) if hue is not None else None
        except Exception:
            out["hue"] = None
    return out


def _ensure_resource_name(conn, name):
    nm = str(name or "").strip()
    if not nm:
        return 0
    try:
        cur = conn.execute(
            "SELECT resource_id FROM resource_catalog WHERE lower(resource_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        conn.execute("INSERT INTO resource_catalog(resource_name) VALUES (?)", (nm,))
    except Exception:
        pass
    try:
        cur = conn.execute(
            "SELECT resource_id FROM resource_catalog WHERE lower(resource_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _ensure_server_id(conn, server_name):
    nm = str(server_name or "").strip()
    if not nm:
        return 0
    try:
        cur = conn.execute(
            "SELECT game_server_id FROM game_servers WHERE lower(server_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        conn.execute("INSERT INTO game_servers(server_name) VALUES (?)", (nm,))
    except Exception:
        pass
    try:
        cur = conn.execute(
            "SELECT game_server_id FROM game_servers WHERE lower(server_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _lookup_server_id(conn, server_name):
    nm = str(server_name or "").strip()
    if not nm:
        return 0
    try:
        cur = conn.execute(
            "SELECT game_server_id FROM game_servers WHERE lower(server_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _ensure_profession_id(conn, profession_name):
    nm = str(profession_name or "").strip()
    if not nm:
        return 0
    for cand in _profession_lookup_candidates(nm):
        try:
            cur = conn.execute(
                "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
                (cand,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0] or 0)
        except Exception:
            pass
    try:
        conn.execute("INSERT INTO crafting_professions(profession_name) VALUES (?)", (str(nm),))
    except Exception:
        pass
    for cand in _profession_lookup_candidates(nm):
        try:
            cur = conn.execute(
                "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
                (cand,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0] or 0)
        except Exception:
            pass
    try:
        cur = conn.execute(
            "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _lookup_profession_id(conn, profession_name):
    nm = str(profession_name or "").strip()
    if not nm:
        return 0
    for cand in _profession_lookup_candidates(nm):
        try:
            cur = conn.execute(
                "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
                (cand,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0] or 0)
        except Exception:
            pass
    try:
        cur = conn.execute(
            "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
            (nm,),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _write_item_resource_costs(conn, server, profession, item_key, resources):
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    ik = str(item_key or "")
    if srv_id <= 0 or prof_id <= 0 or not ik:
        return
    ctx_id = int(_ensure_context_id(conn, int(srv_id), int(prof_id)) or 0)
    if ctx_id <= 0:
        return
    ci_id = int(_lookup_craftable_item_id(conn, int(ctx_id), ik) or 0)
    if ci_id <= 0:
        ci_id = int(_upsert_craftable_item(conn, int(ctx_id), ik, ik, 0, "", "") or 0)
    if ci_id <= 0:
        return
    rows = _normalize_resource_rows(resources)
    conn.execute(
        "DELETE FROM craftable_item_resource_requirements WHERE craftable_item_id=?",
        (int(ci_id),),
    )
    slot = 0
    for rr in rows:
        slot += 1
        rid = _ensure_resource_name(conn, rr.get("material", ""))
        if int(rid) <= 0:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO craftable_item_resource_requirements
            (craftable_item_id, requirement_sequence, resource_id, quantity_per_item)
            VALUES (?, ?, ?, ?)
            """,
            (int(ci_id), int(slot), int(rid), int(rr.get("per_item", 0) or 0)),
        )


def _seed_resource_item_ids(conn):
    if not _has_columns(conn, "resource_catalog", ["resource_name", "game_item_id"]):
        return
    for name, item_id in (RESOURCE_ITEM_ID_SEEDS or {}).items():
        nm = _norm_resource_name(name)
        iid = int(item_id or 0)
        if not nm or iid <= 0:
            continue
        try:
            conn.execute(
                """
                UPDATE resource_catalog
                SET game_item_id=?
                WHERE lower(resource_name)=lower(?) AND coalesce(game_item_id, 0) <= 0
                """,
                (iid, nm),
            )
        except Exception:
            pass


def _write_recipe_child_lists(conn, recipe_id, buttons, materials, material_buttons):
    rid = int(recipe_id or 0)
    if rid <= 0:
        return
    conn.execute("DELETE FROM saved_recipe_navigation_steps WHERE saved_recipe_id=?", (rid,))
    conn.execute("DELETE FROM saved_recipe_material_requirements WHERE saved_recipe_id=?", (rid,))
    conn.execute("DELETE FROM saved_recipe_material_navigation_steps WHERE saved_recipe_id=?", (rid,))

    slot = 0
    for btn in _as_int_list(buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO saved_recipe_navigation_steps(saved_recipe_id, step_number, gump_button_id)
            VALUES (?, ?, ?)
            """,
            (rid, int(slot), int(btn)),
        )

    slot = 0
    for raw_mat in _as_str_list(materials):
        slot += 1
        parsed = _parse_recipe_material_text(raw_mat)
        material_name = _norm_resource_name(parsed.get("material_name", "") or "")
        rid_res = int(_ensure_resource_name(conn, material_name) or 0) if material_name else 0
        conn.execute(
            """
            INSERT OR REPLACE INTO saved_recipe_material_requirements
            (saved_recipe_id, requirement_sequence, material_name, resource_id, required_in_pack_quantity,
             pull_quantity, game_item_id_override, hue_override)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                int(slot),
                material_name,
                (int(rid_res) if int(rid_res) > 0 else None),
                int(parsed.get("min_in_pack", 0) or 0),
                int(parsed.get("pull_amount", 0) or 0),
                (int(parsed.get("item_id", 0) or 0) if int(parsed.get("item_id", 0) or 0) > 0 else None),
                parsed.get("hue", None),
            ),
        )

    slot = 0
    for btn in _as_int_list(material_buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO saved_recipe_material_navigation_steps(saved_recipe_id, step_number, gump_button_id)
            VALUES (?, ?, ?)
            """,
            (rid, int(slot), int(btn)),
        )


def _load_recipe_child_lists(conn):
    out = {}
    rows = _fetchall(
        conn,
        """
        SELECT saved_recipe_id, step_number, gump_button_id
        FROM saved_recipe_navigation_steps
        ORDER BY saved_recipe_id, step_number
        """,
    )
    for row in rows:
        rid = int(row[0] or 0)
        if rid <= 0:
            continue
        if rid not in out:
            out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
        out[rid]["buttons"].append(int(row[2] or 0))

    rows = _fetchall(
        conn,
        """
        SELECT saved_recipe_id, requirement_sequence, material_name, required_in_pack_quantity,
               pull_quantity, game_item_id_override, hue_override
        FROM saved_recipe_material_requirements
        ORDER BY saved_recipe_id, requirement_sequence
        """,
    )
    for row in rows:
        rid = int(row[0] or 0)
        if rid <= 0:
            continue
        if rid not in out:
            out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
        material_name = _norm_resource_name(row[2])
        payload = {
            "material": material_name,
            "min_in_pack": int(row[3] or 0),
            "pull_amount": int(row[4] or 0),
        }
        try:
            iid = int(row[5] or 0)
        except Exception:
            iid = 0
        if iid > 0:
            payload["item_id"] = int(iid)
        hue_val = row[6]
        if hue_val is not None:
            try:
                payload["hue"] = int(hue_val)
            except Exception:
                pass
        out[rid]["materials"].append(_safe_json_dumps(payload, {}))

    rows = _fetchall(
        conn,
        """
        SELECT saved_recipe_id, step_number, gump_button_id
        FROM saved_recipe_material_navigation_steps
        ORDER BY saved_recipe_id, step_number
        """,
    )
    for row in rows:
        rid = int(row[0] or 0)
        if rid <= 0:
            continue
        if rid not in out:
            out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
        out[rid]["material_buttons"].append(int(row[2] or 0))
    return out


def _write_material_key_buttons(conn, server, profession, material_key, material_buttons):
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    mk = str(material_key or "")
    if srv_id <= 0 or prof_id <= 0 or not mk:
        return
    ctx_id = int(_ensure_context_id(conn, int(srv_id), int(prof_id)) or 0)
    if ctx_id <= 0:
        return
    mo_id = int(_lookup_material_option_id(conn, int(ctx_id), mk) or 0)
    if mo_id <= 0:
        mo_id = int(_ensure_material_option_id(conn, int(ctx_id), mk, "ingot") or 0)
    if mo_id <= 0:
        return
    conn.execute("DELETE FROM material_option_navigation_steps WHERE material_option_id=?", (int(mo_id),))
    slot = 0
    for btn in _as_int_list(material_buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO material_option_navigation_steps
            (material_option_id, step_number, gump_button_id)
            VALUES (?, ?, ?)
            """,
            (int(mo_id), int(slot), int(btn)),
        )


def _write_item_key_buttons(conn, server, profession, item_key, buttons):
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    ik = str(item_key or "")
    if srv_id <= 0 or prof_id <= 0 or not ik:
        return
    ctx_id = int(_ensure_context_id(conn, int(srv_id), int(prof_id)) or 0)
    if ctx_id <= 0:
        return
    ci_id = int(_lookup_craftable_item_id(conn, int(ctx_id), ik) or 0)
    if ci_id <= 0:
        ci_id = int(_upsert_craftable_item(conn, int(ctx_id), ik, ik, 0, "", "") or 0)
    if ci_id <= 0:
        return
    conn.execute("DELETE FROM craftable_item_navigation_steps WHERE craftable_item_id=?", (int(ci_id),))
    slot = 0
    for btn in _as_int_list(buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO craftable_item_navigation_steps
            (craftable_item_id, step_number, gump_button_id)
            VALUES (?, ?, ?)
            """,
            (int(ci_id), int(slot), int(btn)),
        )


def _ensure_schema(conn):
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_metadata (
          metadata_key TEXT PRIMARY KEY,
          metadata_value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS game_servers (
          game_server_id INTEGER PRIMARY KEY,
          server_name TEXT NOT NULL UNIQUE COLLATE NOCASE
        );

        CREATE TABLE IF NOT EXISTS crafting_professions (
          profession_id INTEGER PRIMARY KEY,
          profession_name TEXT NOT NULL UNIQUE COLLATE NOCASE
        );

        CREATE TABLE IF NOT EXISTS crafting_contexts (
          context_id INTEGER PRIMARY KEY,
          game_server_id INTEGER NOT NULL,
          profession_id INTEGER NOT NULL,
          UNIQUE (game_server_id, profession_id),
          FOREIGN KEY (game_server_id) REFERENCES game_servers(game_server_id),
          FOREIGN KEY (profession_id) REFERENCES crafting_professions(profession_id)
        );

        CREATE TABLE IF NOT EXISTS material_families (
          material_family_id INTEGER PRIMARY KEY,
          family_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
          family_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS material_options (
          material_option_id INTEGER PRIMARY KEY,
          context_id INTEGER NOT NULL,
          material_option_key TEXT NOT NULL,
          material_family_id INTEGER NOT NULL,
          UNIQUE (context_id, material_option_key),
          FOREIGN KEY (context_id) REFERENCES crafting_contexts(context_id) ON DELETE CASCADE,
          FOREIGN KEY (material_family_id) REFERENCES material_families(material_family_id)
        );
        CREATE INDEX IF NOT EXISTS idx_material_options_context
            ON material_options(context_id);

        CREATE TABLE IF NOT EXISTS material_option_navigation_steps (
          material_option_id INTEGER NOT NULL,
          step_number INTEGER NOT NULL,
          gump_button_id INTEGER NOT NULL,
          PRIMARY KEY (material_option_id, step_number),
          FOREIGN KEY (material_option_id) REFERENCES material_options(material_option_id) ON DELETE CASCADE,
          CHECK (step_number > 0),
          CHECK (gump_button_id > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_material_option_steps_lookup
            ON material_option_navigation_steps(material_option_id, step_number);

        CREATE TABLE IF NOT EXISTS craft_categories (
          category_id INTEGER PRIMARY KEY,
          context_id INTEGER NOT NULL,
          category_name TEXT NOT NULL,
          display_sequence INTEGER NOT NULL,
          category_navigation_button_id INTEGER,
          UNIQUE (context_id, category_name),
          UNIQUE (context_id, display_sequence),
          FOREIGN KEY (context_id) REFERENCES crafting_contexts(context_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_craft_categories_context
            ON craft_categories(context_id, display_sequence);

        CREATE TABLE IF NOT EXISTS craftable_items (
          craftable_item_id INTEGER PRIMARY KEY,
          context_id INTEGER NOT NULL,
          item_key_slug TEXT NOT NULL,
          item_display_name TEXT NOT NULL,
          game_item_id INTEGER,
          category_id INTEGER,
          default_material_option_id INTEGER,
          UNIQUE (context_id, item_key_slug),
          FOREIGN KEY (context_id) REFERENCES crafting_contexts(context_id) ON DELETE CASCADE,
          FOREIGN KEY (category_id) REFERENCES craft_categories(category_id),
          FOREIGN KEY (default_material_option_id) REFERENCES material_options(material_option_id)
        );
        CREATE INDEX IF NOT EXISTS idx_craftable_items_context_name
            ON craftable_items(context_id, item_display_name);

        CREATE TABLE IF NOT EXISTS craftable_item_navigation_steps (
          craftable_item_id INTEGER NOT NULL,
          step_number INTEGER NOT NULL,
          gump_button_id INTEGER NOT NULL,
          PRIMARY KEY (craftable_item_id, step_number),
          FOREIGN KEY (craftable_item_id) REFERENCES craftable_items(craftable_item_id) ON DELETE CASCADE,
          CHECK (step_number > 0),
          CHECK (gump_button_id > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_craftable_item_steps_lookup
            ON craftable_item_navigation_steps(craftable_item_id, step_number);

        CREATE TABLE IF NOT EXISTS resource_catalog (
          resource_id INTEGER PRIMARY KEY,
          resource_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
          game_item_id INTEGER,
          game_item_hue INTEGER
        );

        CREATE TABLE IF NOT EXISTS craftable_item_resource_requirements (
          craftable_item_id INTEGER NOT NULL,
          requirement_sequence INTEGER NOT NULL,
          resource_id INTEGER NOT NULL,
          quantity_per_item INTEGER NOT NULL,
          PRIMARY KEY (craftable_item_id, requirement_sequence),
          UNIQUE (craftable_item_id, resource_id),
          FOREIGN KEY (craftable_item_id) REFERENCES craftable_items(craftable_item_id) ON DELETE CASCADE,
          FOREIGN KEY (resource_id) REFERENCES resource_catalog(resource_id),
          CHECK (requirement_sequence > 0),
          CHECK (quantity_per_item > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_craftable_item_resources_lookup
            ON craftable_item_resource_requirements(craftable_item_id, requirement_sequence);

        CREATE TABLE IF NOT EXISTS recipe_types (
          recipe_type_code TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS saved_craft_recipes (
          saved_recipe_id INTEGER PRIMARY KEY,
          context_id INTEGER NOT NULL,
          recipe_type_code TEXT NOT NULL,
          craftable_item_id INTEGER,
          recipe_name TEXT NOT NULL,
          selected_material_option_id INTEGER,
          declared_material_family_id INTEGER,
          deed_signature_text TEXT,
          game_item_id INTEGER,
          min_skill REAL,
          max_skill REAL,
          FOREIGN KEY (context_id) REFERENCES crafting_contexts(context_id) ON DELETE CASCADE,
          FOREIGN KEY (recipe_type_code) REFERENCES recipe_types(recipe_type_code),
          FOREIGN KEY (craftable_item_id) REFERENCES craftable_items(craftable_item_id),
          FOREIGN KEY (selected_material_option_id) REFERENCES material_options(material_option_id),
          FOREIGN KEY (declared_material_family_id) REFERENCES material_families(material_family_id)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_recipes_lookup
            ON saved_craft_recipes(context_id, recipe_type_code, recipe_name);

        CREATE TABLE IF NOT EXISTS saved_recipe_navigation_steps (
          saved_recipe_id INTEGER NOT NULL,
          step_number INTEGER NOT NULL,
          gump_button_id INTEGER NOT NULL,
          PRIMARY KEY (saved_recipe_id, step_number),
          FOREIGN KEY (saved_recipe_id) REFERENCES saved_craft_recipes(saved_recipe_id) ON DELETE CASCADE,
          CHECK (step_number > 0),
          CHECK (gump_button_id > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_recipe_steps_lookup
            ON saved_recipe_navigation_steps(saved_recipe_id, step_number);

        CREATE TABLE IF NOT EXISTS saved_recipe_material_requirements (
          saved_recipe_id INTEGER NOT NULL,
          requirement_sequence INTEGER NOT NULL,
          material_name TEXT NOT NULL,
          resource_id INTEGER,
          required_in_pack_quantity INTEGER NOT NULL DEFAULT 0,
          pull_quantity INTEGER NOT NULL DEFAULT 0,
          game_item_id_override INTEGER,
          hue_override INTEGER,
          PRIMARY KEY (saved_recipe_id, requirement_sequence),
          FOREIGN KEY (saved_recipe_id) REFERENCES saved_craft_recipes(saved_recipe_id) ON DELETE CASCADE,
          FOREIGN KEY (resource_id) REFERENCES resource_catalog(resource_id),
          CHECK (requirement_sequence > 0)
        );

        CREATE TABLE IF NOT EXISTS saved_recipe_material_navigation_steps (
          saved_recipe_id INTEGER NOT NULL,
          step_number INTEGER NOT NULL,
          gump_button_id INTEGER NOT NULL,
          PRIMARY KEY (saved_recipe_id, step_number),
          FOREIGN KEY (saved_recipe_id) REFERENCES saved_craft_recipes(saved_recipe_id) ON DELETE CASCADE,
          CHECK (step_number > 0),
          CHECK (gump_button_id > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_recipe_material_steps_lookup
            ON saved_recipe_material_navigation_steps(saved_recipe_id, step_number);
        """
    )
    if not _is_normalized_schema(conn):
        raise sqlite3.DatabaseError("normalized craftables schema required")
    _seed_resource_item_ids(conn)
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(metadata_key, metadata_value) VALUES (?, ?)",
        ("schema_version", str(int(SCHEMA_VERSION))),
    )
    conn.commit()


def init_store():
    _diag("init_store: begin")
    conn = _connect()
    try:
        _ensure_schema_ready(conn)
    finally:
        _diag("init_store: connection close begin")
        conn.close()
        _diag("init_store: connection close complete")
        _diag("init_store: complete")


def load_recipes():
    _diag("load_recipes: begin")
    conn = _connect_read_cached()
    try:
        _ensure_schema_ready(conn)
        _diag("load_recipes: schema ready")
        child = _load_recipe_child_lists(conn)
        _diag("load_recipes: child lists loaded")
        out = []
        rows = _fetchall(
            conn,
            """
            SELECT sr.saved_recipe_id, sr.recipe_type_code, gs.server_name, cp.profession_name,
                   sr.recipe_name, sr.game_item_id, mf.family_code, mo.material_option_key,
                   sr.deed_signature_text, sr.min_skill, sr.max_skill
            FROM saved_craft_recipes sr
            JOIN crafting_contexts cc ON cc.context_id = sr.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
            LEFT JOIN material_options mo ON mo.material_option_id = sr.selected_material_option_id
            LEFT JOIN material_families mf ON mf.material_family_id = coalesce(
                sr.declared_material_family_id,
                mo.material_family_id
            )
            ORDER BY sr.saved_recipe_id
            """,
        )
        _diag("load_recipes: rows fetched count=" + str(len(rows)))
        for row in rows:
            rid = int(row[0] or 0)
            ch = child.get(rid, {})
            material = str(row[6] or "").strip()
            mat_key = str(row[7] or "").strip()
            if not mat_key and material:
                mat_key = str(material).lower()
            out.append(
                {
                    "recipe_type": str(row[1] or ""),
                    "server": str(row[2] or ""),
                    "profession": str(row[3] or ""),
                    "name": str(row[4] or ""),
                    "item_id": int(row[5] or 0),
                    "buttons": list(ch.get("buttons") or []),
                    "material": material,
                    "material_key": mat_key,
                    "materials": list(ch.get("materials") or []),
                    "material_buttons": list(ch.get("material_buttons") or []),
                    "deed_key": str(row[8] or ""),
                    "start_at": row[9],
                    "stop_at": row[10],
                }
            )
        return out
    except Exception:
        raise


def save_recipes(rows):
    conn = _connect()
    try:
        _ensure_schema_ready(conn)
        with conn:
            conn.execute("DELETE FROM saved_recipe_navigation_steps")
            conn.execute("DELETE FROM saved_recipe_material_requirements")
            conn.execute("DELETE FROM saved_recipe_material_navigation_steps")
            conn.execute("DELETE FROM saved_craft_recipes")
            for row in (rows or []):
                if not _is_valid_recipe_row(row):
                    continue
                sid = int(_ensure_server_id(conn, row.get("server", "")) or 0)
                pid = int(_ensure_profession_id(conn, row.get("profession", "")) or 0)
                if sid <= 0 or pid <= 0:
                    continue
                recipe_type = str(row.get("recipe_type", "") or "").strip().lower() or "bod"
                recipe_name = str(row.get("name", "") or "")
                material = str(row.get("material", "") or "")
                material_key = str(row.get("material_key", "") or "")
                rid = 0
                ctx_id = int(_ensure_context_id(conn, int(sid), int(pid)) or 0)
                if ctx_id <= 0:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO recipe_types(recipe_type_code) VALUES (?)",
                    (recipe_type,),
                )
                mfid = int(_ensure_material_family_id(conn, material or "ingot") or 0) if material else 0
                mo_id = int(_lookup_material_option_id(conn, int(ctx_id), material_key) or 0)
                if mo_id <= 0 and material_key:
                    mo_id = int(_ensure_material_option_id(conn, int(ctx_id), material_key, material or "ingot") or 0)
                ci_id = 0
                try:
                    cur_item = conn.execute(
                        """
                        SELECT craftable_item_id
                        FROM craftable_items
                        WHERE context_id=? AND lower(item_display_name)=lower(?)
                        LIMIT 1
                        """,
                        (int(ctx_id), recipe_name),
                    )
                    row_item = cur_item.fetchone()
                    ci_id = int(row_item[0] or 0) if row_item else 0
                except Exception:
                    ci_id = 0
                cur = conn.execute(
                    """
                    INSERT INTO saved_craft_recipes
                    (context_id, recipe_type_code, craftable_item_id, recipe_name, selected_material_option_id,
                     declared_material_family_id, deed_signature_text, game_item_id, min_skill, max_skill)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(ctx_id),
                        recipe_type,
                        (int(ci_id) if int(ci_id) > 0 else None),
                        recipe_name,
                        (int(mo_id) if int(mo_id) > 0 else None),
                        (int(mfid) if int(mfid) > 0 else None),
                        (str(row.get("deed_key", "") or "").strip() or None),
                        (int(row.get("item_id", 0) or 0) if int(row.get("item_id", 0) or 0) > 0 else None),
                        row.get("start_at", None),
                        row.get("stop_at", None),
                    ),
                )
                rid = int(getattr(cur, "lastrowid", 0) or 0)
                if rid <= 0:
                    try:
                        cur2 = conn.execute(
                            """
                            SELECT saved_recipe_id
                            FROM saved_craft_recipes
                            WHERE context_id=? AND recipe_type_code=? AND lower(recipe_name)=lower(?)
                              AND coalesce(selected_material_option_id,0)=?
                            ORDER BY saved_recipe_id DESC
                            LIMIT 1
                            """,
                            (int(ctx_id), recipe_type, recipe_name, int(mo_id or 0)),
                        )
                        row2 = cur2.fetchone()
                        rid = int(row2[0] or 0) if row2 else 0
                    except Exception:
                        rid = 0
                _write_recipe_child_lists(
                    conn,
                    int(rid or 0),
                    row.get("buttons", []),
                    row.get("materials", []),
                    row.get("material_buttons", []),
                )
        return True
    finally:
        conn.close()


def load_key_maps():
    _diag("load_key_maps: begin")
    conn = _connect_read_cached()
    try:
        _ensure_schema_ready(conn)
        _diag("load_key_maps: schema ready")
        out = {}
        material_buttons = {}
        rows = _fetchall(
            conn,
            """
            SELECT gs.server_name, cp.profession_name, mo.material_option_key, mons.step_number, mons.gump_button_id
            FROM material_option_navigation_steps mons
            JOIN material_options mo ON mo.material_option_id = mons.material_option_id
            JOIN crafting_contexts cc ON cc.context_id = mo.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
            ORDER BY gs.server_name, cp.profession_name, mo.material_option_key, mons.step_number
            """,
        )
        for row in rows:
            server = str(row[0] or "")
            profession = _canonical_profession_name(row[1])
            material_key = str(row[2] or "")
            if not (server and profession and material_key):
                continue
            try:
                bid = int(row[4] or 0)
            except Exception:
                bid = 0
            if bid <= 0:
                continue
            key = (server, profession, material_key)
            arr = material_buttons.get(key)
            if arr is None:
                arr = []
                material_buttons[key] = arr
            arr.append(int(bid))

        rows = _fetchall(
            conn,
            """
            SELECT gs.server_name, cp.profession_name, mo.material_option_key, mf.family_code
            FROM material_options mo
            JOIN crafting_contexts cc ON cc.context_id = mo.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
            LEFT JOIN material_families mf ON mf.material_family_id = mo.material_family_id
            ORDER BY gs.server_name, cp.profession_name, mo.material_option_key
            """,
        )
        for row in rows:
            server = str(row[0] or "")
            profession = _canonical_profession_name(row[1])
            material_key = str(row[2] or "")
            material = _norm_resource_name(row[3])
            if not material and material_key:
                material = _norm_resource_name(str(material_key).split("_")[0])
            if not material:
                material = "ingot"
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            mk_btns = list(material_buttons.get((server, profession, material_key), []) or [])
            out[server][profession]["material_keys"][material_key] = {
                "material": material,
                "material_buttons": [int(x) for x in mk_btns if int(x) > 0][:2],
            }

        item_steps = {}
        rows = _fetchall(
            conn,
            """
            SELECT craftable_item_id, step_number, gump_button_id
            FROM craftable_item_navigation_steps
            ORDER BY craftable_item_id, step_number
            """,
        )
        for row in rows:
            try:
                item_id = int(row[0] or 0)
                bid = int(row[2] or 0)
            except Exception:
                item_id = 0
                bid = 0
            if item_id <= 0 or bid <= 0:
                continue
            arr = item_steps.get(item_id)
            if arr is None:
                arr = []
                item_steps[item_id] = arr
            arr.append(int(bid))

        item_resources = {}
        rows = _fetchall(
            conn,
            """
            SELECT cir.craftable_item_id, cir.requirement_sequence, rc.resource_name, cir.quantity_per_item
            FROM craftable_item_resource_requirements cir
            JOIN resource_catalog rc ON rc.resource_id = cir.resource_id
            ORDER BY cir.craftable_item_id, cir.requirement_sequence
            """,
        )
        for row in rows:
            try:
                item_id = int(row[0] or 0)
                qty = int(row[3] or 0)
            except Exception:
                item_id = 0
                qty = 0
            mat = _norm_resource_name(row[2])
            if item_id <= 0 or not mat or qty <= 0:
                continue
            arr = item_resources.get(item_id)
            if arr is None:
                arr = []
                item_resources[item_id] = arr
            arr.append({"material": mat, "per_item": int(qty)})

        rows = _fetchall(
            conn,
            """
            SELECT ci.craftable_item_id, gs.server_name, cp.profession_name, ci.item_key_slug, ci.item_display_name,
                   ci.game_item_id, coalesce(mo.material_option_key, ''), coalesce(cat.category_name, ''),
                   coalesce(cat.category_navigation_button_id, 0)
            FROM craftable_items ci
            JOIN crafting_contexts cc ON cc.context_id = ci.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
            LEFT JOIN material_options mo ON mo.material_option_id = ci.default_material_option_id
            LEFT JOIN craft_categories cat ON cat.category_id = ci.category_id
            ORDER BY gs.server_name, cp.profession_name, ci.item_display_name
            """,
        )
        for row in rows:
            try:
                craftable_item_id = int(row[0] or 0)
            except Exception:
                craftable_item_id = 0
            server = str(row[1] or "")
            profession = _canonical_profession_name(row[2])
            item_key = str(row[3] or "")
            name = str(row[4] or "")
            try:
                game_item_id = int(row[5] or 0)
            except Exception:
                game_item_id = 0
            default_material_key = str(row[6] or "")
            category = str(row[7] or "")
            try:
                category_button = int(row[8] or 0)
            except Exception:
                category_button = 0
            if not item_key:
                item_key = _norm_resource_name(name).replace(" ", "_")
            if not (server and profession and item_key):
                continue
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            buttons = []
            if category_button > 0:
                buttons.append(int(category_button))
            for b in list(item_steps.get(craftable_item_id, []) or []):
                try:
                    ib = int(b)
                except Exception:
                    ib = 0
                if ib > 0:
                    buttons.append(int(ib))
            out[server][profession]["item_keys"][item_key] = {
                "name": name,
                "item_id": int(game_item_id or 0),
                "buttons": [int(x) for x in buttons if int(x) > 0][:2],
                "default_material_key": default_material_key,
                "category": category,
                "resources": list(item_resources.get(craftable_item_id, []) or []),
            }

        return out
    except Exception:
        raise


def load_resource_item_map():
    _diag("load_resource_item_map: begin")
    conn = _connect_read_cached()
    try:
        _ensure_schema_ready(conn)
        _diag("load_resource_item_map: schema ready")
        out = {}
        rows = _fetchall(
            conn,
            """
            SELECT resource_id, resource_name, coalesce(game_item_id, 0), game_item_hue
            FROM resource_catalog
            """,
        )
        for row in rows:
            name = _norm_resource_name(row[1])
            if not name:
                continue
            try:
                iid = int(row[2] or 0)
            except Exception:
                iid = 0
            hue = row[3]
            if hue is not None:
                try:
                    hue = int(hue)
                except Exception:
                    hue = None
            out[name] = {
                "resource_id": int(row[0] or 0),
                "item_id": int(iid),
                "hue": hue,
            }
        return out
    except Exception:
        raise


def save_key_maps(key_maps):
    conn = _connect()
    try:
        _ensure_schema_ready(conn)
        with conn:
            conn.execute("DROP TABLE IF EXISTS temp._recipe_link_cache")
            conn.execute(
                """
                CREATE TEMP TABLE _recipe_link_cache (
                    saved_recipe_id INTEGER PRIMARY KEY,
                    context_id INTEGER NOT NULL,
                    material_key TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO _recipe_link_cache(saved_recipe_id, context_id, material_key)
                SELECT sr.saved_recipe_id, sr.context_id, coalesce(mo.material_option_key, '')
                FROM saved_craft_recipes sr
                LEFT JOIN material_options mo ON mo.material_option_id = sr.selected_material_option_id
                """
            )
            conn.execute("UPDATE saved_craft_recipes SET selected_material_option_id=NULL, craftable_item_id=NULL")

            conn.execute("DELETE FROM craftable_item_resource_requirements")
            conn.execute("DELETE FROM craftable_item_navigation_steps")
            conn.execute("DELETE FROM craftable_items")
            conn.execute("DELETE FROM material_option_navigation_steps")
            conn.execute("DELETE FROM material_options")
            conn.execute("DELETE FROM craft_categories")

            km = dict(key_maps or {}) if isinstance(key_maps, dict) else {}
            for server, srv_node in km.items():
                if not isinstance(srv_node, dict):
                    continue
                for profession, prof_node in srv_node.items():
                    if not isinstance(prof_node, dict):
                        continue
                    sid = int(_ensure_server_id(conn, server) or 0)
                    pid = int(_ensure_profession_id(conn, profession) or 0)
                    if sid <= 0 or pid <= 0:
                        continue
                    ctx_id = int(_ensure_context_id(conn, int(sid), int(pid)) or 0)
                    if ctx_id <= 0:
                        continue

                    mats = prof_node.get("material_keys", {})
                    if isinstance(mats, dict):
                        for mk, ent in mats.items():
                            if not isinstance(ent, dict):
                                ent = {}
                            mk_text = str(mk or "").strip()
                            if not mk_text:
                                continue
                            material_code = str(ent.get("material", "") or "").strip().lower()
                            if not material_code and mk_text:
                                material_code = str(mk_text.split("_")[0] or "").strip().lower()
                            if not material_code:
                                material_code = "ingot"
                            _ensure_material_option_id(conn, int(ctx_id), mk_text, material_code)
                            _write_material_key_buttons(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                mk_text,
                                _as_int_list(ent.get("material_buttons", []), 2),
                            )
                    items = prof_node.get("item_keys", {})
                    if isinstance(items, dict):
                        for ik, ent in items.items():
                            if not isinstance(ent, dict):
                                ent = {}
                            ik_text = str(ik or "").strip()
                            if not ik_text:
                                continue
                            _upsert_craftable_item(
                                conn,
                                int(ctx_id),
                                ik_text,
                                str(ent.get("name", "") or ik_text),
                                int(ent.get("item_id", 0) or 0),
                                str(ent.get("category", "") or ""),
                                str(ent.get("default_material_key", "") or ""),
                            )
                            _write_item_key_buttons(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                ik_text,
                                _as_int_list(ent.get("buttons", []), 2),
                            )
                            _write_item_resource_costs(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                ik_text,
                                _as_list(ent.get("resources", [])),
                            )

            conn.execute(
                """
                UPDATE saved_craft_recipes
                SET selected_material_option_id = (
                        SELECT mo.material_option_id
                        FROM _recipe_link_cache c
                        JOIN material_options mo
                          ON mo.context_id = saved_craft_recipes.context_id
                         AND mo.material_option_key = c.material_key
                        WHERE c.saved_recipe_id = saved_craft_recipes.saved_recipe_id
                        LIMIT 1
                    ),
                    craftable_item_id = (
                        SELECT ci.craftable_item_id
                        FROM craftable_items ci
                        WHERE ci.context_id = saved_craft_recipes.context_id
                          AND lower(ci.item_display_name) = lower(saved_craft_recipes.recipe_name)
                        LIMIT 1
                    )
                """
            )
            conn.execute("DROP TABLE IF EXISTS temp._recipe_link_cache")
        return True
    finally:
        conn.close()


def health_summary(selected_server=None):
    conn = _connect()
    try:
        _ensure_schema_ready(conn)
        out = {
            "schema_version": 0,
            "db_path": _db_path(),
            "recipes_total": 0,
            "recipes_by_type": {},
            "recipes_by_server": {},
            "servers_count": 0,
            "profession_nodes": 0,
            "material_keys_total": 0,
            "item_keys_total": 0,
            "item_categories_total": 0,
            "resources_total": 0,
            "resources_with_item_id": 0,
            "item_resource_costs_total": 0,
            "selected_server": str(selected_server or ""),
            "selected_server_recipes": 0,
            "selected_server_material_keys": 0,
            "selected_server_item_keys": 0,
            "selected_server_item_categories": 0,
            "selected_server_item_resource_costs": 0,
        }
        cur = conn.execute(
            "SELECT metadata_value FROM app_metadata WHERE metadata_key='schema_version'"
        )
        row = cur.fetchone()
        try:
            out["schema_version"] = int(row[0] or 0) if row else 0
        except Exception:
            out["schema_version"] = 0

        cur = conn.execute(
            "SELECT recipe_type_code, COUNT(1) FROM saved_craft_recipes GROUP BY recipe_type_code"
        )
        for rt, cnt in cur.fetchall():
            out["recipes_by_type"][str(rt or "unknown")] = int(cnt or 0)
            out["recipes_total"] += int(cnt or 0)

        cur = conn.execute(
            """
            SELECT gs.server_name, COUNT(1)
            FROM saved_craft_recipes sr
            JOIN crafting_contexts cc ON cc.context_id = sr.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            GROUP BY gs.server_name
            """
        )
        for sv, cnt in cur.fetchall():
            out["recipes_by_server"][str(sv or "")] = int(cnt or 0)

        cur = conn.execute("SELECT COUNT(1) FROM material_options")
        out["material_keys_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM craftable_items")
        out["item_keys_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM craft_categories")
        out["item_categories_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM resource_catalog")
        out["resources_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM resource_catalog WHERE coalesce(game_item_id,0) > 0")
        out["resources_with_item_id"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM craftable_item_resource_requirements")
        out["item_resource_costs_total"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute("SELECT COUNT(1) FROM crafting_contexts")
        out["profession_nodes"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute("SELECT COUNT(1) FROM game_servers")
        out["servers_count"] = int((cur.fetchone() or [0])[0] or 0)

        sel = str(selected_server or "").strip()
        if sel:
            sid = int(_lookup_server_id(conn, sel) or 0)
            if sid <= 0:
                return out
            cur = conn.execute(
                """
                SELECT COUNT(1)
                FROM saved_craft_recipes sr
                JOIN crafting_contexts cc ON cc.context_id = sr.context_id
                WHERE cc.game_server_id=?
                """,
                (int(sid),),
            )
            out["selected_server_recipes"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute(
                """
                SELECT COUNT(1)
                FROM material_options mo
                JOIN crafting_contexts cc ON cc.context_id = mo.context_id
                WHERE cc.game_server_id=?
                """,
                (int(sid),),
            )
            out["selected_server_material_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute(
                """
                SELECT COUNT(1)
                FROM craftable_items ci
                JOIN crafting_contexts cc ON cc.context_id = ci.context_id
                WHERE cc.game_server_id=?
                """,
                (int(sid),),
            )
            out["selected_server_item_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute(
                """
                SELECT COUNT(1)
                FROM craft_categories cat
                JOIN crafting_contexts cc ON cc.context_id = cat.context_id
                WHERE cc.game_server_id=?
                """,
                (int(sid),),
            )
            out["selected_server_item_categories"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute(
                """
                SELECT COUNT(1)
                FROM craftable_item_resource_requirements cir
                JOIN craftable_items ci ON ci.craftable_item_id = cir.craftable_item_id
                JOIN crafting_contexts cc ON cc.context_id = ci.context_id
                WHERE cc.game_server_id=?
                """,
                (int(sid),),
            )
            out["selected_server_item_resource_costs"] = int((cur.fetchone() or [0])[0] or 0)
        return out
    finally:
        conn.close()
