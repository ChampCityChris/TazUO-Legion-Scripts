import API
import ast
import json
import os
import sqlite3
import sys
import traceback

"""
recipeedit

In-game editor for saved BOD/training recipes in Databases/craftables.db.
Selection key:
- server
- profession
- recipe_type
- recipe_name
- material_key

Editable fields:
- deed signature text (saved_craft_recipes.deed_signature_text)
- material requirement rows (saved_recipe_material_requirements projection)
- craftable item linkage by selecting an item name from craftable_items in the same context

Manual in-game validation checklist:
1) Open BODAssist and click Edit Recipe.
2) Select a known recipe key and change deed signature + one material row.
3) Save and reopen editor; verify values persisted.
4) Select a different craftable item in same context and save.
5) Confirm log shows start, save action, and stop summary.

Expected log output (success):
- "recipeedit start"
- "recipeedit save success key=..."
- "recipeedit stop reason=saved"

Expected log output (failure):
- "recipeedit save failed ..."
- "recipeedit stop reason=error"
"""

# 1) Config
REQUEST_KEY = "recipe_edit_request"
RESULT_KEY = "recipe_edit_result"
DEBUG_LOG_FILE = "recipeedit.debug.log"
LOGS_DIR = r"F:\Games\Ultima_Online\Clients\TazUO\TazUO\LegionScripts\Logs"
SQLITE_CONNECT_TIMEOUT_S = 2.5
SQLITE_BUSY_TIMEOUT_MS = 2500
MAX_MATERIAL_ROWS = 6
EMPTY_LABEL = "<none>"

# 2) Logging


