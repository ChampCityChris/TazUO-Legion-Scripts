import API
import time
import json

"""
Champion City Code's Paladin Assist
Version: 0.1.0
Last Updated: 2026-01-29

Features:
- In-game gump with Enable/Disable toggle and options menu.
- Maintains Consecrate Weapon buff during combat with hostile targets.
- Designed to grow with additional paladin abilities and per-ability toggles.
"""

# --- Settings ---
HEADMSG_HUE = 1285
COMBAT_RANGE = 12
PAUSE_TICK = 0.1
MIN_RECAST_DELAY = 1.5
# Use FC/FCR tables to enforce global casting delay between spells.
USE_CAST_DELAY_TABLES = True
USE_BUFF_CHECK = False
LOW_HP_PERCENT_FOR_CLOSE_WOUNDS = 30.0
RESERVED_MANA_FOR_HEALING = 21
WEAPON_ABILITY_COOLDOWN = 5.0
# Manual timing inputs if buff data isn't reliable.
CHIVALRY_SKILL = 90.0
KARMA = 10000  # Typical positive karma scale is 0..10000 on many shards.
KARMA_MIN = 0
KARMA_MAX = 10000
CONSECRATE_MIN_SECONDS = 5.0
CONSECRATE_MAX_SECONDS = 11.0
DIVINE_FURY_MIN_SECONDS = 10.0
DIVINE_FURY_MAX_SECONDS = 23.0
ENEMY_OF_ONE_MIN_SECONDS = 67.0
ENEMY_OF_ONE_MAX_SECONDS = 228.0

ABILITIES = {
    "consecrate_weapon": {
        "name": "Consecrate Weapon",
        "spell": "Consecrate Weapon",
        "buff": "Consecrate Weapon",
        "enabled": True,
        "last_cast": 0.0,
        "expires_at": 0.0,
    },
    "divine_fury": {
        "name": "Divine Fury",
        "spell": "Divine Fury",
        "buff": "Divine Fury",
        "enabled": True,
        "last_cast": 0.0,
        "expires_at": 0.0,
    },
    "enemy_of_one": {
        "name": "Enemy of One",
        "spell": "Enemy of One",
        "buff": "Enemy of One",
        "enabled": True,
        "last_cast": 0.0,
        "expires_at": 0.0,
    },
    "close_wounds": {
        "name": "Close Wounds",
        "spell": "Close Wounds",
        "buff": None,
        "enabled": True,
        "last_cast": 0.0,
        "expires_at": 0.0,
    },
    "cleanse_by_fire": {
        "name": "Cleanse By Fire",
        "spell": "Cleanse By Fire",
        "buff": None,
        "enabled": True,
        "last_cast": 0.0,
        "expires_at": 0.0,
    },
}

SPELL_TOGGLES = [
    "consecrate_weapon",
    "divine_fury",
    "enemy_of_one",
]
HEALING_TOGGLES = [
    "close_wounds",
    "cleanse_by_fire",
]

PRIORITY_ORDER = [
    "consecrate_weapon",
    "divine_fury",
    "enemy_of_one",
    "primary_ability",
    "secondary_ability",
]

RUNNING = False
CONTROL_GUMP = None
CONTROL_BUTTON = None
CONTROL_BUTTON_LABEL = None
OPTIONS_GUMP = None
LOG_GUMP = None
LOG_LINES = []
DEBUG = True
DEBUG_INTERVAL = 2.0
_last_debug = 0.0
DEBUG_CAST = True
DEBUG_LOG_MAX_LINES = 120
LAST_SPELL_CAST_TIME = 0.0
PRIMARY_ABILITY_NAME = "Unknown"
SECONDARY_ABILITY_NAME = "Unknown"
ABILITY_REFRESH_INTERVAL = 20.0
_last_ability_refresh = 0.0
PRIMARY_ABILITY_LABEL = None
SECONDARY_ABILITY_LABEL = None
PRIMARY_ABILITY_CHECKBOX = None
SECONDARY_ABILITY_CHECKBOX = None
PRIMARY_ABILITY_ENABLED = True
SECONDARY_ABILITY_ENABLED = True
PRIMARY_ABILITY_LAST_USED = 0.0
SECONDARY_ABILITY_LAST_USED = 0.0
HEALING_TARGET_MODE = {
    "close_wounds": "self",
    "cleanse_by_fire": "self",
}
DEBUG_ABILITY_REASON = True
_last_ability_debug = {"primary": 0.0, "secondary": 0.0}

