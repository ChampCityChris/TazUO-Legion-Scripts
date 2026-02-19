import json
import os
import sqlite3

DB_FILE = "craftables.db"
SCHEMA_VERSION = 1
RECIPES_JSON_FILE = "recipes.json"
MATERIAL_KEYS_JSON_FILE = "material_keys.json"
ITEM_KEYS_JSON_FILE = "item_keys.json"


def _base_dir():
    try:
        return os.path.dirname(__file__)
    except Exception:
        return os.getcwd()


def _db_path():
    return os.path.join(_base_dir(), DB_FILE)


def _json_path(filename):
    return os.path.join(_base_dir(), filename)


def _connect():
    conn = sqlite3.connect(_db_path(), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


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
            buttons_json TEXT NOT NULL DEFAULT '[]',
            material TEXT NOT NULL DEFAULT '',
            material_key TEXT NOT NULL DEFAULT '',
            materials_json TEXT NOT NULL DEFAULT '[]',
            material_buttons_json TEXT NOT NULL DEFAULT '[]',
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
            material_buttons_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(server, profession, material_key)
        );

        CREATE TABLE IF NOT EXISTS item_keys (
            server TEXT NOT NULL,
            profession TEXT NOT NULL,
            item_key TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            item_id INTEGER NOT NULL DEFAULT 0,
            buttons_json TEXT NOT NULL DEFAULT '[]',
            default_material_key TEXT NOT NULL DEFAULT '',
            resources_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(server, profession, item_key)
        );
        """
    )
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
                (server, profession, material_key, material, material_buttons_json)
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

        for server, profession, item_key, name, item_id, buttons, default_mk, resources in _iter_item_keys(item_raw):
            conn.execute(
                """
                INSERT OR REPLACE INTO item_keys
                (server, profession, item_key, name, item_id, buttons_json, default_material_key, resources_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server,
                    profession,
                    item_key,
                    name,
                    int(item_id or 0),
                    _safe_json_dumps(_as_int_list(buttons, 2), []),
                    default_mk,
                    _safe_json_dumps(_as_list(resources), []),
                ),
            )

        for row in _iter_recipes(recipes_raw):
            conn.execute(
                """
                INSERT OR REPLACE INTO recipes
                (recipe_type, server, profession, name, item_id, buttons_json, material, material_key,
                 materials_json, material_buttons_json, deed_key, start_at, stop_at)
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
    init_store()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT recipe_type, server, profession, name, item_id, buttons_json, material, material_key,
                   materials_json, material_buttons_json, deed_key, start_at, stop_at
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
    init_store()
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM recipes")
            for row in (rows or []):
                if not _is_valid_recipe_row(row):
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO recipes
                    (recipe_type, server, profession, name, item_id, buttons_json, material, material_key,
                     materials_json, material_buttons_json, deed_key, start_at, stop_at)
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
    init_store()
    conn = _connect()
    try:
        out = {}
        cur = conn.execute(
            "SELECT server, profession, material_key, material, material_buttons_json FROM material_keys"
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

        cur = conn.execute(
            "SELECT server, profession, item_key, name, item_id, buttons_json, default_material_key, resources_json FROM item_keys"
        )
        for row in cur.fetchall():
            server = str(row[0] or "")
            profession = str(row[1] or "")
            item_key = str(row[2] or "")
            if server not in out:
                out[server] = {}
            if profession not in out[server]:
                out[server][profession] = {"material_keys": {}, "item_keys": {}}
            out[server][profession]["item_keys"][item_key] = {
                "name": str(row[3] or ""),
                "item_id": int(row[4] or 0),
                "buttons": _safe_json_loads(row[5], []),
                "default_material_key": str(row[6] or ""),
                "resources": _safe_json_loads(row[7], []),
            }
        return out
    finally:
        conn.close()


def save_key_maps(key_maps):
    init_store()
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM material_keys")
            conn.execute("DELETE FROM item_keys")
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
                                (server, profession, material_key, material, material_buttons_json)
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
                                (server, profession, item_key, name, item_id, buttons_json, default_material_key, resources_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    str(server or ""),
                                    str(profession or ""),
                                    str(ik or ""),
                                    str(ent.get("name", "") or ""),
                                    int(ent.get("item_id", 0) or 0),
                                    _safe_json_dumps(_as_int_list(ent.get("buttons", []), 2), []),
                                    str(ent.get("default_material_key", "") or ""),
                                    _safe_json_dumps(_as_list(ent.get("resources", [])), []),
                                ),
                            )
        return True
    finally:
        conn.close()


def health_summary(selected_server=None):
    init_store()
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
            "selected_server": str(selected_server or ""),
            "selected_server_recipes": 0,
            "selected_server_material_keys": 0,
            "selected_server_item_keys": 0,
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
        return out
    finally:
        conn.close()
