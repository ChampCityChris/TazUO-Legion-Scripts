import ast
import json
import os
import sqlite3
import time

DB_FILE = "craftables.db"
DB_FOLDER = "Databases"
SCHEMA_VERSION = 8
RECIPES_JSON_FILE = "recipes.json"
MATERIAL_KEYS_JSON_FILE = "material_keys.json"
ITEM_KEYS_JSON_FILE = "item_keys.json"
BASE_DIR_OVERRIDE = ""
SQLITE_CONNECT_TIMEOUT_S = 0.35
SQLITE_BUSY_TIMEOUT_MS = 350
INIT_RETRY_COOLDOWN_S = 1.5
_INIT_OK = False
_INIT_NEXT_RETRY_AT = 0.0
_INIT_LAST_ERROR = ""
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


def set_base_dir(path):
    global BASE_DIR_OVERRIDE
    try:
        p = str(path or "").strip()
    except Exception:
        p = ""
    if p:
        BASE_DIR_OVERRIDE = p


def _db_path():
    base = _base_dir()
    try:
        root = os.path.dirname(base) if os.path.basename(str(base or "")).lower() == "utilities" else base
    except Exception:
        root = base
    return os.path.join(root, DB_FOLDER, DB_FILE)


def _json_path(filename):
    return os.path.join(_base_dir(), filename)


def _is_db_format_error(ex):
    msg = str(ex or "").lower()
    return (
        ("file is encrypted or is not a database" in msg)
        or ("not a database" in msg)
        or ("wal format detected" in msg)
    )


def _remove_sidecars(db_path):
    for suffix in ("-wal", "-shm"):
        p = db_path + suffix
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _connect_raw(db_path):
    conn = sqlite3.connect(db_path, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
    conn.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)) + ";")
    return conn


def _repair_legacy_saved_recipe_index(conn):
    # Some embedded sqlite builds cannot parse expression-based index SQL from older DBs.
    # If present, drop that index so schema parsing no longer fails.
    try:
        cur = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_saved_recipe_natural'"
        )
        row = cur.fetchone()
    except Exception:
        return False
    if not row:
        return False
    try:
        sql = str((row[0] or "")).strip().lower()
    except Exception:
        sql = ""
    if not sql:
        return False
    if ("coalesce(" not in sql) and ("ifnull(" not in sql):
        return False
    try:
        conn.execute("DROP INDEX IF EXISTS uq_saved_recipe_natural")
        conn.commit()
        return True
    except Exception:
        pass
    try:
        conn.execute("PRAGMA writable_schema=ON;")
        conn.execute("DELETE FROM sqlite_master WHERE type='index' AND name='uq_saved_recipe_natural'")
        conn.execute("PRAGMA writable_schema=OFF;")
        conn.commit()
        return True
    except Exception:
        try:
            conn.execute("PRAGMA writable_schema=OFF;")
        except Exception:
            pass
        return False


def _connect():
    db_path = _db_path()
    conn = None
    try:
        conn = _connect_raw(db_path)
        try:
            _repair_legacy_saved_recipe_index(conn)
        except Exception:
            pass
        # Touch schema immediately so header/format errors surface here.
        conn.execute("PRAGMA schema_version;").fetchone()
        return conn
    except Exception as ex:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if not _is_db_format_error(ex):
            raise
        _remove_sidecars(db_path)
        try:
            conn = _connect_raw(db_path)
            conn.execute("PRAGMA schema_version;").fetchone()
            return conn
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        # Final fallback: preserve unreadable DB and recreate from split JSON.
        try:
            if os.path.exists(db_path):
                bad_path = db_path + ".bad." + str(int(time.time()))
                os.replace(db_path, bad_path)
        except Exception:
            pass
        conn = _connect_raw(db_path)
        return conn


def _now_s():
    try:
        return float(time.time())
    except Exception:
        return 0.0


def try_init_store(force=False):
    global _INIT_OK, _INIT_NEXT_RETRY_AT, _INIT_LAST_ERROR
    if _INIT_OK and not force:
        return True
    now = _now_s()
    if not force and now < float(_INIT_NEXT_RETRY_AT or 0.0):
        return False
    try:
        init_store()
        _INIT_OK = True
        _INIT_LAST_ERROR = ""
        _INIT_NEXT_RETRY_AT = 0.0
        return True
    except Exception as ex:
        _INIT_OK = False
        _INIT_LAST_ERROR = str(ex or "")
        _INIT_NEXT_RETRY_AT = now + float(INIT_RETRY_COOLDOWN_S)
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
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _norm_resource_name(name):
    text = str(name or "").strip().lower()
    return " ".join(text.split())


def _is_valid_recipe_row(row):
    if not isinstance(row, dict):
        return False
    name = str(row.get("name", "") or "").strip()
    profession = str(row.get("profession", "") or "").strip()
    buttons = _as_int_list(row.get("buttons", []))
    return bool(name and profession and buttons)


def _read_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _table_columns(conn, table_name):
    out = set()
    try:
        cur = conn.execute("PRAGMA table_info(" + str(table_name) + ")")
        for r in cur.fetchall():
            try:
                out.add(str(r[1] or "").strip().lower())
            except Exception:
                pass
    except Exception:
        return set()
    return out


def _has_columns(conn, table_name, names):
    cols = _table_columns(conn, table_name)
    want = [str(x or "").strip().lower() for x in (names or []) if str(x or "").strip()]
    return bool(cols) and all(n in cols for n in want)


