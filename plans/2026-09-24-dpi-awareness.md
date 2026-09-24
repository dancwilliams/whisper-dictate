# DPI awareness — Implementation Plan

Written against `main` at `ed8e7ef`. Follow-on agreed in `plans/2026-09-23-pill-polish.md`
(grill decision 4, 2026-09-24). House style and ground rules follow that plan.

Grilled 2026-09-24 before anything was built. Outcomes, folded in below: system-aware, not
per-monitor (measured: per-monitor v2 leaves the secondary 1.5x oversized); the saved pill
position is left alone even though, measured, *both* monitors' positions shift; point
strings for distances and `px()` only where Tk demands an integer; two phases as proposed.

## Overview

Whisper Dictate runs DPI-unaware. On Dan's primary monitor at 150 % Windows renders the
whole app at 96 dpi and stretches the bitmap by 1.5, so every glyph is soft. One Win32 call
before the Tk root is created fixes the text; the cost is that every size the code gives in
raw pixels stops matching the text around it. This plan makes the call and converts those
sizes.

Two phases, one PR each. Phase 1 is the call plus everything that would otherwise break:
the two window geometries, the Treeview column widths, the wrap lengths, and the pill's two
pixel constants. Phase 2 is the 91 padding sites, which only look tight after phase 1 and
convert mechanically; kept separate so the phase 1 diff stays readable.

## Ground rules for the implementer

