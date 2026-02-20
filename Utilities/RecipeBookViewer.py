import API
import json
import os
import re
import sqlite3

"""
RecipeBookViewer (read-only)

Key-driven viewer for recipe data in craftables.db.
Selection flow:
Server -> Profession -> Material Key -> Category -> Item Name

Displays (no write operations):
- server
- profession
- category
- item name
- material key
- source key used for lookup (item_keys.item_key)
- category button id
- item button id
- full button path
- resource cost to craft
- deed key count tied to selected recipe key
- training key count tied to selected recipe key
"""

DB_FILE = "craftables.db"

VIEWER_GUMP = None
RUNNING = True
SEARCH_REQUESTED = False
UI_CONTROLS = {}
RESULT_CONTROLS = []

DATA_ROWS = []

SERVER_VALUES = []
PROF_VALUES = []
CAT_VALUES = []
ITEM_KEYS = []
ITEM_LABELS = []
MAT_VALUES = []

SERVER_IDX = 0
PROF_IDX = 0
CAT_IDX = 0
ITEM_IDX = 0
MAT_IDX = 0

METAL_PROGRESSION = [
    "ingot_iron",
    "ingot_dull_copper",
    "ingot_shadow_iron",
    "ingot_copper",
    "ingot_bronze",
    "ingot_gold",
    "ingot_agapite",
    "ingot_verite",
    "ingot_valorite",
]
METAL_SORT_INDEX = {k: i for i, k in enumerate(METAL_PROGRESSION)}


def _say(msg, hue=88):
    try:
        API.SysMsg(str(msg or ""), hue)
    except Exception:
        pass


def _norm_text(value):
    t = str(value or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _safe_buttons(text):
    raw = str(text or "").strip()
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return [int(x) for x in (val or []) if int(x) > 0]
    except Exception:
        out = []
        for n in re.findall(r"\d+", raw):
            try:
                iv = int(n)
            except Exception:
                continue
            if iv > 0:
                out.append(iv)
        return out


def _safe_resources(text):
    raw = str(text or "").strip()
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except Exception:
        return []
    if not isinstance(val, list):
        return []
    out = []
    for r in val:
        if not isinstance(r, dict):
            continue
        mat = str(r.get("material", "") or "").strip().lower()
        qty = int(r.get("per_item", 0) or 0)
        if mat and qty > 0:
            out.append({"material": mat, "per_item": qty})
    return out


def _resource_text(resources):
    if not isinstance(resources, list) or not resources:
        return "<none>"
    parts = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        mat = str(r.get("material", "") or "").strip().lower()
        qty = int(r.get("per_item", 0) or 0)
        if mat and qty > 0:
            parts.append(f"{mat}:{qty}")
    return "; ".join(parts) if parts else "<none>"


def _display_category(cat):
    t = str(cat or "").strip()
    return t if t else "(uncategorized)"


def _display_material_key(mk):
    t = str(mk or "").strip()
    return t if t else "(blank)"


def _material_sort_key(mk):
    k = _norm_text(mk)
    if not k:
        return (9, 0, "")
    if k in METAL_SORT_INDEX:
        return (0, int(METAL_SORT_INDEX[k]), k)
    if k.startswith("ingot_"):
        return (1, 0, k)
    return (2, 0, k)


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


def _base_dir():
    try:
        here = os.path.dirname(__file__)
    except Exception:
        here = os.getcwd()
    if os.path.basename(str(here or "")).lower() == "utilities":
        return here
    cand = os.path.join(here, "Utilities")
    if os.path.isdir(cand):
        return cand
    return here


def _db_path():
    return os.path.join(_base_dir(), DB_FILE)


def _connect_ro():
    p = _db_path()
    uri = "file:" + str(p).replace("\\", "/") + "?mode=ro"
    errs = []
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=0.5)
        try:
            conn.execute("PRAGMA query_only=1")
        except Exception:
            pass
        return conn
    except Exception as ex:
        errs.append("uri_ro=" + str(ex))

    # Compatibility path for embedded Python builds that do not support uri=True.
    try:
        conn = sqlite3.connect(p, timeout=0.5)
        try:
            conn.execute("PRAGMA query_only=1")
        except Exception:
            pass
        return conn
    except Exception as ex:
        errs.append("path=" + str(ex))

    raise Exception("; ".join(errs) if errs else "unknown sqlite open error")


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


