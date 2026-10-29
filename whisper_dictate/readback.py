"""Read back the control a dictation was pasted into, and notice what changed.

Windows UI Automation can read the text of most edit controls from another
process. After an auto-paste the app asks for the focused control, checks the
pasted text is in it, then polls once a second while Dan is still there. The
stretch of text the paste became is compared with what was pasted; a word swap
is a correction. Reading goes through the focused window because Electron
apps only build their accessibility tree when asked that way.

Privacy: the only text that leaves this module is the pasted span as Dan left
it. The rest of the field is read to find that span and dropped.
"""

from __future__ import annotations

import difflib
import logging
import re
import sys
import threading
import time
from typing import Any

from whisper_dictate import glossary

logger = logging.getLogger("whisper_dictate")

POLL_SECONDS = 1.0
WATCH_SECONDS = 120.0
# Chromium builds its accessibility tree after the first ask; give it a moment.
FIRST_READ_TRIES = 3
FIRST_READ_WAIT = 0.5
# Below this share of surviving words the edit is a rewrite, not a correction.
MIN_KEEP = 0.6
# How far, in words, a matching run may drift from where the paste would sit.
SLACK = 5

UIA_TEXT_PATTERN = 10014
UIA_VALUE_PATTERN = 10002


def edited_span(field: str, pasted: str) -> list[str] | None:
    """The words the pasted text became, or None when it is no longer there.

    Anchors on the longest run of matching words, projects where the paste
    would sit unchanged, and keeps the runs near that window: a common word
    matching elsewhere in a long document must not stretch the span.
    """
    fw, pw = field.split(), pasted.split()
    if not pw:
        return None
    blocks = [
        b
        for b in difflib.SequenceMatcher(None, fw, pw, autojunk=False).get_matching_blocks()
        if b.size
    ]
    if not blocks:
        return None
    anchor = max(blocks, key=lambda b: b.size)
    start = anchor.a - anchor.b
    near = [b for b in blocks if start - SLACK <= b.a and b.a + b.size <= start + len(pw) + SLACK]
    if sum(b.size for b in near) < MIN_KEEP * len(pw):
        return None
    first, last = near[0], near[-1]
    # shortcut: an edited edge word is assumed to stay one word; a 1-to-2 swap at
    # either end loses a word. Upgrade to char offsets if the bank shows it matters.
    lo = max(0, first.a - first.b)
    hi = min(len(fw), last.a + last.size + (len(pw) - last.b - last.size))
    return fw[lo:hi]


def map_to_raw(raw: str, final: str, edited: str) -> str | None:
    """Carry each word swap between the pasted and edited text onto the raw
    Whisper text. None when there is no swap, or a swap has nowhere to land
    (cleanup reworded it): the label would not be what Whisper heard."""
    rules = glossary.propose_rules(final, edited)
    if not rules:
        return None
    out = raw
    for rule in rules:
        pattern = re.compile(rf"(?<!\w){re.escape(rule.trigger)}(?!\w)", re.IGNORECASE)
        out, n = pattern.subn(rule.replacement, out, count=1)
        if n == 0:
            return None
    return out


class _Target:
    """One focused control and the pattern it reads through."""

    def __init__(self, uia: Any, element: Any, iface: Any):
        self.uia = uia
        self.element = element
        self.text: Any = None
        self.value: Any = None
        try:
            self.text = element.GetCurrentPattern(UIA_TEXT_PATTERN).QueryInterface(
                iface.IUIAutomationTextPattern
            )
        except Exception:  # a null pointer or COMError: no text pattern
            try:
                self.value = element.GetCurrentPattern(UIA_VALUE_PATTERN).QueryInterface(
                    iface.IUIAutomationValuePattern
                )
            except Exception:
                pass

    def read(self) -> str | None:
        try:
            if self.text is not None:
                return str(self.text.DocumentRange.GetText(-1))
            if self.value is not None:
                return str(self.value.CurrentValue)
        except Exception as e:  # COMError: the control went away
            logger.debug(f"Read-back lost the control: {e!r}")
        return None

    def still_focused(self) -> bool:
        try:
            return bool(self.uia.CompareElements(self.element, self.uia.GetFocusedElement()))
        except Exception:
            return False


def _client() -> tuple[Any, Any]:
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient

    uia = comtypes.client.CreateObject(
        UIAutomationClient.CUIAutomation8, interface=UIAutomationClient.IUIAutomation
    )
    return uia, UIAutomationClient


def _find(uia: Any, iface: Any, pasted: str) -> _Target | None:
    for _ in range(FIRST_READ_TRIES):
        target = _Target(uia, uia.GetFocusedElement(), iface)
        text = target.read()
        if text is not None and " ".join(pasted.split()) in " ".join(text.split()):
            return target
        time.sleep(FIRST_READ_WAIT)
    return None


def _watch(target: _Target, pasted: str, stop: threading.Event) -> str | None:
    last = pasted.split()
    deadline = time.monotonic() + WATCH_SECONDS
    while not stop.wait(POLL_SECONDS) and time.monotonic() < deadline:
        if not target.still_focused():
            break
        text = target.read()
        if text is None or not text.strip():
            break  # sent, cleared, or gone: the last snapshot is the answer
        span = edited_span(text, pasted)
        if span is not None:
            last = span
    return None if last == pasted.split() else " ".join(last)


def run(pasted: str, stop: threading.Event, app: str = "") -> str | None:
    """Find the control `pasted` landed in and watch it until Dan moves on.

    Returns the edited span when it differs from the paste, None otherwise.
    Call on its own thread; it blocks for up to WATCH_SECONDS. Never raises.
    """
    if sys.platform != "win32":
        return None
    import comtypes

    comtypes.CoInitialize()
    try:
        uia, iface = _client()
        target = _find(uia, iface, pasted)
        if target is None:
            logger.info(f"Read-back: {app or '?'} not readable")
            return None
        logger.info(f"Read-back: {app or '?'} readable")
        return _watch(target, pasted, stop)
    except Exception as e:
        logger.warning(f"Read-back failed: {e!r}")
        return None
    finally:
        comtypes.CoUninitialize()


def main() -> None:
    """Self-check: count down, read the focused control, say whether it is readable."""
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    print(f"Click into the box you want to check; reading in {delay:.0f}s")
    time.sleep(delay)
    import comtypes

    comtypes.CoInitialize()
    try:
        uia, iface = _client()
        for _ in range(FIRST_READ_TRIES):  # same patience as _find
            element = uia.GetFocusedElement()
            text = _Target(uia, element, iface).read()
            if text is not None:
                print(f"readable, {len(text)} chars")
                return
            time.sleep(FIRST_READ_WAIT)
        print(
            f"not readable: focus was {element.CurrentName!r}, "
            f"control type {element.CurrentControlType}, class {element.CurrentClassName!r}"
        )
    finally:
        comtypes.CoUninitialize()


if __name__ == "__main__":
    main()