def _write_debug_log(msg):
    try:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(LOGS_DIR, exist_ok=True)
        path = os.path.join(LOGS_DIR, DEBUG_LOG_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {str(msg)}\n")
    except Exception:
        pass


def _say(msg, hue=88):
    try:
        API.SysMsg(str(msg or ""), hue)
    except Exception:
        pass


# 3) Runtime state
EDITOR_GUMP = None
EDITOR_INPUTS = {}
SCRIPT_EXIT_REQUESTED = False
STOP_REASON = "user"

DATA_ROWS = []
CURRENT_ROW_KEY = None

SERVER_VALUES = []
PROF_VALUES = []
TYPE_VALUES = []
NAME_VALUES = []
MATERIAL_VALUES = []

SERVER_IDX = 0
PROF_IDX = 0
TYPE_IDX = 0
NAME_IDX = 0
MATERIAL_IDX = 0

RECIPE_STORE = None


# 4) API adapters / wrappers


def _should_autostart_main():
    # TODO (human): add any additional runner contexts if needed.
    return str(globals().get("__name__", "")) in ("__main__", "<module>")


def _to_index(value):
    try:
        return int(value)
    except Exception:
        try:
            return int(getattr(value, "SelectedIndex", 0))
        except Exception:
            return 0


def _clamp_idx(idx, size):
    if int(size or 0) <= 0:
        return 0
    i = int(idx or 0)
    if i < 0:
        return 0
    if i >= int(size):
        return int(size) - 1
    return i


def _norm_text(value):
    return str(value or "").strip().lower()


def _parse_item_id(value):
    text = str(value or "").strip().lower()
    if not text:
        return 0
    if text.startswith("0x"):
        try:
            return int(text, 16)
        except Exception:
            return 0
    try:
        return int(text)
    except Exception:
        return 0


def _material_base_from_key(material_key, fallback="ingot"):
    mk = _norm_text(material_key)
    if mk in ("cloth", "leather", "board", "feather"):
        return mk
    if mk.startswith("ingot"):
        return "ingot"
    return str(fallback or "ingot").strip().lower() or "ingot"


def _db_candidate_path():
    if RECIPE_STORE is None:
        return ""
    try:
        p = str(RECIPE_STORE._db_path() or "").strip()
    except Exception:
        p = ""
    if not p:
        return ""
    return os.path.normpath(p)


def _has_columns(conn, table_name, needed):
    cols = set()
    try:
        cur = conn.execute("PRAGMA table_info(" + str(table_name) + ")")
        for row in cur.fetchall() or []:
            try:
                cols.add(str(row[1] or "").strip().lower())
            except Exception:
                pass
    except Exception:
        return False
    for name in needed or []:
        if str(name or "").strip().lower() not in cols:
            return False
    return True


def _set_persistent_json(key, payload):
    text = json.dumps(payload or {})
    try:
        API.SavePersistentVar(str(key), text, API.PersistentVar.Char)
        return True
    except Exception:
        try:
            API.SavePersistentVar(str(key), text)
            return True
        except Exception:
            return False


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
        return {}
    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return {}


# 5) Prechecks


def _init_recipe_store():
    global RECIPE_STORE
    script_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
    util_dir = script_dir
    if os.path.basename(str(util_dir or "")).lower() != "utilities":
        cand = os.path.join(script_dir, "Utilities")
        if os.path.isdir(cand):
            util_dir = cand
    project_root = util_dir
    while project_root and os.path.basename(str(project_root or "")).lower() in ("resources", "utilities", "skills", "scripts"):
        project_root = os.path.dirname(project_root)
    if util_dir and util_dir not in sys.path:
        sys.path.insert(0, util_dir)
    try:
        import RecipeStore as recipe_store
        RECIPE_STORE = recipe_store
        try:
            RECIPE_STORE.set_base_dir(project_root or util_dir)
        except Exception:
            pass
        return True
    except Exception:
        RECIPE_STORE = None
        return False


def _normalize_material_payload(raw, fallback_material="ingot"):
    parsed = None
    if isinstance(raw, dict):
        parsed = dict(raw)
    elif isinstance(raw, str):
        text = str(raw or "").strip()
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None
            if not isinstance(parsed, dict):
                parts = [p.strip() for p in text.split(":")]
                if parts and parts[0]:
                    parsed = {
                        "material": _norm_text(parts[0]),
                        "item_id": _parse_item_id(parts[1]) if len(parts) > 1 else 0,
                        "min_in_pack": int(parts[2]) if len(parts) > 2 and str(parts[2]).strip().isdigit() else 0,
                        "pull_amount": int(parts[3]) if len(parts) > 3 and str(parts[3]).strip().isdigit() else 0,
                    }
    if not isinstance(parsed, dict):
        return None
    material_name = _norm_text(parsed.get("material", "") or parsed.get("material_name", ""))
    if not material_name:
        material_name = _norm_text(fallback_material or "ingot") or "ingot"
    try:
        min_in_pack = int(parsed.get("min_in_pack", parsed.get("required_in_pack_quantity", 0)) or 0)
    except Exception:
        min_in_pack = 0
    try:
        pull_amount = int(parsed.get("pull_amount", parsed.get("pull_quantity", 0)) or 0)
    except Exception:
        pull_amount = 0
    item_id = _parse_item_id(parsed.get("item_id", parsed.get("game_item_id_override", 0)))
    out = {
        "material": material_name,
        "min_in_pack": int(max(0, min_in_pack)),
        "pull_amount": int(max(0, pull_amount)),
    }
    if int(item_id) > 0:
        out["item_id"] = int(item_id)
    return out


def _normalize_recipe_row(row):
    if not isinstance(row, dict):
        return None
    name = str(row.get("name", "") or "").strip()
    server = str(row.get("server", "") or "").strip()
    profession = str(row.get("profession", "") or "").strip()
    recipe_type = _norm_text(row.get("recipe_type", "bod")) or "bod"
    material_key = _norm_text(row.get("material_key", ""))
    material = _norm_text(row.get("material", "ingot")) or "ingot"
    if not (name and server and profession and recipe_type):
        return None
    if not material_key:
        material_key = _material_base_from_key(material, material)
    materials = []
    for entry in list(row.get("materials", []) or []):
        normalized = _normalize_material_payload(entry, material)
        if normalized:
            materials.append(normalized)
    if not materials:
        materials.append({"material": material, "min_in_pack": 0, "pull_amount": 0})
    return {
        "name": name,
        "server": server,
        "profession": profession,
        "recipe_type": recipe_type,
        "material": material,
        "material_key": material_key,
        "deed_key": str(row.get("deed_key", "") or ""),
        "item_id": int(row.get("item_id", 0) or 0),
        "buttons": [int(x) for x in (row.get("buttons", []) or []) if int(x) > 0],
        "material_buttons": [int(x) for x in (row.get("material_buttons", []) or []) if int(x) > 0],
        "start_at": row.get("start_at", None),
        "stop_at": row.get("stop_at", None),
        "materials": materials,
    }


def _row_key(row):
    return (
        _norm_text(row.get("server", "")),
        _norm_text(row.get("profession", "")),
        _norm_text(row.get("recipe_type", "")),
        _norm_text(row.get("name", "")),
        _norm_text(row.get("material_key", "")),
    )


def _read_recipe_rows():
    if RECIPE_STORE is None:
        return []
    try:
        raw_rows = list(RECIPE_STORE.load_recipes() or [])
    except Exception as ex:
        _say(f"recipeedit: recipe load failed: {ex}", 33)
        _write_debug_log(f"recipeedit load failed: {ex}")
        return []
    rows = []
    for raw in raw_rows:
        normalized = _normalize_recipe_row(raw)
        if normalized:
            rows.append(normalized)
    return rows


def _encode_material_rows(rows):
    out = []
    for entry in list(rows or []):
        normalized = _normalize_material_payload(entry)
        if not normalized:
            continue
        out.append(json.dumps(normalized, separators=(",", ":")))
    return out


def _write_recipe_rows(rows):
    if RECIPE_STORE is None:
        return False
    try:
        return bool(RECIPE_STORE.save_recipes(list(rows or [])))
    except Exception as ex:
        _say(f"recipeedit: recipe save failed: {ex}", 33)
        _write_debug_log(f"recipeedit save failed: {ex}")
        return False


def _query_resource_names():
    path = _db_candidate_path()
    if not path or not os.path.exists(path):
        return []
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
        if not _has_columns(conn, "resource_catalog", ["resource_name"]):
            return []
        cur = conn.execute(
            """
            SELECT resource_name
            FROM resource_catalog
            WHERE trim(coalesce(resource_name,'')) <> ''
            ORDER BY resource_name COLLATE NOCASE
            """
        )
        rows = cur.fetchall() or []
        out = []
        for row in rows:
            name = str(row["resource_name"] or "").strip()
            if name:
                out.append(name)
        return out
    except Exception:
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _query_craftable_item_names(server_name, profession_name):
    server = str(server_name or "").strip()
    profession = str(profession_name or "").strip()
    if not (server and profession):
        return []
    path = _db_candidate_path()
    if not path or not os.path.exists(path):
        return []
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=float(SQLITE_CONNECT_TIMEOUT_S))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=" + str(int(SQLITE_BUSY_TIMEOUT_MS)))
        if not (
            _has_columns(conn, "craftable_items", ["craftable_item_id", "context_id", "item_display_name"])
            and _has_columns(conn, "crafting_contexts", ["context_id", "game_server_id", "profession_id"])
            and _has_columns(conn, "game_servers", ["game_server_id", "server_name"])
            and _has_columns(conn, "crafting_professions", ["profession_id", "profession_name"])
        ):
            return []
        cur = conn.execute(
            """
            SELECT ci.item_display_name
            FROM craftable_items ci
            JOIN crafting_contexts cc ON cc.context_id = ci.context_id
            JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
            JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
            WHERE lower(coalesce(gs.server_name,''))=lower(?)
              AND lower(coalesce(cp.profession_name,''))=lower(?)
              AND trim(coalesce(ci.item_display_name,'')) <> ''
            ORDER BY ci.item_display_name COLLATE NOCASE
            """,
            (server, profession),
        )
        rows = cur.fetchall() or []
        out = []
        for row in rows:
            item_name = str(row["item_display_name"] or "").strip()
            if item_name:
                out.append(item_name)
        return out
    except Exception:
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _list_unique(values):
    seen = set()
    out = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    out.sort(key=lambda x: x.lower())
    return out


