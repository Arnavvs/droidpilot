"""The write gate: a tap is judged by the element it will actually hit.

    python -m pytest tests/test_writes.py
"""

from __future__ import annotations

import pytest

from droidpilot.policy import writes as wr
from droidpilot.ui import Element

PKG = "com.example.app"


def el(text="", rid="", bounds=(0, 0, 100, 100), desc=""):
    return Element(i=0, rid=rid, anchor=rid, text=text, desc=desc, cls="Button",
                   bounds=bounds, clickable=True, pkg=PKG)


@pytest.mark.parametrize("label,rule", [
    ("Send", "any.send"), ("Post", "any.send"), ("Pay now", "any.money"),
    ("Place order", "any.money"), ("Delete account", "any.account"),
    ("Log out", "any.account"),
])
def test_sends_payments_and_account_actions_are_forbidden(label, rule):
    v = wr.classify(el(label), PKG)
    assert v.kind == "forbidden" and v.rule == rule
    d = wr.decide(v)
    assert not d.allowed and rule in d.why


def test_ordinary_controls_are_reads():
    for label in ("Close", "Settings", "Next", "Sender details", ""):
        v = wr.classify(el(label), PKG)
        assert v.kind == "read"
        assert wr.decide(v).allowed


def test_labels_match_whole_words_after_normalising_case_and_space():
    assert wr.classify(el("  SEND  "), PKG).kind == "forbidden"
    assert wr.classify(el("Send feedback"), PKG).kind == "read"


def test_the_operator_can_allow_one_forbidden_rule_for_a_run():
    wr.configure(allow_rules={"any.send"})
    assert wr.decide(wr.classify(el("Send"), PKG)).allowed
    assert not wr.decide(wr.classify(el("Pay now"), PKG)).allowed


def test_a_tap_is_judged_by_the_stricter_of_target_and_what_is_under_the_point():
    row = el("Contact row", bounds=(0, 0, 1000, 200))
    send = el("Send", bounds=(800, 50, 900, 150))
    v = wr.classify_tap(row, [row, send], 850, 100, PKG)
    assert v.kind == "forbidden"            # the centre of the row is its Send button
    assert wr.classify_tap(row, [row, send], 100, 100, PKG).kind == "read"


def test_at_point_returns_the_smallest_covering_element():
    big = el("big", bounds=(0, 0, 1000, 1000))
    small = el("small", bounds=(10, 10, 20, 20))
    assert wr.at_point([big, small], 15, 15) is small
    assert wr.at_point([big, small], 500, 500) is big
    assert wr.at_point([big, small], 2000, 2000) is None


def test_enabled_writes_respect_readonly_mode(monkeypatch):
    monkeypatch.setitem(wr.rules(), "apps", {PKG: {"platform": "ex", "rules": [
        {"id": "ex.star", "label": "^star$", "action": "star"}]}})
    v = wr.classify(el("Star"), PKG)
    assert v.kind == "write" and v.action == "star"
    assert not wr.decide(v).allowed                 # not enabled for this run
    wr.configure(writes={"star"})
    assert wr.decide(v).allowed
    wr.configure(mode="readonly", writes={"star"})
    assert not wr.decide(v).allowed


def test_gate_action_fails_closed_without_an_action():
    assert not wr.gate_action("", "ex").allowed
    wr.configure(writes={"publish"})
    assert wr.gate_action("publish", "ex").allowed
