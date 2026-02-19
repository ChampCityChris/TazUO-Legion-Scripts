import API

"""
Animal Tamer Trainer
Version: 1.0
Last Updated: 2026-02-01

Features:
- Casts Combat Training mastery on a selected pet.
- Auto-targets the pet and closes the Combat Training gump.
- Simple gump with Start/Pause and Set Pet controls.
"""

# Gump constants.
GUMP_ID = 0x1C05DD2C  # Combat Training gump id.
UI_X = 420
UI_Y = 240
UI_W = 260
UI_H = 120

# Runtime state.
RUNNING = False
PET_SERIAL = 0
CONTROL_GUMP = None
STATUS_LABEL = None


def _set_pet():
    # Target and store the pet serial.
    global PET_SERIAL
    API.SysMsg("Target your pet.")
    serial = API.RequestTarget()
    if serial:
        PET_SERIAL = int(serial)
        API.SysMsg(f"Pet set: 0x{PET_SERIAL:08X}")
    _update_gump()


def _toggle_running():
    # Start/stop the training loop.
    global RUNNING
    RUNNING = not RUNNING
    state = "ON" if RUNNING else "OFF"
    API.SysMsg(f"Tamer trainer: {state}")
    _update_gump()


def _update_gump():
    # Build/refresh the gump UI.
    global CONTROL_GUMP, STATUS_LABEL
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None

    g = API.CreateGump(True, True, False)
    g.SetRect(UI_X, UI_Y, UI_W, UI_H)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, UI_W, UI_H)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("Animal Tamer Trainer", 14, "#FFFFFF", "alagard", "center", UI_W)
    title.SetPos(0, 6)
    g.Add(title)

    pet_status = f"Pet: 0x{PET_SERIAL:08X}" if PET_SERIAL else "Pet: (unset)"
    status = API.CreateGumpTTFLabel(pet_status, 12, "#FFFFFF", "alagard", "left", UI_W - 20)
    status.SetPos(10, 30)
    g.Add(status)
    STATUS_LABEL = status

    btn = API.CreateSimpleButton("Start" if not RUNNING else "Pause", 80, 20)
    btn.SetPos(10, 60)
    g.Add(btn)
    API.AddControlOnClick(btn, _toggle_running)

    pet_btn = API.CreateSimpleButton("Set Pet", 80, 20)
    pet_btn.SetPos(110, 60)
    g.Add(pet_btn)
    API.AddControlOnClick(pet_btn, _set_pet)

    API.AddGump(g)
    CONTROL_GUMP = g


def _train_loop():
    global RUNNING
    _update_gump()
    API.SysMsg("Animal Tamer Trainer loaded. Set pet and press Start.")

    while True:
        API.ProcessCallbacks()
        if not RUNNING:
            API.Pause(0.2)
            continue
        if not PET_SERIAL:
            API.SysMsg("No pet set. Pausing.")
            RUNNING = False
            _update_gump()
            continue

        # Cast mastery (Combat Training).
        API.CastSpell("Combat Training")
        API.Pause(1.0)

        # Target pet if target cursor appears.
        if API.WaitForTarget("any", 5):
            API.Target(PET_SERIAL)
        API.Pause(0.5)

        # Close mastery gump if it appears.
        if API.WaitForGump(GUMP_ID, 8):
            API.CloseGump(GUMP_ID)
        else:
            API.SysMsg("Combat Training gump not found, retrying...")

        API.Pause(2.0)


_train_loop()
