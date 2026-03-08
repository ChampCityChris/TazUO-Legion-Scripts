import time

import API


# 1. Config
SCRIPT_NAME = "AnimalTrain"

STOP_HOTKEY = "CTRL+SHIFT+Q"
CLEAR_IGNORE_ON_START = True

KILL_TAME = True
RENAME_TAMED_TO = "KillMe" if KILL_TAME else "tamed"
FOLLOWERS_TO_KEEP = 0

MAX_TAME_ATTEMPTS = 20  # 0 means unlimited attempts.
MIN_TAMING_DIFFICULTY = 20

HEAL_MODE = "none"  # "none", "bandage", "magery"
ENABLE_PEACEMAKING = False
ENABLE_FOLLOW_ANIMAL = True
ENABLE_COMBAT_DEFENSE = True

SEARCH_RANGE = 12
MAX_TAME_RANGE = 12
FOLLOW_DISTANCE = 2

JOURNAL_ENTRY_DELAY_SEC = 0.10
TARGET_CLEAR_DELAY_SEC = 0.10
TICK_DELAY_SEC = 0.05
NO_TARGET_DELAY_SEC = 0.50

PLAYER_STUCK_TIMEOUT_SEC = 5.0
FOLLOW_TIMEOUT_SEC = 20.0
FOLLOW_RETRY_DELAY_SEC = 0.25

ANIMAL_TAMING_COOLDOWN_SEC = 12.5
TAME_RESULT_TIMEOUT_SEC = 14.0
PEACEMAKING_COOLDOWN_SEC = 5.0
BANDAGE_COOLDOWN_SEC = 10.0
MAGERY_HEAL_COOLDOWN_SEC = 0.75
ATTACK_AFTER_TAME_DELAY_SEC = 0.60
COMBAT_TIMEOUT_SEC = 45.0
COMBAT_TICK_DELAY_SEC = 0.25

TARGET_WAIT_TIMEOUT_SEC = 2.0
MAX_RELEASE_RETRIES = 2
MAX_RELEASE_GUMP_STEPS = 2
RELEASE_CONTEXT_ENTRY = 9
RELEASE_CONTINUE_BUTTON = 2
RELEASE_WARNING_BUTTON = 1
RELEASE_GUMP_WAIT_SEC = 1.0
POST_RELEASE_DELAY_SEC = 0.40
NEW_HAVEN_RELEASE_GUMP_ID = 0x94F89BE1
YEW_RELEASE_GUMP_ID = 0xA723F23E
CUSTOM_RELEASE_GUMP_ID = 0xCB45DE37
SPECIAL_RELEASE_GUMP_ACTIONS = (
    (NEW_HAVEN_RELEASE_GUMP_ID, 1, 2),
    (YEW_RELEASE_GUMP_ID, 1, 2),
    (CUSTOM_RELEASE_GUMP_ID, 2, 1),
)
NEW_HAVEN_RELEASE_CLICK_DELAY_SEC = 0.12

INSTRUMENT_GRAPHICS = (
    0x0E9E,  # Drum
    0x2805,  # Tambourine (alternate)
    0x0E9C,  # Lute
    0x0EB3,  # Lap harp
    0x0EB1,  # Standing harp
    0x0EB2,  # Harp (alternate)
    0x0E9D,  # Tambourine
)

HOSTILE_NOTORIETIES = [
    API.Notoriety.Gray,
    API.Notoriety.Criminal,
    API.Notoriety.Enemy,
    API.Notoriety.Murderer,
]

