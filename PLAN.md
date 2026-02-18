# Lacie Discord Bot - Codebase Cleanup Plan

## Phase 1: Foundation (infrastructure changes everything else depends on)

### 1a. Set up centralized logging
- Create `utils/logger.py` with a configured logger factory
- Replace all ~154 `print()` statements with proper `logging` calls across every file

### 1b. Add `__init__.py` to all 13 packages
- `birthday/`, `commands/`, `embed/`, `events/`, `image/`, `lilac-tools/`, `moderation/`, `profiles/`, `reminders/`, `sparkle/`, `stats/`, `suggestion/`, `wordle/`, `xp/`, `utils/`
- Each `__init__.py` gets a module-level docstring explaining the package's purpose

### 1c. Create `utils/constants.py`
- Move hardcoded IDs (lilac_id, guild IDs, channel IDs) to a single constants file
- Update all files that reference these IDs

---

## Phase 2: File renames & import standardization

### 2a. Rename files for snake_case consistency
- `embed/embedcolor.py` → `embed/embed_color.py`
- `commands/roletrack.py` → `commands/role_track.py`
- `events/roletrack.py` → delete (already marked for deletion in git)
- Update all imports referencing renamed files

### 2b. Standardize import style
- Use absolute imports everywhere (e.g., `from embed.embed_color import ...`)
- Group imports: stdlib → third-party → local, separated by blank lines
- Remove unused imports (`import sys` in generate_role_color_images.py, botban.py, etc.)

### 2c. Standardize database path construction
- Use `pathlib.Path` consistently instead of mixed `os.path.join` / `Path`

---

## Phase 3: Code quality fixes

### 3a. Fix bare `except:` clauses (~40 instances)
- Replace with specific exception types (`except Exception as e:`, `except sqlite3.Error:`, etc.)

### 3b. Fix deprecated patterns
- Replace `bot.loop.create_task()` with `cog_load()` async method or `asyncio.create_task()`

### 3c. Remove dead code
- Clean up unused variables, unreachable code
- Remove the deleted `events/roletrack.py`

### 3d. Rename constants to UPPER_SNAKE_CASE
- e.g., `meow_list` → `MEOW_LIST`, `lilac_id` → move to constants

---

## Phase 4: Comments & docstrings (the big one)

### 4a. Add module-level docstrings to every `.py` file
- Brief description of what the module does

### 4b. Add class docstrings to all Cog classes
- Describe what the cog provides

### 4c. Add function/command docstrings where missing
- Focus on non-obvious logic, complex functions
- Add inline comments for complex algorithms (minesweeper flood fill, XP calculations, spam detection, etc.)

### 4d. Document database schemas
- Add comments in database initialization code describing table structures

---

## Phase 5: bot.py cleanup

### 5a. Clean up bot.py
- Add module docstring and section comments
- DRY up the duplicate cog folder lists (on_ready and reload command)
- Add proper comments for each section

---

## Order of operations
Phases 1-5 are sequential - each builds on the prior. Within each phase, tasks are independent and can be parallelized.