FC_CAST_TIMES = {
    "consecrate_weapon": {-3: 1.50, -2: 1.25, -1: 1.00, 0: 0.75, 1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50, 5: 0.50, 6: 0.50},
    "divine_fury": {-3: 2.00, -2: 1.75, -1: 1.50, 0: 1.25, 1: 1.00, 2: 0.75, 3: 0.50, 4: 0.50, 5: 0.50, 6: 0.50},
    "enemy_of_one": {-3: 1.50, -2: 1.25, -1: 1.00, 0: 0.75, 1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50, 5: 0.50, 6: 0.50},
    "close_wounds": {-3: 2.50, -2: 2.25, -1: 2.00, 0: 1.75, 1: 1.50, 2: 1.25, 3: 1.00, 4: 0.75, 5: 0.50, 6: 0.50},
    "cleanse_by_fire": {-3: 2.00, -2: 1.75, -1: 1.50, 0: 1.25, 1: 1.00, 2: 0.75, 3: 0.50, 4: 0.50, 5: 0.50, 6: 0.50},
}
FCR_RECOVERY = {0: 1.75, 1: 1.50, 2: 1.25, 3: 1.00, 4: 0.75, 5: 0.50, 6: 0.25, 7: 0.00}

SETTINGS_KEY = "paladin_assist_settings"


def _default_settings_state():
    return {
        "debug": bool(DEBUG),
        "priority_order": list(PRIORITY_ORDER),
        "primary_ability_enabled": bool(PRIMARY_ABILITY_ENABLED),
        "secondary_ability_enabled": bool(SECONDARY_ABILITY_ENABLED),
        "ability_enabled": {k: bool(v.get("enabled", False)) for k, v in ABILITIES.items()},
        "healing_target_mode": dict(HEALING_TARGET_MODE),
    }


def _save_settings_state():
    data = _default_settings_state()
    API.SavePersistentVar(SETTINGS_KEY, json.dumps(data), API.PersistentVar.Char)


def _load_settings_state():
    global DEBUG, PRIORITY_ORDER, PRIMARY_ABILITY_ENABLED, SECONDARY_ABILITY_ENABLED, HEALING_TARGET_MODE
    raw = API.GetPersistentVar(SETTINGS_KEY, "", API.PersistentVar.Char)
    if not raw:
        return
    try:
        data = json.loads(raw)
    except Exception:
        return

    DEBUG = bool(data.get("debug", DEBUG))

    saved_priority = data.get("priority_order")
    if isinstance(saved_priority, list):
        valid = [k for k in saved_priority if k in PRIORITY_ORDER]
        for key in PRIORITY_ORDER:
            if key not in valid:
                valid.append(key)
        PRIORITY_ORDER[:] = valid

    ability_enabled = data.get("ability_enabled", {})
    if isinstance(ability_enabled, dict):
        for key, value in ability_enabled.items():
            if key in ABILITIES:
                ABILITIES[key]["enabled"] = bool(value)

    PRIMARY_ABILITY_ENABLED = bool(data.get("primary_ability_enabled", PRIMARY_ABILITY_ENABLED))
    SECONDARY_ABILITY_ENABLED = bool(data.get("secondary_ability_enabled", SECONDARY_ABILITY_ENABLED))

    healing_modes = data.get("healing_target_mode", {})
    if isinstance(healing_modes, dict):
        for key in HEALING_TARGET_MODE.keys():
            mode = healing_modes.get(key, HEALING_TARGET_MODE[key])
            HEALING_TARGET_MODE[key] = "cursor" if mode == "cursor" else "self"

WEAPON_ABILITY_SKILLS = [
    "Swordsmanship",
    "Mace Fighting",
    "Fencing",
    "Archery",
    "Parrying",
    "Lumberjacking",
    "Stealth",
    "Poisoning",
    "Bushido",
    "Ninjitsu",
    "Throwing",
]


def _toggle_running():
    global RUNNING
    RUNNING = not RUNNING
    state = "ON" if RUNNING else "OFF"
    API.SysMsg(f"Paladin Assist: {state}", HEADMSG_HUE)
    _update_control_gump()


def _set_debug_on():
    global DEBUG
    DEBUG = True
    _save_settings_state()
    API.SysMsg("Paladin Assist debug enabled.", HEADMSG_HUE)
    _rebuild_control_gump()


def _set_debug_off():
    global DEBUG
    DEBUG = False
    _save_settings_state()
    API.SysMsg("Paladin Assist debug disabled.", HEADMSG_HUE)
    _rebuild_control_gump()


def _append_log(msg):
    global LOG_LINES
    LOG_LINES.append(str(msg))
    if len(LOG_LINES) > DEBUG_LOG_MAX_LINES:
        LOG_LINES = LOG_LINES[-DEBUG_LOG_MAX_LINES:]
    if LOG_GUMP:
        _create_log_gump()