TAMEABLE_GRAPHICS_BY_MIN_DIFFICULTY = {
    0x001D: 0,
    0x0027: 0,
    0x00CD: 0,
    0x00D9: 0,
    0x0116: 0,
    0x012E: 0,
    0x033F: 0,
    0x0006: 10,
    0x0058: 10,
    0x00D0: 10,
    0x00EE: 10,
    0x083E: 10,
    0x0033: 20,
    0x00CB: 20,
    0x00CF: 20,
    0x00D1: 20,
    0x00D8: 20,
    0x00E7: 20,
    0x0317: 20,
    0x0005: 30,
    0x0051: 40,
    0x00C8: 40,
    0x00CC: 40,
    0x00D2: 40,
    0x00D7: 40,
    0x00DB: 40,
    0x00E1: 40,
    0x00E2: 40,
    0x00E4: 40,
    0x00ED: 40,
    0x0115: 40,
    0x0117: 40,
    0x0122: 40,
    0x0123: 40,
    0x0124: 40,
    0x00D3: 50,
    0x00DC: 50,
    0x00DD: 50,
    0x0030: 60,
    0x003F: 60,
    0x00A7: 60,
    0x00CA: 60,
    0x02CB: 60,
    0x00F8: 68,
    0x0019: 70,
    0x001B: 70,
    0x001C: 70,
    0x0034: 70,
    0x0040: 70,
    0x0041: 70,
    0x00D4: 70,
    0x00D5: 70,
    0x00D6: 70,
    0x00EA: 70,
    0x0022: 80,
    0x0025: 80,
    0x0014: 90,
    0x0050: 90,
    0x00C9: 90,
    0x00DA: 90,
    0x00E8: 90,
    0x00E9: 90,
    0x0017: 100,
    0x003C: 100,
    0x003D: 100,
    0x004A: 100,
    0x0062: 100,
    0x007F: 100,
    0x00BB: 100,
    0x00BC: 100,
    0x00CE: 100,
    0x000B: 110,
    0x003B: 110,
    0x00B4: 110,
    0x00F4: 110,
    0x006A: 120,
}

TAME_SUCCESS_MESSAGES = [
    "It seems to accept you as master.",
    "That wasn't even challenging.",
]
TAME_FAIL_MESSAGES = [
    "You fail to tame the creature.",
    "The animal is too angry to continue taming.",
    "You must wait a few moments to use another skill.",
]
TAME_TOO_FAR_MESSAGES = [
    "That is too far away.",
    "You are too far away to continue taming.",
]
TAME_IGNORE_MESSAGES = [
    " no chance of taming",
    "already taming",
    "Target cannot be seen",
    "not have a clear path to the animal",
    "cannot be tamed",
    "This animal has had too many owners",
    "That animal looks tame already",
]


# 2. Logging
LOG_INFO_HUE = 88
LOG_WARN_HUE = 33
LOG_ERROR_HUE = 38


def _log_info(message):
    API.SysMsg(f"[{SCRIPT_NAME}] {message}", LOG_INFO_HUE)


def _log_warn(message):
    API.SysMsg(f"[{SCRIPT_NAME}] {message}", LOG_WARN_HUE)


def _log_error(message):
    API.SysMsg(f"[{SCRIPT_NAME}] {message}", LOG_ERROR_HUE)


# 3. Runtime state
class RuntimeState:
    def __init__(self):
        self.cycles = 0
        self.tamed_success = 0
        self.tamed_failed = 0
        self.ignored_targets = 0
        self.released_targets = 0
        self.killed_targets = 0
        self.stop_reason = ""

        self.target_serial = 0
        self.target_attempts = 0
        self.tame_ongoing = False
        self.tame_started_at = 0.0
        self.next_tame_ready_at = 0.0
        self.next_peacemaking_ready_at = 0.0
        self.next_heal_ready_at = 0.0
        self.last_player_hits = 0


HOTKEY_STOP_REQUESTED = False
NEW_HAVEN_RELEASE_HANDLED = False


# 4. API adapters / wrappers
def _now():
    return time.time()


def _on_stop_hotkey():
    global HOTKEY_STOP_REQUESTED
    HOTKEY_STOP_REQUESTED = True
    _log_warn(f"Stop hotkey pressed ({STOP_HOTKEY}).")


def _register_stop_hotkey():
    API.OnHotKey(STOP_HOTKEY, _on_stop_hotkey)


def _unregister_stop_hotkey():
    API.OnHotKey(STOP_HOTKEY)


def _stop_requested():
    return bool(API.StopRequested) or HOTKEY_STOP_REQUESTED


def _pause_with_callbacks(seconds, step_seconds=0.05):
    wait_seconds = max(0.0, float(seconds))
    deadline = _now() + wait_seconds
    while _now() < deadline:
        if _stop_requested():
            return False
        API.ProcessCallbacks()
        remaining = deadline - _now()
        sleep_time = step_seconds if remaining > step_seconds else remaining
        if sleep_time > 0:
            API.Pause(sleep_time)
    return not _stop_requested()


def _animal_taming_skill():
    skill = API.GetSkill("Animal Taming")
    if not skill:
        return 0.0
    value = getattr(skill, "Value", 0.0)
    return float(value or 0.0)


