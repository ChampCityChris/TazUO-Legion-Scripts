import API
import json
import ast
import re

"""
RuneMaster (LegionScripts Port)
Version: 1.0.0
Last Updated: 2026-02-13

Ported core features from RuneMaster.cs:
- Scan runebooks from backpack (including nested containers).
- Build searchable, paged rune list.
- Recall / Gate travel per rune entry.
- Run-the-runes automation.
- Persistent settings (page size, sort, search).

Limitations vs original C# RazorEnhanced script:
- Rune Atlas parsing is not implemented in this port.
- World-book handling and transfer-to-nearby-book flow is not implemented.
- Advanced option/super-panel sections are simplified.

TODO Checklist:
Phase 1 (current)
- [x] Runebook scan from backpack/nested containers
- [x] Rune list extraction from runebook gump
- [x] Search + pagination gump
- [x] Recall/Sacred Journey travel and Gate buttons
- [x] Run-the-runes action
- [x] Persistent UI settings (search/page size/sort)

Phase 2
- [ ] Add Rune Atlas discovery and parsing support
- [ ] Support atlas rune travel/gate button mapping
- [ ] Handle atlas page navigation for slot targeting

Phase 3
- [ ] Add world-book tracking data model
- [ ] Add world-book pickup/close-by handling
- [ ] Add world-rune visibility toggle in UI

Phase 4
- [ ] Port options panel parity (listing types, color toggles, etc.)
- [ ] Add map/group listing modes (by book/by map)
- [ ] Add visual state hints and richer status output
"""

# --- Constants ---
RUNEMASTER_DATA_KEY = "runemaster_config"
RUNEMASTER_GUMP_X = 500
RUNEMASTER_GUMP_Y = 300
RUNEMASTER_GUMP_W = 430
RUNEMASTER_ROW_H = 20
RUNEMASTER_GUMP_ID = 0x2C31A4B8

RUNEOBOOK_ID = 0x22C5
RUNEOBOOK_GUMP_ID = 0x59
MAX_RUNES_PER_BOOK = 16
RUNEOBOOK_STRAP_ID = 0xA721

MIN_MAGERY_FOR_RECALL = 40.0
MIN_MAGERY_FOR_GATE = 80.0

PAUSE_GUMP = 350
PAUSE_AFTER_TRAVEL = 1500


# --- Runtime State ---
CONTROL_GUMP = None
CONTROL_CONTROLS = []

RUNES = []  # [{book_serial, book_name, rune_name, slot, recall_button, gate_button, sacred_button}]
FILTERED_INDEXES = []
ACTIVE_PAGE = 0

SEARCH_TEXT = ""
SEARCH_BOX = None
PAGE_SIZE = 16
SORT_TYPE = "book_order"  # book_order | alphabetical

MAGERY = 0.0
CHIVALRY = 0.0


def _say(msg, hue=88):
    API.SysMsg(msg, hue)


def _pause_ms(ms):
    API.Pause(ms / 1000.0)


def _strip_tags(text):
    return re.sub(r"<[^>]*>", "", text or "")


def _default_config():
    return {
        "search_text": "",
        "page_size": 16,
        "sort_type": "book_order",
    }


def _load_config():
    global SEARCH_TEXT, PAGE_SIZE, SORT_TYPE
    raw = API.GetPersistentVar(RUNEMASTER_DATA_KEY, "", API.PersistentVar.Char)
    if not raw:
        d = _default_config()
        SEARCH_TEXT = d["search_text"]
        PAGE_SIZE = d["page_size"]
        SORT_TYPE = d["sort_type"]
        return
    try:
        try:
            data = json.loads(raw)
        except Exception:
            data = ast.literal_eval(raw)
        SEARCH_TEXT = str(data.get("search_text", "") or "")
        PAGE_SIZE = int(data.get("page_size", 16) or 16)
        if PAGE_SIZE < 4:
            PAGE_SIZE = 4
        SORT_TYPE = str(data.get("sort_type", "book_order") or "book_order")
        if SORT_TYPE not in ("book_order", "alphabetical"):
            SORT_TYPE = "book_order"
    except Exception:
        d = _default_config()
        SEARCH_TEXT = d["search_text"]
        PAGE_SIZE = d["page_size"]
        SORT_TYPE = d["sort_type"]


def _save_config():
    data = {
        "search_text": SEARCH_TEXT,
        "page_size": int(PAGE_SIZE),
        "sort_type": SORT_TYPE,
    }
    API.SavePersistentVar(RUNEMASTER_DATA_KEY, json.dumps(data), API.PersistentVar.Char)


