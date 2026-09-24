# Pill polish — Implementation Plan

Written against `main` at `15e7d8f`. Source: Dan's ask on 2026-09-23 — the floating status
pill "runs off the screen depending on placement" and does not look finished; make it fit in,
and say where Tk is the limit. House style and ground rules follow
`plans/2026-09-22-regex-guards-and-dead-code.md`.

Grilled 2026-09-24 with phase 1 built and uncommitted. Outcomes, all folded in below: cap
32 with six messages reworded; a clamped position is never persisted; DPI awareness is its
own plan after phase 2, and phase 2 sizes from font metrics so it survives that; the theme
is followed live from the existing timer; and a phase 3 closes two gaps left by the merged
regex plan (dialog tests, and a skipped glossary rule surfaced once per session).

## Overview

Three things are wrong with the pill, in descending order of how much they matter:

1. **It clamps to the primary monitor only.** `StatusIndicator` keeps itself "on screen" with
   `winfo_screenwidth()` / `winfo_screenheight()`, which on Windows is the primary monitor.
   Measured on the dev box: Tk reports 3413x1440; the desktop is two monitors, the second at
   x 5120..6560, y -235..2325. A pill dragged to the second monitor is dragged back to the
   primary's right edge on the next status update, and the top 235 px of the tall monitor are
   unreachable. This is a bug in our clamping, not a Tk limit.
2. **It changes size on every message.** The window auto-sizes to the label (59 px for "Idle",
   250 px for the longest message), anchored top-left. Parked near a right edge it grows off
   the edge, the clamp pulls it left, and the next shorter message lets it snap back. The
   jiggle is most of the "unfinished" feel.
3. **It is a grey rectangle.** A `ttk.Frame` in the `vista` theme's `SystemButtonFace`, square
   corners, light only.

Three phases, one PR each. Phase 1 is the bug (1 and 2). Phase 2 is the look (3). Phase 3
is the regex plan's follow-up and is independent of 2. Phase 1 is worth merging on its own;
phase 2 is taste and can wait.

### Where Tk is the limit (so nobody spends a day on it)

- **Transparency is 1-bit.** `-transparentcolor` (verified working, Tk 8.6.12) makes rounded
  corners possible but not antialiased. A 1 px outline in a slightly darker shade hides the
  stair-step well enough at this size. There is no way to blend edges.