- `uv` for everything: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy whisper_dictate`. `make` is not installed on this box.
- CI is `windows-latest` at 100 % scaling and excludes the ML wheels (`--no-group ml`).
- One branch and one PR per phase, targeting `main`. Do not start phase 2 until phase 1 is
  merged.
- No AI attribution in commits or PR text. Commits are GPG-signed; ask Dan to run
  `! echo test | gpg --clearsign` before the first commit. Never `--no-gpg-sign`.
- Line numbers are from `ed8e7ef`. If a line has moved, find the quoted code.
- `CHANGELOG.md` gets an entry under `[Unreleased]` for each user-visible change.
- No new dependencies. The one Win32 call goes through `ctypes` like everything else.

## Current State Analysis

Measured 2026-09-24 on the dev box (primary 5120x2160 at 150 %, secondary 1440x2560 at
100 %), a bare `Tk()` with `option_add("*Font", ("Segoe UI", 10))`, unaware and then after
`ctypes.windll.user32.SetProcessDPIAware()`:

| Probe | Unaware | Aware | Scales by itself |
|---|---|---|---|
| `IsProcessDPIAware()` | 0 | 1 | |
| `tk scaling` / px per inch | 1.33 / 96 | 2.0 / 144 | |
| `winfo_screenwidth/height` | 3413 x 1440 | 5120 x 2160 | |
| `ttk.Button("Load model")` | 76 x 25 | 120 x 35 | yes |
| `ttk.Combobox(width=12)` | 107 x 23 | 164 x 34 | yes |
| `ttk.Entry(width=30)` | 216 x 23 | 336 x 34 | yes |
| `tk.Text(width=50, height=8)` | 354 x 140 | 554 x 228 | yes |
| `ttk.Frame(padding=12)` | 12 px | 12 px | **no** |
| `ttk.Frame(padding="9p")` | 12 px | 18 px | yes |
| `ttk.Label(wraplength=440)` | 412 x 89 | 399 x 228 | **no** (wraps at 440 physical px) |
| `Treeview.column(width="90p")` | | `expected integer but got "90p"` | **no**, integers only |
| `padx=(0, "6p")`, `padding=("9p", "6p")`, `wraplength="330p"` | | accepted | yes |
| `padding="4.5p"`, `padx=(0, "4.5p")`, `wraplength="322.5p"` | | accepted; grid reports 6 px | yes |
| Monitors seen by a system-aware process | primary (0,0,3413,1440), secondary (5120,-235,6560,2325) | primary (0,0,5120,2160), secondary **(7680,-353,9840,3487)** | |
| A 400x300 window at app-space (7800,100) | | physical (5200,67), **267x200**, 144 dpi text scaled down | |
| Same window under per-monitor v2 on the secondary | | physical 400x300, text 1.5x too big | |

### Key Discoveries

- **Fonts are already in points.** `App.__init__` sets `option_add("*Font", ("Segoe UI", 10))`
  (`gui.py:158`); the hint label uses `("Segoe UI", 9, "italic")` (`gui.py:398`); the pill
  uses `TkDefaultFont` (`gui_components.py:160`). Every text-sized widget scales without a
  change. Character-width widgets (`Entry width=30`, `Text width=50`, `Listbox width=18`)
  scale with them.
- **Raw pixel sizes that do not scale:**
  - `self.geometry("980x680")` (`gui.py:151`), `window.geometry("900x600")` (`gui.py:785`,
    the log viewer inside `_open_window`).
  - `wraplength=` at `gui.py:398, 554, 658, 751, 761, 767, 799`, `app_prompt_dialog.py:37`,
    `glossary_dialog.py:41, 244`. Ten sites.
  - `self.tree.column(col, width=width)` loops: `app_prompt_dialog.py:52-58` (160, 180, 220)
    and `glossary_dialog.py:51-59` (160, 180, 70, 70, 100).
  - `StatusIndicator.MARGIN = 24` and `PAD_Y = 8` (`gui_components.py:130-131`), used at
    `:164` and `:322-323`. The rest of the capsule is font-derived (`:160-170`) and was made
    so for this plan.
  - 91 `padding=` / `padx=` / `pady=` sites: `gui.py` 51, `app_prompt_dialog.py` 19,
    `glossary_dialog.py` 18, `gui_components.py` 3. Values in use: 4, 6, 8, 10, 12, 16, 20,
    and tuples of those with 0.
- **Tk and Win32 stay in one coordinate space.** `work_area` (`gui_components.py:35-49`)
  says they agree "because the process is not DPI-aware". After the call both are aware and
  both answer in the *system-DPI* space: the primary 1:1 with physical pixels, the 100 %
  secondary presented at x 7680..9840 (its physical 5120..6560 scaled by 1.5) so the app's
  144 dpi drawing fits it once Windows scales it down. `MonitorFromPoint` /
  `GetMonitorInfoW` answer in that same space, so the clamp needs no change. The docstring
  must not say "physical".
- **The saved pill position** (`indicator_position`, `gui.py:1010-1014` load, `:1047-1049`
  save) is in Tk's space, and that space changes on both monitors: a saved primary
  position lands two thirds of the way across, and a saved secondary position falls in the
  new gap (5120..7680) and is clamped to the nearest edge. On screen either way; one drag
  or a double-click fixes it. Discarding it once would cost the same one drag from the
  default corner plus a settings field. Decided 2026-09-24, re-confirmed on the measured
  premise: do nothing but a changelog line.
- **Per-monitor is not usable.** Tk 8.6 does not handle `WM_DPICHANGED` and keeps one
  scaling. Measured under `SetProcessDpiAwarenessContext(-4)`: a window on the secondary is
  drawn at full physical size with 144 dpi text, 1.5x too big, and the pill would be too.
  System-aware, measured: the secondary shows the window at 267x200 physical for 400x300
  app-space, right-sized and slightly softer than the primary. That is the ceiling.
- **`main()` already uses `ctypes.windll` unguarded** (`gui.py:1709`), so the call needs no
  platform guard there. It must run before `App()` at `:1714`; a DPI awareness set after
  the first window is created is refused.
- **Tests never call `main()`** (`test_gui_pipeline.py` builds `App` with `__new__`), and
  the real-Tk tests in `test_gui_components.py` and the two dialog tests run at whatever
  DPI the runner has, which is 100 % on CI. Nothing in `tests/` asserts a pixel size.
- **`Treeview.column` `width` is the only place that rejects units**, so it, and the two
  geometry strings, need a computed integer. A four-line helper covers all four sites.

## Desired End State

- Text in every window is rendered at the monitor's real pixel density on the primary.
- Every window and dialog lays out as it does today: same proportions, nothing clipped,
  nothing overflowing, the log viewer and settings windows the same apparent size.
- The pill is the same apparent size and its default corner the same apparent distance
  from the edges.
- Verified by the manual walk-through under phase 1 and the four automated gates.

## What We're NOT Doing

- **Per-monitor DPI awareness.** Tk 8.6 cannot re-layout on a DPI change; measured, it
  leaves the secondary oversized. Windows scaling the app on the secondary is the ceiling.
- **Migrating or discarding the saved pill position.** Costs the same one drag either way,
  on both monitors.
- **A toolkit change.** Per-monitor crispness, blur, shadows and accessibility are past
  Tk's edge; this plan is Tk used as designed (`tk scaling` and point units exist for
  this). If those are ever wanted, that is a Qt conversation, not a Tk fix.
- **A manifest.** The DPI setting could live in a manifest on the executable, but the
  executable is Python's own `pythonw.exe` and we do not ship one (`no-exe-build`).
- **Converting character-width widgets** (`Entry width=30`, `Text width=50`). They scale
  with the font already.
- **A general "px()" helper used everywhere.** Distances that Tk accepts as screen units
  become point strings; only the integer-only options go through the helper.
- **Touching `docs/startup.md`.** It launches `pythonw.exe` from the venv, which is
  unaffected.

## Implementation Approach

One call in `main()`. Then, for every raw pixel value: if Tk accepts a screen distance
there (padding, padx, pady, wraplength), write it as points, which is pixels × 0.75 at
96 dpi — 12 → `"9p"`, 8 → `"6p"`, 4 → `"3p"`, 16 → `"12p"`, 20 → `"15p"`, 6 → `"4.5p"`,
10 → `"7.5p"`, 440 → `"330p"`. If Tk demands an integer (geometry, Treeview column width),
compute it from points with one helper. The pill's two constants go through the same helper.

---

## Phase 1: Aware, and nothing breaks

Branch: `feat/dpi-aware`.

### Changes Required

#### 1. The call

**File**: `whisper_dictate/gui.py`, `main()` (`:1706-1714`), before `app = App()`:

```python
    # Render at the monitor's real density instead of letting Windows stretch a
    # 96 dpi bitmap. Must precede the first window; Tk then sets its own scaling.
    ctypes.windll.user32.SetProcessDPIAware()