def _animal_taming_cap():
    skill = API.GetSkill("Animal Taming")
    if not skill:
        return 0.0
    cap = getattr(skill, "Cap", 0.0)
    return float(cap or 0.0)


def _player_serial():
    if not API.Player:
        return 0
    return int(getattr(API.Player, "Serial", 0) or 0)


def _player_followers():
    if not API.Player:
        return 0
    return int(getattr(API.Player, "Followers", 0) or 0)


def _current_target_mobile(state):
    if state.target_serial <= 0:
        return None
    return API.FindMobile(state.target_serial)


def _reset_target(state):
    state.target_serial = 0
    state.target_attempts = 0
    state.tame_ongoing = False
    state.tame_started_at = 0.0


def _ignore_current_target(state, reason):
    if state.target_serial > 0:
        API.IgnoreObject(state.target_serial)
        state.ignored_targets += 1
    _log_warn(reason)
    _reset_target(state)


def _matching_tameable_graphics(minimum_difficulty):
    matches = set()
    for graphic, min_difficulty in TAMEABLE_GRAPHICS_BY_MIN_DIFFICULTY.items():
        if min_difficulty >= minimum_difficulty:
            matches.add(int(graphic))
    return matches


# 5. Prechecks
def _run_prechecks(state, tameable_graphics):
    if not API.Player:
        state.stop_reason = "Player context unavailable."
        _log_error(state.stop_reason)
        return False

    if HEAL_MODE not in ("none", "bandage", "magery"):
        state.stop_reason = f"Invalid HEAL_MODE: {HEAL_MODE}"
        _log_error(state.stop_reason)
        return False

    if MIN_TAMING_DIFFICULTY < 0:
        state.stop_reason = "MIN_TAMING_DIFFICULTY must be >= 0."
        _log_error(state.stop_reason)
        return False

    if not tameable_graphics:
        state.stop_reason = "No tameable graphics match MIN_TAMING_DIFFICULTY."
        _log_error(state.stop_reason)
        return False

    skill_value = _animal_taming_skill()
    skill_cap = _animal_taming_cap()
    if skill_cap > 0 and skill_value >= skill_cap:
        state.stop_reason = "Animal Taming already at cap."
        _log_warn(state.stop_reason)
        return False

    if _stop_requested():
        state.stop_reason = "Stop requested before start."
        return False

    _log_info(f"Precheck pass. Animal Taming: {skill_value:.1f}/{skill_cap:.1f}")
    state.last_player_hits = int(getattr(API.Player, "Hits", 0) or 0)
    return True


# 6. Recovery logic (gumps/UI)
def _handle_release_gumps():
    global NEW_HAVEN_RELEASE_HANDLED
    if _clear_special_release_gump():
        NEW_HAVEN_RELEASE_HANDLED = True
        _log_info("Handled shard release gump.")

    for _ in range(MAX_RELEASE_GUMP_STEPS):
        if _stop_requested():
            return False
        if not API.WaitForGump(1337, RELEASE_GUMP_WAIT_SEC):
            break

        if API.GumpContains("CONTINUE"):
            API.ReplyGump(RELEASE_CONTINUE_BUTTON)
            _log_info("Release confirm gump: CONTINUE.")
        elif API.GumpContains("Warning!"):
            API.ReplyGump(RELEASE_WARNING_BUTTON)
            _log_info("Release warning gump confirmed.")
        else:
            _log_error("Unexpected release gump text. Stopping fail-safe.")
            return False

        if not _pause_with_callbacks(POST_RELEASE_DELAY_SEC):
            return False

    return True


def _clear_special_release_gump():
    target_gump_id = 0
    target_button_id = 0
    target_click_count = 0
    for gump_id, button_id, click_count in SPECIAL_RELEASE_GUMP_ACTIONS:
        if API.HasGump(gump_id):
            target_gump_id = int(gump_id)
            target_button_id = int(button_id)
            target_click_count = int(click_count)
            break
    if target_gump_id <= 0 or target_button_id <= 0 or target_click_count <= 0:
        return False

    for _ in range(target_click_count):
        if _stop_requested():
            return False
        API.ReplyGump(target_button_id, target_gump_id)
        if not _pause_with_callbacks(NEW_HAVEN_RELEASE_CLICK_DELAY_SEC):
            return False

    return True