- **No drop shadow, no acrylic, no blur.** Everything Tk draws is flat.
- **The process is DPI-unaware.** `IsProcessDPIAware()` returns 0 and `tk scaling` is 1.33
  (96 dpi). On a 150 % display Windows bitmap-stretches the whole app, so text is slightly
  soft. Fixing that (`SetProcessDpiAwareness`) changes the coordinate space of every window,
  every saved geometry and every widget size in the app — not a pill change. See "What we're
  NOT doing".

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy whisper_dictate`. `make` is not installed on this box; run the four commands.
- CI is `windows-latest` and excludes the ML wheels (`--no-group ml`). Locally the `.venv` has
  them; do not re-sync with different groups.
- One branch and one PR per phase, targeting `main`. Do not start phase 2 until phase 1 is
  merged.
- No AI attribution in commits or PR text. Commits are GPG-signed; if signing fails, stop and
  tell Dan. Never `--no-gpg-sign`.
- Match the code around you. Comments explain why, not what. The existing comments in
  `StatusIndicator` each record a bug that got through; keep them.
- Line numbers are from `15e7d8f`. If a line has moved, find the quoted code.
- `CHANGELOG.md` gets an entry under `[Unreleased]` for each user-visible change, in the
  register already there: symptom, then cause, then what it does now.
- No new dependencies. Win32 goes through `ctypes` like `app_context.py`, `clipboard.py` and
  `speaker.py`.

## Current State Analysis

Measured 2026-09-23 on the dev box (Windows 11, two monitors, primary at 150 %):

| Probe | Result |
|---|---|
| `winfo_screenwidth/height` | 3413 x 1440 (primary only) |
| `EnumDisplayMonitors` rcMonitor / rcWork | primary (0,0,3413,1440) / (0,0,3413,**1392**); secondary (5120,-235,6560,2325) / same |
| Tk `geometry("+3000+1000")` vs `GetWindowRect` | (3000,1000,3250,1031) — **identical coordinate space** |
| `IsProcessDPIAware` | 0 |
| Pill size, "Idle" / longest message / `width=40` | 59x31 / 250x31 / 280x31 |
| `-transparentcolor`, `-alpha` on a Toplevel | both accepted |
| `AppsUseLightTheme` (HKCU Themes\Personalize) | 1 |
| ttk theme | `vista`; Toplevel bg `SystemButtonFace` |
| `pytest` | passes; `tests/test_gui_components.py` runs against a real Tk and skips without a display |

### Key Discoveries

- **Tk and Win32 agree on coordinates.** Because the process is DPI-unaware, `MonitorFromPoint`,
  `GetMonitorInfoW` and `GetWindowRect` all return the same virtualised space Tk uses. No
  conversion. The gap between 3413 and 5120 in that space is real (the secondary is placed in
  physical units); `MONITOR_DEFAULTTONEAREST` maps points in the gap to the nearest monitor,
  measured: (4000,0) → primary.
- **`rcWork` already excludes the taskbar** (1392 vs 1440 on the primary). The hard-coded
  `margin_y = 96` in `_reposition` (`gui_components.py:203-204`) was guessing at that.
- **Three places clamp**: `_on_drag` (`gui_components.py:160-166`), `_reposition`
  (`gui_components.py:196-206`), and the default corner in the same function. All use
  `winfo_screen*`. The saved position is only honoured through `_reposition` (`:199-202`), so
  a saved second-monitor position is clamped back at startup as well as on every update.
- **`update()` reflows then repositions** (`gui_components.py:255-263`): the label changes,
  `update_idletasks()`, then `_reposition()` clamps with the new width. That is the jump. The
  truncation at 40 characters (`:258`) is the natural fixed width.
- **`master.bind("<Configure>", self._reposition)`** (`gui_components.py:99`) means every
  main-window resize also repositions. Cheap; unchanged.
- **Public surface used by `gui.py`**: `StatusIndicator(master, initial_position, menu_items)`,
  `.show()`, `.update(state, message)`, `._reset_position()`, `.get_position()`
  (`gui.py:904-914, 775, 955, 1047`). Tests additionally touch `.window`, `.menu`,
  `._start_drag/_on_drag/_end_drag`, `._raise`, `._show_menu`
  (`tests/test_gui_components.py`). Nothing outside the class touches `.label`, `.dot`, or
  the frame, so phase 2 may replace them.
- **`test_the_pill_is_kept_on_screen`** (`tests/test_gui_components.py:112-122`) asserts the
  pill lands within `winfo_screen*` after a drag to (99999, 99999). On a two-monitor box that
  assertion becomes wrong once clamping is per-monitor: the nearest monitor to (99999, 99999)
  is the secondary. The test must change with the code.
- **Docs that mention the pill**: `README.md:26-27, 107`, `docs/startup.md:50-52`. All stay
  true after both phases (drag anywhere, double-click or Settings to reset).

## Desired End State

- The pill can be dragged onto any monitor and stays there across status updates, restarts,
  and the topmost timer. It never straddles the taskbar.
- The pill is one fixed size. Status messages change its text and dot only.
- (Phase 2) The pill is a rounded capsule with no square window behind it, dark or light to
  match Windows.
- Verified by: the updated `tests/test_gui_components.py` passing on the dev box (real Tk,
  two monitors) and on CI, plus the manual checks under each phase.

## What We're NOT Doing

- **DPI awareness, here.** Decided 2026-09-24: wanted, as its own plan after phase 2.
  Measured: with `SetProcessDpiAwareness(1)` before `Tk()`, `tk scaling` becomes 2.0 and
  text-sized widgets grow by themselves (a 32-char label went 232 → 324 px); raw pixel
  sizes do not (`980x680`, paddings, `wraplength=440`, the 14 px dot), and saved pill
  coordinates on the primary need ×1.5 while the secondary's do not. That plan: the one
  Win32 call, scale the raw sizes in `gui.py`, discard the saved pill position once. Phase 2
  sizes the capsule from font metrics so it needs no change when that lands.
- **Fade in / out with `-alpha`.** The pill is always visible; there is nothing to fade.
  `attributes("-alpha", ...)` is one line if a constant translucency is ever wanted.
- **Edge-anchored growth** (keep the right edge still when parked on the right). Fixed width
  removes the problem with one line; anchoring would need per-edge bookkeeping and still
  needs clamping.
- **Persisting a clamped position.** A pill saved on a monitor that is unplugged today is
  shown on the nearest edge, but its saved spot is kept for when the monitor is back. A
  drag saves a new one. Decided 2026-09-24; pinned by a test.
- **Antialiased corners, shadows.** Tk cannot.
- **A settings UI for pill colours or size.** Constants in the class.

## Implementation Approach

Phase 1 adds one small Win32 helper — the work area of the monitor nearest a point — and
routes all three clamps through it, then pins the label width. Phase 2 swaps the
`ttk.Frame` + `Canvas` + `ttk.Label` for a single `Canvas` drawing a rounded capsule, with
the window background keyed out via `-transparentcolor`. The class's public surface does not
change in either phase.

---

## Phase 1: Clamp to the right monitor, stop resizing

### Overview

Fixes the off-screen bug and the jiggle. After this phase the pill behaves; it still looks
like a grey rectangle.

### Changes Required

#### 1. Work-area helper

**File**: `whisper_dictate/gui_components.py`
**Changes**: module-level Win32 binding following `app_context.py:11-18`, and one function.

```python
import ctypes
import ctypes.wintypes
import platform