def _debug(msg):
    _append_log(msg)
    if DEBUG:
        API.SysMsg(msg, HEADMSG_HUE)


def _toggle_log_gump():
    global LOG_GUMP
    if LOG_GUMP:
        LOG_GUMP.Dispose()
        LOG_GUMP = None
    else:
        _create_log_gump()


def _create_log_gump():
    global LOG_GUMP
    if LOG_GUMP:
        LOG_GUMP.Dispose()
        LOG_GUMP = None

    g = API.CreateGump(True, True, False)
    width = 420
    height = 300
    g.SetRect(430, 120, width, height)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, width, height)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("PaladinAssist Debug Log", 14, "#FFFFFF", "alagard", "center", width)
    title.SetPos(0, 6)
    g.Add(title)

    lines = LOG_LINES[-18:] if LOG_LINES else ["(log empty)"]
    y = 28
    for line in lines:
        label = API.CreateGumpTTFLabel(line[:78], 11, "#CCCCCC", "alagard", "left", width - 16)
        label.SetPos(8, y)
        g.Add(label)
        y += 14

    close_btn = API.CreateSimpleButton("Close", 80, 20)
    close_btn.SetPos(width - 90, height - 28)
    g.Add(close_btn)
    API.AddControlOnClick(close_btn, _toggle_log_gump)

    API.AddGump(g)
    LOG_GUMP = g


def _update_control_gump():
    if not CONTROL_BUTTON:
        return
    text = "Pause" if RUNNING else "Start"
    CONTROL_BUTTON.Text = ""
    if CONTROL_BUTTON_LABEL:
        CONTROL_BUTTON_LABEL.Text = text


def _pause_if_needed():
    while not RUNNING:
        API.ProcessCallbacks()
        API.Pause(PAUSE_TICK)


def _in_combat():
    return bool(API.Player and API.Player.InWarMode)


def _debug_status():
    global _last_debug
    if not DEBUG:
        return
    now = time.time()
    if now - _last_debug < DEBUG_INTERVAL:
        return
    _last_debug = now
    in_combat = _in_combat()
    msg = "PaladinAssist running"
    if API.Player:
        msg += f" | War: {API.Player.InWarMode}"
    msg += f" | Combat: {in_combat}"
    _debug(msg)


def _can_cast_ability(ability):
    now = time.time()
    if API.Player and API.Player.IsCasting:
        if now - LAST_SPELL_CAST_TIME < 0.6:
            return False
    if now - ability["last_cast"] < MIN_RECAST_DELAY:
        return False
    return True


def _player_hp_percent():
    if not API.Player or not API.Player.HitsMax:
        return 100.0
    return (float(API.Player.Hits) / float(API.Player.HitsMax)) * 100.0


def _get_skill_value(name):
    skill = API.GetSkill(name)
    if not skill or skill.Value is None:
        return 0.0
    return float(skill.Value)


def _mana_low_for_non_heal():
    if not API.Player:
        return False
    return int(API.Player.Mana) < int(RESERVED_MANA_FOR_HEALING)


def _has_mana_for_heal(cost):
    if not API.Player:
        return False
    return (int(API.Player.Mana) - int(cost)) >= int(RESERVED_MANA_FOR_HEALING)


def _target_heal_spell(key):
    if HEALING_TARGET_MODE.get(key, "self") == "self":
        API.TargetSelf()
        return
    API.SysMsg("Select healing target.")
    serial = API.RequestTarget()
    if serial:
        API.Target(serial)
    else:
        API.TargetSelf()


def _weapon_ability_skill_points():
    total = 0.0
    for name in WEAPON_ABILITY_SKILLS:
        skill = API.GetSkill(name)
        if skill and skill.Value is not None:
            total += float(skill.Value)
    # Skill.Value is usually reported in tenths (e.g., 100.0 = 1000). Convert to points.
    return total / 10.0


def _weapon_ability_mana_cost():
    points = _weapon_ability_skill_points()
    cost = 30
    if points >= 300:
        cost -= 10
    elif points >= 200:
        cost -= 5
    return cost


def _has_mana_for_weapon_ability():
    if not API.Player:
        return False
    cost = _weapon_ability_mana_cost()
    return (int(API.Player.Mana) - cost) >= int(RESERVED_MANA_FOR_HEALING)


def _current_fc():
    if not API.Player:
        return 0
    return int(API.Player.FasterCasting or 0)


def _current_fcr():
    if not API.Player:
        return 0
    return int(API.Player.FasterCastRecovery or 0)