def _load_rows():
    path = _db_path()
    if not os.path.exists(path):
        _say(f"RecipeBookViewer: DB not found: {path}", 33)
        return []

    try:
        conn = _connect_ro()
    except Exception as ex:
        _say(f"RecipeBookViewer: open failed (read-only): {ex}", 33)
        return []

    rows = []
    try:
        conn.row_factory = sqlite3.Row

        item_cols = _table_columns(conn, "item_keys")
        recipe_cols = _table_columns(conn, "recipes")
        mat_cols = _table_columns(conn, "material_keys")

        item_resource_costs = {}
        irc_cols = _table_columns(conn, "item_resource_costs")
        res_cols = _table_columns(conn, "resources")
        if (
            irc_cols
            and res_cols
            and "server" in irc_cols
            and "profession" in irc_cols
            and "item_key" in irc_cols
            and "slot" in irc_cols
            and "per_item" in irc_cols
            and "resource_id" in irc_cols
            and "id" in res_cols
            and "name" in res_cols
        ):
            cur = conn.execute(
                """
                SELECT irc.server, irc.profession, irc.item_key, irc.slot, irc.per_item, res.name
                FROM item_resource_costs irc
                JOIN resources res ON res.id = irc.resource_id
                ORDER BY irc.server, irc.profession, irc.item_key, irc.slot
                """
            )
            for r in cur.fetchall():
                sk = _norm_text(r["server"])
                pk = _norm_text(r["profession"])
                ik = _norm_text(r["item_key"])
                nm = str(r["name"] or "").strip().lower()
                try:
                    qty = int(r["per_item"] or 0)
                except Exception:
                    qty = 0
                if not (sk and pk and ik and nm and qty > 0):
                    continue
                k = (sk, pk, ik)
                arr = item_resource_costs.get(k)
                if arr is None:
                    arr = []
                    item_resource_costs[k] = arr
                arr.append({"material": nm, "per_item": qty})

        item_records = []
        if item_cols:
            item_buttons_expr = (
                "buttons"
                if "buttons" in item_cols
                else ("buttons_json AS buttons" if "buttons_json" in item_cols else "'[]' AS buttons")
            )
            item_resources_expr = (
                "resources"
                if "resources" in item_cols
                else ("resources_json AS resources" if "resources_json" in item_cols else "'[]' AS resources")
            )
            item_select = [
                "server",
                "profession",
                "item_key",
                "name",
                "category" if "category" in item_cols else "'' AS category",
                item_buttons_expr,
                "default_material_key" if "default_material_key" in item_cols else "'' AS default_material_key",
                item_resources_expr,
            ]
            item_sql = "SELECT " + ", ".join(item_select) + " FROM item_keys ORDER BY server, profession, category, name"
            cur = conn.execute(item_sql)
            for r in cur.fetchall():
                server = str(r["server"] or "")
                profession = str(r["profession"] or "")
                item_key = str(r["item_key"] or "")
                name = str(r["name"] or "")
                category = str(r["category"] or "")
                buttons = _safe_buttons(r["buttons"])
                default_mk = _norm_text(r["default_material_key"])
                resources = _safe_resources(r["resources"])
                if not str(name or "").strip():
                    continue
                rk = (_norm_text(server), _norm_text(profession), _norm_text(item_key))
                if rk in item_resource_costs and item_resource_costs.get(rk):
                    resources = list(item_resource_costs.get(rk) or [])

                item_records.append(
                    {
                        "server": server,
                        "profession": profession,
                        "item_key": item_key,
                        "name": name,
                        "name_k": _norm_text(name),
                        "category": category,
                        "buttons": buttons,
                        "default_material_key": default_mk,
                        "resources": resources,
                    }
                )
        else:
            _say("RecipeBookViewer: item_keys table missing/unreadable.", 33)
            return []

        material_by_prof = {}
        material_buttons_by_key = {}
        if mat_cols and "server" in mat_cols and "profession" in mat_cols and "material_key" in mat_cols:
            mat_buttons_expr = (
                "material_buttons"
                if "material_buttons" in mat_cols
                else ("material_buttons_json AS material_buttons" if "material_buttons_json" in mat_cols else "'[]' AS material_buttons")
            )
            mat_select = [
                "server",
                "profession",
                "material_key",
                mat_buttons_expr,
            ]
            cur = conn.execute("SELECT " + ", ".join(mat_select) + " FROM material_keys")
            for r in cur.fetchall():
                sk = _norm_text(r["server"])
                pk = _norm_text(r["profession"])
                mk = _norm_text(r["material_key"])
                mb = _safe_buttons(r["material_buttons"])
                if not mk:
                    continue
                k = (sk, pk)
                s = material_by_prof.get(k)
                if s is None:
                    s = set()
                    material_by_prof[k] = s
                s.add(mk)
                material_buttons_by_key[(sk, pk, mk)] = list(mb)

        # Aggregate recipe linkage counts by key.
        bod_sets = {}
        training_counts = {}
        recipe_materials = {}
        recipe_buttons = {}
        if recipe_cols and "server" in recipe_cols and "profession" in recipe_cols and "name" in recipe_cols:
            recipe_buttons_expr = (
                "buttons"
                if "buttons" in recipe_cols
                else ("buttons_json AS buttons" if "buttons_json" in recipe_cols else "'[]' AS buttons")
            )
            recipe_select = [
                "recipe_type" if "recipe_type" in recipe_cols else "'' AS recipe_type",
                "server",
                "profession",
                "name",
                "material_key" if "material_key" in recipe_cols else "'' AS material_key",
                "deed_key" if "deed_key" in recipe_cols else "'' AS deed_key",
                recipe_buttons_expr,
            ]
            where_sql = ""
            if "recipe_type" in recipe_cols:
                where_sql = " WHERE lower(coalesce(recipe_type,'')) IN ('bod', 'training')"
            recipe_sql = (
                "SELECT "
                + ", ".join(recipe_select)
                + " FROM recipes"
                + where_sql
                + " ORDER BY server, profession, name, material_key"
            )
            cur = conn.execute(recipe_sql)
            for r in cur.fetchall():
                recipe_type = _norm_text(r["recipe_type"])
                sk = _norm_text(r["server"])
                pk = _norm_text(r["profession"])
                nk = _norm_text(r["name"])
                mk = _norm_text(r["material_key"])
                dkey = str(r["deed_key"] or "").strip()
                btns = _safe_buttons(r["buttons"])
                if not (sk and pk and nk):
                    continue
                by_item = recipe_materials.get((sk, pk, nk))
                if by_item is None:
                    by_item = set()
                    recipe_materials[(sk, pk, nk)] = by_item
                if mk:
                    by_item.add(mk)
                key = (sk, pk, nk, mk)
                if btns and key not in recipe_buttons:
                    recipe_buttons[key] = list(btns)
                if recipe_type == "bod":
                    s = bod_sets.get(key)
                    if s is None:
                        s = set()
                        bod_sets[key] = s
                    if dkey:
                        s.add(dkey)
                elif recipe_type == "training":
                    training_counts[key] = int(training_counts.get(key, 0) or 0) + 1

        for ent in item_records:
            server = str(ent.get("server", "") or "")
            profession = str(ent.get("profession", "") or "")
            name = str(ent.get("name", "") or "")
            name_k = str(ent.get("name_k", "") or "")
            item_key = str(ent.get("item_key", "") or "").strip() or name_k
            category = str(ent.get("category", "") or "").strip()
            item_buttons = [int(x) for x in (ent.get("buttons", []) or []) if int(x) > 0]
            resources = list(ent.get("resources", []) or [])
            default_mk = str(ent.get("default_material_key", "") or "").strip().lower()

            server_k = _norm_text(server)
            prof_k = _norm_text(profession)
            base_item_key = (server_k, prof_k, name_k)

            material_opts = set()
            for mk in (recipe_materials.get(base_item_key) or set()):
                if mk:
                    material_opts.add(mk)
            for mk in (material_by_prof.get((server_k, prof_k)) or set()):
                if mk:
                    material_opts.add(mk)
            if default_mk:
                material_opts.add(default_mk)
            if not material_opts:
                material_opts.add("")

            for mk in sorted(material_opts, key=_material_sort_key):
                mat_k = _norm_text(mk)
                key = (server_k, prof_k, name_k, mat_k)
                blank_key = (server_k, prof_k, name_k, "")

                deed_set = set(bod_sets.get(key, set()))
                if mat_k and blank_key in bod_sets:
                    deed_set |= set(bod_sets.get(blank_key, set()))
                training_count = int(training_counts.get(key, 0) or 0)
                if mat_k and training_count <= 0:
                    training_count = int(training_counts.get(blank_key, 0) or 0)

                effective_buttons = (
                    recipe_buttons.get(key)
                    or recipe_buttons.get(blank_key)
                    or list(item_buttons)
                )
                category_btn = int(effective_buttons[0]) if len(effective_buttons) > 0 else 0
                item_btn = int(effective_buttons[1]) if len(effective_buttons) > 1 else 0
                material_buttons = list(material_buttons_by_key.get((server_k, prof_k, mat_k), []) or [])
                craft_path = list(material_buttons)
                if category_btn > 0:
                    craft_path.append(category_btn)
                if item_btn > 0:
                    craft_path.append(item_btn)

                rows.append(
                    {
                        "server": server,
                        "server_k": server_k,
                        "profession": profession,
                        "profession_k": prof_k,
                        "category": category,
                        "category_k": _norm_text(category),
                        "name": name,
                        "name_k": name_k,
                        "material_key": str(mk or ""),
                        "material_key_k": mat_k,
                        "source_item_key": item_key,
                        "buttons": list(effective_buttons),
                        "material_buttons": material_buttons,
                        "crafting_path": craft_path,
                        "category_button_id": category_btn,
                        "item_button_id": item_btn,
                        "resources": resources,
                        "deed_key_count": len(deed_set),
                        "training_key_count": training_count,
                    }
                )
    except Exception as ex:
        _say(f"RecipeBookViewer: query failed: {ex}", 33)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def _rebuild_options():
    global SERVER_VALUES, PROF_VALUES, CAT_VALUES, ITEM_KEYS, ITEM_LABELS, MAT_VALUES
    global SERVER_IDX, PROF_IDX, CAT_IDX, ITEM_IDX, MAT_IDX

    if not DATA_ROWS:
        SERVER_VALUES = []
        PROF_VALUES = []
        CAT_VALUES = []
        ITEM_KEYS = []
        ITEM_LABELS = []
        MAT_VALUES = []
        SERVER_IDX = PROF_IDX = CAT_IDX = ITEM_IDX = MAT_IDX = 0
        return

    SERVER_VALUES = sorted({r["server"] for r in DATA_ROWS if str(r.get("server", "")).strip()})
    SERVER_IDX = _clamp_idx(SERVER_IDX, len(SERVER_VALUES))
    srv = SERVER_VALUES[SERVER_IDX] if SERVER_VALUES else ""
    rows_s = [r for r in DATA_ROWS if str(r.get("server", "")) == srv]

    PROF_VALUES = sorted({r["profession"] for r in rows_s if str(r.get("profession", "")).strip()})
    PROF_IDX = _clamp_idx(PROF_IDX, len(PROF_VALUES))
    prof = PROF_VALUES[PROF_IDX] if PROF_VALUES else ""
    rows_p = [r for r in rows_s if str(r.get("profession", "")) == prof]

    mat_map = {}
    for r in rows_p:
        mk = str(r.get("material_key_k", "") or "")
        if mk not in mat_map:
            mat_map[mk] = str(r.get("material_key", "") or "")
    MAT_VALUES = sorted(mat_map.keys(), key=_material_sort_key)
    MAT_IDX = _clamp_idx(MAT_IDX, len(MAT_VALUES))
    mat_k = MAT_VALUES[MAT_IDX] if MAT_VALUES else ""
    rows_m = [r for r in rows_p if str(r.get("material_key_k", "") or "") == mat_k]

    cat_map = {}
    for r in rows_m:
        ck = str(r.get("category_k", "") or "")
        if ck not in cat_map:
            cat_map[ck] = str(r.get("category", "") or "")
    CAT_VALUES = sorted(cat_map.keys(), key=lambda k: _display_category(cat_map.get(k, "")).lower())
    CAT_IDX = _clamp_idx(CAT_IDX, len(CAT_VALUES))
    cat_k = CAT_VALUES[CAT_IDX] if CAT_VALUES else ""
    rows_c = [r for r in rows_m if str(r.get("category_k", "") or "") == cat_k]

    item_map = {}
    for r in rows_c:
        nk = str(r.get("name_k", "") or "")
        if nk and nk not in item_map:
            item_map[nk] = str(r.get("name", "") or "")
    ITEM_KEYS = sorted(item_map.keys(), key=lambda k: str(item_map.get(k, "")).lower())
    ITEM_LABELS = [str(item_map.get(k, "")) for k in ITEM_KEYS]
    ITEM_IDX = _clamp_idx(ITEM_IDX, len(ITEM_KEYS))


