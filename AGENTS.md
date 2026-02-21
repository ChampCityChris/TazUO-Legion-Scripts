# AGENTS.md

## Purpose

This repository is built for **agentic AI-assisted development** with a strong teaching focus.

The primary goals are:

1. **Write simple, reliable, readable Python code**
2. **Teach entry-level developers through code comments and explanations**
3. **Use the `LegionScripts` API (via `api.py` in this repo)** to automate/script interactions with the **TazUO client** for Ultima Online
4. Keep code maintainable for long-term use in **VS Code** and version-controlled in **GitHub**

The AI agent used for coding in this environment is **GPT-5.3**.

---

## Core Development Philosophy

### 1) KISS First (Keep It Simple, Stupid)
Prefer the simplest solution that works.

- Small functions
- Clear names
- Minimal nesting
- Minimal indirection
- No “clever” code

If a junior developer cannot follow it, it is too complex.

---

### 2) PEP 8 Always
All Python code must follow **PEP 8** style guidelines.

This includes (not limited to):

- `snake_case` for variables/functions
- `PascalCase` for classes
- Reasonable line lengths
- Consistent spacing
- Clear imports
- Blank lines used for readability

Use type hints when they improve clarity.

---

### 3) Code Must Teach
The AI is not only writing code — it is also teaching developers how the code works.

Every script should be written so a beginner can learn by reading it.

That means:

- Clear docstrings
- Helpful comments
- Step-by-step logic
- No unexplained magic values
- No cryptic abbreviations

---

## Required Commenting Standard (Teaching-Oriented)

The team is entry-level and learning to read code. Comments are required to explain **why** and **how** the code works.

### A) Module Header Comment (Required)
Every script file should begin with a short header explaining:

- What the script does
- When to use it
- Any assumptions (e.g., player state, target selected, inventory requirements)
- Any risks (e.g., script will move items, cast spells, target mobs, etc.)

Example:
```python
"""
Auto-heal script for TazUO using LegionScripts API.

Purpose:
- Checks player health
- Uses a healing action when health drops below a threshold

Assumptions:
- Character has healing resources available
- LegionScripts API is configured and available through api.py
"""
```

---

### B) Function Docstrings (Required)
Every function must include a docstring that explains:

- What the function does
- Inputs (parameters)
- Output (return value)
- Side effects (if any)

Docstrings should be beginner-friendly and plain English.

---

### C) Inline Comments (Required, but purposeful)
Use inline comments to explain:

- Why a step is needed
- What a non-obvious API call is doing
- Timing/wait behavior
- Game-specific logic (e.g., target selection, cooldown handling)

Do **not** comment obvious syntax.

Good:
```python
# Wait briefly so the TazUO client has time to process the target action.
```

Bad:
```python
# Increment i by 1
i += 1
```

---

### D) “Teaching Comments” for Complex Sections (Required)
If a block has multiple steps, add a short “teaching comment” before it.

Example:
```python
# We split this into 3 steps:
# 1) Check if we need healing
# 2) Trigger the heal action
# 3) Pause so the client can finish the action before checking again
```

---

## Python Coding Rules

### Required
- Follow **PEP 8**
- Follow **KISS**
- Use **clear names** (`health_threshold` > `ht`)
- Use **small functions** (single responsibility)
- Use **constants** for tunable values (timers, thresholds, ranges)
- Use **type hints** where practical
- Use **docstrings and comments** as teaching tools
- Prefer explicit logic over compact one-liners

### Avoid
- Clever one-liners
- Deeply nested `if/else`
- Premature abstractions
- Hidden behavior
- Silent failures
- Broad `except:` blocks
- “Magic numbers” without explanation

---

## No-Fallback Policy (Strict)

### Rule
The AI agent must **avoid coding fallbacks by default**.

Fallbacks often make beginner code harder to understand and harder to debug because they hide the real failure.

### If a fallback seems necessary
The AI agent **must stop and ask permission before implementing a fallback**.

The request must include a complete analysis with:

1. **The problem being solved**
2. **Why the normal solution may fail**
3. **Options to solve it** (including no fallback)
4. **Tradeoffs of each option**
5. **Why a fallback is the best choice**
6. **What the fallback will do**
7. **How it will be logged/explained so juniors can understand it**

### Example fallback-request format (required)
```md
Fallback Request: [short title]

Problem:
[Describe the failure scenario]

Why this happens:
[Root cause / likely causes]

Options considered:
1. [Option A]
2. [Option B]
3. [Fallback option]

Recommendation:
[Why fallback is best here]

Proposed fallback behavior:
[Exactly what the code will do]

Impact on readability / teaching:
[How comments/docstrings will explain this]
```