def _cast_delay_for_spell(spell_key):
    fc = _current_fc()
    if fc < -3:
        fc = -3
    if fc > 6:
        fc = 6
    fcr = _current_fcr()
    if fcr < 0:
        fcr = 0
    if fcr > 7:
        fcr = 7
    cast_time = FC_CAST_TIMES.get(spell_key, {}).get(fc, 0.50)
    recovery = FCR_RECOVERY.get(fcr, 0.00)
    return cast_time + recovery


def _can_cast_global(spell_key):
    if not USE_CAST_DELAY_TABLES:
        return True
    now = time.time()
    delay = _cast_delay_for_spell(spell_key)
    return (now - LAST_SPELL_CAST_TIME) >= delay


def _consecrate_duration_seconds():
    # Karma scales duration from 5-11 seconds. If your shard differs, adjust these values.
    karma = max(KARMA_MIN, min(KARMA, KARMA_MAX))
    if KARMA_MAX == KARMA_MIN:
        return CONSECRATE_MIN_SECONDS
    t = float(karma - KARMA_MIN) / float(KARMA_MAX - KARMA_MIN)
    return CONSECRATE_MIN_SECONDS + (CONSECRATE_MAX_SECONDS - CONSECRATE_MIN_SECONDS) * t


def _divine_fury_duration_seconds():
    # Use same scaling as Consecrate Weapon by default; adjust if your shard differs.
    karma = max(KARMA_MIN, min(KARMA, KARMA_MAX))
    if KARMA_MAX == KARMA_MIN:
        return DIVINE_FURY_MIN_SECONDS
    t = float(karma - KARMA_MIN) / float(KARMA_MAX - KARMA_MIN)
    return DIVINE_FURY_MIN_SECONDS + (DIVINE_FURY_MAX_SECONDS - DIVINE_FURY_MIN_SECONDS) * t


def _enemy_of_one_duration_seconds():
    # Scales by karma and chivalry skill (min 45). Linear blend.
    karma = max(KARMA_MIN, min(KARMA, KARMA_MAX))
    if KARMA_MAX == KARMA_MIN:
        karma_t = 0.0
    else:
        karma_t = float(karma - KARMA_MIN) / float(KARMA_MAX - KARMA_MIN)
    chiv_skill = API.GetSkill("Chivalry")
    chiv = float(chiv_skill.Value) if chiv_skill and chiv_skill.Value is not None else 0.0
    if chiv < 45:
        chiv_t = 0.0
    elif chiv >= 120:
        chiv_t = 1.0
    else:
        chiv_t = (chiv - 45.0) / (120.0 - 45.0)
    t = (karma_t + chiv_t) / 2.0
    return ENEMY_OF_ONE_MIN_SECONDS + (ENEMY_OF_ONE_MAX_SECONDS - ENEMY_OF_ONE_MIN_SECONDS) * t


def _cast_consecrate_weapon(in_combat):
    ability = ABILITIES["consecrate_weapon"]
    if not ability["enabled"]:
        return False
    if not in_combat:
        return False
    if _mana_low_for_non_heal():
        return False
    if not _can_cast_global("consecrate_weapon"):
        return False
    if not _can_cast_ability(ability):
        return False
    now = time.time()
    expires_at = ability.get("expires_at", 0.0)
    if USE_BUFF_CHECK and API.BuffExists(ability["buff"]):
        if not expires_at:
            ability["expires_at"] = now + _consecrate_duration_seconds()
            expires_at = ability["expires_at"]
        if now < expires_at:
            return False
    elif expires_at and now < expires_at:
        return False
    if DEBUG_CAST:
        _debug("Casting Consecrate Weapon")
    API.CastSpell(ability["spell"])
    ability["last_cast"] = now
    ability["expires_at"] = now + _consecrate_duration_seconds()
    global LAST_SPELL_CAST_TIME
    LAST_SPELL_CAST_TIME = now
    return True


def _cast_divine_fury(in_combat):
    ability = ABILITIES["divine_fury"]
    if not ability["enabled"]:
        return False
    if not in_combat:
        return False
    if _mana_low_for_non_heal():
        return False
    if not _can_cast_global("divine_fury"):
        return False
    if not _can_cast_ability(ability):
        return False
    now = time.time()
    expires_at = ability.get("expires_at", 0.0)
    if USE_BUFF_CHECK and API.BuffExists(ability["buff"]):
        if not expires_at:
            ability["expires_at"] = now + _divine_fury_duration_seconds()
            expires_at = ability["expires_at"]
        if now < expires_at:
            return False
    elif expires_at and now < expires_at:
        return False
    if DEBUG_CAST:
        _debug("Casting Divine Fury")
    API.CastSpell(ability["spell"])
    ability["last_cast"] = now
    ability["expires_at"] = now + _divine_fury_duration_seconds()
    global LAST_SPELL_CAST_TIME
    LAST_SPELL_CAST_TIME = now
    return True