def _dropdown_value(options, idx):
    opts = list(options or [])
    if not opts:
        return ""
    i = _clamp_idx(idx, len(opts))
    return str(opts[i] or "")


def _refresh_selection_options():
    global SERVER_VALUES, PROF_VALUES, TYPE_VALUES, NAME_VALUES, MATERIAL_VALUES
    global SERVER_IDX, PROF_IDX, TYPE_IDX, NAME_IDX, MATERIAL_IDX, CURRENT_ROW_KEY

    if not DATA_ROWS:
        SERVER_VALUES = [EMPTY_LABEL]
        PROF_VALUES = [EMPTY_LABEL]
        TYPE_VALUES = [EMPTY_LABEL]
        NAME_VALUES = [EMPTY_LABEL]
        MATERIAL_VALUES = [EMPTY_LABEL]
        SERVER_IDX = 0
        PROF_IDX = 0
        TYPE_IDX = 0
        NAME_IDX = 0
        MATERIAL_IDX = 0
        CURRENT_ROW_KEY = None
        return

    SERVER_VALUES = _list_unique([r.get("server", "") for r in DATA_ROWS])
    SERVER_IDX = _clamp_idx(SERVER_IDX, len(SERVER_VALUES))
    selected_server = _dropdown_value(SERVER_VALUES, SERVER_IDX)

    server_rows = [r for r in DATA_ROWS if _norm_text(r.get("server", "")) == _norm_text(selected_server)]
    PROF_VALUES = _list_unique([r.get("profession", "") for r in server_rows])
    PROF_IDX = _clamp_idx(PROF_IDX, len(PROF_VALUES))
    selected_prof = _dropdown_value(PROF_VALUES, PROF_IDX)

    prof_rows = [
        r for r in server_rows if _norm_text(r.get("profession", "")) == _norm_text(selected_prof)
    ]
    TYPE_VALUES = _list_unique([r.get("recipe_type", "") for r in prof_rows])
    TYPE_IDX = _clamp_idx(TYPE_IDX, len(TYPE_VALUES))
    selected_type = _dropdown_value(TYPE_VALUES, TYPE_IDX)

    type_rows = [
        r for r in prof_rows if _norm_text(r.get("recipe_type", "")) == _norm_text(selected_type)
    ]
    NAME_VALUES = _list_unique([r.get("name", "") for r in type_rows])
    NAME_IDX = _clamp_idx(NAME_IDX, len(NAME_VALUES))
    selected_name = _dropdown_value(NAME_VALUES, NAME_IDX)

    name_rows = [
        r for r in type_rows if _norm_text(r.get("name", "")) == _norm_text(selected_name)
    ]
    MATERIAL_VALUES = _list_unique([r.get("material_key", "") for r in name_rows])
    MATERIAL_IDX = _clamp_idx(MATERIAL_IDX, len(MATERIAL_VALUES))
    selected_material_key = _dropdown_value(MATERIAL_VALUES, MATERIAL_IDX)

    row = None
    for candidate in name_rows:
        if _norm_text(candidate.get("material_key", "")) == _norm_text(selected_material_key):
            row = candidate
            break
    if row is None and name_rows:
        row = name_rows[0]
    CURRENT_ROW_KEY = _row_key(row) if isinstance(row, dict) else None