def _rename_column_if_present(conn, table_name, old_name, new_name):
    old_col = str(old_name or "").strip().lower()
    new_col = str(new_name or "").strip().lower()
    if not old_col or not new_col or old_col == new_col:
        return
    cols = _table_columns(conn, table_name)
    if not cols or new_col in cols or old_col not in cols:
        return
    try:
        conn.execute(
            "ALTER TABLE "
            + str(table_name)
            + " RENAME COLUMN "
            + str(old_name)
            + " TO "
            + str(new_name)
        )
    except Exception:
        pass


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
            SELECT coalesce(MAX(display_sequence), 0) + 1,
                   coalesce(MAX(legacy_sort_token), 0) + 1
            FROM craft_categories
            WHERE context_id=?
            """,
            (int(ctx),),
        )
        row = cur.fetchone()
        disp = int((row[0] if row else 1) or 1)
        legacy = int((row[1] if row else disp) or disp)
        conn.execute(
            """
            INSERT INTO craft_categories(context_id, category_name, display_sequence, category_navigation_button_id, legacy_sort_token)
            VALUES (?, ?, ?, NULL, ?)
            ON CONFLICT(context_id, category_name) DO NOTHING
            """,
            (int(ctx), cat, int(disp), int(legacy)),
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
        "legacy": text,
    }
    if not text:
        return out
    payload = None
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if payload is None and text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text.replace("'", '"').replace("None", "null"))
        except Exception:
            payload = None
    if payload is None and text.startswith("{") and text.endswith("}"):
        try:
            payload = ast.literal_eval(text)
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
    if _is_normalized_schema(conn):
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
    try:
        cur = conn.execute("SELECT id FROM resources WHERE lower(name)=lower(?) LIMIT 1", (nm,))
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        cur = conn.execute("INSERT INTO resources(name) VALUES (?)", (nm,))
        return int(getattr(cur, "lastrowid", 0) or 0)
    except Exception:
        try:
            cur = conn.execute("SELECT id FROM resources WHERE lower(name)=lower(?) LIMIT 1", (nm,))
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0


def _ensure_server_id(conn, server_name):
    nm = str(server_name or "").strip()
    if not nm:
        return 0
    if _is_normalized_schema(conn):
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
    try:
        cur = conn.execute("SELECT id FROM servers WHERE lower(name)=lower(?) LIMIT 1", (nm,))
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        cur = conn.execute("INSERT INTO servers(name) VALUES (?)", (nm,))
        return int(getattr(cur, "lastrowid", 0) or 0)
    except Exception:
        try:
            cur = conn.execute("SELECT id FROM servers WHERE lower(name)=lower(?) LIMIT 1", (nm,))
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0


def _lookup_server_id(conn, server_name):
    nm = str(server_name or "").strip()
    if not nm:
        return 0
    if _is_normalized_schema(conn):
        try:
            cur = conn.execute(
                "SELECT game_server_id FROM game_servers WHERE lower(server_name)=lower(?) LIMIT 1",
                (nm,),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0
    try:
        cur = conn.execute("SELECT id FROM servers WHERE lower(name)=lower(?) LIMIT 1", (nm,))
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _ensure_profession_id(conn, profession_name):
    nm = str(profession_name or "").strip()
    if not nm:
        return 0
    if _is_normalized_schema(conn):
        try:
            cur = conn.execute(
                "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
                (nm,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0] or 0)
        except Exception:
            pass
        try:
            conn.execute("INSERT INTO crafting_professions(profession_name) VALUES (?)", (nm,))
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
    try:
        cur = conn.execute("SELECT id FROM professions WHERE lower(name)=lower(?) LIMIT 1", (nm,))
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass
    try:
        cur = conn.execute("INSERT INTO professions(name) VALUES (?)", (nm,))
        return int(getattr(cur, "lastrowid", 0) or 0)
    except Exception:
        try:
            cur = conn.execute("SELECT id FROM professions WHERE lower(name)=lower(?) LIMIT 1", (nm,))
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0


def _lookup_profession_id(conn, profession_name):
    nm = str(profession_name or "").strip()
    if not nm:
        return 0
    if _is_normalized_schema(conn):
        try:
            cur = conn.execute(
                "SELECT profession_id FROM crafting_professions WHERE lower(profession_name)=lower(?) LIMIT 1",
                (nm,),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0
    try:
        cur = conn.execute("SELECT id FROM professions WHERE lower(name)=lower(?) LIMIT 1", (nm,))
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _server_name_map(conn):
    out = {}
    if _is_normalized_schema(conn):
        try:
            cur = conn.execute("SELECT game_server_id, server_name FROM game_servers")
            for row in cur.fetchall():
                sid = int(row[0] or 0)
                if sid <= 0:
                    continue
                out[sid] = str(row[1] or "")
            return out
        except Exception:
            return out
    if not _has_columns(conn, "servers", ["id", "name"]):
        return out
    cur = conn.execute("SELECT id, name FROM servers")
    for row in cur.fetchall():
        try:
            sid = int(row[0] or 0)
        except Exception:
            sid = 0
        if sid <= 0:
            continue
        out[sid] = str(row[1] or "")
    return out


def _profession_name_map(conn):
    out = {}
    if _is_normalized_schema(conn):
        try:
            cur = conn.execute("SELECT profession_id, profession_name FROM crafting_professions")
            for row in cur.fetchall():
                pid = int(row[0] or 0)
                if pid <= 0:
                    continue
                out[pid] = str(row[1] or "")
            return out
        except Exception:
            return out
    if not _has_columns(conn, "professions", ["id", "name"]):
        return out
    cur = conn.execute("SELECT id, name FROM professions")
    for row in cur.fetchall():
        try:
            pid = int(row[0] or 0)
        except Exception:
            pid = 0
        if pid <= 0:
            continue
        out[pid] = str(row[1] or "")
    return out


def _write_item_resource_costs(conn, server, profession, item_key, resources):
    if _is_normalized_schema(conn):
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
        return
    if not _has_columns(conn, "item_resource_costs", ["server_id", "profession_id", "item_key", "slot", "resource_id", "per_item"]):
        return
    if not _has_columns(conn, "resources", ["id", "name"]):
        return
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    ik = str(item_key or "")
    if srv_id <= 0 or prof_id <= 0 or not ik:
        return
    rows = _normalize_resource_rows(resources)
    conn.execute(
        "DELETE FROM item_resource_costs WHERE server_id=? AND profession_id=? AND item_key=?",
        (int(srv_id), int(prof_id), ik),
    )
    slot = 0
    for rr in rows:
        slot += 1
        rid = _ensure_resource_name(conn, rr.get("material", ""))
        if int(rid) <= 0:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO item_resource_costs
            (server_id, profession_id, item_key, slot, resource_id, per_item)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(srv_id), int(prof_id), ik, int(slot), int(rid), int(rr.get("per_item", 0) or 0)),
        )


def _seed_resource_item_ids(conn):
    if _is_normalized_schema(conn):
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
        return
    if not _has_columns(conn, "resources", ["name", "item_id"]):
        return
    for name, item_id in (RESOURCE_ITEM_ID_SEEDS or {}).items():
        nm = _norm_resource_name(name)
        iid = int(item_id or 0)
        if not nm or iid <= 0:
            continue
        try:
            conn.execute(
                """
                UPDATE resources
                SET item_id=?
                WHERE lower(name)=lower(?) AND coalesce(item_id, 0) <= 0
                """,
                (iid, nm),
            )
        except Exception:
            pass


def _load_item_resource_costs(conn):
    out = {}
    if not _has_columns(conn, "item_resource_costs", ["server_id", "profession_id", "item_key", "slot", "resource_id", "per_item"]):
        return out
    if not _has_columns(conn, "resources", ["id", "name"]):
        return out
    server_by_id = _server_name_map(conn)
    prof_by_id = _profession_name_map(conn)
    cur = conn.execute(
        """
        SELECT irc.server_id, irc.profession_id, irc.item_key, irc.slot, irc.per_item, res.name
        FROM item_resource_costs irc
        JOIN resources res ON res.id = irc.resource_id
        ORDER BY irc.server_id, irc.profession_id, irc.item_key, irc.slot
        """
    )
    for row in cur.fetchall():
        srv = str(server_by_id.get(int(row[0] or 0), "") or "")
        prof = str(prof_by_id.get(int(row[1] or 0), "") or "")
        ik = str(row[2] or "")
        mat = _norm_resource_name(row[5])
        try:
            qty = int(row[4] or 0)
        except Exception:
            qty = 0
        if not (srv and prof and ik and mat and qty > 0):
            continue
        k = (srv, prof, ik)
        if k not in out:
            out[k] = []
        out[k].append({"material": mat, "per_item": int(qty)})
    return out


def _bootstrap_item_resource_costs_from_item_keys(conn):
    if not _has_columns(conn, "item_resource_costs", ["server_id", "profession_id", "item_key", "slot", "resource_id", "per_item"]):
        return
    if not _has_columns(conn, "resources", ["id", "name"]):
        return
    try:
        cur = conn.execute("SELECT COUNT(1) FROM item_resource_costs")
        count = int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        count = 0
    if count > 0:
        return
    cols = _table_columns(conn, "item_keys")
    if not cols:
        return
    src_col = "resources" if "resources" in cols else ("resources_json" if "resources_json" in cols else "")
    if not src_col:
        return
    cur = conn.execute(
        "SELECT server, profession, item_key, " + str(src_col) + " FROM item_keys"
    )
    for row in cur.fetchall():
        resources = _safe_json_loads(row[3], [])
        _write_item_resource_costs(
            conn,
            str(row[0] or ""),
            str(row[1] or ""),
            str(row[2] or ""),
            resources,
        )


def _write_recipe_child_lists(conn, recipe_id, buttons, materials, material_buttons):
    rid = int(recipe_id or 0)
    if rid <= 0:
        return
    if _is_normalized_schema(conn):
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
                 pull_quantity, game_item_id_override, hue_override, legacy_material_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    str(parsed.get("legacy", raw_mat) or ""),
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
        return

    if _has_columns(conn, "recipe_buttons", ["recipe_id", "slot", "button_id"]):
        conn.execute("DELETE FROM recipe_buttons WHERE recipe_id=?", (rid,))
        slot = 0
        for btn in _as_int_list(buttons):
            slot += 1
            conn.execute(
                "INSERT OR REPLACE INTO recipe_buttons(recipe_id, slot, button_id) VALUES (?, ?, ?)",
                (rid, int(slot), int(btn)),
            )

    if _has_columns(conn, "recipe_materials", ["recipe_id", "slot", "material"]):
        conn.execute("DELETE FROM recipe_materials WHERE recipe_id=?", (rid,))
        slot = 0
        for mat in _as_str_list(materials):
            slot += 1
            conn.execute(
                "INSERT OR REPLACE INTO recipe_materials(recipe_id, slot, material) VALUES (?, ?, ?)",
                (rid, int(slot), str(mat)),
            )

    if _has_columns(conn, "recipe_material_buttons", ["recipe_id", "slot", "button_id"]):
        conn.execute("DELETE FROM recipe_material_buttons WHERE recipe_id=?", (rid,))
        slot = 0
        for btn in _as_int_list(material_buttons):
            slot += 1
            conn.execute(
                "INSERT OR REPLACE INTO recipe_material_buttons(recipe_id, slot, button_id) VALUES (?, ?, ?)",
                (rid, int(slot), int(btn)),
            )


def _load_recipe_child_lists(conn):
    out = {}
    if _has_columns(conn, "recipe_buttons", ["recipe_id", "slot", "button_id"]):
        cur = conn.execute("SELECT recipe_id, slot, button_id FROM recipe_buttons ORDER BY recipe_id, slot")
        for row in cur.fetchall():
            rid = int(row[0] or 0)
            if rid <= 0:
                continue
            if rid not in out:
                out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
            out[rid]["buttons"].append(int(row[2] or 0))

    if _has_columns(conn, "recipe_materials", ["recipe_id", "slot", "material"]):
        cur = conn.execute("SELECT recipe_id, slot, material FROM recipe_materials ORDER BY recipe_id, slot")
        for row in cur.fetchall():
            rid = int(row[0] or 0)
            mat = str(row[2] or "").strip()
            if rid <= 0 or not mat:
                continue
            if rid not in out:
                out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
            out[rid]["materials"].append(mat)

    if _has_columns(conn, "recipe_material_buttons", ["recipe_id", "slot", "button_id"]):
        cur = conn.execute(
            "SELECT recipe_id, slot, button_id FROM recipe_material_buttons ORDER BY recipe_id, slot"
        )
        for row in cur.fetchall():
            rid = int(row[0] or 0)
            if rid <= 0:
                continue
            if rid not in out:
                out[rid] = {"buttons": [], "materials": [], "material_buttons": []}
            out[rid]["material_buttons"].append(int(row[2] or 0))
    return out


def _bootstrap_recipe_child_lists_from_recipes(conn):
    if not _has_columns(conn, "recipes", ["id", "buttons", "materials", "material_buttons"]):
        return
    if not _has_columns(conn, "recipe_buttons", ["recipe_id", "slot", "button_id"]):
        return
    try:
        cur = conn.execute("SELECT COUNT(1) FROM recipe_buttons")
        count = int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        count = 0
    if count > 0:
        return
    cur = conn.execute("SELECT id, buttons, materials, material_buttons FROM recipes")
    for row in cur.fetchall():
        _write_recipe_child_lists(
            conn,
            int(row[0] or 0),
            _safe_json_loads(row[1], []),
            _safe_json_loads(row[2], []),
            _safe_json_loads(row[3], []),
        )


def _write_material_key_buttons(conn, server, profession, material_key, material_buttons):
    if _is_normalized_schema(conn):
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
        return
    if not _has_columns(
        conn, "material_key_buttons", ["server_id", "profession_id", "material_key", "slot", "button_id"]
    ):
        return
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    mk = str(material_key or "")
    if srv_id <= 0 or prof_id <= 0 or not mk:
        return
    conn.execute(
        "DELETE FROM material_key_buttons WHERE server_id=? AND profession_id=? AND material_key=?",
        (int(srv_id), int(prof_id), mk),
    )
    slot = 0
    for btn in _as_int_list(material_buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO material_key_buttons
            (server_id, profession_id, material_key, slot, button_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(srv_id), int(prof_id), mk, int(slot), int(btn)),
        )


def _load_material_key_buttons(conn):
    out = {}
    if not _has_columns(
        conn, "material_key_buttons", ["server_id", "profession_id", "material_key", "slot", "button_id"]
    ):
        return out
    server_by_id = _server_name_map(conn)
    prof_by_id = _profession_name_map(conn)
    cur = conn.execute(
        """
        SELECT server_id, profession_id, material_key, slot, button_id
        FROM material_key_buttons
        ORDER BY server_id, profession_id, material_key, slot
        """
    )
    for row in cur.fetchall():
        k = (
            str(server_by_id.get(int(row[0] or 0), "") or ""),
            str(prof_by_id.get(int(row[1] or 0), "") or ""),
            str(row[2] or ""),
        )
        if k not in out:
            out[k] = []
        out[k].append(int(row[4] or 0))
    return out


def _bootstrap_material_key_buttons_from_material_keys(conn):
    if not _has_columns(conn, "material_keys", ["server", "profession", "material_key", "material_buttons"]):
        return
    if not _has_columns(
        conn, "material_key_buttons", ["server_id", "profession_id", "material_key", "slot", "button_id"]
    ):
        return
    try:
        cur = conn.execute("SELECT COUNT(1) FROM material_key_buttons")
        count = int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        count = 0
    if count > 0:
        return
    cur = conn.execute("SELECT server, profession, material_key, material_buttons FROM material_keys")
    for row in cur.fetchall():
        _write_material_key_buttons(
            conn,
            str(row[0] or ""),
            str(row[1] or ""),
            str(row[2] or ""),
            _safe_json_loads(row[3], []),
        )


def _write_item_key_buttons(conn, server, profession, item_key, buttons):
    if _is_normalized_schema(conn):
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
        return
    if not _has_columns(conn, "item_key_buttons", ["server_id", "profession_id", "item_key", "slot", "button_id"]):
        return
    srv_id = int(_ensure_server_id(conn, server) or 0)
    prof_id = int(_ensure_profession_id(conn, profession) or 0)
    ik = str(item_key or "")
    if srv_id <= 0 or prof_id <= 0 or not ik:
        return
    conn.execute(
        "DELETE FROM item_key_buttons WHERE server_id=? AND profession_id=? AND item_key=?",
        (int(srv_id), int(prof_id), ik),
    )
    slot = 0
    for btn in _as_int_list(buttons):
        slot += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO item_key_buttons
            (server_id, profession_id, item_key, slot, button_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(srv_id), int(prof_id), ik, int(slot), int(btn)),
        )


def _load_item_key_buttons(conn):
    out = {}
    if not _has_columns(conn, "item_key_buttons", ["server_id", "profession_id", "item_key", "slot", "button_id"]):
        return out
    server_by_id = _server_name_map(conn)
    prof_by_id = _profession_name_map(conn)
    cur = conn.execute(
        """
        SELECT server_id, profession_id, item_key, slot, button_id
        FROM item_key_buttons
        ORDER BY server_id, profession_id, item_key, slot
        """
    )
    for row in cur.fetchall():
        k = (
            str(server_by_id.get(int(row[0] or 0), "") or ""),
            str(prof_by_id.get(int(row[1] or 0), "") or ""),
            str(row[2] or ""),
        )
        if k not in out:
            out[k] = []
        out[k].append(int(row[4] or 0))
    return out


def _bootstrap_item_key_buttons_from_item_keys(conn):
    if not _has_columns(conn, "item_keys", ["server", "profession", "item_key", "buttons"]):
        return
    if not _has_columns(conn, "item_key_buttons", ["server_id", "profession_id", "item_key", "slot", "button_id"]):
        return
    try:
        cur = conn.execute("SELECT COUNT(1) FROM item_key_buttons")
        count = int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        count = 0
    if count > 0:
        return
    cur = conn.execute("SELECT server, profession, item_key, buttons FROM item_keys")
    for row in cur.fetchall():
        _write_item_key_buttons(
            conn,
            str(row[0] or ""),
            str(row[1] or ""),
            str(row[2] or ""),
            _safe_json_loads(row[3], []),
        )


def _hard_cutover_drop_legacy_json_columns(conn):
    recipes_cols = _table_columns(conn, "recipes")
    if recipes_cols and ("buttons" in recipes_cols or "materials" in recipes_cols or "material_buttons" in recipes_cols):
        conn.executescript(
            """
            CREATE TABLE recipes_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_type TEXT NOT NULL,
                server TEXT NOT NULL,
                profession TEXT NOT NULL,
                name TEXT NOT NULL,
                item_id INTEGER NOT NULL DEFAULT 0,
                material TEXT NOT NULL DEFAULT '',
                material_key TEXT NOT NULL DEFAULT '',
                deed_key TEXT NOT NULL DEFAULT '',
                start_at REAL,
                stop_at REAL,
                UNIQUE(recipe_type, server, profession, name, material_key)
            );
            INSERT INTO recipes_new(id, recipe_type, server, profession, name, item_id, material, material_key, deed_key, start_at, stop_at)
            SELECT id, recipe_type, server, profession, name, item_id, material, material_key, deed_key, start_at, stop_at
            FROM recipes;
            DROP TABLE recipes;
            ALTER TABLE recipes_new RENAME TO recipes;
            CREATE INDEX IF NOT EXISTS idx_recipes_lookup
                ON recipes(recipe_type, server, profession, name);
            """
        )

    mat_cols = _table_columns(conn, "material_keys")
    if mat_cols and "material_buttons" in mat_cols:
        conn.executescript(
            """
            CREATE TABLE material_keys_new (
                server TEXT NOT NULL,
                profession TEXT NOT NULL,
                material_key TEXT NOT NULL,
                material TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(server, profession, material_key)
            );
            INSERT INTO material_keys_new(server, profession, material_key, material)
            SELECT server, profession, material_key, material
            FROM material_keys;
            DROP TABLE material_keys;
            ALTER TABLE material_keys_new RENAME TO material_keys;
            """
        )

    item_cols = _table_columns(conn, "item_keys")
    if item_cols and ("buttons" in item_cols or "resources" in item_cols):
        conn.executescript(
            """
            CREATE TABLE item_keys_new (
                server TEXT NOT NULL,
                profession TEXT NOT NULL,
                item_key TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                item_id INTEGER NOT NULL DEFAULT 0,
                default_material_key TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(server, profession, item_key)
            );
            INSERT INTO item_keys_new(server, profession, item_key, name, item_id, default_material_key, category)
            SELECT server, profession, item_key, name, item_id, default_material_key, category
            FROM item_keys;
            DROP TABLE item_keys;
            ALTER TABLE item_keys_new RENAME TO item_keys;
            """
        )


def _hard_cutover_server_profession_ids(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS professions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        """
    )

    for tname in (
        "recipes",
        "material_keys",
        "item_keys",
        "item_categories",
        "item_resource_costs",
        "material_key_buttons",
        "item_key_buttons",
    ):
        cols = _table_columns(conn, tname)
        if "server" in cols:
            try:
                cur = conn.execute("SELECT DISTINCT server FROM " + str(tname))
                for row in cur.fetchall():
                    _ensure_server_id(conn, str(row[0] or ""))
            except Exception:
                pass
        if "profession" in cols:
            try:
                cur = conn.execute("SELECT DISTINCT profession FROM " + str(tname))
                for row in cur.fetchall():
                    _ensure_profession_id(conn, str(row[0] or ""))
            except Exception:
                pass

    rcols = _table_columns(conn, "recipes")
    if rcols and "server" in rcols and "profession" in rcols:
        data = []
        cur = conn.execute(
            "SELECT id, recipe_type, server, profession, name, item_id, material, material_key, deed_key, start_at, stop_at FROM recipes"
        )
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[2]) or 0)
            pid = int(_ensure_profession_id(conn, row[3]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append(
                (
                    int(row[0] or 0),
                    str(row[1] or ""),
                    int(sid),
                    int(pid),
                    str(row[4] or ""),
                    int(row[5] or 0),
                    str(row[6] or ""),
                    str(row[7] or ""),
                    str(row[8] or ""),
                    row[9],
                    row[10],
                )
            )
        conn.executescript(
            """
            DROP TABLE recipes;
            CREATE TABLE recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_type TEXT NOT NULL,
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                item_id INTEGER NOT NULL DEFAULT 0,
                material TEXT NOT NULL DEFAULT '',
                material_key TEXT NOT NULL DEFAULT '',
                deed_key TEXT NOT NULL DEFAULT '',
                start_at REAL,
                stop_at REAL,
                UNIQUE(recipe_type, server_id, profession_id, name, material_key)
            );
            CREATE INDEX IF NOT EXISTS idx_recipes_lookup
                ON recipes(recipe_type, server_id, profession_id, name);
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO recipes
            (id, recipe_type, server_id, profession_id, name, item_id, material, material_key, deed_key, start_at, stop_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )

    mcols = _table_columns(conn, "material_keys")
    if mcols and "server" in mcols and "profession" in mcols:
        data = []
        cur = conn.execute("SELECT server, profession, material_key, material FROM material_keys")
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append((int(sid), int(pid), str(row[2] or ""), str(row[3] or "")))
        conn.executescript(
            """
            DROP TABLE material_keys;
            CREATE TABLE material_keys (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                material_key TEXT NOT NULL,
                material TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(server_id, profession_id, material_key)
            );
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO material_keys(server_id, profession_id, material_key, material) VALUES (?, ?, ?, ?)",
            data,
        )

    icols = _table_columns(conn, "item_keys")
    if icols and "server" in icols and "profession" in icols:
        data = []
        cur = conn.execute(
            "SELECT server, profession, item_key, name, item_id, default_material_key, category FROM item_keys"
        )
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append(
                (
                    int(sid),
                    int(pid),
                    str(row[2] or ""),
                    str(row[3] or ""),
                    int(row[4] or 0),
                    str(row[5] or ""),
                    str(row[6] or ""),
                )
            )
        conn.executescript(
            """
            DROP TABLE item_keys;
            CREATE TABLE item_keys (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                item_id INTEGER NOT NULL DEFAULT 0,
                default_material_key TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(server_id, profession_id, item_key)
            );
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO item_keys
            (server_id, profession_id, item_key, name, item_id, default_material_key, category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )

    ccols = _table_columns(conn, "item_categories")
    if ccols and "server" in ccols and "profession" in ccols:
        data = []
        cur = conn.execute("SELECT server, profession, category, sort_order FROM item_categories")
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append((int(sid), int(pid), str(row[2] or ""), int(row[3] or 0)))
        conn.executescript(
            """
            DROP TABLE item_categories;
            CREATE TABLE item_categories (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(server_id, profession_id, category)
            );
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO item_categories(server_id, profession_id, category, sort_order) VALUES (?, ?, ?, ?)",
            data,
        )

    rccols = _table_columns(conn, "item_resource_costs")
    if rccols and "server" in rccols and "profession" in rccols:
        data = []
        cur = conn.execute("SELECT server, profession, item_key, slot, resource_id, per_item FROM item_resource_costs")
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append((int(sid), int(pid), str(row[2] or ""), int(row[3] or 0), int(row[4] or 0), int(row[5] or 0)))
        conn.executescript(
            """
            DROP TABLE item_resource_costs;
            CREATE TABLE item_resource_costs (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                slot INTEGER NOT NULL,
                resource_id INTEGER NOT NULL,
                per_item INTEGER NOT NULL,
                PRIMARY KEY(server_id, profession_id, item_key, slot)
            );
            CREATE INDEX IF NOT EXISTS idx_item_resource_costs_lookup
                ON item_resource_costs(server_id, profession_id, item_key);
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO item_resource_costs
            (server_id, profession_id, item_key, slot, resource_id, per_item)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            data,
        )

    mkb_cols = _table_columns(conn, "material_key_buttons")
    if mkb_cols and "server" in mkb_cols and "profession" in mkb_cols:
        data = []
        cur = conn.execute("SELECT server, profession, material_key, slot, button_id FROM material_key_buttons")
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append((int(sid), int(pid), str(row[2] or ""), int(row[3] or 0), int(row[4] or 0)))
        conn.executescript(
            """
            DROP TABLE material_key_buttons;
            CREATE TABLE material_key_buttons (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                material_key TEXT NOT NULL,
                slot INTEGER NOT NULL,
                button_id INTEGER NOT NULL,
                PRIMARY KEY(server_id, profession_id, material_key, slot)
            );
            CREATE INDEX IF NOT EXISTS idx_material_key_buttons_lookup
                ON material_key_buttons(server_id, profession_id, material_key);
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO material_key_buttons
            (server_id, profession_id, material_key, slot, button_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            data,
        )

    ikb_cols = _table_columns(conn, "item_key_buttons")
    if ikb_cols and "server" in ikb_cols and "profession" in ikb_cols:
        data = []
        cur = conn.execute("SELECT server, profession, item_key, slot, button_id FROM item_key_buttons")
        for row in cur.fetchall():
            sid = int(_ensure_server_id(conn, row[0]) or 0)
            pid = int(_ensure_profession_id(conn, row[1]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            data.append((int(sid), int(pid), str(row[2] or ""), int(row[3] or 0), int(row[4] or 0)))
        conn.executescript(
            """
            DROP TABLE item_key_buttons;
            CREATE TABLE item_key_buttons (
                server_id INTEGER NOT NULL,
                profession_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                slot INTEGER NOT NULL,
                button_id INTEGER NOT NULL,
                PRIMARY KEY(server_id, profession_id, item_key, slot)
            );
            CREATE INDEX IF NOT EXISTS idx_item_key_buttons_lookup
                ON item_key_buttons(server_id, profession_id, item_key);
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO item_key_buttons
            (server_id, profession_id, item_key, slot, button_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            data,
        )


def _ensure_schema(conn):
    if _is_normalized_schema(conn):
        _seed_resource_item_ids(conn)
        conn.execute(
            "INSERT OR REPLACE INTO app_metadata(metadata_key, metadata_value) VALUES (?, ?)",
            ("schema_version", str(int(SCHEMA_VERSION))),
        )
        conn.commit()
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS professions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_type TEXT NOT NULL,
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            item_id INTEGER NOT NULL DEFAULT 0,
            material TEXT NOT NULL DEFAULT '',
            material_key TEXT NOT NULL DEFAULT '',
            deed_key TEXT NOT NULL DEFAULT '',
            start_at REAL,
            stop_at REAL,
            UNIQUE(recipe_type, server_id, profession_id, name, material_key)
        );

        CREATE INDEX IF NOT EXISTS idx_recipes_lookup
            ON recipes(recipe_type, server_id, profession_id, name);

        CREATE TABLE IF NOT EXISTS material_keys (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            material_key TEXT NOT NULL,
            material TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(server_id, profession_id, material_key)
        );

        CREATE TABLE IF NOT EXISTS item_keys (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            item_key TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            item_id INTEGER NOT NULL DEFAULT 0,
            default_material_key TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(server_id, profession_id, item_key)
        );

        CREATE TABLE IF NOT EXISTS item_categories (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(server_id, profession_id, category)
        );

        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            item_id INTEGER NOT NULL DEFAULT 0,
            hue INTEGER
        );

        CREATE TABLE IF NOT EXISTS item_resource_costs (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            item_key TEXT NOT NULL,
            slot INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            per_item INTEGER NOT NULL,
            PRIMARY KEY(server_id, profession_id, item_key, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_item_resource_costs_lookup
            ON item_resource_costs(server_id, profession_id, item_key);

        CREATE TABLE IF NOT EXISTS recipe_buttons (
            recipe_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            button_id INTEGER NOT NULL,
            PRIMARY KEY(recipe_id, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_recipe_buttons_lookup
            ON recipe_buttons(recipe_id);

        CREATE TABLE IF NOT EXISTS recipe_materials (
            recipe_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            material TEXT NOT NULL,
            PRIMARY KEY(recipe_id, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_recipe_materials_lookup
            ON recipe_materials(recipe_id);

        CREATE TABLE IF NOT EXISTS recipe_material_buttons (
            recipe_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            button_id INTEGER NOT NULL,
            PRIMARY KEY(recipe_id, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_recipe_material_buttons_lookup
            ON recipe_material_buttons(recipe_id);

        CREATE TABLE IF NOT EXISTS material_key_buttons (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            material_key TEXT NOT NULL,
            slot INTEGER NOT NULL,
            button_id INTEGER NOT NULL,
            PRIMARY KEY(server_id, profession_id, material_key, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_material_key_buttons_lookup
            ON material_key_buttons(server_id, profession_id, material_key);

        CREATE TABLE IF NOT EXISTS item_key_buttons (
            server_id INTEGER NOT NULL,
            profession_id INTEGER NOT NULL,
            item_key TEXT NOT NULL,
            slot INTEGER NOT NULL,
            button_id INTEGER NOT NULL,
            PRIMARY KEY(server_id, profession_id, item_key, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_item_key_buttons_lookup
            ON item_key_buttons(server_id, profession_id, item_key);
        """
    )
    # Backward-compatible migration for legacy databases, followed by hard cutover.
    try:
        _rename_column_if_present(conn, "recipes", "buttons_json", "buttons")
        _rename_column_if_present(conn, "recipes", "materials_json", "materials")
        _rename_column_if_present(conn, "recipes", "material_buttons_json", "material_buttons")
        _rename_column_if_present(conn, "material_keys", "material_buttons_json", "material_buttons")
        _rename_column_if_present(conn, "item_keys", "buttons_json", "buttons")
        _rename_column_if_present(conn, "item_keys", "resources_json", "resources")

        col_names = _table_columns(conn, "item_keys")
        if "category" not in col_names:
            conn.execute("ALTER TABLE item_keys ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        res_cols = _table_columns(conn, "resources")
        if "item_id" not in res_cols:
            conn.execute("ALTER TABLE resources ADD COLUMN item_id INTEGER NOT NULL DEFAULT 0")
        if "hue" not in res_cols:
            conn.execute("ALTER TABLE resources ADD COLUMN hue INTEGER")
    except Exception:
        pass
    _seed_resource_item_ids(conn)
    _bootstrap_item_resource_costs_from_item_keys(conn)
    _bootstrap_recipe_child_lists_from_recipes(conn)
    _bootstrap_material_key_buttons_from_material_keys(conn)
    _bootstrap_item_key_buttons_from_item_keys(conn)
    _hard_cutover_drop_legacy_json_columns(conn)
    _hard_cutover_server_profession_ids(conn)
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(int(SCHEMA_VERSION))),
    )
    conn.commit()


def _table_count(conn, table_name):
    cur = conn.execute("SELECT COUNT(1) FROM " + table_name)
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _has_any_data(conn):
    return (
        _table_count(conn, "recipes") > 0
        or _table_count(conn, "material_keys") > 0
        or _table_count(conn, "item_keys") > 0
        or _table_count(conn, "item_categories") > 0
    )


def _iter_material_keys(material_data):
    if not isinstance(material_data, dict):
        return
    for server, srv_node in material_data.items():
        if not isinstance(srv_node, dict):
            continue
        for profession, prof_node in srv_node.items():
            if not isinstance(prof_node, dict):
                continue
            mks = prof_node.get("material_keys", {})
            if not isinstance(mks, dict):
                continue
            for material_key, ent in mks.items():
                if not isinstance(ent, dict):
                    ent = {}
                yield (
                    str(server or ""),
                    str(profession or ""),
                    str(material_key or ""),
                    str(ent.get("material", "") or ""),
                    [int(x) for x in (ent.get("material_buttons", []) or []) if int(x) > 0][:2],
                )


def _iter_item_keys(item_data):
    if not isinstance(item_data, dict):
        return
    for server, srv_node in item_data.items():
        if not isinstance(srv_node, dict):
            continue
        for profession, prof_node in srv_node.items():
            if not isinstance(prof_node, dict):
                continue
            iks = prof_node.get("item_keys", {})
            if not isinstance(iks, dict):
                continue
            for item_key, ent in iks.items():
                if not isinstance(ent, dict):
                    ent = {}
                yield (
                    str(server or ""),
                    str(profession or ""),
                    str(item_key or ""),
                    str(ent.get("name", "") or ""),
                    int(ent.get("item_id", 0) or 0),
                    [int(x) for x in (ent.get("buttons", []) or []) if int(x) > 0][:2],
                    str(ent.get("default_material_key", "") or ""),
                    str(ent.get("category", "") or ""),
                    list(ent.get("resources", []) or []),
                )


def _iter_recipes(recipes_data):
    rows = []
    if isinstance(recipes_data, dict):
        rows = recipes_data.get("recipes", []) or []
    elif isinstance(recipes_data, list):
        rows = recipes_data
    if not isinstance(rows, list):
        return
    for r in rows:
        if not isinstance(r, dict):
            continue
        yield {
            "recipe_type": str(r.get("recipe_type", "") or ""),
            "server": str(r.get("server", "") or ""),
            "profession": str(r.get("profession", "") or ""),
            "name": str(r.get("name", "") or ""),
            "item_id": int(r.get("item_id", 0) or 0),
            "buttons": [int(x) for x in (r.get("buttons", []) or []) if int(x) > 0],
            "material": str(r.get("material", "") or ""),
            "material_key": str(r.get("material_key", "") or ""),
            "materials": list(r.get("materials", []) or []),
            "material_buttons": [int(x) for x in (r.get("material_buttons", []) or []) if int(x) > 0],
            "deed_key": str(r.get("deed_key", "") or ""),
            "start_at": r.get("start_at", None),
            "stop_at": r.get("stop_at", None),
        }


def _bootstrap_from_split_json_if_empty(conn):
    if _has_any_data(conn):
        return
    recipes_raw = _read_json_file(_json_path(RECIPES_JSON_FILE), {"recipes": []})
    material_raw = _read_json_file(_json_path(MATERIAL_KEYS_JSON_FILE), {})
    item_raw = _read_json_file(_json_path(ITEM_KEYS_JSON_FILE), {})

    with conn:
        for server, profession, material_key, material, material_buttons in _iter_material_keys(material_raw):
            sid = int(_ensure_server_id(conn, server) or 0)
            pid = int(_ensure_profession_id(conn, profession) or 0)
            if sid <= 0 or pid <= 0:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO material_keys
                (server_id, profession_id, material_key, material)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(sid),
                    int(pid),
                    material_key,
                    material,
                ),
            )
            _write_material_key_buttons(
                conn,
                server,
                profession,
                material_key,
                _as_int_list(material_buttons, 2),
            )

        for server, profession, item_key, name, item_id, buttons, default_mk, category, resources in _iter_item_keys(item_raw):
            sid = int(_ensure_server_id(conn, server) or 0)
            pid = int(_ensure_profession_id(conn, profession) or 0)
            if sid <= 0 or pid <= 0:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO item_keys
                (server_id, profession_id, item_key, name, item_id, default_material_key, category)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(sid),
                    int(pid),
                    item_key,
                    name,
                    int(item_id or 0),
                    default_mk,
                    category,
                ),
            )
            _write_item_key_buttons(conn, server, profession, item_key, _as_int_list(buttons, 2))
            _write_item_resource_costs(conn, server, profession, item_key, resources)

        for row in _iter_recipes(recipes_raw):
            sid = int(_ensure_server_id(conn, row["server"]) or 0)
            pid = int(_ensure_profession_id(conn, row["profession"]) or 0)
            if sid <= 0 or pid <= 0:
                continue
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO recipes
                (recipe_type, server_id, profession_id, name, item_id, material, material_key, deed_key, start_at, stop_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["recipe_type"],
                    int(sid),
                    int(pid),
                    row["name"],
                    int(row["item_id"] or 0),
                    row["material"],
                    row["material_key"],
                    row["deed_key"],
                    row["start_at"],
                    row["stop_at"],
                ),
            )
            _write_recipe_child_lists(
                conn,
                int(getattr(cur, "lastrowid", 0) or 0),
                row["buttons"],
                row["materials"],
                row["material_buttons"],
            )