def _release_tame(state, serial):
    global NEW_HAVEN_RELEASE_HANDLED
    for attempt in range(1, MAX_RELEASE_RETRIES + 1):
        NEW_HAVEN_RELEASE_HANDLED = False

        if _clear_special_release_gump():
            state.released_targets += 1
            _log_info(f"Released tame via shard release gump (attempt {attempt}).")
            return True

        API.ContextMenu(serial, RELEASE_CONTEXT_ENTRY)
        if not _pause_with_callbacks(TARGET_CLEAR_DELAY_SEC):
            return False
        if not _handle_release_gumps():
            return False
        if NEW_HAVEN_RELEASE_HANDLED:
            state.released_targets += 1
            _log_info(f"Released tame via shard release gump (attempt {attempt}).")
            return True
        if _clear_special_release_gump():
            state.released_targets += 1
            _log_info(f"Released tame via shard release gump (attempt {attempt}).")
            return True
        if not _pause_with_callbacks(POST_RELEASE_DELAY_SEC):
            return False

        if _player_followers() <= FOLLOWERS_TO_KEEP:
            state.released_targets += 1
            _log_info(f"Released tame (attempt {attempt}).")
            return True

    return False


# 7. Core actions
def _find_nearest_tameable(tameable_graphics):
    player_serial = _player_serial()
    best_mobile = None
    best_distance = 999
    mobiles = API.GetAllMobiles(distance=SEARCH_RANGE) or []

    for mobile in mobiles:
        serial = int(getattr(mobile, "Serial", 0) or 0)
        if serial <= 0 or serial == player_serial:
            continue
        if API.OnIgnoreList(serial):
            continue
        if bool(getattr(mobile, "IsDead", False)):
            continue

        graphic = int(getattr(mobile, "Graphic", 0) or 0)
        if graphic not in tameable_graphics:
            continue

        name = str(getattr(mobile, "Name", "") or "")
        if name.lower() == RENAME_TAMED_TO.lower():
            continue

        if not mobile.HasLineOfSightFrom(API.Player):
            continue

        distance = int(getattr(mobile, "Distance", 999) or 999)
        if distance < best_distance:
            best_mobile = mobile
            best_distance = distance

    return best_mobile


def _follow_target(state):
    start_time = _now()
    last_position = (int(API.Player.X), int(API.Player.Y))
    stuck_started_at = _now()

    while not _stop_requested():
        target = _current_target_mobile(state)
        if not target:
            return False

        distance = int(getattr(target, "Distance", 999) or 999)
        if distance <= FOLLOW_DISTANCE:
            return True
        if distance > MAX_TAME_RANGE:
            return False
        if (_now() - start_time) > FOLLOW_TIMEOUT_SEC:
            return False

        moved = API.PathfindEntity(state.target_serial, FOLLOW_DISTANCE, True, 3)
        current_position = (int(API.Player.X), int(API.Player.Y))
        if moved and current_position != last_position:
            last_position = current_position
            stuck_started_at = _now()
        elif current_position != last_position:
            last_position = current_position
            stuck_started_at = _now()
        elif (_now() - stuck_started_at) >= PLAYER_STUCK_TIMEOUT_SEC:
            state.stop_reason = "Player appears stuck while following target."
            _log_error(state.stop_reason)
            return False

        if not _pause_with_callbacks(FOLLOW_RETRY_DELAY_SEC):
            return False

    return False


def _find_instrument_item():
    backpack_serial = int(API.Backpack or 0)
    if backpack_serial <= 0:
        return None
    items = API.ItemsInContainer(backpack_serial, True) or []
    for item in items:
        if int(getattr(item, "Graphic", 0) or 0) in INSTRUMENT_GRAPHICS:
            return item
    return None


def _find_war_enemy():
    enemies = API.GetAllMobiles(distance=SEARCH_RANGE, notoriety=HOSTILE_NOTORIETIES) or []
    for enemy in enemies:
        if bool(getattr(enemy, "InWarMode", False)):
            return enemy
    return None


