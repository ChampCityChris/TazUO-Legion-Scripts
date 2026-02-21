import API
import json
import ast

"""
AutoJacker
Last Updated: 2026-02-13

Features:
- Runebook-driven lumberjacking loop (home rune in slot 1, lumber runes in slots 2-15).
- Uses LumberAssist-style nearby tree scan/harvest loop.
- Uses the player's equipped axe to harvest and cut logs.
- Overweight handling: cuts logs to boards, optionally loads boards to Giant Beetle,
  then recalls home to unload and resumes.
- Travel mode toggle (Mage/Chiv) with matching runebook button ranges.
- Optional Giant Beetle support to offload boards for carry weight relief.

Notes:
- Auto tooling is intentionally not included.
- You must equip an axe before starting.
"""

# Journal texts.
NO_WOOD_TEXTS = [
    "There is no wood here to harvest",
    "There is no wood here to chop",
    "There's not enough wood here to harvest.",
    "You cannot see that",
    "That is too far away",
]
INVALID_AXE_TEXTS = [
    "You can't use an axe on that.",
]
WAIT_TEXT = "You must wait to perform another action"

# Item graphics.
AXE_GRAPHICS = [
    0x0F47,  # Battle axe
    0x0F49,  # Axe
    0x13FB,  # Large battle axe
    0x143E,  # Halberd
]
LOG_GRAPHIC = 0x1BDD
BOARD_GRAPHIC = 0x1BD7

# Tree/harvest behavior.
SEARCH_RADIUS = 2
OVERWEIGHT_BUFFER = 50
MARK_HUE = 96
HARVEST_TARGET_TIMEOUT_S = 2
HARVEST_RESULT_WAIT_S = 1.0
CUT_RESULT_WAIT_S = 0.85

# Travel / recall.
RECALL_GUMP_ID = 0x59
HOME_RECALL_BUTTON = 50
LUMBER_RUNES = list(range(51, 66))
CURRENT_LUMBER_INDEX = 0
RECALL_SETTLE_S = 4.5

# UI / runtime state.
RUNNING = False
CONTROL_GUMP = None
CONTROL_BUTTON = None
USE_SACRED_JOURNEY = False
USE_GIANT_BEETLE = False

RUNBOOK_SERIAL = 0
DROP_CONTAINER_SERIAL = 0
GIANT_BEETLE_SERIAL = 0

MARKED_TILE = None
LAST_PLAYER_POS = None
DEPLETED_TILES = set()

DATA_KEY = "auto_jacker_config"


def _sleep(seconds):
    API.Pause(seconds)


def _responsive_wait(seconds):
    remaining = float(seconds)
    while remaining > 0:
        API.ProcessCallbacks()
        if not RUNNING:
            _pause_if_needed()
        step = 0.1 if remaining > 0.1 else remaining
        API.Pause(step)
        remaining -= step


def _say(msg, hue=88):
    API.SysMsg(msg, hue)


def _pause_if_needed():
    while not RUNNING:
        API.ProcessCallbacks()
        API.Pause(0.1)


def _stop_running():
    global RUNNING
    RUNNING = False
    if CONTROL_BUTTON:
        CONTROL_BUTTON.Text = "Start"


def _default_config():
    return {
        "runebook_serial": 0,
        "drop_container_serial": 0,
        "giant_beetle_serial": 0,
        "use_sacred_journey": False,
        "use_giant_beetle": False,
    }


def _apply_travel_mode():
    global HOME_RECALL_BUTTON, LUMBER_RUNES
    if USE_SACRED_JOURNEY:
        HOME_RECALL_BUTTON = 75
        LUMBER_RUNES = list(range(76, 91))
    else:
        HOME_RECALL_BUTTON = 50
        LUMBER_RUNES = list(range(51, 66))