```

#### 2. The helper

**File**: `whisper_dictate/gui_components.py`, next to `work_area`:

```python
def px(widget: Misc, points: float) -> int:
    """Pixels for a distance given in points, at this display's density.

    For the options Tk insists are integers: window geometry and Treeview column
    widths. Everything else takes "9p" directly.
    """
    return round(widget.winfo_fpixels(f"{points}p"))
```

`Misc` from `tkinter`. One test in `tests/test_gui_components.py`: `px(root, 72)` equals
`round(root.winfo_fpixels("1i"))`.

#### 3. Geometry

**File**: `whisper_dictate/gui.py`

- `:151` `self.geometry("980x680")` → `self.geometry(f"{px(self, 735)}x{px(self, 510)}")`
- `:785` `window.geometry("900x600")` → `window.geometry(f"{px(window, 675)}x{px(window, 450)}")`

Import `px` alongside `PromptDialog, StatusIndicator` (`gui.py:69`).

#### 4. Wrap lengths

Ten sites; each pixel value becomes the point string of 0.75 × value:

- `gui.py:398` 380 → `"285p"`; `:554` 420 → `"315p"`; `:658, 751, 761, 767` 440 → `"330p"`;
  `:799` 600 → `"450p"`.
- `app_prompt_dialog.py:37` 520 → `"390p"`; `glossary_dialog.py:41` 520 → `"390p"`;
  `glossary_dialog.py:244` 430 → `"322.5p"`.

#### 5. Treeview column widths

**File**: `whisper_dictate/app_prompt_dialog.py:52-58` and `whisper_dictate/glossary_dialog.py:51-59`

The tuples keep their numbers but in points (120, 135, 165 / 120, 135, 52.5, 52.5, 75), and
the loop body becomes `self.tree.column(col, width=px(self, width), anchor="w")`. Import
`px` from `gui_components` in both.

#### 6. The pill

**File**: `whisper_dictate/gui_components.py`

`MARGIN` and `PAD_Y` (`:130-131`) become points — `MARGIN_PT = 18`, `PAD_Y_PT = 6` — and
the three uses (`:164`, `:322-323`) go through `px(self.window, ...)`. The `work_area`
docstring (`:41`) becomes: "Tk and Win32 share one coordinate space, the system-DPI space
both see after main()'s SetProcessDPIAware(); a 100 % secondary appears scaled by the
primary's factor to both. Do not convert."

Nothing else in the capsule changes: it was sized from the font for this.

#### 7. Changelog

`[Unreleased]` / `Changed`:

- Text is rendered at the display's real density instead of being stretched from 96 dpi,
  so it is sharp on a scaled monitor. The pill may sit in a different spot once after the
  update: its saved position was in the old coordinates. Drag it, or double-click to reset.

### Success Criteria

#### Automated Verification
- [x] `uv run pytest` passes, with the `px` test added
- [x] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy whisper_dictate` exit 0
- [x] `git grep -n "wraplength=[0-9]" whisper_dictate` returns nothing
- [x] `git grep -n 'geometry("[0-9]' whisper_dictate` returns nothing
- [x] CI green