def init_store():
    conn = _connect()
    try:
        _ensure_schema(conn)
        _bootstrap_from_split_json_if_empty(conn)
    finally:
        conn.close()


def load_recipes():
    conn = _connect()
    try:
        _ensure_schema(conn)
        _bootstrap_from_split_json_if_empty(conn)
        server_by_id = _server_name_map(conn)
        prof_by_id = _profession_name_map(conn)
        cur = conn.execute(
            """
            SELECT id, recipe_type, server_id, profession_id, name, item_id, material, material_key,
                   deed_key, start_at, stop_at
            FROM recipes
            """
        )
        child = _load_recipe_child_lists(conn)
        out = []
        for row in cur.fetchall():
            rid = int(row[0] or 0)
            ch = child.get(rid, {})
            buttons = list(ch.get("buttons") or [])
            materials = list(ch.get("materials") or [])
            material_buttons = list(ch.get("material_buttons") or [])
            out.append(
                {
                    "recipe_type": str(row[1] or ""),
                    "server": str(server_by_id.get(int(row[2] or 0), "") or ""),
                    "profession": str(prof_by_id.get(int(row[3] or 0), "") or ""),
                    "name": str(row[4] or ""),
                    "item_id": int(row[5] or 0),
                    "buttons": buttons,
                    "material": str(row[6] or ""),
                    "material_key": str(row[7] or ""),
                    "materials": materials,
                    "material_buttons": material_buttons,
                    "deed_key": str(row[8] or ""),
                    "start_at": row[9],
                    "stop_at": row[10],
                }
            )
        return out
    finally:
        conn.close()


