"""Event spill file: replay, rotation, retention purge (I-PROXY-12, Step 25)."""
import io
import json
import os
import pathlib
import re
import time
import urllib.error

import pytest

from xg_netpolicy import proxy_logic
from xg_netpolicy.proxy_logic import EventShipper, PolicyCache

URL = "http://127.0.0.1:8000/api/internal/net-events"
DAY_MS = 86400 * 1000


def _now_ms():
    return int(time.time() * 1000)


def _ev(n, ts=None, **kw):
    return {"client_ip": "192.168.10.30", "host": f"h{n}.example", "layer": "sni", "action": "blocked",
            "ts": _now_ms() if ts is None else ts, **kw}


@pytest.fixture
def shipper(tmp_path, monkeypatch):
    monkeypatch.delenv("XG_RETENTION_RAW_DAYS", raising=False)
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "t" * 20)
    p = tmp_path / "proxy.json"
    p.write_text(json.dumps({"events_url": URL}))
    s = EventShipper(PolicyCache(p), fallback=str(tmp_path / "log" / "ev.jsonl"))
    s.stop()  # tests drive _ship / replay_spill / purge_spill directly
    s.posts = []
    s.status = lambda batch: 200

    def fake_post(batch):
        s.posts.append([e["host"] for e in batch])
        return s.status(batch)

    s._post = fake_post
    return s


def _lines(f):
    f = pathlib.Path(f)
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_failed_post_is_spilled_then_replayed_oldest_first_after_a_success(shipper):
    shipper.status = lambda b: None  # CCC unreachable
    shipper._ship([_ev(1), _ev(2)])
    shipper._ship([_ev(3)])
    assert [e["host"] for e in _lines(shipper.fallback)] == ["h1.example", "h2.example", "h3.example"]
    assert shipper.stats["spilled"] == 3

    shipper.status = lambda b: 200
    shipper.posts.clear()
    shipper._ship([_ev(4)])
    # the live batch first, then the spill in its original order
    assert shipper.posts == [["h4.example"], ["h1.example", "h2.example", "h3.example"]]
    assert not pathlib.Path(shipper.fallback).exists()
    assert shipper.stats["replayed"] == 3


def test_replay_is_not_started_by_a_failed_post(shipper):
    shipper.status = lambda b: 503
    shipper._ship([_ev(1)])
    shipper._ship([_ev(2)])
    assert shipper.posts == [["h1.example"], ["h2.example"]]  # no replay attempt in between
    assert len(_lines(shipper.fallback)) == 2


def test_replay_batches_are_capped_and_limited_per_success(shipper):
    shipper.status = lambda b: None
    shipper._ship([_ev(i) for i in range(1200)])
    shipper.status = lambda b: 200
    shipper.posts.clear()
    assert shipper.replay_spill(max_batches=2) == 1000
    assert [len(b) for b in shipper.posts] == [500, 500]
    left = _lines(shipper.fallback)
    assert [e["host"] for e in left] == [f"h{i}.example" for i in range(1000, 1200)]
    assert shipper.replay_spill() == 200 and not pathlib.Path(shipper.fallback).exists()


def test_replay_stops_at_first_failure_and_keeps_the_rest_in_order(shipper):
    shipper.status = lambda b: None
    shipper._ship([_ev(i) for i in range(700)])
    calls = iter([200, 500])
    shipper.status = lambda b: next(calls)
    assert shipper.replay_spill() == 500
    assert [e["host"] for e in _lines(shipper.fallback)] == [f"h{i}.example" for i in range(500, 700)]


def test_rejected_batch_is_split_bad_event_dropped_not_replayed_forever(shipper):
    bad = {"bad.example"}
    shipper.status = lambda b: 422 if any(e["host"] in bad for e in b) else 200
    shipper._ship([_ev(i) for i in range(8)] + [dict(_ev(0), host="bad.example")])
    assert shipper.stats["rejected"] == 1
    assert not pathlib.Path(shipper.fallback).exists()  # good events delivered, bad one gone
    delivered = [h for b in shipper.posts if len(b) and "bad.example" not in b for h in b]
    assert sorted(delivered) == sorted(f"h{i}.example" for i in range(8))

    # an already spilled batch the CCC refuses is dropped on replay, not kept
    shipper.status = lambda b: None
    shipper._ship([dict(_ev(0), host="bad.example"), _ev(9)])
    shipper.status = lambda b: 422 if any(e["host"] in bad for e in b) else 200
    shipper.replay_spill()
    assert not pathlib.Path(shipper.fallback).exists()
    assert shipper.stats["rejected"] == 2
    shipper.posts.clear()
    assert shipper.replay_spill() == 0 and shipper.posts == []


