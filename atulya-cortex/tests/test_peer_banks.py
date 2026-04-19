"""tests/test_peer_banks.py — stable bank ids + config wiring."""

from __future__ import annotations

from cortex.peer_banks import peer_bank_id


def test_peer_bank_id_stable() -> None:
    a = peer_bank_id("default", "919999@s.whatsapp.net")
    b = peer_bank_id("default", "919999@s.whatsapp.net")
    assert a == b
    assert a.startswith("cortex_default_")


def test_peer_bank_id_differs_by_profile() -> None:
    assert peer_bank_id("work", "u1") != peer_bank_id("home", "u1")


def test_peer_bank_id_uses_hash_when_absurdly_long() -> None:
    long_peer = "x" * 500
    bid = peer_bank_id("p", long_peer)
    assert len(bid) <= 120
    assert bid.startswith("cortex_p_")