def _load_config():
    global RUNBOOK_SERIAL, DROP_CONTAINER_SERIAL, GIANT_BEETLE_SERIAL, USE_SACRED_JOURNEY, USE_GIANT_BEETLE
    raw = API.GetPersistentVar(DATA_KEY, "", API.PersistentVar.Char)
    if raw:
        try:
            try:
                data = json.loads(raw)
            except Exception:
                data = ast.literal_eval(raw)
            RUNBOOK_SERIAL = int(data.get("runebook_serial", 0) or 0)
            DROP_CONTAINER_SERIAL = int(data.get("drop_container_serial", 0) or 0)
            GIANT_BEETLE_SERIAL = int(data.get("giant_beetle_serial", 0) or 0)
            USE_SACRED_JOURNEY = bool(data.get("use_sacred_journey", False))
            USE_GIANT_BEETLE = bool(data.get("use_giant_beetle", False))
        except Exception:
            data = _default_config()
            RUNBOOK_SERIAL = data["runebook_serial"]
            DROP_CONTAINER_SERIAL = data["drop_container_serial"]
            GIANT_BEETLE_SERIAL = data["giant_beetle_serial"]
            USE_SACRED_JOURNEY = data["use_sacred_journey"]
            USE_GIANT_BEETLE = data["use_giant_beetle"]
    else:
        data = _default_config()
        RUNBOOK_SERIAL = data["runebook_serial"]
        DROP_CONTAINER_SERIAL = data["drop_container_serial"]
        GIANT_BEETLE_SERIAL = data["giant_beetle_serial"]
        USE_SACRED_JOURNEY = data["use_sacred_journey"]
        USE_GIANT_BEETLE = data["use_giant_beetle"]
    _apply_travel_mode()


def _save_config():
    data = {
        "runebook_serial": int(RUNBOOK_SERIAL or 0),
        "drop_container_serial": int(DROP_CONTAINER_SERIAL or 0),
        "giant_beetle_serial": int(GIANT_BEETLE_SERIAL or 0),
        "use_sacred_journey": bool(USE_SACRED_JOURNEY),
        "use_giant_beetle": bool(USE_GIANT_BEETLE),
    }
    API.SavePersistentVar(DATA_KEY, json.dumps(data), API.PersistentVar.Char)


def _toggle_running():
    global RUNNING
    RUNNING = not RUNNING
    if CONTROL_BUTTON:
        CONTROL_BUTTON.Text = "Pause" if RUNNING else "Start"


def _set_mage():
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = False
    _apply_travel_mode()
    _save_config()
    _rebuild_gump()


def _set_chiv():
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = True
    _apply_travel_mode()
    _save_config()
    _rebuild_gump()


def _toggle_giant_beetle():
    global USE_GIANT_BEETLE
    USE_GIANT_BEETLE = not USE_GIANT_BEETLE
    _save_config()
    _rebuild_gump()


def _set_runebook():
    global RUNBOOK_SERIAL
    _say("Target runebook.")
    serial = API.RequestTarget()
    if serial:
        RUNBOOK_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_runebook():
    global RUNBOOK_SERIAL
    RUNBOOK_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_drop_container():
    global DROP_CONTAINER_SERIAL
    _say("Target drop container.")
    serial = API.RequestTarget()
    if serial:
        DROP_CONTAINER_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_drop_container():
    global DROP_CONTAINER_SERIAL
    DROP_CONTAINER_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _set_giant_beetle():
    global GIANT_BEETLE_SERIAL
    _say("Target giant beetle.")
    serial = API.RequestTarget()
    if serial:
        GIANT_BEETLE_SERIAL = int(serial)
        _save_config()
    _rebuild_gump()


def _unset_giant_beetle():
    global GIANT_BEETLE_SERIAL
    GIANT_BEETLE_SERIAL = 0
    _save_config()
    _rebuild_gump()