def test_post_maps_http_errors_to_status(tmp_path, monkeypatch):
    p = tmp_path / "proxy.json"
    p.write_text(json.dumps({"events_url": URL}))
    s = EventShipper(PolicyCache(p), fallback=str(tmp_path / "ev.jsonl"))
    s.stop()

    def raise_422(req, timeout=None):
        raise urllib.error.HTTPError(URL, 422, "Unprocessable", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(proxy_logic.urllib.request, "urlopen", raise_422)
    assert s._post([_ev(1)]) == 422

    def unreachable(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(proxy_logic.urllib.request, "urlopen", unreachable)
    assert s._post([_ev(1)]) is None
    s._ship([_ev(1)])
    assert len(_lines(s.fallback)) == 1


def test_spill_rotates_at_size_cap_and_drops_the_oldest_file(shipper, monkeypatch):
    monkeypatch.setattr(proxy_logic, "SPILL_MAX_BYTES", 300)
    shipper.status = lambda b: None
    for i in range(12):
        shipper._ship([_ev(i), _ev(100 + i)])
    live = pathlib.Path(shipper.fallback)
    files = [live.with_name(f"ev.jsonl.{i}") for i in (3, 2, 1)] + [live]
    assert all(f.exists() for f in files)
    assert not live.with_name("ev.jsonl.4").exists()
    assert all(f.stat().st_size < 300 + 400 for f in files)
    assert shipper.stats["spill_lost"] > 0
    kept = [e["host"] for f in files for e in _lines(f)]
    assert kept[-1] == "h111.example" and "h0.example" not in kept  # newest kept, oldest dropped
    assert len(kept) + shipper.stats["spill_lost"] == 24

    shipper.status = lambda b: 200
    shipper.posts.clear()
    shipper.replay_spill()
    replayed = [h for b in shipper.posts for h in b]
    assert replayed == kept  # oldest file first, each in order
    assert not any(f.exists() for f in files)


def test_retention_default_is_ethics_raw_events_and_env_overrides(monkeypatch):
    monkeypatch.delenv("XG_RETENTION_RAW_DAYS", raising=False)
    assert proxy_logic.retention_days() == 140
    ethics = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "ETHICS.md").read_text(encoding="utf-8")
    assert re.search(r"Raw events.*default 140 days", ethics)
    server_cfg = (pathlib.Path(__file__).resolve().parents[2] / "server" / "config" / "xephyguard.php").read_text()
    assert "env('XG_RETENTION_RAW_DAYS', 140)" in server_cfg
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "30")
    assert proxy_logic.retention_days() == 30
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "1")
    assert proxy_logic.retention_days() == 7
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "forever")
    assert proxy_logic.retention_days() == 140


def test_purge_drops_expired_events_while_ccc_stays_down(shipper, monkeypatch):
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "30")
    shipper.status = lambda b: None
    old, fresh = _now_ms() - 31 * DAY_MS, _now_ms() - 29 * DAY_MS
    shipper._ship([_ev(1, ts=old), _ev(2, ts=fresh)])
    live = pathlib.Path(shipper.fallback)
    live.write_text(live.read_text() + "not json\n" + json.dumps({"host": "no-ts"}) + "\n")
    assert shipper.purge_spill() == 3
    assert [e["host"] for e in _lines(live)] == ["h2.example"]

    # a rotated file last written before the cutoff is deleted without being read
    rotated = live.with_name("ev.jsonl.1")
    rotated.write_text(json.dumps(_ev(3, ts=old)) + "\n")
    t = time.time() - 31 * 86400
    os.utime(rotated, (t, t))
    assert shipper.purge_spill() == 1 and not rotated.exists()
    assert shipper.stats["purged"] == 4


def test_replay_never_sends_expired_events(shipper, monkeypatch):
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "30")
    shipper.status = lambda b: None
    shipper._ship([_ev(1, ts=_now_ms() - 31 * DAY_MS), _ev(2)])
    shipper.status = lambda b: 200
    shipper.posts.clear()
    assert shipper.replay_spill() == 1
    assert shipper.posts == [["h2.example"]]


def test_run_loop_purges_on_start(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "30")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "ev.jsonl").write_text(json.dumps(_ev(1, ts=_now_ms() - 31 * DAY_MS)) + "\n")
    p = tmp_path / "proxy.json"
    p.write_text("{}")
    s = EventShipper(PolicyCache(p), fallback=str(log_dir / "ev.jsonl"))
    try:
        deadline = time.time() + 3
        while (log_dir / "ev.jsonl").exists() and time.time() < deadline:
            time.sleep(0.05)
    finally:
        s.stop()
    assert not (log_dir / "ev.jsonl").exists()