def _current_row():
    if CURRENT_ROW_KEY is None:
        return None
    for row in DATA_ROWS:
        if _row_key(row) == CURRENT_ROW_KEY:
            return dict(row)
    return None


# 6) Recovery logic (gump/UI)


def _close_editor():
    global EDITOR_GUMP, EDITOR_INPUTS
    if EDITOR_GUMP is not None:
        try:
            EDITOR_GUMP.Dispose()
        except Exception:
            pass
    EDITOR_GUMP = None
    EDITOR_INPUTS = {}


def _selected_dropdown_text(dd, options):
    opts = list(options or [])
    try:
        idx = int(dd.GetSelectedIndex()) if dd else -1
    except Exception:
        idx = -1
    if 0 <= idx < len(opts):
        return str(opts[idx] or "").strip()
    return ""


def _collect_material_rows(material_rows):
    collected = []
    for row in list(material_rows or []):
        if not isinstance(row, dict):
            continue
        dd = row.get("material")
        opts = list(row.get("options", []) or [])
        material_name = _selected_dropdown_text(dd, opts)
        if not material_name or _norm_text(material_name) == _norm_text(EMPTY_LABEL):
            continue
        min_tb = row.get("min_in_pack")
        pull_tb = row.get("pull_amount")
        item_tb = row.get("item_id")
        try:
            min_in_pack = int(str((min_tb.Text if min_tb else "") or "0").strip() or 0)
        except Exception:
            min_in_pack = 0
        try:
            pull_amount = int(str((pull_tb.Text if pull_tb else "") or "0").strip() or 0)
        except Exception:
            pull_amount = 0
        item_id = _parse_item_id(str((item_tb.Text if item_tb else "") or "").strip())
        payload = {
            "material": _norm_text(material_name),
            "min_in_pack": int(max(0, min_in_pack)),
            "pull_amount": int(max(0, pull_amount)),
        }
        if int(item_id) > 0:
            payload["item_id"] = int(item_id)
        collected.append(payload)
    return collected