def _create_gump():
    global CONTROL_GUMP, CONTROL_BUTTON
    w = 330
    h = 250
    g = API.CreateGump(True, True, False)
    g.SetRect(420, 220, w, h)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, w, h)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("AutoJacker", 16, "#FFFFFF", "alagard", "center", w)
    title.SetPos(0, 6)
    g.Add(title)

    y = 38
    travel_mode = "Chiv" if USE_SACRED_JOURNEY else "Mage"
    travel_label = API.CreateGumpTTFLabel(f"Travel: {travel_mode}", 12, "#FFFFFF", "alagard", "left", 170)
    travel_label.SetPos(10, y)
    g.Add(travel_label)
    mage_btn = API.CreateSimpleButton("Mage", 50, 18)
    mage_btn.SetPos(190, y - 2)
    g.Add(mage_btn)
    API.AddControlOnClick(mage_btn, _set_mage)
    chiv_btn = API.CreateSimpleButton("Chiv", 50, 18)
    chiv_btn.SetPos(245, y - 2)
    g.Add(chiv_btn)
    API.AddControlOnClick(chiv_btn, _set_chiv)

    y += 26
    runebook_status = "Set" if RUNBOOK_SERIAL else "Unset"
    runebook_label = API.CreateGumpTTFLabel(f"Runebook: {runebook_status}", 12, "#FFFFFF", "alagard", "left", 180)
    runebook_label.SetPos(10, y)
    g.Add(runebook_label)
    runebook_set = API.CreateSimpleButton("Set", 50, 18)
    runebook_set.SetPos(190, y - 2)
    g.Add(runebook_set)
    API.AddControlOnClick(runebook_set, _set_runebook)
    runebook_unset = API.CreateSimpleButton("Unset", 50, 18)
    runebook_unset.SetPos(245, y - 2)
    g.Add(runebook_unset)
    API.AddControlOnClick(runebook_unset, _unset_runebook)

    y += 26
    drop_status = "Set" if DROP_CONTAINER_SERIAL else "Unset"
    drop_label = API.CreateGumpTTFLabel(f"Drop Container: {drop_status}", 12, "#FFFFFF", "alagard", "left", 180)
    drop_label.SetPos(10, y)
    g.Add(drop_label)
    drop_set = API.CreateSimpleButton("Set", 50, 18)
    drop_set.SetPos(190, y - 2)
    g.Add(drop_set)
    API.AddControlOnClick(drop_set, _set_drop_container)
    drop_unset = API.CreateSimpleButton("Unset", 50, 18)
    drop_unset.SetPos(245, y - 2)
    g.Add(drop_unset)
    API.AddControlOnClick(drop_unset, _unset_drop_container)

    y += 26
    gb_status = "On" if USE_GIANT_BEETLE else "Off"
    gb_label = API.CreateGumpTTFLabel(f"Giant Beetle: {gb_status}", 12, "#FFFFFF", "alagard", "left", 180)
    gb_label.SetPos(10, y)
    g.Add(gb_label)
    gb_toggle = API.CreateSimpleButton("Toggle", 50, 18)
    gb_toggle.SetPos(190, y - 2)
    g.Add(gb_toggle)
    API.AddControlOnClick(gb_toggle, _toggle_giant_beetle)
    gb_target = API.CreateSimpleButton("Set", 50, 18)
    gb_target.SetPos(245, y - 2)
    g.Add(gb_target)
    API.AddControlOnClick(gb_target, _set_giant_beetle)

    y += 26
    gb_serial_status = "Set" if GIANT_BEETLE_SERIAL else "Unset"
    gb_serial_label = API.CreateGumpTTFLabel(f"Beetle Target: {gb_serial_status}", 12, "#FFFFFF", "alagard", "left", 180)
    gb_serial_label.SetPos(10, y)
    g.Add(gb_serial_label)
    gb_unset = API.CreateSimpleButton("Unset", 50, 18)
    gb_unset.SetPos(245, y - 2)
    g.Add(gb_unset)
    API.AddControlOnClick(gb_unset, _unset_giant_beetle)

    CONTROL_BUTTON = API.CreateSimpleButton("Start", 100, 20)
    CONTROL_BUTTON.SetPos(int(w / 2) - 50, h - 28)
    g.Add(CONTROL_BUTTON)
    API.AddControlOnClick(CONTROL_BUTTON, _toggle_running)

    API.AddGump(g)
    CONTROL_GUMP = g


def _rebuild_gump():
    global CONTROL_GUMP
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
    _create_gump()


def _mark_tile(x, y):
    global MARKED_TILE
    if MARKED_TILE:
        API.RemoveMarkedTile(MARKED_TILE[0], MARKED_TILE[1])
    API.MarkTile(x, y, MARK_HUE)
    MARKED_TILE = (x, y)