def _selected_rows():
    if not (SERVER_VALUES and PROF_VALUES and MAT_VALUES and CAT_VALUES and ITEM_KEYS):
        return []
    srv = SERVER_VALUES[_clamp_idx(SERVER_IDX, len(SERVER_VALUES))]
    prof = PROF_VALUES[_clamp_idx(PROF_IDX, len(PROF_VALUES))]
    mat_k = MAT_VALUES[_clamp_idx(MAT_IDX, len(MAT_VALUES))]
    cat_k = CAT_VALUES[_clamp_idx(CAT_IDX, len(CAT_VALUES))]
    item_k = ITEM_KEYS[_clamp_idx(ITEM_IDX, len(ITEM_KEYS))]

    out = []
    for r in DATA_ROWS:
        if str(r.get("server", "")) != str(srv):
            continue
        if str(r.get("profession", "")) != str(prof):
            continue
        if str(r.get("material_key_k", "") or "") != str(mat_k):
            continue
        if str(r.get("category_k", "") or "") != str(cat_k):
            continue
        if str(r.get("name_k", "") or "") != str(item_k):
            continue
        out.append(r)
    return out


def _selected_summary():
    rows = _selected_rows()
    if not rows:
        return None

    rep = rows[0]

    return {
        "server": str(rep.get("server", "") or ""),
        "profession": str(rep.get("profession", "") or ""),
        "category": str(rep.get("category", "") or ""),
        "item_name": str(rep.get("name", "") or ""),
        "material_key": str(rep.get("material_key", "") or ""),
        "source_item_key": str(rep.get("source_item_key", "") or ""),
        "buttons": list(rep.get("buttons", []) or []),
        "material_buttons": list(rep.get("material_buttons", []) or []),
        "crafting_path": list(rep.get("crafting_path", []) or []),
        "category_button_id": int(rep.get("category_button_id", 0) or 0),
        "item_button_id": int(rep.get("item_button_id", 0) or 0),
        "resource_text": _resource_text(rep.get("resources", [])),
        "deed_key_count": int(rep.get("deed_key_count", 0) or 0),
        "training_key_count": int(rep.get("training_key_count", 0) or 0),
        "rows_matched": len(rows),
    }