def _refresh_skills():
    global MAGERY, CHIVALRY
    magery = API.GetSkill("Magery")
    chiv = API.GetSkill("Chivalry")
    MAGERY = float(magery.Value) if magery and magery.Value is not None else 0.0
    CHIVALRY = float(chiv.Value) if chiv and chiv.Value is not None else 0.0


def _use_magery_for_recall():
    return MAGERY > CHIVALRY and MAGERY >= MIN_MAGERY_FOR_RECALL


def _can_gate():
    return MAGERY >= MIN_MAGERY_FOR_GATE


def _prime_runebook_containers():
    # Open likely runebook holder containers (e.g., runebook strap) so recursive scans can see contents.
    top_items = API.ItemsInContainer(API.Backpack, False) or []
    for it in top_items:
        serial = int(getattr(it, "Serial", 0) or 0)
        if not serial:
            continue
        graphic = int(getattr(it, "Graphic", 0) or 0)
        name = str(getattr(it, "Name", "") or "").lower()
        is_target = graphic == RUNEOBOOK_STRAP_ID or "runebook strap" in name
        if not is_target:
            continue
        API.UseObject(serial)
        _pause_ms(200)


def _find_runebooks():
    _prime_runebook_containers()
    items = API.ItemsInContainer(API.Backpack, True) or []
    books = []
    seen = set()
    for it in items:
        if int(getattr(it, "Graphic", 0)) != RUNEOBOOK_ID:
            continue
        serial = int(getattr(it, "Serial", 0) or 0)
        if not serial or serial in seen:
            continue
        seen.add(serial)
        books.append(it)
    return books


def _sanitize_rune_text(value):
    txt = _strip_tags(str(value or "")).strip()
    if not txt:
        return None
    low = txt.lower()
    skip_words = (
        "charges",
        "default",
        "drop rune",
        "rename",
        "recall",
        "gate",
        "sacred",
        "minimize",
        "max",
        "book",
        "runebook",
        "set default",
    )
    if any(w in low for w in skip_words):
        return None
    if low == "empty":
        return ""
    if len(txt) > 45:
        return None
    return txt


def _extract_text_list_from_runebook_gump(gump_id):
    # Prefer structured gump string-list data if exposed by this client build.
    try:
        g = API.GetGump(gump_id)
    except Exception:
        g = None

    candidates = [g] if g else []
    for gg in API.GetAllGumps() or []:
        try:
            gid = int(getattr(gg, "ID", getattr(gg, "Serial", getattr(gg, "GumpID", getattr(gg, "GumpId", 0)))) or 0)
        except Exception:
            gid = 0
        if gid == int(gump_id):
            candidates.append(gg)

    attr_names = ("stringList", "StringList", "Strings", "TextList", "LineList", "Lines")
    for obj in candidates:
        if not obj:
            continue
        for attr in attr_names:
            if not hasattr(obj, attr):
                continue
            try:
                raw = getattr(obj, attr)
                if raw:
                    return [str(x) for x in raw]
            except Exception:
                pass
        inner = getattr(obj, "Gump", None)
        if inner:
            for attr in attr_names:
                if not hasattr(inner, attr):
                    continue
                try:
                    raw = getattr(inner, attr)
                    if raw:
                        return [str(x) for x in raw]
                except Exception:
                    pass
    return []


def _extract_rune_names_from_contents(contents):
    text = _strip_tags(contents)
    parts = []
    parts.extend([ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln and ln.strip()])
    parts.extend([p.strip() for p in text.split("|") if p and p.strip()])
    parts.extend([m.strip() for m in re.findall(r'"([^"\n]{1,45})"', text or "") if m and m.strip()])

    names = []
    for ptxt in parts:
        clean = _sanitize_rune_text(ptxt)
        if clean is None:
            continue
        names.append(clean)

    if len(names) < MAX_RUNES_PER_BOOK:
        names.extend([""] * (MAX_RUNES_PER_BOOK - len(names)))
    return names[:MAX_RUNES_PER_BOOK]