def _clear_mark():
    global MARKED_TILE
    if MARKED_TILE:
        API.RemoveMarkedTile(MARKED_TILE[0], MARKED_TILE[1])
        MARKED_TILE = None


def _get_equipped_axe():
    # Prefer currently equipped hand items.
    hand_layers = ["RightHand", "LeftHand", "OneHanded", "TwoHanded"]
    for layer in hand_layers:
        try:
            item = API.FindLayer(layer)
        except Exception:
            item = None
        if item and int(getattr(item, "Graphic", 0)) in AXE_GRAPHICS:
            return item
    return None


def _cut_logs_to_boards():
    axe = _get_equipped_axe()
    if not axe:
        _say("No equipped axe found to cut logs.")
        return
    while True:
        _pause_if_needed()
        log = API.FindType(LOG_GRAPHIC, API.Backpack)
        if not log:
            break
        API.ClearJournal()
        API.UseObject(axe.Serial)
        if API.WaitForTarget("any", HARVEST_TARGET_TIMEOUT_S):
            API.Target(log.Serial)
        _responsive_wait(CUT_RESULT_WAIT_S)
        if API.InJournal(WAIT_TEXT, True):
            _responsive_wait(0.6)


def _find_tree_tiles():
    px = int(API.Player.X)
    py = int(API.Player.Y)
    statics = API.GetStaticsInArea(px - SEARCH_RADIUS, py - SEARCH_RADIUS, px + SEARCH_RADIUS, py + SEARCH_RADIUS) or []
    tiles = []
    for s in statics:
        tx = int(s.X)
        ty = int(s.Y)
        if (tx, ty) in DEPLETED_TILES:
            continue
        if getattr(s, "IsTree", False):
            tiles.append((tx, ty, int(s.Z), int(s.Graphic)))
    uniq = []
    seen = set()
    for t in tiles:
        key = (t[0], t[1])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    return uniq


def _attempt_chop_tile(tile):
    axe = _get_equipped_axe()
    if not axe:
        _say("No equipped axe found for chopping.")
        return "no_axe"
    tx, ty, tz, graphic = tile
    _mark_tile(tx, ty)
    API.ClearJournal()
    API.UseObject(axe.Serial)
    if API.WaitForTarget("any", HARVEST_TARGET_TIMEOUT_S):
        API.Target(tx, ty, tz, graphic)
    _responsive_wait(HARVEST_RESULT_WAIT_S)
    if API.InJournal(WAIT_TEXT, True):
        _responsive_wait(0.6)
        return "retry"
    if API.InJournalAny(INVALID_AXE_TEXTS, True):
        DEPLETED_TILES.add((tx, ty))
        return "no_wood"
    if API.InJournalAny(NO_WOOD_TEXTS, True):
        DEPLETED_TILES.add((tx, ty))
        return "no_wood"
    return "ok"


def _reset_cache_if_moved():
    global LAST_PLAYER_POS
    pos = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
    if LAST_PLAYER_POS is None:
        LAST_PLAYER_POS = pos
        return
    if pos != LAST_PLAYER_POS:
        DEPLETED_TILES.clear()
        LAST_PLAYER_POS = pos


def _is_overweight():
    try:
        return int(API.Player.Weight) >= int(API.Player.WeightMax) - OVERWEIGHT_BUFFER
    except Exception:
        return False


def _move_item_to_container(item, container_serial):
    if not item or not container_serial:
        return False
    amount = int(getattr(item, "Amount", 1) or 1)
    API.MoveItem(item.Serial, container_serial, amount)
    _responsive_wait(0.6)
    return True


def _move_boards_to_giant_beetle():
    if not USE_GIANT_BEETLE or not GIANT_BEETLE_SERIAL:
        return
    beetle = API.FindItem(GIANT_BEETLE_SERIAL)
    if not beetle:
        _say("Giant beetle not found.")
        return
    while True:
        board = API.FindType(BOARD_GRAPHIC, API.Backpack)
        if not board:
            break
        _pause_if_needed()
        _move_item_to_container(board, GIANT_BEETLE_SERIAL)