def _set_result(status, extra=None):
    payload = {
        "status": str(status or ""),
        "key": list(CURRENT_ROW_KEY) if isinstance(CURRENT_ROW_KEY, tuple) else None,
    }
    if isinstance(extra, dict):
        payload.update(dict(extra))
    _set_persistent_json(RESULT_KEY, payload)


# 7) Core actions


def _on_server(idx):
    global SERVER_IDX, PROF_IDX, TYPE_IDX, NAME_IDX, MATERIAL_IDX
    SERVER_IDX = _to_index(idx)
    PROF_IDX = 0
    TYPE_IDX = 0
    NAME_IDX = 0
    MATERIAL_IDX = 0
    _open_editor()


def _on_profession(idx):
    global PROF_IDX, TYPE_IDX, NAME_IDX, MATERIAL_IDX
    PROF_IDX = _to_index(idx)
    TYPE_IDX = 0
    NAME_IDX = 0
    MATERIAL_IDX = 0
    _open_editor()


def _on_type(idx):
    global TYPE_IDX, NAME_IDX, MATERIAL_IDX
    TYPE_IDX = _to_index(idx)
    NAME_IDX = 0
    MATERIAL_IDX = 0
    _open_editor()


def _on_name(idx):
    global NAME_IDX, MATERIAL_IDX
    NAME_IDX = _to_index(idx)
    MATERIAL_IDX = 0
    _open_editor()


def _on_material_key(idx):
    global MATERIAL_IDX
    MATERIAL_IDX = _to_index(idx)
    _open_editor()


def _save_and_exit():
    global DATA_ROWS, SCRIPT_EXIT_REQUESTED, STOP_REASON
    current = _current_row()
    if not isinstance(current, dict):
        _say("recipeedit: no selected recipe row.", 33)
        return

    controls = EDITOR_INPUTS or {}
    craftable_options = list(controls.get("craftable_options", []) or [])
    craftable_dd = controls.get("craftable")
    selected_craftable = _selected_dropdown_text(craftable_dd, craftable_options)
    if not selected_craftable or _norm_text(selected_craftable) == _norm_text(EMPTY_LABEL):
        _say("recipeedit: select a craftable item.", 33)
        return

    deed_box = controls.get("deed_text")
    deed_text = str((deed_box.Text if deed_box else "") or "")

    material_rows = _collect_material_rows(controls.get("material_rows", []))
    if not material_rows:
        _say("recipeedit: at least one material row is required.", 33)
        return

    updated = dict(current)
    updated["name"] = str(selected_craftable)
    updated["deed_key"] = deed_text
    updated["materials"] = _encode_material_rows(material_rows)

    # Keep material family coherent with selected key.
    updated["material"] = _material_base_from_key(
        updated.get("material_key", ""),
        updated.get("material", "ingot"),
    )

    old_key = tuple(CURRENT_ROW_KEY or ())
    new_key = _row_key(updated)

    out_rows = []
    replaced = False
    for row in DATA_ROWS:
        key = _row_key(row)
        if key == old_key and not replaced:
            out_rows.append(updated)
            replaced = True
            continue
        if key == new_key and key != old_key:
            # If key changed to one that already exists, keep the newly edited row.
            continue
        out_rows.append(row)

    if not replaced:
        _say("recipeedit: selected recipe row no longer exists. Reload and retry.", 33)
        _write_debug_log(f"recipeedit save failed: missing old key {old_key}")
        return

    if not _write_recipe_rows(out_rows):
        _write_debug_log(f"recipeedit save failed old_key={old_key} new_key={new_key}")
        _say("recipeedit: save failed.", 33)
        STOP_REASON = "error"
        _set_result("error", {"error": "save_failed"})
        return

    DATA_ROWS = _read_recipe_rows()
    _write_debug_log(f"recipeedit save success key={new_key}")
    _say(
        f"recipe updated: {updated.get('recipe_type', '')} | {updated.get('profession', '')} | {updated.get('name', '')}",
        88,
    )
    STOP_REASON = "saved"
    _set_result("saved", {"old_key": list(old_key), "new_key": list(new_key)})
    _close_editor()
    SCRIPT_EXIT_REQUESTED = True