def _close_viewer():
    global VIEWER_GUMP, RUNNING, UI_CONTROLS, RESULT_CONTROLS
    RUNNING = False
    if VIEWER_GUMP:
        try:
            VIEWER_GUMP.Dispose()
        except Exception:
            pass
    VIEWER_GUMP = None
    UI_CONTROLS = {}
    RESULT_CONTROLS = []


def _set_dropdown_items(dd, labels, selected_idx):
    labels = list(labels or [])
    idx = _clamp_idx(selected_idx, len(labels))
    ok = False

    # Try known mutator names across host versions.
    for m in ("SetItems", "SetOptions", "SetValues", "UpdateItems", "ResetItems"):
        try:
            fn = getattr(dd, m, None)
            if callable(fn):
                fn(labels)
                ok = True
                break
        except Exception:
            pass

    if not ok:
        return False

    for m in ("SetSelectedIndex", "SelectIndex", "SetIndex"):
        try:
            fn = getattr(dd, m, None)
            if callable(fn):
                fn(idx)
                return True
        except Exception:
            pass
    try:
        dd.SelectedIndex = idx
        return True
    except Exception:
        return True


def _replace_dropdown_control(key, labels, selected_idx):
    if VIEWER_GUMP is None:
        return None
    spec = UI_CONTROLS.get(key + "_spec", {})
    if not spec:
        return None
    old = UI_CONTROLS.get(key)
    try:
        if old:
            old.Dispose()
    except Exception:
        pass
    dd = API.CreateDropDown(
        int(spec.get("width", 150)),
        list(labels or ["<none>"]),
        _clamp_idx(selected_idx, len(labels or ["<none>"])),
    )
    dd.SetPos(int(spec.get("x", 0)), int(spec.get("y", 0)))
    VIEWER_GUMP.Add(dd)
    cb = spec.get("callback")
    if cb is not None:
        dd.OnDropDownOptionSelected(cb)
    UI_CONTROLS[key] = dd
    return dd


