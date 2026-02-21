# README.md

# TazUO Agentic Scripting Environment

This repository is set up for **AI-assisted Python scripting** for the **TazUO (Ultima Online) client** using the **LegionScripts API** exposed through `api.py`.

The goal is twofold:

1. Build working scripts quickly with an AI coding agent (GPT-5.3)
2. Help entry-level developers learn Python by reading well-commented code

> The coding rules and teaching standards for the AI agent are defined in [`AGENTS.md`](./AGENTS.md).

---

## What This Repo Is For

Use this repo to create Python scripts that interact with the TazUO client through the LegionScripts API.

Typical scripts may include:

- Auto-heal / self-preservation
- Looting helpers
- Targeting helpers
- Buff / support actions
- Resource usage automation
- Other TazUO client scripting workflows

All scripts should be:

- Simple
- Readable
- Well-commented
- Safe to run and easy to stop

---

## Development Stack

- **Language:** Python (primary)
- **AI coding agent:** GPT-5.3
- **Editor:** VS Code
- **Version control:** Git + GitHub
- **Game client integration:** TazUO via LegionScripts (`api.py`)

---

## Repo Standards

Before writing or modifying code, read:

- [`AGENTS.md`](./AGENTS.md) ← required rules for the AI agent and coding style

Key standards (summary):

- Follow **PEP 8**
- Follow **KISS** (Keep It Simple)
- Write **teaching-oriented comments**
- Use `api.py` as the source of truth for LegionScripts access
- **No fallbacks** without explicit approval and written analysis

---

## Suggested Repository Layout

If your repo does not already have a structure, this layout works well:

```text
.
├── AGENTS.md
├── README.md
├── api.py                  # LegionScripts API wrapper / integration layer
├── scripts/                # TazUO automation scripts
│   ├── auto_heal.py
│   ├── auto_loot.py
│   └── ...
├── examples/               # Small demo scripts (optional)
├── tests/                  # Simple tests or validation helpers (optional)
└── docs/                   # Notes / setup docs (optional)
```

Keep the structure simple. Avoid adding folders unless they are useful.

---

## VS Code Setup

### 1) Open the repo in VS Code
- Open VS Code
- Select **File → Open Folder**
- Choose this repository

### 2) Install the Python extension
Install the official Python extension for VS Code if it is not already installed.

### 3) Create a virtual environment (recommended)
From the VS Code terminal:

```bash
python -m venv .venv
```

Activate it:

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Windows (cmd):**
```cmd
.\.venv\Scripts\activate
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

### 4) Select the Python interpreter in VS Code
- Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
- Search for **Python: Select Interpreter**
- Choose the `.venv` interpreter

---

## Working With `api.py` (LegionScripts)

`api.py` is the integration point for the LegionScripts API used by TazUO.

### Rules for developers and the AI agent
- **Use methods/functions that already exist in `api.py`**
- **Do not invent API calls**
- If a capability is unclear:
  1. Inspect `api.py`
  2. Document assumptions in comments
  3. Keep the script simple and explicit

### Why this matters
Using `api.py` consistently makes scripts:
- Easier to maintain
- Easier to teach from
- Easier to debug when the TazUO client behavior changes

---

## How to Work With the AI Agent

When asking the AI to build or update a script, include:

1. The script goal (what you want it to do)
2. Any game assumptions (target selected, items required, etc.)
3. Which file to create/update
4. Any timing/range thresholds you care about
5. A request for beginner-friendly comments (the AI should already do this via `AGENTS.md`)

### Example prompt
```text
Create scripts/auto_heal.py.

Goal:
- If health drops below 60%, use a heal action through api.py
- Check every 300 ms
- Add beginner-friendly comments and docstrings
- Keep the code simple and PEP 8 compliant
- Include how to run and debug it in VS Code
```

---

## Script Template (Recommended)

Use this pattern for new scripts:

1. Module docstring
2. Imports
3. Constants / configuration
4. Helper functions
5. `main()` function
6. Entry point (`if __name__ == "__main__":`)

This makes scripts predictable for newer developers.

---

## Running a Script in VS Code

### Option 1: Run from terminal
From the repo root:

```bash
python scripts/your_script_name.py
```

### Option 2: Run using VS Code
- Open the script file
- Click **Run Python File** (or use the Run panel)

> Make sure the correct virtual environment/interpreter is selected first.

---

## Debugging Basics (Beginner Friendly)

When a script does not behave as expected:

### 1) Check assumptions
- Is the TazUO client open and ready?
- Does the script require a target to be selected?
- Do you have the required items/resources?
- Is the script using the right thresholds/ranges?

### 2) Read the comments/docstrings
The code should explain:
- What each step is doing
- Why waits/timers are used
- What API calls are expected to do

### 3) Add simple debug prints (if needed)
Prefer small, clear debug messages, for example:

```python
print(f"Current health: {current_health}")
print("Triggering heal action")
```

### 4) Check `api.py` usage
If a script fails around API calls:
- Verify the method name exists in `api.py`
- Verify the parameters are correct
- Verify the game state supports the action

---

## No-Fallback Policy

This repo intentionally avoids hidden fallback logic because it makes code harder to learn from.

If a fallback is truly needed, the AI agent must:
- Stop
- Present a complete fallback analysis
- Ask for permission before implementing it

See [`AGENTS.md`](./AGENTS.md) for the required fallback request format.

---

## GitHub Workflow (Recommended)

Keep version control simple and clean.

### Branching (optional but recommended)
- `main` for stable code
- Feature branches for new scripts or refactors

### Commit style
Use small, focused commits:

- `add auto-heal script with beginner comments`
- `refactor targeting loop for readability`
- `document api assumptions in loot script`

### Pull request checklist
Before opening a PR (or before merging), verify:

- [ ] Script works for the requested use case
- [ ] Uses `api.py` correctly
- [ ] Follows PEP 8
- [ ] Follows KISS
- [ ] Includes beginner-friendly comments and docstrings
- [ ] No fallback logic was added (unless approved)
- [ ] Run/test steps are documented

---

## Team Workflow for Entry-Level Developers

A good working pattern for juniors:

1. **Describe the task clearly** to the AI agent
2. **Read the generated code comments** before running the script
3. **Run the script in VS Code**
4. **Observe behavior in TazUO**
5. **Ask the AI to explain any part you do not understand**
6. **Commit small improvements often**

The goal is not just to ship scripts — it is to learn Python and automation as you go.

---

## Common Questions

### “What if I don’t understand the code?”
Ask the AI to explain the script line-by-line or function-by-function in plain English.

### “What if the script is too complicated?”
Ask the AI to simplify it and explicitly state:
- “Use KISS”
- “Break it into smaller functions”
- “Add more teaching comments”

### “What if we need more reliability?”
Ask for:
- Clear error messages
- Safer loop exits
- Better debug output

(But still avoid fallback behavior unless approved.)

---

## Next Steps

Good next additions to this repo:

- A `scripts/` folder with your first 2–3 core scripts
- A small `examples/` folder for learning demos
- A short troubleshooting doc in `docs/`
- A team checklist for testing scripts safely in TazUO

---

## Final Reminder

This environment is designed to help junior developers grow fast.

Keep everything:
- simple
- readable
- well-commented
- easy to debug
- easy to learn from