#### Manual Verification (dev box, primary at 150 %)
- [x] Launch. Text in the main window is sharp, not soft. The window is the same apparent
      size as before (compare against `main` if unsure: it should not look two thirds size).
- [x] Every window opens and lays out with nothing clipped or overflowing: main window,
      Speech recognition settings, Cleanup settings, Automation settings, the log viewer,
      Per-app prompts (list and entry dialog), Glossary (list and rule dialog), Edit prompt.
- [x] The hint and help labels wrap at about the same word count as before, not taller and
      narrower.
- [x] The two Treeview lists show their columns at the same proportions as before.
- [x] The pill is the same apparent size; double-click puts it the same apparent distance
      from the corner. Dragging across both monitors still clamps correctly.
- [x] Drag the main window onto the 100 % secondary. It is the same apparent size as on
      the primary and slightly softer (measured before build: 267x200 physical for a
      400x300 window). This is the system-aware ceiling.
- [x] Drag the pill onto the secondary, dictate, relaunch: it stays. The saved position
      from before the update was elsewhere once; after one drag it is stable.
- [x] Paddings look tight. Expected; phase 2.

**Implementation Note**: pause for Dan's confirmation before phase 2.

---

## Phase 2: Paddings in points

Branch: `chore/dpi-paddings`.

### Changes Required

All 91 `padding=`, `padx=`, `pady=` sites in `gui.py`, `gui_components.py`,
`app_prompt_dialog.py`, `glossary_dialog.py`: every integer pixel value becomes the point
string of 0.75 × value, inside tuples too. `0` stays `0`. The conditional at
`gui.py:900-901` (`pady=4 if row > 0 else (0, 4)`) becomes `pady="3p" if row > 0 else (0, "3p")`.

Mechanical; do it with one script, not by hand, and review the diff for anything the
script touched that is not a padding.

Mapping: 4 → `"3p"`, 6 → `"4.5p"`, 8 → `"6p"`, 10 → `"7.5p"`, 12 → `"9p"`, 16 → `"12p"`,
20 → `"15p"`.

### Success Criteria

#### Automated Verification
- [ ] `git grep -nE "(padding|padx|pady)=\(?[1-9]" whisper_dictate` returns nothing
- [ ] Four gates exit 0; CI green

#### Manual Verification
- [ ] Every window from the phase 1 list looks as it did on `main` before phase 1: same
      spacing, now with sharp text.
- [ ] At 100 % (CI, or Windows set to 100 % briefly) nothing changed at all: a point is
      exactly 4/3 px there, so `"9p"` is 12 px.

---

## Testing Strategy

### Unit Tests
- `px` against `winfo_fpixels("1i")` on a real Tk root.
- The existing real-Tk pill and dialog tests keep running; at 100 % on CI nothing they
  measure changes.

### Manual
- The window-by-window walk-through under phase 1 is the real test. Nothing automated can
  see soft text or a clipped label.

## Performance Considerations

None. The call runs once; `winfo_fpixels` is a multiplication.

## Migration Notes

The saved pill position on a scaled primary lands elsewhere once. Decided: no migration, a
changelog line. Settings file format unchanged.

## References

- `plans/2026-09-23-pill-polish.md` — the capsule sized from font metrics; decision 4
- `whisper_dictate/gui.py:151, 158, 398, 785, 1706-1714` — geometry, font option, hint font, main()
- `whisper_dictate/gui_components.py:35-49, 130-131, 160-170` — `work_area`, pill constants, capsule sizing
- `whisper_dictate/app_prompt_dialog.py:37, 52-58`, `whisper_dictate/glossary_dialog.py:41, 51-59, 244`
- Tk screen distances: an integer is pixels, a suffix of `p` is points; `tk scaling` is
  points-to-pixels and is set from the display at startup