def _clear_result_controls():
    global RESULT_CONTROLS
    for c in RESULT_CONTROLS:
        try:
            c.Dispose()
        except Exception:
            pass
    RESULT_CONTROLS = []


def _render_results_into_gump(g, w, panel_y):
    global RESULT_CONTROLS
    _clear_result_controls()

    if not SEARCH_REQUESTED:
        txt = API.CreateGumpTTFLabel("Click Search to populate recipe details for the selected keys.", 12, "#FFD58A", "alagard", "left", w - 36)
        txt.SetPos(20, panel_y + 14)
        g.Add(txt)
        RESULT_CONTROLS.append(txt)
        return

    summary = _selected_summary()
    if not summary:
        txt = API.CreateGumpTTFLabel("No recipe rows available for current key selection.", 12, "#FFD58A", "alagard", "left", w - 36)
        txt.SetPos(20, panel_y + 14)
        g.Add(txt)
        RESULT_CONTROLS.append(txt)
        return

    line_y = panel_y + 14
    result_w = w - 36
    result_x = (w - result_w) // 2
    lines = [
        f"Server: {summary['server']}",
        f"Profession: {summary['profession']}",
        f"Material Key: {summary['material_key']}",
        f"Material Path: [{', '.join(str(int(x)) for x in (summary['material_buttons'] or []))}]",
        f"Category: {(_display_category(summary['category']))}",
        f"Category Button ID: {summary['category_button_id']}",
        f"Item Name: {summary['item_name']}",
        f"Item Button ID: {summary['item_button_id']}",
        f"Crafting Path: [{', '.join(str(int(x)) for x in (summary['crafting_path'] or []))}]",
        f"Resource Cost (per craft): {summary['resource_text']}",
        f"Deed Keys Tied (count): {summary['deed_key_count']}",
        f"Training Keys Tied (count): {summary['training_key_count']}",
        f"Matched Rows For Selected Key: {summary['rows_matched']}",
    ]
    for ln in lines:
        lbl = API.CreateGumpTTFLabel(str(ln), 15, "#E7F0FA", "alagard", "left", result_w)
        lbl.SetPos(result_x, line_y)
        g.Add(lbl)
        RESULT_CONTROLS.append(lbl)
        line_y += 25