def _cast_enemy_of_one(in_combat):
    ability = ABILITIES["enemy_of_one"]
    if not ability["enabled"]:
        return False
    if not in_combat:
        return False
    if _mana_low_for_non_heal():
        return False
    chiv_skill = API.GetSkill("Chivalry")
    chiv = float(chiv_skill.Value) if chiv_skill and chiv_skill.Value is not None else 0.0
    if chiv < 45:
        return False
    if not _can_cast_global("enemy_of_one"):
        return False
    if not _can_cast_ability(ability):
        return False
    now = time.time()
    expires_at = ability.get("expires_at", 0.0)
    if USE_BUFF_CHECK and API.BuffExists(ability["buff"]):
        if not expires_at:
            ability["expires_at"] = now + _enemy_of_one_duration_seconds()
            expires_at = ability["expires_at"]
        if now < expires_at:
            return False
    elif expires_at and now < expires_at:
        return False
    if DEBUG_CAST:
        _debug("Casting Enemy of One")
    API.CastSpell(ability["spell"])
    ability["last_cast"] = now
    ability["expires_at"] = now + _enemy_of_one_duration_seconds()
    global LAST_SPELL_CAST_TIME
    LAST_SPELL_CAST_TIME = now
    return True


def _cast_close_wounds():
    ability = ABILITIES["close_wounds"]
    if not ability["enabled"]:
        return False
    if _player_hp_percent() >= LOW_HP_PERCENT_FOR_CLOSE_WOUNDS:
        return False
    if not _has_mana_for_heal(11):
        return False
    if not _can_cast_global("close_wounds"):
        return False
    if not _can_cast_ability(ability):
        return False
    now = time.time()
    if DEBUG_CAST:
        _debug("Casting Close Wounds")
    API.CastSpell(ability["spell"])
    if API.WaitForTarget("any", 2):
        _target_heal_spell("close_wounds")
    ability["last_cast"] = now
    global LAST_SPELL_CAST_TIME
    LAST_SPELL_CAST_TIME = now
    return True


def _cast_cleanse_by_fire():
    ability = ABILITIES["cleanse_by_fire"]
    if not ability["enabled"]:
        return False
    if not API.Player or (not API.Player.IsPoisoned and not API.BuffExists("Disease")):
        return False
    if not _can_cast_global("cleanse_by_fire"):
        return False
    if not _can_cast_ability(ability):
        return False
    now = time.time()
    if DEBUG_CAST:
        _debug("Casting Cleanse By Fire")
    API.CastSpell(ability["spell"])
    if API.WaitForTarget("any", 2):
        _target_heal_spell("cleanse_by_fire")
    ability["last_cast"] = now
    global LAST_SPELL_CAST_TIME
    LAST_SPELL_CAST_TIME = now
    return True


def _set_ability_enabled(key, enabled):
    if key in ABILITIES:
        ABILITIES[key]["enabled"] = bool(enabled)
        _save_settings_state()


def _make_toggle_callback(key, checkbox):
    def _toggle():
        _set_ability_enabled(key, checkbox.IsChecked)
    return _toggle


def _on_options_closed():
    global OPTIONS_GUMP
    OPTIONS_GUMP = None


def _close_options_gump():
    global OPTIONS_GUMP
    if OPTIONS_GUMP:
        OPTIONS_GUMP.Dispose()
        OPTIONS_GUMP = None
        _clear_ability_labels()


def _clear_ability_labels():
    global PRIMARY_ABILITY_LABEL, SECONDARY_ABILITY_LABEL, PRIMARY_ABILITY_CHECKBOX, SECONDARY_ABILITY_CHECKBOX
    PRIMARY_ABILITY_LABEL = None
    SECONDARY_ABILITY_LABEL = None
    PRIMARY_ABILITY_CHECKBOX = None
    SECONDARY_ABILITY_CHECKBOX = None


def _load_weapon_abilities():
    global PRIMARY_ABILITY_NAME, SECONDARY_ABILITY_NAME, _last_ability_refresh
    names = API.CurrentAbilityNames() or []
    if len(names) >= 1 and names[0]:
        PRIMARY_ABILITY_NAME = str(names[0])
    else:
        PRIMARY_ABILITY_NAME = "Unknown"
    if len(names) >= 2 and names[1]:
        SECONDARY_ABILITY_NAME = str(names[1])
    else:
        SECONDARY_ABILITY_NAME = "Unknown"
    _last_ability_refresh = time.time()
    _update_ability_labels()


