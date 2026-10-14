"""Target-level write detection: judge a tap by the element it will actually hit.

A tool-level risk class is too coarse. `tap` is harmless on "Close" and is a
purchase on "Pay now", so every tap is classified by its real target (after the
pre-tap check has re-found it) against `writes.json`:

    read        not a write                                   -> tap
    forbidden   sends, payments, account-level actions...     -> refuse, unless the
                                                                 operator allowed that
                                                                 rule id for the run
    write       an action an operator may enable per run      -> tap only if the mode
                                                                 is not readonly AND the
                                                                 action is enabled

Every "no" fails closed. `decide()` is also the hook for a rate limiter: a
deployment that needs per-action ceilings can wrap it (see policy/reads.py for
the matching hook on reads).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
_RULES: Optional[dict] = None


# ------------------------------------------------------------------ config

@dataclass
class Config:
    """Set per run by the agent (Policy), or from the environment for direct use."""
    mode: str = "auto"                              # auto | ask | readonly
    writes: set = field(default_factory=set)       # write actions enabled this run
    allow_rules: set = field(default_factory=set)  # forbidden rule ids allowed this run
    allow_uncounted_reads: bool = True             # kept for API compatibility
    run_id: str = ""


def _env_set(name: str) -> set:
    return {x.strip() for x in os.environ.get(name, "").split(",") if x.strip()}


CONFIG = Config(writes=_env_set("DROIDPILOT_WRITES"),
                allow_rules=_env_set("DROIDPILOT_ALLOW_RULES"))


def configure(mode: str = "auto", writes=(), allow_rules=(), run_id: str = "",
              allow_uncounted_reads: bool = True) -> None:
    CONFIG.mode = mode
    CONFIG.writes = set(writes) | _env_set("DROIDPILOT_WRITES")
    CONFIG.allow_rules = set(allow_rules) | _env_set("DROIDPILOT_ALLOW_RULES")
    CONFIG.allow_uncounted_reads = bool(allow_uncounted_reads)
    CONFIG.run_id = run_id


# ------------------------------------------------------------------ rules

def rules() -> dict:
    global _RULES
    if _RULES is None:
        with open(os.path.join(HERE, "writes.json"), encoding="utf-8") as f:
            _RULES = json.load(f)
    return _RULES


@dataclass
class Verdict:
    kind: str = "read"            # read | write | forbidden
    rule: str = ""
    action: str = ""
    reason: str = ""
    platform: str = ""
    label: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


def _label(e) -> str:
    return " ".join(((e.text or "") or (e.desc or "")).split()).lower()


def _labels(e) -> list:
    return [" ".join(v.split()).lower() for v in (e.text or "", e.desc or "") if v]


def _matches(rule: dict, e) -> bool:
    rid = rule.get("rid")
    if rid:
        pat = re.compile("(?:" + rid + ")")
        if not (pat.fullmatch(e.rid or "") or pat.fullmatch(e.anchor or "")):
            return False
    lab = rule.get("label")
    if lab:
        pat = re.compile(lab)
        if not any(pat.search(v) for v in _labels(e)):
            return False
    return bool(rid or lab)


def classify(e, package: str = "") -> Verdict:
    """What tapping element `e` inside `package` would do."""
    if e is None:
        return Verdict()
    spec = rules()
    app = (spec.get("apps") or {}).get(package or "") or {}
    platform = app.get("platform", "")
    for rule in (app.get("rules") or []) + (spec.get("any_app") or []):
        if not _matches(rule, e):
            continue
        if rule.get("action"):
            return Verdict("write", rule["id"], rule["action"], "",
                           platform, _label(e)[:60])
        return Verdict("forbidden", rule["id"], "", rule.get("forbidden", ""),
                       platform, _label(e)[:60])
    return Verdict(platform=platform)


_RANK = {"read": 0, "write": 1, "forbidden": 2}


def _contains(b, x: int, y: int) -> bool:
    return b[0] <= x < b[2] and b[1] <= y < b[3]


def at_point(elements, x: int, y: int):
    """The smallest element covering (x, y) - what a tap there actually hits.

    Clickable or not: a label inside a button (anchor = the button's id) is
    enough to name the control."""
    hits = [e for e in elements or [] if _contains(e.bounds, x, y)]
    if not hits:
        return None
    return min(hits, key=lambda e: (e.bounds[2] - e.bounds[0]) *
                                   (e.bounds[3] - e.bounds[1]))


def classify_tap(target, elements, x: int, y: int, package: str = "") -> Verdict:
    """Judge the tap by the stricter of the intended target and what is under
    the point. A clickable row whose centre sits on its own "Send" button is a
    send, whatever the row's label says."""
    verdicts = [classify(target, package)]
    under = at_point(elements, x, y)
    if under is not None and under is not target:
        verdicts.append(classify(under, package))
    return max(verdicts, key=lambda v: _RANK[v.kind])


# ------------------------------------------------------------------ the gate

@dataclass
class Decision:
    allowed: bool
    verdict: Verdict
    why: str = ""

    def to_dict(self) -> dict:
        d = {"allowed": self.allowed, **self.verdict.to_dict()}
        if self.why:
            d["why"] = self.why
        return d


def decide(verdict: Verdict, serial: str = "") -> Decision:
    """Whether a tap with this verdict may proceed. Fails closed."""
    if verdict.kind == "read":
        return Decision(True, verdict)
    if verdict.kind == "forbidden":
        if verdict.rule in CONFIG.allow_rules:
            return Decision(True, verdict, why="rule allowed by the operator for this run")
        return Decision(False, verdict,
                        why="forbidden: " + verdict.reason + " (allow rule '"
                            + verdict.rule + "' explicitly to override for one run)")
    if CONFIG.mode == "readonly":
        return Decision(False, verdict, why="readonly mode: " + verdict.action
                                            + " changes state")
    if verdict.action not in CONFIG.writes:
        return Decision(False, verdict,
                        why="write '" + verdict.action + "' is not enabled for this "
                            "run (enable with --allow-write " + verdict.action
                            + " or DROIDPILOT_WRITES)")
    return Decision(True, verdict)


def commit(decision: Decision, target: str = "", serial: str = "") -> Optional[str]:
    """Hook: record an executed write. The default build keeps no ledger."""
    return None


def gate_action(action: str, platform: str, serial: str = "",
                rule: str = "") -> Decision:
    """For tools that write without a generic tap."""
    if not action:
        return decide(Verdict("forbidden", rule or "tool", "", "a write with no "
                              "enabled action", platform), serial)
    return decide(Verdict("write", rule or ("tool." + action), action, "",
                          platform), serial)
