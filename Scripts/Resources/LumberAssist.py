import API

"""
LumberAssist
Version: 1.0
Last Updated: 2026-02-01

Features:
- Auto-chops nearby trees in a radius around the player.
- Marks the current target tree tile.
- Cuts logs into boards when overweight or when trees are depleted.
- Works with multiple axes; equips an axe before chopping.
- Simple gump with Start/Pause control.
"""

# Lumber journal texts that indicate no resources.
NO_WOOD_TEXTS = [
    "There is no wood here to harvest",
    "There is no wood here to chop",
    "There's not enough wood here to harvest.",
    "You can't think of a way to use that item",
    "You cannot see that",
    "That is too far away",
]
INVALID_AXE_TEXTS = [
    "You can't use an axe on that.",
]

# Items and tools.
AXE_GRAPHICS = [0x0F47]  # Battle axe (preferred first).
LOG_GRAPHIC = 0x1BDD  # Logs.
BOARD_GRAPHIC = 0x1BD7  # Boards.

# Search/behavior settings.
SEARCH_RADIUS = 2  # Tiles around player to scan for trees.
OVERWEIGHT_BUFFER = 60  # Cut logs to boards when within this of max.
MARK_HUE = 96  # Hue for MarkTile highlight (blue).

# Runtime state.
RUNNING = False
CONTROL_GUMP = None
CONTROL_BUTTON = None
MARKED_TILE = None
LAST_PLAYER_POS = None
DEPLETED_TILES = set()
CURRENT_AXE_SERIAL = None


def _find_axe():
    # Find an axe (equipped or in backpack), preferring battle axe.
    for graphic in AXE_GRAPHICS:
        axe = API.FindType(graphic)
        if axe:
            return axe
        axe = API.FindType(graphic, API.Backpack)
        if axe:
            return axe
    return None


def _equip_axe(axe):
    # Equip the axe if not already equipped.
    if not axe:
        return False
    API.EquipItem(axe.Serial)
    API.Pause(0.4)
    return True


def _get_active_axe():
    # Use the currently equipped axe if possible; otherwise equip one.
    global CURRENT_AXE_SERIAL
    if CURRENT_AXE_SERIAL:
        existing = API.FindItem(CURRENT_AXE_SERIAL)
        if existing:
            return existing
    axe = _find_axe()
    if not axe:
        return None
    _equip_axe(axe)
    CURRENT_AXE_SERIAL = axe.Serial
    return axe


def _mark_tile(x, y):
    # Mark the current tree tile and clear the previous mark.
    global MARKED_TILE
    if MARKED_TILE:
        API.RemoveMarkedTile(MARKED_TILE[0], MARKED_TILE[1])
    API.MarkTile(x, y, MARK_HUE)
    MARKED_TILE = (x, y)


def _clear_mark():
    # Clear any existing mark.
    global MARKED_TILE
    if MARKED_TILE:
        API.RemoveMarkedTile(MARKED_TILE[0], MARKED_TILE[1])
        MARKED_TILE = None


def _cut_logs_to_boards():
    # Convert logs to boards using the equipped axe.
    axe = _get_active_axe()
    if not axe:
        API.SysMsg("No axe found to cut logs.")
        return
    while True:
        log = API.FindType(LOG_GRAPHIC, API.Backpack)
        if not log:
            break
        API.SysMsg("Cut logs: using axe on logs.")
        API.UseObject(axe.Serial)
        if API.WaitForTarget("any", 2):
            API.Target(log.Serial)
        API.Pause(0.85)
        if API.InJournal("You must wait to perform another action", True):
            API.SysMsg("Cut logs: wait message seen.")


def _find_tree_tiles():
    # Scan nearby statics and return unique tree tiles.
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
    # De-dupe by tile position.
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
    # Attempt to chop a specific tile with an equipped axe.
    axe = _get_active_axe()
    if not axe:
        API.SysMsg("No axe found for chopping.")
        return False
    tx, ty, tz, graphic = tile
    _mark_tile(tx, ty)
    API.ClearJournal()
    API.SysMsg(f"Chop: using axe on tile {tx},{ty}.")
    API.Pause(0.75)
    API.UseObject(axe.Serial)
    if API.WaitForTarget("any", 2):
        API.Target(tx, ty, tz, graphic)
    API.Pause(1.0)
    if API.InJournal("You must wait to perform another action", True):
        API.SysMsg("Chop: wait message seen.")
        API.Pause(0.75)
        return False
    if API.InJournalAny(INVALID_AXE_TEXTS, True):
        DEPLETED_TILES.add((tx, ty))
        return False
    if API.InJournalAny(NO_WOOD_TEXTS, True):
        DEPLETED_TILES.add((tx, ty))
        return False
    return True


def _reset_cache_if_moved():
    # Clear depleted cache when the player moves.
    global LAST_PLAYER_POS
    pos = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
    if LAST_PLAYER_POS is None:
        LAST_PLAYER_POS = pos
        return
    if pos != LAST_PLAYER_POS:
        DEPLETED_TILES.clear()
        LAST_PLAYER_POS = pos


def _toggle_running():
    # Start/stop the lumber loop.
    global RUNNING
    RUNNING = not RUNNING
    state = "ON" if RUNNING else "OFF"
    API.SysMsg(f"LumberAssist: {state}")
    _update_gump()


def _update_gump():
    # Build or refresh the gump UI.
    global CONTROL_GUMP, CONTROL_BUTTON
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None

    g = API.CreateGump(True, True, False)
    g.SetRect(200, 200, 220, 90)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, 220, 90)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("LumberAssist", 14, "#FFFFFF", "alagard", "center", 220)
    title.SetPos(0, 6)
    g.Add(title)

    button = API.CreateSimpleButton("Start" if not RUNNING else "Pause", 80, 20)
    button.SetPos(70, 40)
    g.Add(button)
    API.AddControlOnClick(button, _toggle_running)
    CONTROL_BUTTON = button

    API.AddGump(g)
    CONTROL_GUMP = g


def _main_loop():
    _update_gump()
    API.SysMsg("LumberAssist loaded. Press Start to begin.")

    while True:
        API.ProcessCallbacks()
        if not RUNNING:
            API.Pause(0.2)
            continue

        _reset_cache_if_moved()

        if API.Player.Weight >= (API.Player.WeightMax - OVERWEIGHT_BUFFER):
            API.SysMsg("Overweight: cutting logs into boards.")
            _cut_logs_to_boards()

        tiles = _find_tree_tiles()
        if not tiles:
            API.SysMsg("No trees found nearby. Move to more trees.")
            _clear_mark()
            API.Pause(2.0)
            continue

        worked_any = False
        for tile in tiles:
            if not RUNNING:
                break
            success = _attempt_chop_tile(tile)
            if success:
                worked_any = True

        if not worked_any:
            API.HeadMsg("All nearby trees depleted. Move to more trees.", API.Player)
            _cut_logs_to_boards()
            _clear_mark()
            API.Pause(2.0)


_main_loop()