def _format_ability_name(name):
    return name if name and name != "Unknown" else "ability"


def _update_ability_labels():
    return


def _create_options_gump():
    global OPTIONS_GUMP
    if OPTIONS_GUMP:
        return
    g = API.CreateGump(True, True, False)
    row_h = 22
    width = 300
    height = 140 + (len(PRIORITY_ORDER) * row_h) + (len(SPELL_TOGGLES) * row_h) + (2 * row_h) + ((len(HEALING_TOGGLES) * 2) * row_h) + (6 * row_h)
    g.SetRect(140, 140, width, height)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, width, height)
    g.Add(bg)

    label = API.CreateGumpTTFLabel("Paladin Assist Options", 16, "#FFFFFF", "alagard", "center", width)
    label.SetPos(0, 6)
    g.Add(label)

    y = 30
    priority_label = API.CreateGumpTTFLabel("CAST PRIORITY:", 14, "#FFFFFF", "alagard", "let", width - 20)
    priority_label.SetPos(10, y)
    g.Add(priority_label)
    y += row_h

    for key in _active_priority_order():
        name = _priority_display_name(key)
        item_label = API.CreateGumpTTFLabel(name, 12, "#FFFFFF", "alagard", "let", width - 110)
        item_label.SetPos(10, y)
        g.Add(item_label)

        up_btn = API.CreateSimpleButton("Up", 40, 18)
        up_btn.SetPos(width - 90, y - 2)
        g.Add(up_btn)
        API.AddControlOnClick(up_btn, lambda k=key: _move_priority(k, -1))

        down_btn = API.CreateSimpleButton("Dn", 40, 18)
        down_btn.SetPos(width - 45, y - 2)
        g.Add(down_btn)
        API.AddControlOnClick(down_btn, lambda k=key: _move_priority(k, 1))
        y += row_h

    y += 6
    for key in SPELL_TOGGLES:
        ability = ABILITIES.get(key)
        if not ability:
            continue
        cb = API.CreateGumpCheckbox(ability["name"], 996, ability["enabled"])
        cb.SetPos(10, y)
        g.Add(cb)
        API.AddControlOnClick(cb, _make_toggle_callback(key, cb))
        y += row_h

    y += 6
    abilities_label = API.CreateGumpTTFLabel("ABILITIES:", 12, "#FFFFFF", "alagard", "let", width - 20)
    abilities_label.SetPos(10, y)
    g.Add(abilities_label)
    y += row_h

    global PRIMARY_ABILITY_CHECKBOX, SECONDARY_ABILITY_CHECKBOX

    primary_cb = API.CreateGumpCheckbox("Use Primary Ability", 996, PRIMARY_ABILITY_ENABLED)
    primary_cb.SetPos(10, y)
    g.Add(primary_cb)
    API.AddControlOnClick(primary_cb, lambda c=primary_cb: _set_primary_enabled(c.IsChecked))
    PRIMARY_ABILITY_CHECKBOX = primary_cb
    y += row_h

    secondary_cb = API.CreateGumpCheckbox("Use Secondary Ability", 996, SECONDARY_ABILITY_ENABLED)
    secondary_cb.SetPos(10, y)
    g.Add(secondary_cb)
    API.AddControlOnClick(secondary_cb, lambda c=secondary_cb: _set_secondary_enabled(c.IsChecked))
    SECONDARY_ABILITY_CHECKBOX = secondary_cb
    y += row_h

    y += 6
    heal_label = API.CreateGumpTTFLabel("HEALING:", 12, "#FFFFFF", "alagard", "let", width - 20)
    heal_label.SetPos(10, y)
    g.Add(heal_label)
    y += row_h

    col_label_spell = API.CreateGumpTTFLabel("Spell", 12, "#FFFFFF", "alagard", "let", 80)
    col_label_spell.SetPos(10, y)
    g.Add(col_label_spell)
    col_label_self = API.CreateGumpTTFLabel("Self", 12, "#FFFFFF", "alagard", "let", 40)
    col_label_self.SetPos(180, y)
    g.Add(col_label_self)
    col_label_cursor = API.CreateGumpTTFLabel("Cursor", 12, "#FFFFFF", "alagard", "let", 50)
    col_label_cursor.SetPos(240, y)
    g.Add(col_label_cursor)
    y += row_h

    for key in HEALING_TOGGLES:
        ability = ABILITIES.get(key)
        if not ability:
            continue
        heal_cb = API.CreateGumpCheckbox(ability["name"], 996, ability["enabled"])
        heal_cb.SetPos(10, y)
        g.Add(heal_cb)
        API.AddControlOnClick(heal_cb, _make_toggle_callback(key, heal_cb))
        mode = HEALING_TARGET_MODE.get(key, "self")
        self_cb = API.CreateGumpCheckbox("", 996, mode == "self")
        self_cb.SetPos(180, y)
        g.Add(self_cb)
        API.AddControlOnClick(self_cb, lambda k=key: _set_healing_target_mode(k, "self"))

        cursor_cb = API.CreateGumpCheckbox("", 996, mode == "cursor")
        cursor_cb.SetPos(240, y)
        g.Add(cursor_cb)
        API.AddControlOnClick(cursor_cb, lambda k=key: _set_healing_target_mode(k, "cursor"))
        y += row_h

    close_button = API.CreateSimpleButton("Close", 80, 20)
    close_button.SetPos(width - 90, height - 26)
    g.Add(close_button)
    API.AddControlOnClick(close_button, _close_options_gump)

    API.AddControlOnDisposed(g, _on_options_closed)
    API.AddGump(g)
    OPTIONS_GUMP = g