def save_recipes(rows):
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn:
            if _is_normalized_schema(conn):
                conn.execute("DELETE FROM saved_recipe_navigation_steps")
                conn.execute("DELETE FROM saved_recipe_material_requirements")
                conn.execute("DELETE FROM saved_recipe_material_navigation_steps")
                conn.execute("DELETE FROM saved_craft_recipes")
            else:
                conn.execute("DELETE FROM recipes")
                if _has_columns(conn, "recipe_buttons", ["recipe_id"]):
                    conn.execute("DELETE FROM recipe_buttons")
                if _has_columns(conn, "recipe_materials", ["recipe_id"]):
                    conn.execute("DELETE FROM recipe_materials")
                if _has_columns(conn, "recipe_material_buttons", ["recipe_id"]):
                    conn.execute("DELETE FROM recipe_material_buttons")
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
                if _is_normalized_schema(conn):
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
                else:
                    cur = conn.execute(
                        """
                        INSERT OR REPLACE INTO recipes
                        (recipe_type, server_id, profession_id, name, item_id, material, material_key, deed_key, start_at, stop_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            recipe_type,
                            int(sid),
                            int(pid),
                            recipe_name,
                            int(row.get("item_id", 0) or 0),
                            material,
                            material_key,
                            str(row.get("deed_key", "") or ""),
                            row.get("start_at", None),
                            row.get("stop_at", None),
                        ),
                    )
                    rid = int(getattr(cur, "lastrowid", 0) or 0)
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
    conn = _connect()
    try:
        _ensure_schema(conn)
        _bootstrap_from_split_json_if_empty(conn)
        server_by_id = _server_name_map(conn)
        prof_by_id = _profession_name_map(conn)
        out = {}
        mk_btns = _load_material_key_buttons(conn)
        cur = conn.execute(
            "SELECT server_id, profession_id, material_key, material FROM material_keys"
        )
        for row in cur.fetchall():
            server = str(server_by_id.get(int(row[0] or 0), "") or "")
            profession = str(prof_by_id.get(int(row[1] or 0), "") or "")
            mk = str(row[2] or "")
            material = str(row[3] or "")
            mbtns = []
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            k = (server, profession, mk)
            if k in mk_btns and mk_btns.get(k):
                mbtns = list(mk_btns.get(k) or [])
            out[server][profession]["material_keys"][mk] = {
                "material": material,
                "material_buttons": mbtns,
            }

        ik_btns = _load_item_key_buttons(conn)
        item_resource_costs = _load_item_resource_costs(conn)
        cur = conn.execute(
            "SELECT server_id, profession_id, item_key, name, item_id, default_material_key, category FROM item_keys"
        )
        for row in cur.fetchall():
            server = str(server_by_id.get(int(row[0] or 0), "") or "")
            profession = str(prof_by_id.get(int(row[1] or 0), "") or "")
            item_key = str(row[2] or "")
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            entry = {
                "name": str(row[3] or ""),
                "item_id": int(row[4] or 0),
                "buttons": [],
                "default_material_key": str(row[5] or ""),
                "category": str(row[6] or ""),
                "resources": [],
            }
            key = (server, profession, item_key)
            if key in ik_btns and ik_btns.get(key):
                entry["buttons"] = list(ik_btns.get(key) or [])
            entry["resources"] = list(item_resource_costs.get(key) or [])
            out[server][profession]["item_keys"][item_key] = entry
        return out
    finally:
        conn.close()


def load_resource_item_map():
    conn = _connect()
    try:
        _ensure_schema(conn)
        out = {}
        if not _has_columns(conn, "resources", ["id", "name"]):
            return out
        res_cols = _table_columns(conn, "resources")
        iid_expr = "item_id" if "item_id" in res_cols else "0 AS item_id"
        hue_expr = "hue" if "hue" in res_cols else "NULL AS hue"
        cur = conn.execute(
            "SELECT id, name, " + str(iid_expr) + ", " + str(hue_expr) + " FROM resources"
        )
        for row in cur.fetchall():
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
    finally:
        conn.close()


def save_key_maps(key_maps):
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn:
            if _is_normalized_schema(conn):
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
                                mk_text = str(mk or "")
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
                                ik_text = str(ik or "")
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

            conn.execute("DELETE FROM material_keys")
            conn.execute("DELETE FROM item_keys")
            if _has_columns(conn, "material_key_buttons", ["server_id", "profession_id", "material_key"]):
                conn.execute("DELETE FROM material_key_buttons")
            if _has_columns(conn, "item_key_buttons", ["server_id", "profession_id", "item_key"]):
                conn.execute("DELETE FROM item_key_buttons")
            if _has_columns(conn, "item_resource_costs", ["server_id", "profession_id", "item_key"]):
                conn.execute("DELETE FROM item_resource_costs")
            km = dict(key_maps or {}) if isinstance(key_maps, dict) else {}
            for server, srv_node in km.items():
                if not isinstance(srv_node, dict):
                    continue
                for profession, prof_node in srv_node.items():
                    if not isinstance(prof_node, dict):
                        continue
                    mats = prof_node.get("material_keys", {})
                    if isinstance(mats, dict):
                        for mk, ent in mats.items():
                            if not isinstance(ent, dict):
                                ent = {}
                            sid = int(_ensure_server_id(conn, server) or 0)
                            pid = int(_ensure_profession_id(conn, profession) or 0)
                            if sid <= 0 or pid <= 0:
                                continue
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO material_keys
                                (server_id, profession_id, material_key, material)
                                VALUES (?, ?, ?, ?)
                                """,
                                (
                                    int(sid),
                                    int(pid),
                                    str(mk or ""),
                                    str(ent.get("material", "") or ""),
                                ),
                            )
                            _write_material_key_buttons(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                str(mk or ""),
                                _as_int_list(ent.get("material_buttons", []), 2),
                            )
                    items = prof_node.get("item_keys", {})
                    if isinstance(items, dict):
                        for ik, ent in items.items():
                            if not isinstance(ent, dict):
                                ent = {}
                            sid = int(_ensure_server_id(conn, server) or 0)
                            pid = int(_ensure_profession_id(conn, profession) or 0)
                            if sid <= 0 or pid <= 0:
                                continue
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO item_keys
                                (server_id, profession_id, item_key, name, item_id, default_material_key, category)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    int(sid),
                                    int(pid),
                                    str(ik or ""),
                                    str(ent.get("name", "") or ""),
                                    int(ent.get("item_id", 0) or 0),
                                    str(ent.get("default_material_key", "") or ""),
                                    str(ent.get("category", "") or ""),
                                ),
                            )
                            _write_item_key_buttons(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                str(ik or ""),
                                _as_int_list(ent.get("buttons", []), 2),
                            )
                            _write_item_resource_costs(
                                conn,
                                str(server or ""),
                                str(profession or ""),
                                str(ik or ""),
                                _as_list(ent.get("resources", [])),
                            )
        return True
    finally:
        conn.close()


