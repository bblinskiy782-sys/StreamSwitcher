"""Tests for the headless CLI entry point."""

from __future__ import annotations

import main


def test_parse_args_defaults():
    args = main._parse_args([])
    assert args.headless is False
    assert args.config is None
    assert args.port is None
    assert args.api_key is None


def test_parse_args_headless_flag():
    args = main._parse_args(["--headless"])
    assert args.headless is True


def test_parse_args_full():
    args = main._parse_args(
        ["--headless", "--config", "/tmp/c.json", "--port", "9999", "--api-key", "abc"]
    )
    assert args.headless is True
    assert args.config == "/tmp/c.json"
    assert args.port == 9999
    assert args.api_key == "abc"


def test_main_dispatches_to_headless(monkeypatch):
    called = {"value": False}

    def fake_headless(args):
        called["value"] = True
        assert args.headless is True
        return 0

    monkeypatch.setattr(main, "run_headless", fake_headless)
    assert main.main(["--headless"]) == 0
    assert called["value"] is True


def test_main_dispatches_to_gui(monkeypatch):
    called = {"value": False}

    def fake_gui():
        called["value"] = True
        return 0

    monkeypatch.setattr(main, "run_gui", fake_gui)
    # Force --headless=False
    assert main.main([]) == 0
    assert called["value"] is True