def _find_nearest_hostile():
    player_serial = _player_serial()
    nearest = None
    nearest_distance = 999
    enemies = API.GetAllMobiles(distance=SEARCH_RANGE, notoriety=HOSTILE_NOTORIETIES) or []
    for enemy in enemies:
        serial = int(getattr(enemy, "Serial", 0) or 0)
        if serial <= 0 or serial == player_serial:
            continue
        if bool(getattr(enemy, "IsDead", False)):
            continue
        distance = int(getattr(enemy, "Distance", 999) or 999)
        if distance < nearest_distance:
            nearest = enemy
            nearest_distance = distance
    return nearest


def _should_interrupt_for_combat(state):
    if not ENABLE_COMBAT_DEFENSE:
        return False

    war_enemy = _find_war_enemy()
    if war_enemy:
        return True

    current_hits = int(getattr(API.Player, "Hits", 0) or 0)
    took_damage = current_hits < int(state.last_player_hits or 0)
    if took_damage and _find_nearest_hostile():
        return True
    return False


def _fight_nearest_enemy_until_slain(state):
    enemy = _find_nearest_hostile()
    if not enemy:
        return True

    enemy_serial = int(getattr(enemy, "Serial", 0) or 0)
    enemy_name = str(getattr(enemy, "Name", "") or "hostile")
    _log_warn(f"Combat interrupt: attacking nearest enemy '{enemy_name}' 0x{enemy_serial:08X}.")

    state.tame_ongoing = False
    API.CancelTarget()
    API.ClearJournal()
    state.next_tame_ready_at = _now() + 1.0

    combat_deadline = _now() + COMBAT_TIMEOUT_SEC
    while not _stop_requested():
        if _now() > combat_deadline:
            state.stop_reason = f"Combat timeout while fighting 0x{enemy_serial:08X}."
            _log_error(state.stop_reason)
            return False

        live_enemy = API.FindMobile(enemy_serial)
        if not live_enemy:
            _log_info(f"Enemy 0x{enemy_serial:08X} no longer present. Resuming taming.")
            if not KILL_TAME and bool(getattr(API.Player, "InWarMode", False)):
                API.SetWarMode(False)
            return True

        if bool(getattr(live_enemy, "IsDead", False)):
            _log_info(f"Enemy slain: 0x{enemy_serial:08X}. Resuming taming.")
            if not KILL_TAME and bool(getattr(API.Player, "InWarMode", False)):
                API.SetWarMode(False)
            return True

        if not bool(getattr(API.Player, "InWarMode", False)):
            API.SetWarMode(True)

        API.Attack(enemy_serial)
        _heal_if_needed(state)
        state.last_player_hits = int(getattr(API.Player, "Hits", 0) or 0)
        if not _pause_with_callbacks(COMBAT_TICK_DELAY_SEC):
            return False

    return False


def _try_peacemaking(state):
    if not ENABLE_PEACEMAKING:
        return
    if _now() < state.next_peacemaking_ready_at:
        return

    enemy = _find_war_enemy()
    if not enemy:
        return

    API.CancelTarget()
    if not _pause_with_callbacks(TARGET_CLEAR_DELAY_SEC):
        return

    API.UseSkill("Peacemaking")
    if not _pause_with_callbacks(JOURNAL_ENTRY_DELAY_SEC):
        return

    if API.InJournal("What instrument shall you play?", True):
        instrument = _find_instrument_item()
        if not instrument:
            _log_warn("Peacemaking needs an instrument, none found.")
            state.next_peacemaking_ready_at = _now() + PEACEMAKING_COOLDOWN_SEC
            return
        if API.WaitForTarget("any", TARGET_WAIT_TIMEOUT_SEC):
            API.Target(int(getattr(instrument, "Serial", 0) or 0))

    if API.InJournal("Whom do you wish to calm?", True):
        if API.WaitForTarget("any", TARGET_WAIT_TIMEOUT_SEC):
            API.Target(int(getattr(enemy, "Serial", 0) or 0))
            _log_info("Peacemaking used.")

    if not KILL_TAME and bool(getattr(API.Player, "InWarMode", False)):
        API.SetWarMode(False)

    state.next_peacemaking_ready_at = _now() + PEACEMAKING_COOLDOWN_SEC