def _unload_wood_resources():
    if not DROP_CONTAINER_SERIAL:
        return
    API.UseObject(DROP_CONTAINER_SERIAL)
    _responsive_wait(0.6)
    backpack_items = API.ItemsInContainer(API.Backpack, True) or []
    for item in backpack_items:
        if int(getattr(item, "Graphic", 0)) in (LOG_GRAPHIC, BOARD_GRAPHIC):
            _move_item_to_container(item, DROP_CONTAINER_SERIAL)
    if USE_GIANT_BEETLE and GIANT_BEETLE_SERIAL:
        beetle_items = API.ItemsInContainer(GIANT_BEETLE_SERIAL, True) or []
        for item in beetle_items:
            if int(getattr(item, "Graphic", 0)) == BOARD_GRAPHIC:
                _move_item_to_container(item, DROP_CONTAINER_SERIAL)




def _wait_for_recall_mana(min_mana=20):
    announced = False
    while True:
        _pause_if_needed()
        try:
            mana = int(API.Player.Mana)
        except Exception:
            return True
        if mana >= int(min_mana):
            return True
        if not announced:
            _say(f"Waiting for mana ({mana}/{int(min_mana)}) before recall.")
            announced = True
        _responsive_wait(0.25)

def _cast_runebook_button(button_id):
    if not RUNBOOK_SERIAL:
        return False
    if not _wait_for_recall_mana(20):
        return False
    API.UseObject(RUNBOOK_SERIAL)
    _responsive_wait(0.4)
    try:
        API.ReplyGump(int(button_id), RECALL_GUMP_ID)
    except Exception:
        API.ReplyGump(int(button_id))
    _responsive_wait(RECALL_SETTLE_S)
    return True


def _recall_home():
    return _cast_runebook_button(HOME_RECALL_BUTTON)


def _recall_lumber_spot():
    if not LUMBER_RUNES:
        return False
    return _cast_runebook_button(LUMBER_RUNES[CURRENT_LUMBER_INDEX])


def _advance_lumber_spot():
    global CURRENT_LUMBER_INDEX
    if not LUMBER_RUNES:
        return
    CURRENT_LUMBER_INDEX = (CURRENT_LUMBER_INDEX + 1) % len(LUMBER_RUNES)


def _recall_home_and_unload():
    if not _recall_home():
        _say("Unable to recall home.")
        return False
    _cut_logs_to_boards()
    _move_boards_to_giant_beetle()
    _unload_wood_resources()
    return True


def _main():
    _load_config()
    _create_gump()
    _say("AutoJacker loaded. Equip an axe and press Start.")

    while True:
        API.ProcessCallbacks()
        _pause_if_needed()
        _reset_cache_if_moved()

        axe = _get_equipped_axe()
        if not axe:
            _say("Equip an axe to continue.")
            _stop_running()
            _sleep(0.3)
            continue

        if _is_overweight():
            _say("Overweight: cutting logs and unloading.")
            _cut_logs_to_boards()
            _move_boards_to_giant_beetle()
            if _is_overweight():
                if _recall_home_and_unload():
                    _responsive_wait(0.8)
                    _recall_lumber_spot()
            continue

        tiles = _find_tree_tiles()
        if not tiles:
            _say("No trees nearby at this spot. Advancing.")
            _clear_mark()
            if _is_overweight():
                if _recall_home_and_unload():
                    _advance_lumber_spot()
                    _responsive_wait(0.8)
                    _recall_lumber_spot()
            else:
                _advance_lumber_spot()
                _responsive_wait(0.8)
                _recall_lumber_spot()
            continue

        worked_any = False
        for tile in tiles:
            _pause_if_needed()
            result = _attempt_chop_tile(tile)
            if result == "no_axe":
                _stop_running()
                break
            if result == "ok":
                worked_any = True
            if _is_overweight():
                break

        if _is_overweight():
            continue

        if not worked_any:
            _say("Trees depleted here. Moving to next rune.")
            _cut_logs_to_boards()
            _move_boards_to_giant_beetle()
            _clear_mark()
            if _is_overweight():
                if _recall_home_and_unload():
                    _advance_lumber_spot()
                    _responsive_wait(0.8)
                    _recall_lumber_spot()
            else:
                _advance_lumber_spot()
                _responsive_wait(0.8)
                _recall_lumber_spot()

        _responsive_wait(0.2)


_main()