def _update_ui_in_place():
    if VIEWER_GUMP is None:
        return False
    dd_server = UI_CONTROLS.get("dd_server")
    dd_prof = UI_CONTROLS.get("dd_prof")
    dd_mat = UI_CONTROLS.get("dd_mat")
    dd_cat = UI_CONTROLS.get("dd_cat")
    dd_item = UI_CONTROLS.get("dd_item")
    panel_y = int(UI_CONTROLS.get("panel_y", 160) or 160)
    w = int(UI_CONTROLS.get("w", 520) or 520)
    if not (dd_server and dd_prof and dd_mat and dd_cat and dd_item):
        return False

    _rebuild_options()
    server_labels = _labels_or_placeholder(SERVER_VALUES)
    prof_labels = _labels_or_placeholder(PROF_VALUES)
    mat_labels = _labels_or_placeholder(MAT_VALUES, _display_material_key)
    cat_labels = _labels_or_placeholder(CAT_VALUES, _display_category)
    item_labels = _labels_or_placeholder(ITEM_LABELS)

    if not _set_dropdown_items(dd_server, server_labels, SERVER_IDX):
        dd_server = _replace_dropdown_control("dd_server", server_labels, SERVER_IDX)
        if dd_server is None:
            return False
    if not _set_dropdown_items(dd_prof, prof_labels, PROF_IDX):
        dd_prof = _replace_dropdown_control("dd_prof", prof_labels, PROF_IDX)
        if dd_prof is None:
            return False
    if not _set_dropdown_items(dd_mat, mat_labels, MAT_IDX):
        dd_mat = _replace_dropdown_control("dd_mat", mat_labels, MAT_IDX)
        if dd_mat is None:
            return False
    if not _set_dropdown_items(dd_cat, cat_labels, CAT_IDX):
        dd_cat = _replace_dropdown_control("dd_cat", cat_labels, CAT_IDX)
        if dd_cat is None:
            return False
    if not _set_dropdown_items(dd_item, item_labels, ITEM_IDX):
        dd_item = _replace_dropdown_control("dd_item", item_labels, ITEM_IDX)
        if dd_item is None:
            return False

    _render_results_into_gump(VIEWER_GUMP, w, panel_y)
    return True