def _heal_if_needed(state):
    if HEAL_MODE == "none":
        return
    if _now() < state.next_heal_ready_at:
        return

    hits = int(getattr(API.Player, "Hits", 0) or 0)
    hits_max = int(getattr(API.Player, "HitsMax", 0) or 0)
    missing_hits = hits_max - hits
    if missing_hits <= 0:
        return

    if HEAL_MODE == "bandage":
        if API.BandageSelf():
            state.next_heal_ready_at = _now() + BANDAGE_COOLDOWN_SEC
            _log_info("Bandage applied.")
        return

    if HEAL_MODE == "magery":
        if missing_hits <= 10:
            return
        if bool(getattr(API.Player, "IsPoisoned", False)):
            API.CastSpell("Cure")
        elif missing_hits > 30:
            API.CastSpell("Greater Heal")
        else:
            API.CastSpell("Heal")
        if API.WaitForTarget("any", TARGET_WAIT_TIMEOUT_SEC):
            API.TargetSelf()
            state.next_heal_ready_at = _now() + MAGERY_HEAL_COOLDOWN_SEC
            _pause_with_callbacks(0.5)


def _start_tame_attempt(state):
    if state.tame_ongoing:
        return
    if state.target_serial <= 0:
        return
    if _now() < state.next_tame_ready_at:
        return

    API.ClearJournal()
    API.CancelTarget()
    if not _pause_with_callbacks(TARGET_CLEAR_DELAY_SEC):
        return

    API.UseSkill("Animal Taming")
    if not API.WaitForTarget("any", TARGET_WAIT_TIMEOUT_SEC):
        _log_warn("No target cursor after Animal Taming use.")
        state.next_tame_ready_at = _now() + 1.0
        return

    API.Target(state.target_serial)
    if not _pause_with_callbacks(JOURNAL_ENTRY_DELAY_SEC):
        return

    if API.InJournal("Tame which animal?", True):
        state.target_attempts += 1
        state.tame_ongoing = True
        state.tame_started_at = _now()
        state.next_tame_ready_at = _now() + ANIMAL_TAMING_COOLDOWN_SEC
        _log_info(f"Tame attempt {state.target_attempts}.")
    else:
        state.next_tame_ready_at = _now() + 1.0


def _handle_max_attempts(state):
    if MAX_TAME_ATTEMPTS == 0:
        return
    if state.target_serial <= 0:
        return
    if state.target_attempts <= MAX_TAME_ATTEMPTS:
        return

    if KILL_TAME:
        _log_warn(
            f"Attempt limit exceeded ({MAX_TAME_ATTEMPTS}). Attacking target 0x{state.target_serial:08X}."
        )
        API.Attack(state.target_serial)
        state.killed_targets += 1
        _pause_with_callbacks(ATTACK_AFTER_TAME_DELAY_SEC)
    else:
        _log_warn(
            f"Attempt limit exceeded ({MAX_TAME_ATTEMPTS}). Ignoring target 0x{state.target_serial:08X}."
        )

    API.IgnoreObject(state.target_serial)
    state.ignored_targets += 1
    _reset_target(state)
    API.ClearJournal()


def _handle_tame_success(state):
    target = _current_target_mobile(state)
    serial = state.target_serial

    if serial <= 0:
        _reset_target(state)
        return

    if (
        target
        and bool(getattr(target, "IsRenamable", False))
        and str(getattr(target, "Name", "") or "").lower() != RENAME_TAMED_TO.lower()
    ):
        API.Rename(serial, RENAME_TAMED_TO)
        _pause_with_callbacks(0.2)

    if _player_followers() > FOLLOWERS_TO_KEEP:
        if not _release_tame(state, serial):
            state.stop_reason = f"Failed to release tame 0x{serial:08X}."
            _log_error(state.stop_reason)
            return

    if KILL_TAME:
        API.Attack(serial)
        state.killed_targets += 1
        _pause_with_callbacks(ATTACK_AFTER_TAME_DELAY_SEC)

    API.IgnoreObject(serial)
    state.ignored_targets += 1
    state.tamed_success += 1
    _log_info(f"Tame success on 0x{serial:08X}.")
    _reset_target(state)
    API.ClearJournal()