def health_summary(selected_server=None):
    conn = _connect()
    try:
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
        cur = conn.execute("SELECT value FROM metadata WHERE key='schema_version'")
        row = cur.fetchone()
        try:
            out["schema_version"] = int(row[0] or 0) if row else 0
        except Exception:
            out["schema_version"] = 0

        cur = conn.execute("SELECT recipe_type, COUNT(1) FROM recipes GROUP BY recipe_type")
        for rt, cnt in cur.fetchall():
            out["recipes_by_type"][str(rt or "unknown")] = int(cnt or 0)
            out["recipes_total"] += int(cnt or 0)

        cur = conn.execute(
            """
            SELECT s.name, COUNT(1)
            FROM recipes r
            JOIN servers s ON s.id = r.server_id
            GROUP BY s.name
            """
        )
        for sv, cnt in cur.fetchall():
            out["recipes_by_server"][str(sv or "")] = int(cnt or 0)

        cur = conn.execute("SELECT COUNT(1) FROM material_keys")
        out["material_keys_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM item_keys")
        out["item_keys_total"] = int((cur.fetchone() or [0])[0] or 0)
        cur = conn.execute("SELECT COUNT(1) FROM item_categories")
        out["item_categories_total"] = int((cur.fetchone() or [0])[0] or 0)
        if _has_columns(conn, "resources", ["id", "name"]):
            cur = conn.execute("SELECT COUNT(1) FROM resources")
            out["resources_total"] = int((cur.fetchone() or [0])[0] or 0)
            if "item_id" in _table_columns(conn, "resources"):
                cur = conn.execute("SELECT COUNT(1) FROM resources WHERE coalesce(item_id,0) > 0")
                out["resources_with_item_id"] = int((cur.fetchone() or [0])[0] or 0)
        if _has_columns(conn, "item_resource_costs", ["server_id", "profession_id", "item_key"]):
            cur = conn.execute("SELECT COUNT(1) FROM item_resource_costs")
            out["item_resource_costs_total"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute(
            """
            SELECT COUNT(1) FROM (
                SELECT server_id, profession_id FROM material_keys
                UNION
                SELECT server_id, profession_id FROM item_keys
            ) t
            """
        )
        out["profession_nodes"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute("SELECT COUNT(1) FROM servers")
        out["servers_count"] = int((cur.fetchone() or [0])[0] or 0)

        sel = str(selected_server or "").strip()
        if sel:
            sid = int(_lookup_server_id(conn, sel) or 0)
            if sid <= 0:
                return out
            cur = conn.execute("SELECT COUNT(1) FROM recipes WHERE server_id=?", (int(sid),))
            out["selected_server_recipes"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM material_keys WHERE server_id=?", (int(sid),))
            out["selected_server_material_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM item_keys WHERE server_id=?", (int(sid),))
            out["selected_server_item_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM item_categories WHERE server_id=?", (int(sid),))
            out["selected_server_item_categories"] = int((cur.fetchone() or [0])[0] or 0)
            if _has_columns(conn, "item_resource_costs", ["server_id"]):
                cur = conn.execute("SELECT COUNT(1) FROM item_resource_costs WHERE server_id=?", (int(sid),))
                out["selected_server_item_resource_costs"] = int((cur.fetchone() or [0])[0] or 0)
        return out
    finally:
        conn.close()
