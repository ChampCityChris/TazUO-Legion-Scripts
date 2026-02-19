# Copilot instructions for TazUO LegionScripts

This repo is a collection of Python scripts run inside the TazUO/UO client scripting engine. The codebase is not a standalone Python package — scripts are executed by the game client's embedded Python runtime via the provided API module. These instructions focus on what an AI agent needs to be productive editing and extending the scripts.

**Big picture**:
- **What:** Many independent scripts (under root, `Resources/`, `Skills/`, `Utilities/`) automate in-game behaviors (crafting, mining, trainers).
- **How they run:** Each script is written for the TazUO embedded Python runtime and calls functions on the API module. Agents should not assume CPython-only behavior (scripts rely on client-side APIs and in-game state).
- **UI pattern:** Gump-based control panels are common. Look for `_create_gump`, `_rebuild_gump`, `API.CreateGump*`, `API.AddControlOnClick`, `CONTROL_GUMP`, and `CONTROL_BUTTON` usage (example: CrafterTrainer).

**Key patterns & conventions** (use these when changing or adding scripts):
- Global state variables: scripts use module-level globals for run state and selected serials (`RUNNING`, `STOCK_SERIAL`, `DATA_KEY`). Match this style when adding state.
- Helper naming: internal helpers start with `_` (e.g. `_pause_ms`, `_save_config`). Follow same prefix for private helpers.
- Persistent config: scripts persist JSON strings via `API.SavePersistentVar` / `API.GetPersistentVar` using a `DATA_KEY` constant. Reuse this pattern for new persistent settings.
- Event loop / cooperative scheduling: scripts call `API.ProcessCallbacks()` in wait loops rather than blocking long sleeps; prefer short `API.Pause()` calls and allow callback processing.
- Gump interaction: use `API.WaitForGump(gump_id, timeout)`, `API.GetGumpContents(gid)` and `API.GumpIDs()` to detect and interact with menus; blacksmith/crafting flows in CrafterTrainer and AutoMiner are good references.

**Concrete examples to copy/inspect**:
- Persistent config pattern: in CrafterTrainer use `DATA_KEY` + `json.dumps()` and `API.SavePersistentVar`.
- Gump + controls: `_create_gump()` in CrafterTrainer — shows `API.CreateGumpTTFLabel`, `API.CreateSimpleButton`, and `API.AddControlOnClick` usage.
- Mining flow & flags: AutoMiner demonstrates complex feature flags (e.g. `USE_TOOL_CRAFTING`, `USE_SACRED_JOURNEY`) and how scripts store and restore UI/gump state.

**What not to assume**:
- These scripts are not runnable with plain CPython without the TazUO API present. Do not add imports or test code that expects a normal Python environment unless guarded.
- No standard test harness or build system exists. Changes must be validated in-client or via small, well-guarded runtime shims.

**Safe change checklist for agents**:
1. Preserve `DATA_KEY` names and persistent-var shape when refactoring persisted structures (or add migration code).  
2. For UI changes, maintain `_rebuild_gump()` + `Dispose()` pattern so existing gumps are refreshed cleanly.  
3. Keep loops cooperative: call `API.ProcessCallbacks()` often and avoid huge blocking sleeps.  
4. When adding new script-wide globals, document them near top of file and persist if needed.  

If any piece of behavior is unclear (how scripts are launched inside TazUO, or what API constants exist at runtime), tell me which script(s) you want clarified and I'll extract concise examples and update this guidance.

---
Please review these sections and tell me if you'd like more detail (examples, migrations, or in-client run steps). I can update the file accordingly.