def _cancel_and_exit():
    global SCRIPT_EXIT_REQUESTED, STOP_REASON
    STOP_REASON = "cancel"
    _set_result("cancel")
    _close_editor()
    SCRIPT_EXIT_REQUESTED = True


def _reload_and_rebuild():
    global DATA_ROWS
    DATA_ROWS = _read_recipe_rows()
    _open_editor()


def _open_editor():
    global EDITOR_GUMP, EDITOR_INPUTS
    _close_editor()
    _refresh_selection_options()

    row = _current_row()

    g = API.CreateGump(True, True, False)
    w = 840
    h = 760
    g.SetRect(500, 120, w, h)
    try:
        g.SetInScreen()
    except Exception:
        pass

    bg = API.CreateGumpColorBox(0.78, "#111923")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("Recipe Editor (Saved Recipes)", 16, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 8)
    g.Add(title)

    y = 42
    l_server = API.CreateGumpTTFLabel("Server", 12, "#E7F0FA", "alagard", "left", 70)
    l_server.SetPos(12, y)
    g.Add(l_server)
    dd_server = API.CreateDropDown(170, list(SERVER_VALUES or [EMPTY_LABEL]), _clamp_idx(SERVER_IDX, len(SERVER_VALUES or [EMPTY_LABEL])))
    dd_server.SetPos(78, y - 2)
    g.Add(dd_server)
    dd_server.OnDropDownOptionSelected(_on_server)

    l_prof = API.CreateGumpTTFLabel("Profession", 12, "#E7F0FA", "alagard", "left", 90)
    l_prof.SetPos(270, y)
    g.Add(l_prof)
    dd_prof = API.CreateDropDown(180, list(PROF_VALUES or [EMPTY_LABEL]), _clamp_idx(PROF_IDX, len(PROF_VALUES or [EMPTY_LABEL])))
    dd_prof.SetPos(350, y - 2)
    g.Add(dd_prof)
    dd_prof.OnDropDownOptionSelected(_on_profession)

    l_type = API.CreateGumpTTFLabel("Type", 12, "#E7F0FA", "alagard", "left", 50)
    l_type.SetPos(550, y)
    g.Add(l_type)
    dd_type = API.CreateDropDown(120, list(TYPE_VALUES or [EMPTY_LABEL]), _clamp_idx(TYPE_IDX, len(TYPE_VALUES or [EMPTY_LABEL])))
    dd_type.SetPos(590, y - 2)
    g.Add(dd_type)
    dd_type.OnDropDownOptionSelected(_on_type)

    y += 32
    l_name = API.CreateGumpTTFLabel("Recipe", 12, "#E7F0FA", "alagard", "left", 70)
    l_name.SetPos(12, y)
    g.Add(l_name)
    dd_name = API.CreateDropDown(430, list(NAME_VALUES or [EMPTY_LABEL]), _clamp_idx(NAME_IDX, len(NAME_VALUES or [EMPTY_LABEL])))
    dd_name.SetPos(78, y - 2)
    g.Add(dd_name)
    dd_name.OnDropDownOptionSelected(_on_name)

    l_mk = API.CreateGumpTTFLabel("Material Key", 12, "#E7F0FA", "alagard", "left", 90)
    l_mk.SetPos(530, y)
    g.Add(l_mk)
    dd_mk = API.CreateDropDown(180, list(MATERIAL_VALUES or [EMPTY_LABEL]), _clamp_idx(MATERIAL_IDX, len(MATERIAL_VALUES or [EMPTY_LABEL])))
    dd_mk.SetPos(622, y - 2)
    g.Add(dd_mk)
    dd_mk.OnDropDownOptionSelected(_on_material_key)

    y += 34
    if not isinstance(row, dict):
        msg = API.CreateGumpTTFLabel("No saved recipes found.", 14, "#FFAAAA", "alagard", "left", 320)
        msg.SetPos(12, y)
        g.Add(msg)

        close_btn = API.CreateSimpleButton("Close", 80, 20)
        close_btn.SetPos(380, h - 34)
        g.Add(close_btn)
        API.AddControlOnClick(close_btn, _cancel_and_exit)

        API.AddGump(g)
        EDITOR_GUMP = g
        EDITOR_INPUTS = {
            "server": dd_server,
            "profession": dd_prof,
            "recipe_type": dd_type,
            "name": dd_name,
            "material_key": dd_mk,
        }
        _set_result("opened")
        return

    l_key = API.CreateGumpTTFLabel(
        f"Selected Key: {row.get('server','')} | {row.get('profession','')} | {row.get('recipe_type','')} | {row.get('name','')} | {row.get('material_key','')}",
        11,
        "#DCEBFF",
        "alagard",
        "left",
        w - 24,
    )
    l_key.SetPos(12, y)
    g.Add(l_key)

    y += 24
    l_deed = API.CreateGumpTTFLabel("Deed Signature Text", 12, "#E7F0FA", "alagard", "left", 180)
    l_deed.SetPos(12, y)
    g.Add(l_deed)
    deed_box = API.CreateGumpTextBox(str(row.get("deed_key", "") or ""), w - 24, 78, True)
    deed_box.SetPos(12, y + 18)
    g.Add(deed_box)

    y += 106
    l_craftable = API.CreateGumpTTFLabel("Craftable Item", 12, "#E7F0FA", "alagard", "left", 120)
    l_craftable.SetPos(12, y)
    g.Add(l_craftable)

    craftable_options = _query_craftable_item_names(row.get("server", ""), row.get("profession", ""))
    if row.get("name", "") and _norm_text(row.get("name", "")) not in {_norm_text(x) for x in craftable_options}:
        craftable_options.append(str(row.get("name", "")))
    craftable_options = _list_unique(craftable_options)
    if not craftable_options:
        craftable_options = [str(row.get("name", "") or EMPTY_LABEL)]
    craftable_idx = 0
    for idx_opt, opt in enumerate(craftable_options):
        if _norm_text(opt) == _norm_text(row.get("name", "")):
            craftable_idx = idx_opt
            break
    dd_craftable = API.CreateDropDown(360, list(craftable_options), _clamp_idx(craftable_idx, len(craftable_options)))
    dd_craftable.SetPos(110, y - 2)
    g.Add(dd_craftable)

    y += 34
    panel = API.CreateGumpColorBox(0.55, "#1B2A3A")
    panel.SetRect(12, y, w - 24, 290)
    g.Add(panel)

    hdr = API.CreateGumpTTFLabel("Material Requirements", 12, "#E7F0FA", "alagard", "left", 200)
    hdr.SetPos(20, y + 6)
    g.Add(hdr)

    hdr_mat = API.CreateGumpTTFLabel("Material", 11, "#FFFFFF", "alagard", "left", 180)
    hdr_mat.SetPos(28, y + 28)
    g.Add(hdr_mat)
    hdr_min = API.CreateGumpTTFLabel("Required In Pack", 11, "#FFFFFF", "alagard", "left", 120)
    hdr_min.SetPos(250, y + 28)
    g.Add(hdr_min)
    hdr_pull = API.CreateGumpTTFLabel("Pull Qty", 11, "#FFFFFF", "alagard", "left", 90)
    hdr_pull.SetPos(390, y + 28)
    g.Add(hdr_pull)
    hdr_item = API.CreateGumpTTFLabel("Item ID Override", 11, "#FFFFFF", "alagard", "left", 130)
    hdr_item.SetPos(500, y + 28)
    g.Add(hdr_item)

    resource_options = _query_resource_names()
    for m in list(row.get("materials", []) or []):
        name = str((m or {}).get("material", "") if isinstance(m, dict) else "").strip()
        if name:
            resource_options.append(name)
    resource_options = _list_unique(resource_options)
    if not resource_options:
        resource_options = ["ingot", "cloth", "leather", "board", "feather"]

    material_rows = []
    initial_materials = list(row.get("materials", []) or [])
    while len(initial_materials) < int(MAX_MATERIAL_ROWS):
        initial_materials.append({"material": "", "min_in_pack": 0, "pull_amount": 0})

    for i in range(int(MAX_MATERIAL_ROWS)):
        entry = initial_materials[i] if i < len(initial_materials) else {}
        material_name = str((entry or {}).get("material", "") if isinstance(entry, dict) else "").strip()
        min_in_pack = int((entry or {}).get("min_in_pack", 0) if isinstance(entry, dict) else 0)
        pull_amount = int((entry or {}).get("pull_amount", 0) if isinstance(entry, dict) else 0)
        item_id = _parse_item_id((entry or {}).get("item_id", 0) if isinstance(entry, dict) else 0)

        options = [EMPTY_LABEL] + list(resource_options)
        selected_idx = 0
        for idx_opt, opt in enumerate(options):
            if _norm_text(opt) == _norm_text(material_name):
                selected_idx = idx_opt
                break

        row_y = y + 50 + (i * 38)
        slot_label = API.CreateGumpTTFLabel(f"{int(i + 1)}.", 11, "#FFFFFF", "alagard", "left", 16)
        slot_label.SetPos(20, row_y + 4)
        g.Add(slot_label)

        dd_material = API.CreateDropDown(200, list(options), _clamp_idx(selected_idx, len(options)))
        dd_material.SetPos(40, row_y)
        g.Add(dd_material)

        tb_min = API.CreateGumpTextBox(str(int(max(0, min_in_pack))), 120, 18, False)
        tb_min.SetPos(246, row_y)
        g.Add(tb_min)

        tb_pull = API.CreateGumpTextBox(str(int(max(0, pull_amount))), 90, 18, False)
        tb_pull.SetPos(386, row_y)
        g.Add(tb_pull)

        tb_item = API.CreateGumpTextBox((f"0x{int(item_id):X}" if int(item_id) > 0 else ""), 140, 18, False)
        tb_item.SetPos(496, row_y)
        g.Add(tb_item)

        material_rows.append(
            {
                "material": dd_material,
                "options": list(options),
                "min_in_pack": tb_min,
                "pull_amount": tb_pull,
                "item_id": tb_item,
            }
        )

    y += 306
    reload_btn = API.CreateSimpleButton("Reload", 90, 20)
    reload_btn.SetPos(220, y)
    g.Add(reload_btn)
    API.AddControlOnClick(reload_btn, _reload_and_rebuild)

    save_btn = API.CreateSimpleButton("Save", 90, 20)
    save_btn.SetPos(320, y)
    g.Add(save_btn)
    API.AddControlOnClick(save_btn, _save_and_exit)

    cancel_btn = API.CreateSimpleButton("Cancel", 90, 20)
    cancel_btn.SetPos(420, y)
    g.Add(cancel_btn)
    API.AddControlOnClick(cancel_btn, _cancel_and_exit)

    API.AddGump(g)
    EDITOR_GUMP = g
    EDITOR_INPUTS = {
        "server": dd_server,
        "profession": dd_prof,
        "recipe_type": dd_type,
        "name": dd_name,
        "material_key": dd_mk,
        "deed_text": deed_box,
        "craftable": dd_craftable,
        "craftable_options": list(craftable_options),
        "material_rows": material_rows,
    }
    _set_result("opened")