No fallback code may be added until permission is granted.

---

## LegionScripts / TazUO Integration Rules

### API Source of Truth
- Use the **LegionScripts API through `api.py` in this repository**
- Prefer existing wrappers/utilities in `api.py` instead of re-implementing API access
- Do not invent API methods that do not exist
- If unsure about an API capability, inspect `api.py` and document assumptions in comments

### TazUO Script Behavior
When writing scripts for TazUO:

- Be explicit about timing and waits
- Explain client interaction steps in comments
- Keep loops safe and easy to stop
- Document assumptions about game state
- Avoid hidden automation behavior

### Runtime Entrypoint Note (`__name__` in TazUO)
The TazUO/LegionScripts script manager may execute files with `__name__` set to `"<module>"` (not always `"__main__"`).

For LegionScripts entrypoints, support both runtime contexts:
- `"__main__"`
- `"<module>"`
- Any additional known module-name variant your script runner uses

Preferred pattern:
- Wrap startup logic in a helper like `_should_autostart_main()`
- Call `main()` when the helper confirms the current `__name__` is an allowed entrypoint context

### Safety / Control
Scripts should be easy for a junior developer to understand, run, and stop.

Include:
- Clear thresholds
- Simple loop exit conditions
- Comments on timing and target behavior
- Optional debug prints/logging when helpful

---

## Error Handling Rules

Error handling should be **simple, explicit, and educational**.

### Required
- Catch only expected exceptions
- Explain the reason for the exception handling in comments
- Provide useful error messages
- Fail clearly when something important is missing

### Avoid
- `except Exception:` unless there is a strong reason
- Silent `pass`
- Retry loops without clear limits
- Automatic fallback behavior (see No-Fallback Policy)

Example:
```python
# We catch this specific error so the script can show a clear message
# instead of crashing with a confusing traceback for new developers.
```

---

## Script Structure Standard (Preferred Template)

Use this structure for most Python scripts:

1. **Module docstring**
2. **Imports**
3. **Constants / configuration**
4. **Helper functions**
5. **Main function**
6. **Entry point (`if __name__ == "__main__":`)**

This makes scripts predictable for beginners.

---

## Output Expectations for the AI Agent

When generating or updating code, the AI agent should provide:

1. **What changed** (plain English summary)
2. **Why it changed** (teaching-focused explanation)
3. **The code**
4. **How to run/test it in VS Code**
5. **What to look for when debugging**
6. **Any assumptions about `api.py` or TazUO state**

The explanation should be written for a beginner, not an expert.

---

## VS Code Workflow Expectations

Development happens in **VS Code**.

The AI agent should assume developers will:

- Open the repository in VS Code
- Edit Python scripts there
- Run scripts from the terminal or configured runner
- Review diffs before commit

The AI agent should help by:

- Keeping files organized
- Using clear file names
- Suggesting simple run/test steps
- Avoiding unnecessary project complexity

---

## GitHub Workflow Expectations

Final code is committed to a GitHub repository.

The AI agent should support clean version control habits:

- Make small, focused changes
- Keep commits logically grouped
- Write code that produces readable diffs
- Avoid unrelated refactors in the same change

### Suggested commit style
Use clear commit messages, for example:

- `add auto-heal script with beginner comments`
- `refactor targeting logic for readability`
- `document api.py assumptions in loot script`

---

## Definition of Done (Per Script)

A script is considered complete when:

- It solves the requested task
- It uses `api.py` / LegionScripts correctly
- It follows PEP 8
- It follows KISS
- It includes teaching-quality comments and docstrings
- It avoids fallbacks (or has approved fallback analysis)
- It is understandable by an entry-level developer
- It includes basic run/test instructions

---

## AI Agent Behavior Summary (Non-Negotiable)

The AI agent must:

- Write **simple Python**
- Follow **PEP 8**
- Follow **KISS**
- Use **beginner-friendly comments**
- Teach through docstrings and explanations
- Avoid unnecessary complexity
- Avoid fallbacks unless permission is requested and granted
- Be explicit about assumptions and API usage

The standard is not just “working code.”
The standard is **working code that teaches**.

## Final Note

This environment is designed to grow junior developers into confident developers.

Write code like a patient senior engineer:
- clear
- simple
- well-commented
- easy to debug
- easy to learn from