def _read_runebook(serial):
    book = API.FindItem(serial)
    if not book:
        return []
    book_name = str(getattr(book, "Name", "") or f"Runebook 0x{int(serial):08X}")
    API.UseObject(serial)
    if not API.WaitForGump(RUNEOBOOK_GUMP_ID, 2):
        return []
    _pause_ms(PAUSE_GUMP)

    rune_names = []
    string_list = _extract_text_list_from_runebook_gump(RUNEOBOOK_GUMP_ID)
    if string_list:
        # RuneMaster.cs uses stringList.Skip(2).Take(16) for runebook names.
        slot_lines = string_list[2:2 + MAX_RUNES_PER_BOOK]
        for line in slot_lines:
            clean = _sanitize_rune_text(line)
            if clean is None:
                clean = ""
            rune_names.append(clean)

    if len(rune_names) < MAX_RUNES_PER_BOOK:
        contents = API.GetGumpContents(RUNEOBOOK_GUMP_ID) or ""
        fallback = _extract_rune_names_from_contents(contents)
        if rune_names:
            # Fill blanks from fallback without changing known slot names.
            for i in range(MAX_RUNES_PER_BOOK):
                if i >= len(rune_names):
                    rune_names.append(fallback[i])
                elif not rune_names[i] and fallback[i]:
                    rune_names[i] = fallback[i]
        else:
            rune_names = fallback

    if len(rune_names) < MAX_RUNES_PER_BOOK:
        rune_names.extend([""] * (MAX_RUNES_PER_BOOK - len(rune_names)))
    rune_names = rune_names[:MAX_RUNES_PER_BOOK]

    runes = []
    for slot in range(MAX_RUNES_PER_BOOK):
        name = rune_names[slot] if slot < len(rune_names) else ""
        if not name:
            continue
        runes.append({
            "book_serial": int(serial),
            "book_name": book_name,
            "rune_name": name,
            "slot": slot,
            "recall_button": 50 + slot,
            "gate_button": 100 + slot,
            "sacred_button": 75 + slot,
        })
    API.CloseGump(RUNEOBOOK_GUMP_ID)
    return runes


def _scan_runes():
    global RUNES, ACTIVE_PAGE
    _refresh_skills()
    books = _find_runebooks()
    out = []
    for b in books:
        out.extend(_read_runebook(int(b.Serial)))
    RUNES = out
    ACTIVE_PAGE = 0
    _apply_filter_and_sort()