def _sync_ui():
    # Keep a single gump alive; fallback to major rebuild only if API cannot mutate controls.
    if not _update_ui_in_place():
        _rebuild_gump_major()


def _on_server(idx):
    global SERVER_IDX, PROF_IDX, CAT_IDX, ITEM_IDX, MAT_IDX, SEARCH_REQUESTED
    SERVER_IDX = _to_index(idx)
    PROF_IDX = CAT_IDX = ITEM_IDX = MAT_IDX = 0
    SEARCH_REQUESTED = False
    _sync_ui()


def _on_profession(idx):
    global PROF_IDX, MAT_IDX, CAT_IDX, ITEM_IDX, SEARCH_REQUESTED
    PROF_IDX = _to_index(idx)
    MAT_IDX = CAT_IDX = ITEM_IDX = 0
    SEARCH_REQUESTED = False
    _sync_ui()


def _on_category(idx):
    global CAT_IDX, ITEM_IDX, SEARCH_REQUESTED
    CAT_IDX = _to_index(idx)
    ITEM_IDX = 0
    SEARCH_REQUESTED = False
    _sync_ui()


def _on_item(idx):
    global ITEM_IDX, SEARCH_REQUESTED
    ITEM_IDX = _to_index(idx)
    SEARCH_REQUESTED = False
    _sync_ui()


def _on_material(idx):
    global MAT_IDX, CAT_IDX, ITEM_IDX, SEARCH_REQUESTED
    MAT_IDX = _to_index(idx)
    CAT_IDX = ITEM_IDX = 0
    SEARCH_REQUESTED = False
    _sync_ui()


def _search():
    global SEARCH_REQUESTED
    SEARCH_REQUESTED = True
    _sync_ui()


def _labels_or_placeholder(values, display_fn=None):
    if not values:
        return ["<none>"]
    if display_fn is None:
        return [str(v) for v in values]
    return [str(display_fn(v)) for v in values]