USER32: ctypes.WinDLL | None = ctypes.windll.user32 if platform.system() == "Windows" else None

MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def work_area(master: Tk, x: int, y: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the usable desktop on the monitor nearest (x, y).

    winfo_screenwidth() is the primary monitor only, so a pill on a second
    monitor was clamped back onto the first on every status update. rcWork
    excludes the taskbar. Tk and Win32 share one coordinate space here because
    the process is not DPI-aware; do not convert.
    """
    if USER32 is not None:
        monitor = USER32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
        if monitor and USER32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right, r.bottom
    return 0, 0, master.winfo_screenwidth(), master.winfo_screenheight()
```

`MonitorFromPoint` takes `POINT` by value; declare
`USER32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]` and
`.restype = ctypes.wintypes.HMONITOR` next to the binding, or ctypes will pass it wrong on
64-bit. Do the same for `GetMonitorInfoW` (`[HMONITOR, POINTER(_MONITORINFO)]`, `BOOL`).

The fallback branch exists for the non-Windows import (mypy runs on Windows in CI, but the
module must still import elsewhere) and for a `GetMonitorInfoW` failure; it reproduces
today's behaviour.

#### 2. Route the three clamps through it

**File**: `whisper_dictate/gui_components.py`

`_on_drag` (`:160-166`) — pick the monitor from the **pointer**, so the pill follows the
cursor across monitors:

```python
left, top, right, bottom = work_area(self.master, event.x_root, event.y_root)
self.window.update_idletasks()
ww = self.window.winfo_width()
wh = self.window.winfo_height()
x = max(left, min(x, right - ww))
y = max(top, min(y, bottom - wh))
```

`_reposition` (`:196-206`) — pick the monitor from the **saved top-left** for a user
position, and from `(0, 0)` (always the primary) for the default corner:

```python
window_w = self.window.winfo_width()
window_h = self.window.winfo_height()
if self.user_position is not None and not self._dragging:
    x, y = self.user_position
    left, top, right, bottom = work_area(self.master, int(x), int(y))
    x = max(left, min(int(x), right - window_w))
    y = max(top, min(int(y), bottom - window_h))
else:
    _left, _top, right, bottom = work_area(self.master, 0, 0)
    x = right - window_w - MARGIN
    y = bottom - window_h - MARGIN
```

`MARGIN = 24` as a class constant replaces `margin_x = 24` / `margin_y = 96`; `rcWork` now
does the taskbar's job. Delete the two `winfo_screen*` reads in each function.

#### 3. Fixed width

**File**: `whisper_dictate/gui_components.py`

Class constant `MAX_CHARS = 32`. `ttk.Label(frame, text="Idle", anchor="w", width=MAX_CHARS)`
at `:94`, and `update()` (`:258`) truncates with the same constant:

```python
display = message if len(message) <= self.MAX_CHARS else message[: self.MAX_CHARS - 1] + "…"
```

Measured: 232x31 at every message. `update()` may keep its `_reposition()` call; with a
constant size it is now a no-op move, and it is what re-asserts topmost.

32 was chosen over 40 (grill, decision 2) because a 280 px bar reading "Idle" is mostly
empty. Six messages in `gui.py` were over 32 and are reworded; every other fixed message is
25 or under:

| Was | Now |
|---|---|
| `Recording (locked) - press again to stop` (`:1330`) | `Locked; press again to stop` |
| `Recording - release to transcribe` (`:1374`) | `Recording; release to stop` |
| `Cleanup returned nothing, used raw text` (`:1608`) | `Cleanup empty; used raw text` |
| `Cleanup unavailable; using raw text` (`:1604`) | `No cleanup; used raw text` |
| `Clipboard locked; text is in the transcript` (`:1638`) | `Clipboard locked; see transcript` |
| `Recognizer: {desc}` (`:1251`) | `{desc} ready` |

Still over 32 and left alone, truncating on the pill only (the main window's status label
and the log carry the full text): the 63-char unreadable-settings warning (`:201`), the
Cohere recognizer id, and free-text loader warnings (`:1193`). `tests/test_gui_pipeline.py`
asserts two of the reworded messages (`:329`, `:362`) and changes with them.

#### 4. Tests

**File**: `tests/test_gui_components.py`

- Add a fixture-level `monkeypatch` of `gui_components.work_area` to a fixed rect, e.g.
  `(0, 0, 1600, 900)`, for the existing `TestDragging` cases so they are deterministic on any
  monitor layout. Existing assertions stay as they are; `test_the_pill_is_kept_on_screen`
  asserts against the patched rect instead of `winfo_screen*`.
- New cases in `TestDragging` (patched rect list, e.g. primary `(0,0,1000,800)` and secondary
  `(1200,-100,2000,900)`, where `work_area` returns whichever contains or is nearest the
  point):
  - `test_a_saved_position_on_a_second_monitor_is_honoured`: `initial_position=(1500, 0)`
    → position stays `(1500, 0)` after `show()` and after `update(...)`. This is the bug.
  - `test_a_negative_y_on_a_tall_monitor_is_allowed`: `initial_position=(1500, -50)` → stays.
  - `test_the_default_corner_clears_the_taskbar`: with primary work bottom 760 and
    `_reset_position()`, `y + height <= 760`.
  - `test_a_clamped_position_is_not_persisted`: `initial_position` beyond the secondary's
    right edge → shown inside it, `get_position()` still returns the saved value.
- New `test_the_pill_does_not_resize_between_messages`: width after `update("ready", "Idle")`
  equals width after `update("listening", "Recording (locked) - press again to stop")`.
- New `@pytest.mark.skipif(sys.platform != "win32")` case (pattern:
  `tests/test_clipboard.py:208`) calling the real `work_area(root, 0, 0)`: returns a rect
  containing (0, 0) with `bottom <= root.winfo_screenheight()` and
  `right <= root.winfo_screenwidth()`. Proves the ctypes signature on CI.

#### 5. Changelog

**File**: `CHANGELOG.md`, under `[Unreleased]` / `Fixed`:

- The status pill could not be kept on a second monitor: it was clamped to the primary
  screen on every status change, and the top of a taller monitor was out of reach. It now
  clamps to the monitor it is on, and its default corner sits above the taskbar instead of a
  guessed 96 px up.
- The pill grew and shrank with each message and jumped when that ran it into a screen edge.
  It is now one fixed size.

and under `[Unreleased]` / `Changed`:

- Status messages fit the pill: 32 characters, with the six longer ones reworded.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` passes, including the new cases in `tests/test_gui_components.py`
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0
- [ ] `uv run mypy whisper_dictate` exit 0 (ctypes bindings typed as in `app_context.py`)
- [ ] CI green on the PR (three Python versions, Windows)

#### Manual Verification (dev box, two monitors)
- [ ] Drag the pill onto the second monitor; trigger a dictation; it stays there through
      "Recording", "Transcribing", "Cleaned", "Pasted".
- [ ] Drag it to the top of the tall monitor (negative y); it is allowed and stays.
- [ ] Quit and relaunch; it reappears on the second monitor where it was.
- [ ] Double-click: it lands bottom-right of the primary, above the taskbar, 24 px in.
- [ ] Park it hard against the right edge of either monitor and dictate: no jiggle.
- [ ] Drag across the gap between monitors: it follows the cursor, no dead zone, no jump
      back.
- [ ] Settings → Reset status indicator position still works.

**Implementation Note**: pause here for Dan's manual confirmation before opening phase 2.

---

## Phase 2: Rounded capsule, light or dark

### Overview

Replaces the frame with one Canvas drawing a capsule, keys out the window background, and
picks colours from the Windows app theme. Behaviour from phase 1 is unchanged.

### Changes Required

#### 1. Theme colours

**File**: `whisper_dictate/gui_components.py`

```python
KEY = "#010203"  # keyed out by -transparentcolor; nothing else may use it

THEMES = {
    "light": {"fill": "#f3f3f3", "edge": "#c8c8c8", "text": "#1b1b1b"},
    "dark": {"fill": "#2b2b2b", "edge": "#3f3f3f", "text": "#f0f0f0"},
}


def _apps_use_light_theme() -> bool:
    if platform.system() != "Windows":
        return True
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return True
```

Read in `__init__` and again from `_ensure_topmost` (`:238-243`), which already fires every
3 s; when the answer changes, `_apply_theme(theme)` reconfigures the capsule items' `fill`
and `outline` and the text's `fill`. Six lines, no new timer, no message pump. A pill that
stays light on a desktop that just went dark reads as broken (grill, decision 5). The
`edge` colour is the 1 px outline that hides the 1-bit stair-step on the corners.

#### 2. One Canvas instead of frame + dot + label

**File**: `whisper_dictate/gui_components.py`, `__init__` (`:89-97`) and `update()` (`:255-263`)

Sizes come from the font, not pixel constants, so the DPI plan that follows does not have
to touch this (grill, decision 4). With `f = tkfont.nametofont("TkDefaultFont")`:

```python
line = f.metrics("linespace")
HEIGHT = line + 2 * PAD_Y            # PAD_Y = 6, in the same units Tk pads the ttk pill today
RADIUS = HEIGHT // 2
DOT = max(8, line * 2 // 3)
WIDTH = RADIUS + DOT + f.measure("0") * self.MAX_CHARS + RADIUS
```

Today that comes to roughly 232 x 32. When the process becomes DPI-aware and `tk scaling`
is 2.0, `linespace` and `measure` scale with the font and the capsule follows.

```python
self.window.configure(background=KEY)
self.window.attributes("-transparentcolor", KEY)
theme = THEMES["light" if _apps_use_light_theme() else "dark"]
self.canvas = Canvas(
    self.window, width=WIDTH, height=HEIGHT, bg=KEY, highlightthickness=0, borderwidth=0
)
self.canvas.pack()
self._capsule(theme)  # two ovals + one rectangle, fill=theme["fill"], outline=theme["edge"]
cx = RADIUS
self.dot_oval = self.canvas.create_oval(
    cx - DOT / 2, HEIGHT / 2 - DOT / 2, cx + DOT / 2, HEIGHT / 2 + DOT / 2,
    fill=self.COLORS["idle"], outline="",
)
self.text = self.canvas.create_text(
    RADIUS + DOT, HEIGHT / 2, anchor="w", text="Idle", fill=theme["text"], font="TkDefaultFont"
)
```

`_capsule` draws `create_oval` at each end and a `create_rectangle` between them, all with
the same fill and outline, then covers the two interior outline segments with a fill-only
rectangle so the seams do not show. (A single `create_polygon(..., smooth=True)` is the
alternative; Tk's smoothing is a spline, not a true arc, and the ends look pinched. Ovals
are exact.)

`update()` becomes `self.canvas.itemconfigure(self.dot_oval, fill=color)` and
`self.canvas.itemconfigure(self.text, text=display)`. Truncation stays at `MAX_CHARS`, and
`WIDTH` is derived from it, so the text always fits.

Bindings (`:102-106`, `:122-123`): bind on `self.window` and `self.canvas` only; the label
and dot widgets no longer exist. `self.dot` and `self.label` attributes are removed; nothing
outside the class reads them (verified against `gui.py` and the tests).

Because clicks on keyed-out pixels fall through to whatever is beneath, the corners are not
grabbable. That is the correct behaviour for a capsule.

#### 3. Tests

**File**: `tests/test_gui_components.py`

- `test_update_changes_the_dot_and_text`: after `update("error", "Boom")`,
  `canvas.itemcget(dot_oval, "fill") == COLORS["error"]` and `itemcget(text, "text") == "Boom"`.
- `test_long_messages_are_truncated` from phase 1 carries over, reading the canvas text item.
- `test_the_window_background_is_keyed_out`: `window.attributes("-transparentcolor")` equals
  `KEY` (skipif not win32).
- `_apps_use_light_theme`: one test with `winreg.QueryValueEx` monkeypatched to return
  `(0, 4)` → `False`, one raising `OSError` → `True`.
- `test_the_theme_follows_windows`: patch `_apps_use_light_theme` to `False`, call
  `_ensure_topmost()` directly, assert the capsule fill is `THEMES["dark"]["fill"]`.
- Phase 1's fixed-size test now covers the canvas; leave it.

#### 4. Docs and changelog

- `CHANGELOG.md` `[Unreleased]` / `Changed`: The status pill is a rounded capsule, dark or
  light to match the Windows app theme, instead of a square grey window.
- `docs/startup.md:50` says "A small pill" — already true; no change. `README.md:26` — no
  change.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy whisper_dictate` all exit 0
- [ ] CI green

#### Manual Verification
- [ ] Over a busy desktop the corners show desktop, not grey. Outline hides the stair-step
      at arm's length.
- [ ] With the app running, switch Windows to dark apps mode: within 3 s the capsule is
      dark with light text. Switch back: the reverse, no relaunch.
- [ ] Drag from the text, from the dot, from the empty capsule: all work. Clicking exactly
      on a corner pixel falls through (expected).
- [ ] Right-click menu still opens; Quit still exits without a traceback.
- [ ] All seven phase 1 manual checks still pass.
- [ ] Every status colour is readable on both themes ("warning" yellow dot on light fill
      is the one to look at).

---

## Phase 3: Close the regex plan's two gaps

Branch: `fix/glossary-skip-visible`. Independent of phase 2; can go before or after it.
Both items came out of grilling `plans/2026-09-22-regex-guards-and-dead-code.md` on
2026-09-24 (decisions 6 and 7).

### Overview

That plan's save-time regex refusal in both dialogs is proven by hand only: nothing in
`tests/` constructs `AppPromptEntryDialog` or `GlossaryRuleDialog`, and the modules sit at
12 % and 13 % coverage. Its "no harness, covered by hand" note was true then; the real-Tk
fixture in `tests/test_gui_components.py` has since made a harness cheap. And a glossary
rule skipped at dictation time is logged and nothing more — a rule that silently stops
working looks like the app broke, and a regular user never opens the log.

### Changes Required

#### 1. Drive the two dialogs' `_on_save`

**Files**: new `tests/test_app_prompt_dialog.py`, new `tests/test_glossary_dialog.py`

Copy the `root` fixture from `tests/test_gui_components.py:17-40` (retry loop, withdrawn,
skip without a display). Per dialog, construct it against `root`, set the Tk variables,
monkeypatch that module's `messagebox.showerror` to a recorder, call `_on_save()`:

- `(unclosed` → `showerror` called once with a message containing the `re` error text,
  `result` is `None`, `winfo_exists()` is true.
- `(\w+ )?Report - Word` (app prompt) / a valid regex trigger (glossary, match type
  `regex`) → `showerror` not called, `result` populated, dialog destroyed.

Four tests. Both constructors take only the parent and an optional existing entry:
`AppPromptEntryDialog(parent, entry=None)` (`app_prompt_dialog.py:198-201`) and
`GlossaryRuleDialog(parent, rule=None)` (`glossary_dialog.py:190-193`). Both call
`grab_set()` on a withdrawn root; if that raises under pytest, `wait_visibility` first or
patch `grab_set` on the instance, and say which in the PR.

#### 2. A skipped glossary rule is reported once per session

**File**: `whisper_dictate/glossary.py`, `GlossaryManager.apply` (`:309-316`)

Record what was skipped instead of only logging it: `self.skipped: list[str] = []` reset at
the top of `apply()`, `self.skipped.append(rule.trigger)` in the `except`. The log line
stays.

**File**: `whisper_dictate/gui.py`

`_refresh_glossary_cache` (`:1504`) rebuilds the manager from disk every dictation, so the
memory lives on the `App`: `self._reported_bad_rules: set[str] = set()` in `__init__`. After
the first `apply_glossary` call (`:1507-1509`):

```python
for trigger in self.glossary_manager.skipped:
    if trigger not in self._reported_bad_rules:
        self._reported_bad_rules.add(trigger)
        self._set_status("warning", f"Glossary rule skipped: {trigger}")
```

`_set_status` is thread-safe (`:949-951`). The warning survives the end of the pipeline
because `:1569` and `:1652` leave a standing warning alone. The message can exceed 32
characters; it truncates on the pill and reads in full in the window and log, which is
already the rule for free-text warnings. Once reported, the rule is silent for the rest of
the session — the log still has it every time.

**Tests**: `tests/test_glossary.py` — `apply()` with one bad rule leaves `skipped ==
["(unclosed"]`, and with none leaves it empty. `tests/test_gui_pipeline.py` — a glossary
with a bad rule: first dictation ends in state `warning` with the trigger in the message;
second dictation ends in `ready`.

#### 3. Changelog

`[Unreleased]` / `Fixed`:

- A glossary rule that could not be applied was named in the log and nowhere else. The
  first dictation that skips it now shows a warning naming the rule; later ones stay quiet.

### Success Criteria

#### Automated Verification
- [ ] `uv run pytest` passes with the four dialog tests and the three glossary tests added
- [ ] `app_prompt_dialog.py` and `glossary_dialog.py` coverage each above 30 %
- [ ] ruff, format check, mypy exit 0; CI green

#### Manual Verification
- [ ] Hand-edit `~/.whisper_dictate/whisper_dictate_glossary.json` to give a regex rule the
      trigger `(unclosed`; restart; dictate. The pill goes yellow with "Glossary rule
      skipped: (unclosed" (truncated) and the dictation is pasted.
- [ ] Dictate again: pill ends on "Ready", no warning.
- [ ] Fix the rule in the Glossary dialog; dictate; no warning, rule applies.

---

## Testing Strategy

### Unit Tests
- `work_area` patched to fixed rects for all geometry tests; one unpatched Windows-only case
  to prove the ctypes call.
- Fixed size across messages.
- Theme detection with `winreg` patched; both failure paths default to light.

### Integration
- The real-Tk tests in `tests/test_gui_components.py` already exercise show, drag, update,
  reset, topmost timer and the menu. They keep running on the dev box and on CI's Windows
  runners.

### Manual Testing Steps
Listed under each phase. Phase 1 is the one that needs a two-monitor box; phase 2 needs a
theme flip.

## Performance Considerations

`work_area` is two Win32 calls, run on drag motion and on every main-window `<Configure>`.
Microseconds. Nothing to do.

## Migration Notes

`indicator_position` in the settings file is unchanged in meaning and coordinate space. A
position saved on a second monitor before this change was being clamped at load; after
phase 1 it is honoured. No migration.

## References

- `whisper_dictate/gui_components.py:47-269` — `StatusIndicator` as it stands
- `whisper_dictate/gui.py:904-914, 771-776, 955, 1010-1014, 1047-1049` — construction, reset,
  update, load and save of the position
- `whisper_dictate/app_context.py:11-18` — the `ctypes.windll` binding pattern to copy
- `tests/test_gui_components.py` — real-Tk test fixture and drag helper
- `tests/test_clipboard.py:208` — `skipif(sys.platform != "win32")` pattern
- `plans/2026-09-22-regex-guards-and-dead-code.md` — ground rules and register