def _apply_filter_and_sort():
    global FILTERED_INDEXES, ACTIVE_PAGE
    indexed = list(range(len(RUNES)))
    if SEARCH_TEXT.strip():
        needle = SEARCH_TEXT.strip().lower()
        indexed = [i for i in indexed if needle in RUNES[i]["rune_name"].lower()]
    if SORT_TYPE == "alphabetical":
        indexed.sort(key=lambda i: RUNES[i]["rune_name"].lower())
    # book_order keeps natural scan order.
    FILTERED_INDEXES = indexed
    max_page = max(0, (_filtered_count() - 1) // max(1, PAGE_SIZE))
    if ACTIVE_PAGE > max_page:
        ACTIVE_PAGE = max_page


def _filtered_count():
    return len(FILTERED_INDEXES)


def _page_slice():
    start = ACTIVE_PAGE * PAGE_SIZE
    end = start + PAGE_SIZE
    return FILTERED_INDEXES[start:end]


def _travel_to_rune(rune_index, gate=False):
    if rune_index < 0 or rune_index >= len(RUNES):
        return
    r = RUNES[rune_index]
    book_serial = int(r["book_serial"])
    button = int(r["gate_button"] if gate else (r["recall_button"] if _use_magery_for_recall() else r["sacred_button"]))
    API.UseObject(book_serial)
    if not API.WaitForGump(RUNEOBOOK_GUMP_ID, 2):
        _say(f"Runebook open failed: {r['book_name']}", 33)
        return
    _pause_ms(PAUSE_GUMP)
    API.ReplyGump(button, RUNEOBOOK_GUMP_ID)
    _pause_ms(PAUSE_AFTER_TRAVEL)
    _say(f"{'Gate' if gate else 'Travel'}: {r['rune_name']}")


def _run_the_runes():
    _say("Running all filtered runes...")
    ids = list(_page_slice()) if SEARCH_TEXT.strip() else list(FILTERED_INDEXES)
    for idx in ids:
        _travel_to_rune(idx, False)
    _say("Run-the-runes complete.")


def _on_search():
    global SEARCH_TEXT, ACTIVE_PAGE
    SEARCH_TEXT = SEARCH_BOX.Text.strip() if SEARCH_BOX and SEARCH_BOX.Text else ""
    ACTIVE_PAGE = 0
    _save_config()
    _apply_filter_and_sort()
    _rebuild_gump()


def _on_clear_search():
    global SEARCH_TEXT, ACTIVE_PAGE
    SEARCH_TEXT = ""
    ACTIVE_PAGE = 0
    _save_config()
    _apply_filter_and_sort()
    _rebuild_gump()


def _on_prev_page():
    global ACTIVE_PAGE
    if ACTIVE_PAGE > 0:
        ACTIVE_PAGE -= 1
        _rebuild_gump()


def _on_next_page():
    global ACTIVE_PAGE
    max_page = max(0, (_filtered_count() - 1) // max(1, PAGE_SIZE))
    if ACTIVE_PAGE < max_page:
        ACTIVE_PAGE += 1
        _rebuild_gump()


def _set_sort_book():
    global SORT_TYPE, ACTIVE_PAGE
    SORT_TYPE = "book_order"
    ACTIVE_PAGE = 0
    _save_config()
    _apply_filter_and_sort()
    _rebuild_gump()


def _set_sort_alpha():
    global SORT_TYPE, ACTIVE_PAGE
    SORT_TYPE = "alphabetical"
    ACTIVE_PAGE = 0
    _save_config()
    _apply_filter_and_sort()
    _rebuild_gump()


def _set_page_size_12():
    _set_page_size(12)


def _set_page_size_16():
    _set_page_size(16)


def _set_page_size_24():
    _set_page_size(24)


def _set_page_size(size):
    global PAGE_SIZE, ACTIVE_PAGE
    PAGE_SIZE = int(size)
    ACTIVE_PAGE = 0
    _save_config()
    _apply_filter_and_sort()
    _rebuild_gump()


def _refresh_runes():
    _scan_runes()
    _rebuild_gump()
    _say(f"RuneMaster refreshed: {len(RUNES)} runes.")


def _on_travel_button(idx):
    _travel_to_rune(idx, False)


def _on_gate_button(idx):
    _travel_to_rune(idx, True)


def _create_gump():
    global CONTROL_GUMP, CONTROL_CONTROLS, SEARCH_BOX
    CONTROL_CONTROLS = []
    row_count = max(6, min(PAGE_SIZE, 24))
    g_h = 110 + (row_count * RUNEMASTER_ROW_H) + 30
    g = API.CreateGump(True, True, False)
    g.SetRect(RUNEMASTER_GUMP_X, RUNEMASTER_GUMP_Y, RUNEMASTER_GUMP_W, g_h)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, RUNEMASTER_GUMP_W, g_h)
    g.Add(bg)
    CONTROL_CONTROLS.append(bg)

    title = API.CreateGumpTTFLabel("RuneMaster", 16, "#FFFFFF", "alagard", "center", RUNEMASTER_GUMP_W)
    title.SetPos(0, 6)
    g.Add(title)
    CONTROL_CONTROLS.append(title)

    mode = "Magery Recall" if _use_magery_for_recall() else "Sacred Journey"
    gate_txt = "Gate On" if _can_gate() else "Gate Off"
    stat = API.CreateGumpTTFLabel(f"{mode} | {gate_txt} | Runes: {_filtered_count()}", 11, "#CCCCCC", "alagard", "left", RUNEMASTER_GUMP_W - 16)
    stat.SetPos(8, 24)
    g.Add(stat)
    CONTROL_CONTROLS.append(stat)

    SEARCH_BOX = API.CreateGumpTextBox(SEARCH_TEXT, 180, 18, False)
    SEARCH_BOX.SetPos(8, 40)
    g.Add(SEARCH_BOX)
    CONTROL_CONTROLS.append(SEARCH_BOX)

    sbtn = API.CreateSimpleButton("Search", 52, 18)
    sbtn.SetPos(194, 40)
    g.Add(sbtn)
    API.AddControlOnClick(sbtn, _on_search)
    CONTROL_CONTROLS.append(sbtn)

    cbtn = API.CreateSimpleButton("Clear", 48, 18)
    cbtn.SetPos(250, 40)
    g.Add(cbtn)
    API.AddControlOnClick(cbtn, _on_clear_search)
    CONTROL_CONTROLS.append(cbtn)

    rbtn = API.CreateSimpleButton("Refresh", 58, 18)
    rbtn.SetPos(302, 40)
    g.Add(rbtn)
    API.AddControlOnClick(rbtn, _refresh_runes)
    CONTROL_CONTROLS.append(rbtn)

    y = 64
    header = API.CreateGumpTTFLabel("T", 12, "#FFFFFF", "alagard", "left", 12)
    header.SetPos(10, y)
    g.Add(header)
    gh = API.CreateGumpTTFLabel("G", 12, "#FFFFFF", "alagard", "left", 12)
    gh.SetPos(34, y)
    g.Add(gh)
    lh = API.CreateGumpTTFLabel("Rune", 12, "#FFFFFF", "alagard", "left", 320)
    lh.SetPos(58, y)
    g.Add(lh)
    y += RUNEMASTER_ROW_H

    rows = _page_slice()
    for ridx in rows:
        r = RUNES[ridx]
        tbtn = API.CreateSimpleButton("T", 16, 16)
        tbtn.SetPos(8, y - 2)
        g.Add(tbtn)
        API.AddControlOnClick(tbtn, lambda i=ridx: _on_travel_button(i))
        CONTROL_CONTROLS.append(tbtn)

        gbtn = API.CreateSimpleButton("G", 16, 16)
        gbtn.SetPos(30, y - 2)
        g.Add(gbtn)
        API.AddControlOnClick(gbtn, lambda i=ridx: _on_gate_button(i))
        CONTROL_CONTROLS.append(gbtn)

        label = API.CreateGumpTTFLabel(f"{r['rune_name']} [{r['book_name']}]", 11, "#FFFFFF", "alagard", "left", RUNEMASTER_GUMP_W - 64)
        label.SetPos(56, y)
        g.Add(label)
        CONTROL_CONTROLS.append(label)
        y += RUNEMASTER_ROW_H

    page_y = g_h - 28
    pbtn = API.CreateSimpleButton("<", 24, 18)
    pbtn.SetPos(8, page_y)
    g.Add(pbtn)
    API.AddControlOnClick(pbtn, _on_prev_page)
    CONTROL_CONTROLS.append(pbtn)

    nbtn = API.CreateSimpleButton(">", 24, 18)
    nbtn.SetPos(36, page_y)
    g.Add(nbtn)
    API.AddControlOnClick(nbtn, _on_next_page)
    CONTROL_CONTROLS.append(nbtn)

    max_page = max(0, (_filtered_count() - 1) // max(1, PAGE_SIZE))
    page_lbl = API.CreateGumpTTFLabel(f"Page {ACTIVE_PAGE + 1}/{max_page + 1}", 11, "#CCCCCC", "alagard", "left", 90)
    page_lbl.SetPos(66, page_y + 2)
    g.Add(page_lbl)
    CONTROL_CONTROLS.append(page_lbl)

    sort_book = API.CreateSimpleButton("Book", 42, 18)
    sort_book.SetPos(156, page_y)
    g.Add(sort_book)
    API.AddControlOnClick(sort_book, _set_sort_book)
    CONTROL_CONTROLS.append(sort_book)

    sort_alpha = API.CreateSimpleButton("Alpha", 46, 18)
    sort_alpha.SetPos(202, page_y)
    g.Add(sort_alpha)
    API.AddControlOnClick(sort_alpha, _set_sort_alpha)
    CONTROL_CONTROLS.append(sort_alpha)

    ps12 = API.CreateSimpleButton("12", 26, 18)
    ps12.SetPos(252, page_y)
    g.Add(ps12)
    API.AddControlOnClick(ps12, _set_page_size_12)
    CONTROL_CONTROLS.append(ps12)

    ps16 = API.CreateSimpleButton("16", 26, 18)
    ps16.SetPos(282, page_y)
    g.Add(ps16)
    API.AddControlOnClick(ps16, _set_page_size_16)
    CONTROL_CONTROLS.append(ps16)

    ps24 = API.CreateSimpleButton("24", 26, 18)
    ps24.SetPos(312, page_y)
    g.Add(ps24)
    API.AddControlOnClick(ps24, _set_page_size_24)
    CONTROL_CONTROLS.append(ps24)

    run_all = API.CreateSimpleButton("Run", 40, 18)
    run_all.SetPos(342, page_y)
    g.Add(run_all)
    API.AddControlOnClick(run_all, _run_the_runes)
    CONTROL_CONTROLS.append(run_all)

    API.AddGump(g)
    CONTROL_GUMP = g


def _rebuild_gump():
    global CONTROL_GUMP
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
    _create_gump()


def _main():
    _load_config()
    _scan_runes()
    _create_gump()
    _say(f"RuneMaster loaded. {len(RUNES)} runes found.")
    while True:
        API.ProcessCallbacks()
        API.Pause(0.1)


_main()