def _create_gump():
    global VIEWER_GUMP, UI_CONTROLS
    _rebuild_options()

    g = API.CreateGump(True, True, False)
    w = 520
    h = 560
    g.SetRect(220, 120, w, h)
    bg = API.CreateGumpColorBox(0.78, "#111923")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("Recipe Book (Viewer)", 16, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 8)
    g.Add(title)

    y1 = 44
    l1 = API.CreateGumpTTFLabel("Server", 12, "#FFFFFF", "alagard", "left", 70)
    l1.SetPos(12, y1)
    g.Add(l1)
    dd_server = API.CreateDropDown(170, _labels_or_placeholder(SERVER_VALUES), _clamp_idx(SERVER_IDX, len(SERVER_VALUES)))
    dd_server.SetPos(92, y1 - 2)
    g.Add(dd_server)
    dd_server.OnDropDownOptionSelected(_on_server)

    l2 = API.CreateGumpTTFLabel("Profession", 12, "#FFFFFF", "alagard", "left", 90)
    l2.SetPos(280, y1)
    g.Add(l2)
    dd_prof = API.CreateDropDown(150, _labels_or_placeholder(PROF_VALUES), _clamp_idx(PROF_IDX, len(PROF_VALUES)))
    dd_prof.SetPos(360, y1 - 2)
    g.Add(dd_prof)
    dd_prof.OnDropDownOptionSelected(_on_profession)

    y2 = 76
    l3 = API.CreateGumpTTFLabel("Material", 12, "#FFFFFF", "alagard", "left", 70)
    l3.SetPos(12, y2)
    g.Add(l3)
    dd_mat = API.CreateDropDown(170, _labels_or_placeholder(MAT_VALUES, _display_material_key), _clamp_idx(MAT_IDX, len(MAT_VALUES)))
    dd_mat.SetPos(92, y2 - 2)
    g.Add(dd_mat)
    dd_mat.OnDropDownOptionSelected(_on_material)

    l4 = API.CreateGumpTTFLabel("Category", 12, "#FFFFFF", "alagard", "left", 78)
    l4.SetPos(280, y2)
    g.Add(l4)
    dd_cat = API.CreateDropDown(150, _labels_or_placeholder(CAT_VALUES, _display_category), _clamp_idx(CAT_IDX, len(CAT_VALUES)))
    dd_cat.SetPos(360, y2 - 2)
    g.Add(dd_cat)
    dd_cat.OnDropDownOptionSelected(_on_category)

    y3 = 108
    l5 = API.CreateGumpTTFLabel("Item", 12, "#FFFFFF", "alagard", "left", 44)
    l5.SetPos(12, y3)
    g.Add(l5)
    dd_item = API.CreateDropDown(420, _labels_or_placeholder(ITEM_LABELS), _clamp_idx(ITEM_IDX, len(ITEM_LABELS)))
    dd_item.SetPos(92, y3 - 2)
    g.Add(dd_item)
    dd_item.OnDropDownOptionSelected(_on_item)

    y4 = 142
    search_btn = API.CreateSimpleButton("Search", 78, 20)
    search_btn.SetPos((w // 2) - 39, y4 - 1)
    g.Add(search_btn)
    API.AddControlOnClick(search_btn, _search)

    panel_y = 160
    panel = API.CreateGumpColorBox(0.55, "#1B2A3A")
    panel.SetRect(10, panel_y, w - 20, h - panel_y - 10)
    g.Add(panel)

    _render_results_into_gump(g, w, panel_y)

    API.AddGump(g)
    VIEWER_GUMP = g
    UI_CONTROLS = {
        "dd_server": dd_server,
        "dd_prof": dd_prof,
        "dd_mat": dd_mat,
        "dd_cat": dd_cat,
        "dd_item": dd_item,
        "dd_server_spec": {"x": 92, "y": y1 - 2, "width": 170, "callback": _on_server},
        "dd_prof_spec": {"x": 360, "y": y1 - 2, "width": 150, "callback": _on_profession},
        "dd_mat_spec": {"x": 92, "y": y2 - 2, "width": 170, "callback": _on_material},
        "dd_cat_spec": {"x": 360, "y": y2 - 2, "width": 150, "callback": _on_category},
        "dd_item_spec": {"x": 92, "y": y3 - 2, "width": 420, "callback": _on_item},
        "panel_y": panel_y,
        "w": w,
    }


def _rebuild_gump_major():
    global VIEWER_GUMP
    if VIEWER_GUMP:
        try:
            VIEWER_GUMP.Dispose()
        except Exception:
            pass
        VIEWER_GUMP = None
    _create_gump()


def _main():
    global DATA_ROWS
    DATA_ROWS = _load_rows()
    _create_gump()
    server_count = len({str(r.get("server", "") or "").strip() for r in DATA_ROWS if str(r.get("server", "") or "").strip()})
    prof_count = len({str(r.get("profession", "") or "").strip() for r in DATA_ROWS if str(r.get("profession", "") or "").strip()})
    _say(
        "RecipeBookViewer loaded (read-only). rows="
        + str(len(DATA_ROWS))
        + ", servers="
        + str(server_count)
        + ", professions="
        + str(prof_count)
    )
    while RUNNING and VIEWER_GUMP is not None:
        API.ProcessCallbacks()
        API.Pause(0.1)


try:
    _main()
except Exception as ex:
    msg = str(ex or "")
    if "ThreadInterrupted" in msg or "interrupted" in msg.lower():
        pass
    else:
        raise