def _toggle_options_gump():
    if OPTIONS_GUMP:
        _close_options_gump()
    else:
        _create_options_gump()


def _set_primary_enabled(enabled):
    global PRIMARY_ABILITY_ENABLED
    PRIMARY_ABILITY_ENABLED = bool(enabled)
    _save_settings_state()


def _set_secondary_enabled(enabled):
    global SECONDARY_ABILITY_ENABLED
    SECONDARY_ABILITY_ENABLED = bool(enabled)
    _save_settings_state()


def _set_healing_target_mode(key, mode):
    HEALING_TARGET_MODE[key] = mode
    _save_settings_state()


def _priority_display_name(key):
    if key == "primary_ability":
        return f"Primary {_format_ability_name(PRIMARY_ABILITY_NAME)}"
    if key == "secondary_ability":
        return f"Secondary {_format_ability_name(SECONDARY_ABILITY_NAME)}"
    ability = ABILITIES.get(key)
    return ability["name"] if ability else key


def _priority_enabled(key):
    if key == "primary_ability":
        return PRIMARY_ABILITY_ENABLED
    if key == "secondary_ability":
        return SECONDARY_ABILITY_ENABLED
    ability = ABILITIES.get(key)
    return bool(ability and ability["enabled"])


def _active_priority_order():
    return [k for k in PRIORITY_ORDER if _priority_enabled(k)]


def _move_priority(key, direction):
    if key not in PRIORITY_ORDER:
        return
    idx = PRIORITY_ORDER.index(key)
    new_idx = idx + direction
    if new_idx < 0 or new_idx >= len(PRIORITY_ORDER):
        return
    PRIORITY_ORDER[idx], PRIORITY_ORDER[new_idx] = PRIORITY_ORDER[new_idx], PRIORITY_ORDER[idx]
    _save_settings_state()
    _rebuild_control_gump()


def _rebuild_control_gump():
    global CONTROL_GUMP, CONTROL_BUTTON, CONTROL_BUTTON_LABEL
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
        CONTROL_BUTTON = None
        CONTROL_BUTTON_LABEL = None
    _create_control_gump()


def _on_control_closed():
    global CONTROL_GUMP, CONTROL_BUTTON
    CONTROL_GUMP = None
    CONTROL_BUTTON = None


def _can_use_weapon_ability(last_used):
    return (time.time() - last_used) >= WEAPON_ABILITY_COOLDOWN


def _debug_ability_skip(which, reason):
    if not (DEBUG_CAST and DEBUG_ABILITY_REASON):
        return
    now = time.time()
    last = _last_ability_debug.get(which, 0.0)
    if now - last < 2.0:
        return
    _last_ability_debug[which] = now
    _debug(f"{which.capitalize()} ability skipped: {reason}")


def _use_primary_ability():
    global PRIMARY_ABILITY_LAST_USED
    if not PRIMARY_ABILITY_ENABLED:
        _debug_ability_skip("primary", "disabled")
        return False
    if not _has_mana_for_weapon_ability():
        _debug_ability_skip("primary", "mana reserve")
        return False
    if API.PrimaryAbilityActive():
        _debug_ability_skip("primary", "already active")
        return False
    if not _can_use_weapon_ability(PRIMARY_ABILITY_LAST_USED):
        _debug_ability_skip("primary", "cooldown")
        return False
    API.ToggleAbility("primary")
    if DEBUG_CAST:
        _debug("Toggled Primary Ability")
    PRIMARY_ABILITY_LAST_USED = time.time()
    return True