def test_compose_passes_retention_to_proxy():
    compose = (pathlib.Path(__file__).resolve().parents[2] / "ccc-deploy" / "docker-compose.yml").read_text()
    proxy = re.search(r"\n  proxy:.*?(?=\n  \w)", compose, re.S).group(0)
    assert "XG_RETENTION_RAW_DAYS: ${XG_RETENTION_RAW_DAYS:-140}" in proxy


def test_allowed_dedup_table_stays_bounded(shipper, monkeypatch):
    monkeypatch.setattr(proxy_logic, "DEDUP_MAX_KEYS", 100)
    for i in range(1000):
        assert shipper.should_emit_allowed("192.168.10.30", f"h{i}.example") is True
    assert len(shipper._seen_allowed) <= 100
    assert shipper.should_emit_allowed("192.168.10.30", "h999.example") is False  # newest kept


def test_full_queue_drops_are_counted_logged_and_written_to_stats(shipper, caplog):
    import queue as _queue
    shipper.q = _queue.Queue(maxsize=2)
    for i in range(5):
        shipper.emit(**_ev(i))
    assert shipper.stats["queue_full"] == 3
    shipper.should_emit_allowed("192.168.10.30", "a.example")
    shipper.should_emit_allowed("192.168.10.30", "a.example")
    shipper.should_emit_observed("192.168.10.30", "openai.com")
    shipper.should_emit_observed("192.168.10.30", "openai.com")
    with caplog.at_level("WARNING", logger="xg-proxy"):
        shipper.write_stats()
        shipper.write_stats()  # nothing new: no second warning
    assert sum("3 events dropped: event queue full" in r.getMessage() for r in caplog.records) == 1
    stats = json.loads(shipper.stats_path.read_text())
    assert stats["queue_full"] == 3 and stats["deduped_allowed"] == 1 and stats["deduped_observed"] == 1
    assert stats["queued"] == 2 and "spilled" in stats and "rejected" in stats
    assert shipper.stats_path.name == "proxy-stats.json"
    assert "192.168.10.30" not in shipper.stats_path.read_text()  # counts only


def test_stop_writes_stats(tmp_path):
    p = tmp_path / "proxy.json"
    p.write_text("{}")
    s = EventShipper(PolicyCache(p), fallback=str(tmp_path / "log" / "ev.jsonl"))
    s.stop()
    assert json.loads((tmp_path / "log" / "proxy-stats.json").read_text())["queue_full"] == 0


def test_policy_retention_from_ccc_wins_over_env(tmp_path, monkeypatch, state_dict):
    """Server S-64: state.json `retention_days_raw` (the admin's current setting) reaches proxy.json and
    drives the purge; env XG_RETENTION_RAW_DAYS is only the fallback (older CCC, unusable value)."""
    from xg_netpolicy import generate
    from xg_netpolicy.state import State

    monkeypatch.setenv("XG_RETENTION_RAW_DAYS", "30")
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "t" * 20)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({**state_dict, "events_url": URL, "retention_days_raw": 10}))
    generate.generate(state, tmp_path / "net")
    proxy_json = tmp_path / "net" / "proxy.json"
    assert json.loads(proxy_json.read_text())["retention_days_raw"] == 10
    s = EventShipper(PolicyCache(proxy_json), fallback=str(tmp_path / "log" / "ev.jsonl"))
    s.stop()
    s._post = lambda batch: None   # CCC down: everything spills
    assert s.retention_days() == 10
    s._ship([_ev(1, ts=_now_ms() - 11 * DAY_MS), _ev(2, ts=_now_ms() - 9 * DAY_MS)])
    assert s.purge_spill() == 1                                   # 11 days old: past the CCC's 10, inside env's 30
    assert [e["host"] for e in _lines(s.fallback)] == ["h2.example"]

    assert proxy_logic.retention_days(3) == 7 and proxy_logic.retention_days(5000) == 1095   # clamped like the server
    for bad in ("10", True, 1.5):
        st = State.from_dict({**state_dict, "retention_days_raw": bad})
        assert st.retention_days_raw is None and any(x.startswith("retention_days_raw") for x in st.skipped)
    assert State.from_dict(state_dict).retention_days_raw is None   # older CCC: no field
    assert _env_retention_without_field(tmp_path, state_dict) == 30


def _env_retention_without_field(tmp_path, state_dict):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({**state_dict, "events_url": URL}))
    s = EventShipper(PolicyCache(p), fallback=str(tmp_path / "log2" / "ev.jsonl"))
    s.stop()
    return s.retention_days()