def _handle_tame_journal(state):
    if not state.tame_ongoing:
        return
    if state.target_serial <= 0:
        state.tame_ongoing = False
        return

    target = _current_target_mobile(state)
    if not target:
        state.tame_ongoing = False
        _reset_target(state)
        return

    if API.InJournalAny(TAME_SUCCESS_MESSAGES, True):
        state.tame_ongoing = False
        _handle_tame_success(state)
        return

    if API.InJournalAny(TAME_FAIL_MESSAGES, True):
        state.tamed_failed += 1
        state.tame_ongoing = False
        _log_info(f"Tame failed on attempt {state.target_attempts}.")
        return

    if API.InJournalAny(TAME_TOO_FAR_MESSAGES, True):
        state.tame_ongoing = False
        _log_warn("Target moved too far away.")
        _reset_target(state)
        return

    if API.InJournalAny(TAME_IGNORE_MESSAGES, True):
        state.tame_ongoing = False
        _ignore_current_target(state, "Target is not valid for taming. Ignoring target.")
        return

    if (_now() - state.tame_started_at) > TAME_RESULT_TIMEOUT_SEC:
        state.tame_ongoing = False
        _log_warn("Tame result timed out; retrying when cooldown is ready.")


# 8. Main loop
def _main():
    state = RuntimeState()
    tameable_graphics = _matching_tameable_graphics(MIN_TAMING_DIFFICULTY)

    _register_stop_hotkey()
    _log_info(
        f"Start. Stop hotkey: {STOP_HOTKEY}. "
        f"Min difficulty: {MIN_TAMING_DIFFICULTY}. Kill tame: {KILL_TAME}."
    )

    if CLEAR_IGNORE_ON_START:
        API.ClearIgnoreList()
        _log_info("Ignore list cleared.")

    if not _run_prechecks(state, tameable_graphics):
        _shutdown(state)
        return

    if not KILL_TAME and bool(getattr(API.Player, "InWarMode", False)):
        API.SetWarMode(False)

    while not _stop_requested():
        state.cycles += 1
        API.ProcessCallbacks()
        _clear_special_release_gump()

        if not API.Player:
            state.stop_reason = "Player context unavailable during runtime."
            break
        if bool(getattr(API.Player, "IsDead", False)):
            state.stop_reason = "Player is dead."
            break

        if _should_interrupt_for_combat(state):
            if not _fight_nearest_enemy_until_slain(state):
                break
            if state.stop_reason:
                break

        _try_peacemaking(state)
        _heal_if_needed(state)

        if state.target_serial <= 0:
            target = _find_nearest_tameable(tameable_graphics)
            if not target:
                if not _pause_with_callbacks(NO_TARGET_DELAY_SEC):
                    break
                continue
            state.target_serial = int(getattr(target, "Serial", 0) or 0)
            state.target_attempts = 0
            state.tame_ongoing = False
            target_name = str(getattr(target, "Name", "") or "unknown")
            target_distance = int(getattr(target, "Distance", 0) or 0)
            _log_info(
                f"Found target '{target_name}' 0x{state.target_serial:08X} at {target_distance} tiles."
            )

        target_mobile = _current_target_mobile(state)
        if not target_mobile:
            _reset_target(state)
            continue

        target_distance = int(getattr(target_mobile, "Distance", 999) or 999)
        if target_distance > MAX_TAME_RANGE:
            _log_warn("Target moved out of tame range.")
            _reset_target(state)
            continue

        if ENABLE_FOLLOW_ANIMAL and target_distance > FOLLOW_DISTANCE:
            if not _follow_target(state):
                if state.stop_reason:
                    break
                _ignore_current_target(state, "Could not catch up to target. Ignoring target.")
                continue

        _handle_max_attempts(state)
        if state.target_serial <= 0:
            continue

        _start_tame_attempt(state)
        _handle_tame_journal(state)

        if state.stop_reason:
            break
        state.last_player_hits = int(getattr(API.Player, "Hits", 0) or 0)
        if not _pause_with_callbacks(TICK_DELAY_SEC):
            break

    if not state.stop_reason:
        state.stop_reason = "Stop requested."
    _shutdown(state)


# 9. Shutdown summary
def _shutdown(state):
    _unregister_stop_hotkey()
    _log_info(
        "Stop. "
        f"Reason: {state.stop_reason} | "
        f"Cycles: {state.cycles} | "
        f"Tamed: {state.tamed_success} | "
        f"Fails: {state.tamed_failed} | "
        f"Ignored: {state.ignored_targets} | "
        f"Released: {state.released_targets} | "
        f"Killed: {state.killed_targets}"
    )


def _should_autostart_main():
    # TODO (human): add additional runner contexts if your environment uses them.
    return __name__ in ("__main__", "<module>")


if _should_autostart_main():
    _main()