# 8) Main loop


def _main():
    global DATA_ROWS, STOP_REASON, SCRIPT_EXIT_REQUESTED

    if not _init_recipe_store():
        STOP_REASON = "error"
        _say("recipeedit: RecipeStore unavailable.", 33)
        _set_result("error", {"error": "recipe_store_unavailable"})
        return

    request = _get_persistent_json(REQUEST_KEY) or {}
    payload = request.get("payload", {}) if isinstance(request, dict) else {}
    _write_debug_log("recipeedit start payload=" + str(payload))

    DATA_ROWS = _read_recipe_rows()
    _open_editor()

    try:
        while not SCRIPT_EXIT_REQUESTED and EDITOR_GUMP is not None:
            try:
                if bool(getattr(API, "StopRequested", False)):
                    STOP_REASON = "stop_requested"
                    break
            except Exception:
                pass
            API.ProcessCallbacks()
            API.Pause(0.1)
    except Exception:
        STOP_REASON = "error"
        _write_debug_log("recipeedit main loop error:\n" + traceback.format_exc())
        _set_result("error", {"error": "main_loop"})
    finally:
        _close_editor()
        _write_debug_log("recipeedit stop reason=" + str(STOP_REASON))


# 9) Shutdown summary
if _should_autostart_main():
    _main()
