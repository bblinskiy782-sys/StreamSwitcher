"""Tests for :class:`core.remote_api.RemoteAPI` using Flask's test client."""

from __future__ import annotations

import pytest

from core.remote_api import RemoteAPI


@pytest.fixture
def api():
    r = RemoteAPI(port=0)
    return r


@pytest.fixture
def client(api):
    api.wsgi_app().testing = True
    return api.wsgi_app().test_client()


# ---------------------------------------------------------------------------
# Basic control endpoints
# ---------------------------------------------------------------------------


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"StreamSwitcher" in r.data


def test_status_default(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json["source"] == "unknown"


def test_status_with_callback(api, client):
    api.get_status = lambda: {"source": "live_input", "uptime": "01:23:45"}
    r = client.get("/api/status")
    assert r.json == {"source": "live_input", "uptime": "01:23:45"}


def test_control_play_invokes_callback(api, client):
    calls = []
    api.on_play = lambda: calls.append("play")
    r = client.post("/api/control", json={"action": "play"})
    assert r.status_code == 200
    assert calls == ["play"]


def test_control_unknown_action(client):
    r = client.post("/api/control", json={"action": "wat"})
    assert r.status_code == 400


def test_source_switch(api, client):
    received = []
    api.on_source_switch = received.append
    r = client.post("/api/source", json={"source": "mp3_file"})
    assert r.status_code == 200
    assert received == ["mp3_file"]


# ---------------------------------------------------------------------------
# Extended endpoints
# ---------------------------------------------------------------------------


def test_volume_endpoint(api, client):
    received = []
    api.on_volume = received.append
    r = client.post("/api/volume", json={"master": 0.42})
    assert r.status_code == 200
    assert received == [0.42]


def test_volume_clamps(api, client):
    received = []
    api.on_volume = received.append
    client.post("/api/volume", json={"master": 5.0})
    client.post("/api/volume", json={"master": -1.0})
    assert received == [1.0, 0.0]


def test_volume_not_wired(client):
    r = client.post("/api/volume", json={"master": 0.5})
    assert r.status_code == 501


def test_playlist_get(api, client):
    api.get_playlist = lambda: [{"path": "/a.mp3", "title": "A"}]
    r = client.get("/api/playlist")
    assert r.status_code == 200
    assert r.json["tracks"][0]["path"] == "/a.mp3"


def test_playlist_set(api, client):
    received = []
    api.set_playlist = received.append
    r = client.post("/api/playlist", json={"tracks": ["/a.mp3", "/b.mp3"]})
    assert r.status_code == 200
    assert received == [["/a.mp3", "/b.mp3"]]


def test_playlist_set_rejects_non_list(api, client):
    api.set_playlist = lambda paths: None
    r = client.post("/api/playlist", json={"tracks": "/a.mp3"})
    assert r.status_code == 400


def test_playlist_add(api, client):
    added = []
    api.on_playlist_add = added.append
    r = client.post("/api/playlist/add", json={"path": "/c.mp3"})
    assert r.status_code == 200
    assert added == ["/c.mp3"]


def test_playlist_add_rejects_empty(api, client):
    api.on_playlist_add = lambda p: None
    r = client.post("/api/playlist/add", json={"path": ""})
    assert r.status_code == 400


def test_playlist_remove(api, client):
    removed = []
    api.on_playlist_remove = removed.append
    r = client.post("/api/playlist/remove", json={"index": 2})
    assert r.status_code == 200
    assert removed == [2]


def test_eq_get(api, client):
    api.get_eq = lambda: {"enabled": True, "bands": {"1000": 3.0}}
    r = client.get("/api/eq")
    assert r.status_code == 200
    assert r.json["bands"]["1000"] == 3.0


def test_eq_set(api, client):
    received = []
    api.set_eq = received.append
    r = client.post("/api/eq", json={"bands": {"1000": 3, "4000": -2}})
    assert r.status_code == 200
    assert received == [{1000: 3.0, 4000: -2.0}]


def test_history_not_wired(client):
    r = client.get("/api/history")
    assert r.status_code == 501


def test_history_returns_entries(api, client):
    api.get_history = lambda limit: [{"track": f"t{i}"} for i in range(limit)]
    r = client.get("/api/history?limit=3")
    assert r.status_code == 200
    assert len(r.json["entries"]) == 3


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_auth_off_by_default(client):
    r = client.get("/api/status")
    assert r.status_code == 200


def test_auth_required_when_key_set():
    api = RemoteAPI(port=0, api_key="secret123")
    client = api.wsgi_app().test_client()
    r = client.get("/api/status")
    assert r.status_code == 401


def test_auth_passes_with_correct_token():
    api = RemoteAPI(port=0, api_key="secret123")
    api.get_status = lambda: {"source": "ok"}
    client = api.wsgi_app().test_client()
    r = client.get("/api/status", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200
    assert r.json["source"] == "ok"


def test_auth_rejects_wrong_token():
    api = RemoteAPI(port=0, api_key="secret123")
    client = api.wsgi_app().test_client()
    r = client.get("/api/status", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_auth_does_not_protect_root():
    api = RemoteAPI(port=0, api_key="secret123")
    client = api.wsgi_app().test_client()
    r = client.get("/")
    assert r.status_code == 200
