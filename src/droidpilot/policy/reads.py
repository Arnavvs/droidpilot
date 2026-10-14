"""Read hooks: the points where a deployment can count or rate-limit reads.

Tools that open things (a deep link, a swipe through a feed, a search) call

    d = reads.acquire(action, platform, target=...)
    if not d.allowed:
        return reads.refusal(d)
    ... do the read ...
    reads.commit(d, target=...)

The default build counts nothing and allows every read, so the agent works out
of the box. To bound an agent by reads (per-minute pacing, hourly or daily
ceilings), replace `acquire` / `commit` with calls into your own limiter; the
call sites do not change.

Also here: `composer_on_screen`, which spots a comment / message / reply box,
because typing into one is a send and the input tools refuse it by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import writes as wr


def uncounted_allowed() -> bool:
    return True


@dataclass
class ReadDecision:
    allowed: bool
    action: str
    platform: str
    n: int = 1
    why: str = ""
    counted: bool = False
    recorded: int = 0

    def to_dict(self) -> dict:
        d = {"allowed": self.allowed, "action": self.action, "n": self.n}
        if self.why:
            d["why"] = self.why
        return d


def refusal(d: ReadDecision, **extra) -> dict:
    return {"error": "read refused by policy", "read": d.to_dict(), **extra}


def acquire(action: str, platform: str, target: str = "", n: int = 1,
            serial: Optional[str] = None, pace: bool = True,
            max_wait_s: float = 0.0) -> ReadDecision:
    """Hook: reserve `n` reads before doing them. Default: always allowed."""
    return ReadDecision(True, action, platform, n)


def unit(d: ReadDecision, target: str = "", serial: Optional[str] = None,
         max_wait_s: float = 0.0) -> bool:
    """Hook: pace and record ONE unit of an acquired batch. False = stop."""
    if not d.allowed:
        return False
    d.recorded += 1
    return True


def commit(d: ReadDecision, target: str = "", serial: Optional[str] = None,
           n: int = 1) -> None:
    """Hook: record `n` executed reads. Default: nothing to record."""
    if d.allowed:
        d.recorded += max(0, n)


def bucketed(action: str, platform: str, target: str = "", serial: Optional[str] = None,
             per: int = 10) -> Optional[ReadDecision]:
    """Hook for counting high-frequency reads (swipes) in batches. Default: never refuses."""
    return None


def classify_count(e, package: str = "") -> tuple[str, str]:
    """(rule id, read action) if tapping `e` opens a counted read, else ("", "")."""
    if e is None:
        return "", ""
    app = (wr.rules().get("apps") or {}).get(package or "") or {}
    for rule in app.get("counted") or []:
        if wr._matches(rule, e):
            return rule["id"], rule["count"]
    return "", ""


def classify_tap_count(target, elements, x: int, y: int, package: str = "") -> tuple[str, str]:
    rule, action = classify_count(target, package)
    if action:
        return rule, action
    return classify_count(wr.at_point(elements, x, y), package)


def reel_advance_action(elements, package: str) -> str:
    """Hook: what a forward swipe counts as on this screen. Default: nothing."""
    return ""


def platform_of(package: str) -> str:
    return ((wr.rules().get("apps") or {}).get(package or "") or {}).get("platform", "")


def _editable(e) -> bool:
    """A text field. Class names vary: EditText, app subclasses, and
    AutoCompleteTextView all show up as comment boxes."""
    c = (e.cls or "").lower()
    return "edittext" in c or "autocompletetextview" in c


def composer_on_screen(elements, package: str) -> Optional[dict]:
    """A comment / message / reply box on screen, if any: typing there is a send."""
    spec = wr.rules().get("composers") or {}
    ids = set((spec.get("rids") or {}).get(package or "", []))
    hint = re.compile(spec.get("hint", "$^"))
    for e in elements or []:
        label = " ".join(((e.text or "") or (e.desc or "")).split()).lower()
        if (e.rid and e.rid in ids) or (_editable(e) and label and hint.search(label)):
            return {"rid": e.rid, "label": label[:40]}
    return None


def search_box_on_screen(elements, package: str) -> bool:
    """Hook: whether typing here runs a counted search. Default: never."""
    return False