def _use_secondary_ability():
    global SECONDARY_ABILITY_LAST_USED
    if not SECONDARY_ABILITY_ENABLED:
        _debug_ability_skip("secondary", "disabled")
        return False
    if not _has_mana_for_weapon_ability():
        _debug_ability_skip("secondary", "mana reserve")
        return False
    if API.SecondaryAbilityActive():
        _debug_ability_skip("secondary", "already active")
        return False
    if not _can_use_weapon_ability(SECONDARY_ABILITY_LAST_USED):
        _debug_ability_skip("secondary", "cooldown")
        return False
    API.ToggleAbility("secondary")
    if DEBUG_CAST:
        _debug("Toggled Secondary Ability")
    SECONDARY_ABILITY_LAST_USED = time.time()
    return True


def _create_control_gump():
    global CONTROL_GUMP, CONTROL_BUTTON, CONTROL_BUTTON_LABEL
    if CONTROL_GUMP:
        return
    g = API.CreateGump(True, True, True)
    row_h = 22
    width = 320
    height = 190
    g.SetRect(100, 100, width, height)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, width, height)
    g.Add(bg)

    label = API.CreateGumpTTFLabel("Paladin's Squire 1.0", 16, "#FFFFFF", "alagard", "center", width)
    label.SetPos(0, 6)
    g.Add(label)

    button_w = 120
    button_h = 26
    button_x = int((width - button_w) / 2)
    button_y = 32
    button = API.CreateSimpleButton("", button_w, button_h)
    button.SetPos(button_x, button_y)
    g.Add(button)
    API.AddControlOnClick(button, _toggle_running)
    CONTROL_BUTTON = button
    label = API.CreateGumpTTFLabel("Enable", 15, "#FFFFFF", "alagard", "center", button_w)
    label.SetPos(button_x, button_y + 3)
    g.Add(label)
    CONTROL_BUTTON_LABEL = label

    opt_btn = API.CreateSimpleButton("", 120, 24)
    opt_btn.SetPos(int((width - 120) / 2), 70)
    g.Add(opt_btn)
    API.AddControlOnClick(opt_btn, _toggle_options_gump)
    opt_label = API.CreateGumpTTFLabel("Options", 14, "#FFFFFF", "alagard", "center", 120)
    opt_label.SetPos(int((width - 120) / 2), 72)
    g.Add(opt_label)

    debug_status = "On" if DEBUG else "Off"
    debug_label = API.CreateGumpTTFLabel(f"Debug: {debug_status}", 12, "#FFFFFF", "alagard", "left", 120)
    debug_label.SetPos(14, 104)
    g.Add(debug_label)
    debug_on = API.CreateSimpleButton("On", 50, 18)
    debug_on.SetPos(190, 102)
    g.Add(debug_on)
    API.AddControlOnClick(debug_on, _set_debug_on)
    debug_off = API.CreateSimpleButton("Off", 50, 18)
    debug_off.SetPos(245, 102)
    g.Add(debug_off)
    API.AddControlOnClick(debug_off, _set_debug_off)

    log_btn = API.CreateSimpleButton("Log", 70, 20)
    log_btn.SetPos(125, 136)
    g.Add(log_btn)
    API.AddControlOnClick(log_btn, _toggle_log_gump)

    API.AddControlOnDisposed(g, _on_control_closed)
    API.AddGump(g)
    CONTROL_GUMP = g
    _update_control_gump()
    _update_ability_labels()


_load_settings_state()
_create_control_gump()
API.SysMsg("Paladin Assist loaded. Use the gump to Enable/Disable.", HEADMSG_HUE)
_load_weapon_abilities()

while True:
    _pause_if_needed()
    API.ProcessCallbacks()
    if time.time() - _last_ability_refresh >= ABILITY_REFRESH_INTERVAL:
        _load_weapon_abilities()
    in_combat = _in_combat()
    if in_combat:
        if not _cast_cleanse_by_fire() and not _cast_close_wounds():
            for key in _active_priority_order():
                if key == "consecrate_weapon" and _cast_consecrate_weapon(in_combat):
                    break
                if key == "divine_fury" and _cast_divine_fury(in_combat):
                    break
                if key == "enemy_of_one" and _cast_enemy_of_one(in_combat):
                    break
                if key == "primary_ability" and _use_primary_ability():
                    break
                if key == "secondary_ability" and _use_secondary_ability():
                    break
    _debug_status()
    API.Pause(PAUSE_TICK)
