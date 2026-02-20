import json
import os
import sqlite3
import time

DB_FILE = "craftables.db"
SCHEMA_VERSION = 4
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
    return os.path.join(_base_dir(), DB_FILE)


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


def _connect():
    db_path = _db_path()
    conn = None
    try:
        conn = _connect_raw(db_path)
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


def _ensure_resource_name(conn, name):
    nm = str(name or "").strip()
    if not nm:
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


def _write_item_resource_costs(conn, server, profession, item_key, resources):
    if not _has_columns(conn, "item_resource_costs", ["server", "profession", "item_key", "slot", "resource_id", "per_item"]):
        return
    if not _has_columns(conn, "resources", ["id", "name"]):
        return
    srv = str(server or "")
    prof = str(profession or "")
    ik = str(item_key or "")
    if not (srv and prof and ik):
        return
    rows = _normalize_resource_rows(resources)
    conn.execute(
        "DELETE FROM item_resource_costs WHERE server=? AND profession=? AND item_key=?",
        (srv, prof, ik),
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
            (server, profession, item_key, slot, resource_id, per_item)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (srv, prof, ik, int(slot), int(rid), int(rr.get("per_item", 0) or 0)),
        )


def _seed_resource_item_ids(conn):
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
    if not _has_columns(conn, "item_resource_costs", ["server", "profession", "item_key", "slot", "resource_id", "per_item"]):
        return out
    if not _has_columns(conn, "resources", ["id", "name"]):
        return out
    cur = conn.execute(
        """
        SELECT irc.server, irc.profession, irc.item_key, irc.slot, irc.per_item, res.name
        FROM item_resource_costs irc
        JOIN resources res ON res.id = irc.resource_id
        ORDER BY irc.server, irc.profession, irc.item_key, irc.slot
        """
    )
    for row in cur.fetchall():
        srv = str(row[0] or "")
        prof = str(row[1] or "")
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
    if not _has_columns(conn, "item_resource_costs", ["server", "profession", "item_key", "slot", "resource_id", "per_item"]):
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


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_type TEXT NOT NULL,
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            name TEXT NOT NULL,
            item_id INTEGER NOT NULL DEFAULT 0,
            buttons TEXT NOT NULL DEFAULT '[]',
            material TEXT NOT NULL DEFAULT '',
            material_key TEXT NOT NULL DEFAULT '',
            materials TEXT NOT NULL DEFAULT '[]',
            material_buttons TEXT NOT NULL DEFAULT '[]',
            deed_key TEXT NOT NULL DEFAULT '',
            start_at REAL,
            stop_at REAL,
            UNIQUE(recipe_type, server, profession, name, material_key)
        );

        CREATE INDEX IF NOT EXISTS idx_recipes_lookup
            ON recipes(recipe_type, server, profession, name);

        CREATE TABLE IF NOT EXISTS material_keys (
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            material_key TEXT NOT NULL,
            material TEXT NOT NULL DEFAULT '',
            material_buttons TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(server, profession, material_key)
        );

        CREATE TABLE IF NOT EXISTS item_keys (
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            item_key TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            item_id INTEGER NOT NULL DEFAULT 0,
            buttons TEXT NOT NULL DEFAULT '[]',
            default_material_key TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            resources TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(server, profession, item_key)
        );

        CREATE TABLE IF NOT EXISTS item_categories (
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            category TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(server, profession, category)
        );

        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            item_id INTEGER NOT NULL DEFAULT 0,
            hue INTEGER
        );

        CREATE TABLE IF NOT EXISTS item_resource_costs (
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            item_key TEXT NOT NULL,
            slot INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            per_item INTEGER NOT NULL,
            PRIMARY KEY(server, profession, item_key, slot)
        );

        CREATE INDEX IF NOT EXISTS idx_item_resource_costs_lookup
            ON item_resource_costs(server, profession, item_key);
        """
    )
    # Backward-compatible migration for existing databases.
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
        if "buttons" not in col_names:
            conn.execute("ALTER TABLE item_keys ADD COLUMN buttons TEXT NOT NULL DEFAULT '[]'")
        if "resources" not in col_names:
            conn.execute("ALTER TABLE item_keys ADD COLUMN resources TEXT NOT NULL DEFAULT '[]'")

        recipe_cols = _table_columns(conn, "recipes")
        if "buttons" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN buttons TEXT NOT NULL DEFAULT '[]'")
        if "materials" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN materials TEXT NOT NULL DEFAULT '[]'")
        if "material_buttons" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN material_buttons TEXT NOT NULL DEFAULT '[]'")

        mat_cols = _table_columns(conn, "material_keys")
        if "material_buttons" not in mat_cols:
            conn.execute("ALTER TABLE material_keys ADD COLUMN material_buttons TEXT NOT NULL DEFAULT '[]'")
        res_cols = _table_columns(conn, "resources")
        if "item_id" not in res_cols:
            conn.execute("ALTER TABLE resources ADD COLUMN item_id INTEGER NOT NULL DEFAULT 0")
        if "hue" not in res_cols:
            conn.execute("ALTER TABLE resources ADD COLUMN hue INTEGER")
    except Exception:
        pass
    _seed_resource_item_ids(conn)
    _bootstrap_item_resource_costs_from_item_keys(conn)
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
            conn.execute(
                """
                INSERT OR REPLACE INTO material_keys
                (server, profession, material_key, material, material_buttons)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    server,
                    profession,
                    material_key,
                    material,
                    _safe_json_dumps(_as_int_list(material_buttons, 2), []),
                ),
            )

        for server, profession, item_key, name, item_id, buttons, default_mk, category, resources in _iter_item_keys(item_raw):
            conn.execute(
                """
                INSERT OR REPLACE INTO item_keys
                (server, profession, item_key, name, item_id, buttons, default_material_key, category, resources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server,
                    profession,
                    item_key,
                    name,
                    int(item_id or 0),
                    _safe_json_dumps(_as_int_list(buttons, 2), []),
                    default_mk,
                    category,
                    _safe_json_dumps(_as_list(resources), []),
                ),
            )
            _write_item_resource_costs(conn, server, profession, item_key, resources)

        for row in _iter_recipes(recipes_raw):
            conn.execute(
                """
                INSERT OR REPLACE INTO recipes
                (recipe_type, server, profession, name, item_id, buttons, material, material_key,
                 materials, material_buttons, deed_key, start_at, stop_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["recipe_type"],
                    row["server"],
                    row["profession"],
                    row["name"],
                    int(row["item_id"] or 0),
                    _safe_json_dumps(_as_int_list(row["buttons"]), []),
                    row["material"],
                    row["material_key"],
                    _safe_json_dumps(_as_list(row["materials"]), []),
                    _safe_json_dumps(_as_int_list(row["material_buttons"], 2), []),
                    row["deed_key"],
                    row["start_at"],
                    row["stop_at"],
                ),
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
        cur = conn.execute(
            """
            SELECT recipe_type, server, profession, name, item_id, buttons, material, material_key,
                   materials, material_buttons, deed_key, start_at, stop_at
            FROM recipes
            """
        )
        out = []
        for row in cur.fetchall():
            out.append(
                {
                    "recipe_type": str(row[0] or ""),
                    "server": str(row[1] or ""),
                    "profession": str(row[2] or ""),
                    "name": str(row[3] or ""),
                    "item_id": int(row[4] or 0),
                    "buttons": _safe_json_loads(row[5], []),
                    "material": str(row[6] or ""),
                    "material_key": str(row[7] or ""),
                    "materials": _safe_json_loads(row[8], []),
                    "material_buttons": _safe_json_loads(row[9], []),
                    "deed_key": str(row[10] or ""),
                    "start_at": row[11],
                    "stop_at": row[12],
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
            conn.execute("DELETE FROM recipes")
            for row in (rows or []):
                if not _is_valid_recipe_row(row):
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO recipes
                    (recipe_type, server, profession, name, item_id, buttons, material, material_key,
                     materials, material_buttons, deed_key, start_at, stop_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row.get("recipe_type", "") or ""),
                        str(row.get("server", "") or ""),
                        str(row.get("profession", "") or ""),
                        str(row.get("name", "") or ""),
                        int(row.get("item_id", 0) or 0),
                        _safe_json_dumps(_as_int_list(row.get("buttons", [])), []),
                        str(row.get("material", "") or ""),
                        str(row.get("material_key", "") or ""),
                        _safe_json_dumps(_as_list(row.get("materials", [])), []),
                        _safe_json_dumps(_as_int_list(row.get("material_buttons", []), 2), []),
                        str(row.get("deed_key", "") or ""),
                        row.get("start_at", None),
                        row.get("stop_at", None),
                    ),
                )
        return True
    finally:
        conn.close()


def load_key_maps():
    conn = _connect()
    try:
        _ensure_schema(conn)
        _bootstrap_from_split_json_if_empty(conn)
        out = {}
        cur = conn.execute(
            "SELECT server, profession, material_key, material, material_buttons FROM material_keys"
        )
        for row in cur.fetchall():
            server = str(row[0] or "")
            profession = str(row[1] or "")
            mk = str(row[2] or "")
            material = str(row[3] or "")
            mbtns = _safe_json_loads(row[4], [])
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            out[server][profession]["material_keys"][mk] = {
                "material": material,
                "material_buttons": mbtns,
            }

        item_resource_costs = _load_item_resource_costs(conn)
        cur = conn.execute(
            "SELECT server, profession, item_key, name, item_id, buttons, default_material_key, category, resources FROM item_keys"
        )
        for row in cur.fetchall():
            server = str(row[0] or "")
            profession = str(row[1] or "")
            item_key = str(row[2] or "")
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            entry = {
                "name": str(row[3] or ""),
                "item_id": int(row[4] or 0),
                "buttons": _safe_json_loads(row[5], []),
                "default_material_key": str(row[6] or ""),
                "category": str(row[7] or ""),
                "resources": _safe_json_loads(row[8], []),
            }
            key = (server, profession, item_key)
            if key in item_resource_costs and item_resource_costs.get(key):
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
            conn.execute("DELETE FROM material_keys")
            conn.execute("DELETE FROM item_keys")
            if _has_columns(conn, "item_resource_costs", ["server", "profession", "item_key"]):
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
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO material_keys
                                (server, profession, material_key, material, material_buttons)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    str(server or ""),
                                    str(profession or ""),
                                    str(mk or ""),
                                    str(ent.get("material", "") or ""),
                                    _safe_json_dumps(_as_int_list(ent.get("material_buttons", []), 2), []),
                                ),
                            )
                    items = prof_node.get("item_keys", {})
                    if isinstance(items, dict):
                        for ik, ent in items.items():
                            if not isinstance(ent, dict):
                                ent = {}
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO item_keys
                                (server, profession, item_key, name, item_id, buttons, default_material_key, category, resources)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    str(server or ""),
                                    str(profession or ""),
                                    str(ik or ""),
                                    str(ent.get("name", "") or ""),
                                    int(ent.get("item_id", 0) or 0),
                                    _safe_json_dumps(_as_int_list(ent.get("buttons", []), 2), []),
                                    str(ent.get("default_material_key", "") or ""),
                                    str(ent.get("category", "") or ""),
                                    _safe_json_dumps(_as_list(ent.get("resources", [])), []),
                                ),
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

        cur = conn.execute("SELECT server, COUNT(1) FROM recipes GROUP BY server")
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
        if _has_columns(conn, "item_resource_costs", ["server", "profession", "item_key"]):
            cur = conn.execute("SELECT COUNT(1) FROM item_resource_costs")
            out["item_resource_costs_total"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute(
            """
            SELECT COUNT(1) FROM (
                SELECT server, profession FROM material_keys
                UNION
                SELECT server, profession FROM item_keys
            ) t
            """
        )
        out["profession_nodes"] = int((cur.fetchone() or [0])[0] or 0)

        cur = conn.execute(
            """
            SELECT COUNT(1) FROM (
                SELECT server FROM material_keys
                UNION
                SELECT server FROM item_keys
                UNION
                SELECT server FROM recipes
            ) t
            """
        )
        out["servers_count"] = int((cur.fetchone() or [0])[0] or 0)

        sel = str(selected_server or "").strip()
        if sel:
            cur = conn.execute("SELECT COUNT(1) FROM recipes WHERE server=?", (sel,))
            out["selected_server_recipes"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM material_keys WHERE server=?", (sel,))
            out["selected_server_material_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM item_keys WHERE server=?", (sel,))
            out["selected_server_item_keys"] = int((cur.fetchone() or [0])[0] or 0)
            cur = conn.execute("SELECT COUNT(1) FROM item_categories WHERE server=?", (sel,))
            out["selected_server_item_categories"] = int((cur.fetchone() or [0])[0] or 0)
            if _has_columns(conn, "item_resource_costs", ["server"]):
                cur = conn.execute("SELECT COUNT(1) FROM item_resource_costs WHERE server=?", (sel,))
                out["selected_server_item_resource_costs"] = int((cur.fetchone() or [0])[0] or 0)
        return out
    finally:
        conn.close()
