import json

import pandas as pd
import pytest

from xg_analysis.__main__ import main
from xg_analysis.features import FEATURES, compute, data_dir, load_session, scoring_lists
from xg_analysis.pipeline import score_session
from xg_analysis.scoring import V2_FEATURES, score_v1, score_v2


def honest_and_suspicious(lab, sid=10):
    lab.session(sid, "test")
    a = lab.pc(sid, "A1")
    b = lab.pc(sid, "A2")
    lab.student(1, "alice")
    lab.student(2, "bob")
    # alice: steady typing with corrections the whole session, small pastes, stays in the IDE
    lab.typing(sid, a, "alice", 1, 55, kpm=160, bs=0.09)
    lab.paste(sid, a, "alice", 20, 40, 2)
    lab.event(sid, a, "alice", 0.5, "window_focus", {"app": "code"})
    # bob: types a little, goes idle, then a large code paste appears; AI tool + blocked attempts
    lab.typing(sid, b, "bob", 1, 10, kpm=120, bs=0.05)
    lab.event(sid, b, "bob", 0.5, "window_focus", {"app": "code"})
    lab.event(sid, b, "bob", 12, "window_focus", {"app": "firefox"})
    lab.event(sid, b, "bob", 40, "window_focus", {"app": "code"})
    lab.paste(sid, b, "bob", 40, 2400, 85, code=True)
    lab.event(sid, b, "bob", 41, "file_activity", {"dir": "/home/bob/lab", "saves": 2, "bytes_delta": 2600})
    lab.alert(sid, b, "bob", 15, "proc.ollama", "local_llm")
    for m in (13, 14, 16):
        lab.blocked(sid, b, m)
    lab.db.conn.commit()
    return a, b


def test_features(lab, db):
    a, b = honest_and_suspicious(lab)
    f = compute(load_session(db, 10)).set_index("user")
    assert f.loc["alice", "keys_per_min"] == pytest.approx(156, rel=0.05)   # 13 keys per 5 s window
    assert f.loc["bob", "largest_paste"] == 2400
    assert f.loc["bob", "idle_then_burst"] == 1        # the 2400-char paste and its save 1 min later are one insertion
    assert f.loc["alice", "idle_then_burst"] == 0
    assert f.loc["bob", "blocked_attempts"] == 3
    assert f.loc["bob", "ai_flags"] == 1
    assert f.loc["bob", "time_outside_ide"] > 0.4
    assert f.loc["bob", "paste_to_typed"] > 1


@pytest.mark.parametrize("growth_after_s, expected", [(None, 1), (30, 1), (60, 1), (90, 2), (-30, 2)])
def test_paste_and_the_save_it_causes_count_once(lab, db, growth_after_s, expected):
    lab.session(17, "test")
    pc = lab.pc(17, "H1")
    lab.typing(17, pc, "hal", 1, 5)                  # last keys around minute 6, then idle
    lab.paste(17, pc, "hal", 20, 2000, 60)
    if growth_after_s is not None:
        lab.event(17, pc, "hal", 20 + growth_after_s / 60, "file_activity", {"dir": "/w", "saves": 1, "bytes_delta": 2100})
    lab.db.conn.commit()
    assert compute(load_session(db, 17)).iloc[0].idle_then_burst == expected


def test_folder_growth_without_a_paste_is_a_burst(lab, db):
    lab.session(18, "test")
    pc = lab.pc(18, "H2")
    lab.typing(18, pc, "ida", 1, 5)
    lab.paste(18, pc, "ida", 20, 100, 3)              # small paste: not a burst, does not absorb the growth
    lab.event(18, pc, "ida", 20.5, "file_activity", {"dir": "/w", "saves": 1, "bytes_delta": 5000})
    lab.paste(18, pc, "ida", 30, 800, 30)             # two separate big pastes stay two
    lab.paste(18, pc, "ida", 30.5, 800, 30)
    lab.db.conn.commit()
    assert compute(load_session(db, 18)).iloc[0].idle_then_burst == 3


def test_alerts_without_a_user_count_for_every_user_of_the_pc(lab, db):
    lab.session(19, "test")
    pc = lab.pc(19, "J1")
    other = lab.pc(19, "J2")
    lab.typing(19, pc, "jo", 1, 20)
    lab.typing(19, pc, "kim", 25, 20)                       # second login on the same PC
    lab.typing(19, other, "lee", 1, 40)
    lab.alert(19, pc, None, 0.5, "tamper.unclean_restart", "tamper")
    lab.alert(19, pc, "", 30, "proc.ollama", "local_llm")
    lab.alert(19, pc, "kim", 31, "proc.lmstudio", "local_llm")
    lab.alert(19, other, None, 2, "tamper.clock", "tamper")
    lab.db.conn.commit()
    f = compute(load_session(db, 19)).set_index("user")
    assert (f.loc["jo", "tamper_flags"], f.loc["jo", "ai_flags"]) == (1, 1)    # used to be (0, 0)
    assert (f.loc["kim", "tamper_flags"], f.loc["kim", "ai_flags"]) == (1, 2)  # own alert + the PC's
    assert (f.loc["lee", "tamper_flags"], f.loc["lee", "ai_flags"]) == (1, 0)  # never another PC's


def test_blocked_attempts_go_to_the_user_active_on_the_pc(lab, db):
    lab.session(20, "test")
    pc = lab.pc(20, "K1")
    solo = lab.pc(20, "K2")
    lab.typing(20, pc, "ann", 1, 19)                        # ann until minute 20 ...
    lab.typing(20, pc, "ben", 30, 20)                       # ... ben from minute 30
    lab.typing(20, solo, "cy", 10, 10)
    for m in (0.2, 10, 12, 25):                             # before anyone (-> first user), ann, ann, gap after ann
        lab.blocked(20, pc, m)
    for m in (31, 40):
        lab.blocked(20, pc, m)
    for m in (1, 50):                                       # a single user gets all of the PC's, as before
        lab.blocked(20, solo, m)
    lab.db.conn.commit()
    f = compute(load_session(db, 20)).set_index("user")
    assert f.loc["ann", "blocked_attempts"] == 4             # each used to get all 6
    assert f.loc["ben", "blocked_attempts"] == 2
    assert f.loc["cy", "blocked_attempts"] == 2


def test_unused_columns_are_neither_loaded_nor_computed(lab, db):
    honest_and_suspicious(lab)
    sd = load_session(db, 10)
    assert "title" not in sd.alerts.columns
    assert not {"source_app", "target_app"} & set(sd.pastes.columns)
    assert not {"alert_titles", "categories"} & set(compute(sd).columns)


def test_roster_load_has_no_name_number_or_pseudonym(lab, db):
    honest_and_suspicious(lab)
    st = load_session(db, 10).students
    assert set(st.columns) == {"student_id", "login", "exempt", "exempt_reason"}    # data minimisation (ETHICS.md)
    cells = {str(v) for v in st.to_numpy().ravel()}
    assert not cells & {"Student 1", "Student 2", "S0001", "S0002", "P-0001", "P-0002"}


def test_v1_scores_are_explained_and_ranked(lab, db):
    honest_and_suspicious(lab)
    out = score_session(db, 10, v2=False)
    assert out["scored"] == 2
    rows = {r[0]: r for r in db.conn.execute("SELECT user, score, confidence, reasons, not_observable FROM scores")}
    bob, alice = rows["bob"], rows["alice"]
    assert bob[1] >= 60 and alice[1] <= 10
    assert bob[2] == "high"
    signals = [r["signal"] for r in json.loads(bob[3])]
    assert {"ai_flags", "idle_then_burst", "largest_paste", "blocked_attempts"} <= set(signals)
    burst = next(r for r in json.loads(bob[3]) if r["signal"] == "idle_then_burst")
    assert (burst["label"], burst["points"]) == ("1 burst(s) of new code right after a 2+ minute idle gap", 8)
    assert sum(r["points"] for r in json.loads(bob[3])) >= bob[1]          # every point is traceable
    assert any("phone" in x for x in json.loads(alice[4]))                  # states what is not observable
    assert [f["user"] for f in out["flagged"]] == ["bob"]
    # idempotent re-scoring
    score_session(db, 10, v2=False)
    assert db.conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 2


def test_exempt_student_behavior_signals_ignored(lab, db):
    lab.session(11, "test")
    pc = lab.pc(11, "B1")
    lab.student(3, "carol", exempt="speech-to-text tool")
    lab.typing(11, pc, "carol", 1, 5, kpm=60, bs=0.0)
    lab.paste(11, pc, "carol", 30, 3000, 100)
    lab.db.conn.commit()
    score_session(db, 11, v2=False)
    score, reasons, nobs = db.conn.execute("SELECT score, reasons, not_observable FROM scores").fetchone()
    assert score == 0
    assert any("exempt" in x for x in json.loads(nobs))


def test_early_boilerplate_paste_discounted():
    base = dict(ai_flags=0, tamper_flags=0, net_flags=0, blocked_attempts=0, largest_paste=1200, largest_paste_code=True,
                largest_paste_early=True, early_paste_chars=1200, paste_to_typed=0.2, pasted_chars=1200, idle_then_burst=0,
                keys_total=2000, backspace_ratio=0.08, time_outside_ide=0.1, focus_switches_per_min=1, keys_per_min=150,
                burstiness=1)
    early = score_v1(base, mode="test")
    late = score_v1({**base, "largest_paste_early": False, "early_paste_chars": 0}, mode="test")
    assert early.score < late.score
    assert "boilerplate" in early.reasons[0].label


def test_late_large_paste_is_not_discounted_by_small_early_pastes(lab, db):
    lab.session(16, "test")
    pc = lab.pc(16, "G1")
    lab.typing(16, pc, "gus", 1, 50)
    lab.paste(16, pc, "gus", 1, 500, 20)      # two early pastes that add up to the late one ...
    lab.paste(16, pc, "gus", 2, 500, 20)
    lab.paste(16, pc, "gus", 40, 1000, 40)    # ... the largest paste, 35 minutes later
    lab.db.conn.commit()
    f = compute(load_session(db, 16)).iloc[0]
    assert f.early_paste_chars == 1000 and f.largest_paste == 1000 and not f.largest_paste_early
    r = next(r for r in score_v1(f.to_dict(), mode="test").reasons if r.signal == "largest_paste")
    assert r.points == 15 and "early" not in r.label      # used to be halved to 7 and called boilerplate (I-ANALYSIS-8)


def test_idle_gap_label_follows_IDLE_GAP_S(monkeypatch):
    from xg_analysis import scoring
    f = dict(ai_flags=0, tamper_flags=0, net_flags=0, blocked_attempts=0, largest_paste=0, largest_paste_code=False,
             early_paste_chars=0, paste_to_typed=0, pasted_chars=0, idle_then_burst=1, keys_total=2000,
             backspace_ratio=0.08, time_outside_ide=0, focus_switches_per_min=0, keys_per_min=150, burstiness=1)
    label = lambda: next(r.label for r in score_v1(f, mode="test").reasons if r.signal == "idle_then_burst")  # noqa: E731
    assert "after a 2+ minute idle gap" in label()           # IDLE_GAP_S = 120
    monkeypatch.setattr(scoring, "IDLE_GAP_S", 300)
    assert "after a 5+ minute idle gap" in label()
    monkeypatch.setattr(scoring, "IDLE_GAP_S", 90)
    assert "after a 1.5+ minute idle gap" in label()


def test_personal_baseline_z_scores():
    f = dict(ai_flags=0, tamper_flags=0, net_flags=0, blocked_attempts=0, largest_paste=0, largest_paste_code=False,
             early_paste_chars=0, paste_to_typed=0, pasted_chars=0, idle_then_burst=0, keys_total=3000,
             backspace_ratio=0.002, time_outside_ide=0, focus_switches_per_min=0, keys_per_min=420, burstiness=1)
    res = score_v1(f, mode="test", base={"keys_per_min": (150.0, 30.0, 6), "backspace_ratio": (0.08, 0.02, 6)})
    sig = {r.signal for r in res.reasons}
    assert {"z_keys_per_min", "z_backspace_ratio"} <= sig
    # slow typist relative to the cohort but normal for themself: no flag
    calm = score_v1({**f, "keys_per_min": 60, "backspace_ratio": 0.1}, mode="test", base={"keys_per_min": (55.0, 10.0, 6)})
    assert calm.score == 0


def test_v2_isolation_forest_alongside_v1(lab, db):
    lab.session(12, "test")
    for i in range(8):
        pc = lab.pc(12, f"C{i}")
        user = f"u{i}"
        lab.student(100 + i, user)
        lab.typing(12, pc, user, 1, 40, kpm=150 + i * 3, bs=0.07)
    odd = lab.pc(12, "C9")
    lab.student(200, "odd")
    lab.typing(12, odd, "odd", 1, 3, kpm=400, bs=0.0)
    lab.paste(12, odd, "odd", 30, 4000, 120)
    lab.db.conn.commit()
    score_session(db, 12, v2=True)
    v2 = dict(db.conn.execute("SELECT user, score FROM scores WHERE method = 'v2'").fetchall())
    assert len(v2) == 9
    assert max(v2, key=v2.get) == "odd"
    assert db.conn.execute("SELECT count(*) FROM scores WHERE method = 'v1'").fetchone()[0] == 9
    assert v2["odd"] >= 30


def _cohort(n, **over):
    rows = []
    for i in range(n):
        r = {k: 0.0 for k in V2_FEATURES}
        r.update(keys_per_min=150 + (i % 3), backspace_ratio=0.07, burstiness=1.0)
        rows.append(r)
    rows[-1].update(over)
    return pd.DataFrame(rows)


def test_v2_quiet_session_gives_nobody_a_high_score():
    # Per-session min-max used to give the least ordinary student 100 even when nobody stands out (I-ANALYSIS-7).
    scores = [r.score for r in score_v2(_cohort(10))]
    assert max(scores) < 30


def test_v2_high_score_always_keeps_reasons():
    res = score_v2(_cohort(10, largest_paste=4000.0, paste_to_typed=3.0, keys_per_min=400))
    assert res[-1].score >= 30 and res[-1].reasons
    assert all(r.reasons for r in res if r.score >= 30)


def test_v2_scale_is_absolute():
    from xg_analysis.scoring import v2_scale
    assert v2_scale(0.4) == 0 and v2_scale(0.5) == 0 and v2_scale(0.75) == 50 and v2_scale(1.0) == 100


def test_v2_leaves_exempt_students_out(lab, db):
    lab.session(13, "test")
    for i in range(7):
        pc = lab.pc(13, f"D{i}")
        lab.student(300 + i, f"w{i}")
        lab.typing(13, pc, f"w{i}", 1, 40, kpm=150 + i * 3, bs=0.07)
    ex = lab.pc(13, "D9")
    lab.student(400, "dave", exempt="speech-to-text tool")
    lab.typing(13, ex, "dave", 1, 3, kpm=400, bs=0.0)   # extreme behaviour that must not count anywhere
    lab.paste(13, ex, "dave", 30, 4000, 120)
    lab.db.conn.commit()
    score_session(db, 13, v2=True)
    v2 = dict(db.conn.execute("SELECT user, score FROM scores WHERE method = 'v2'").fetchall())
    assert "dave" not in v2 and len(v2) == 7                 # no stored v2 score for the exempt student
    assert db.conn.execute("SELECT count(*) FROM scores WHERE method = 'v1' AND user = 'dave'").fetchone()[0] == 1
    # ... and the cohort is ranked as if dave were not in the session
    f = compute(load_session(db, 13))
    alone = {u: r.score for u, r in zip(f[f.user != "dave"].user, score_v2(f[f.user != "dave"]))}
    assert v2 == alone


def _shared_login_session(lab, second_exempt=None):
    lab.session(14, "test")
    pc = lab.pc(14, "E1")
    other = lab.pc(14, "E2")
    lab.student(500, "alice")
    lab.student(501, "alice", exempt=second_exempt)       # students.login is indexed, not unique
    lab.student(502, "erin")
    lab.typing(14, pc, "alice", 1, 5, kpm=60, bs=0.0)
    lab.paste(14, pc, "alice", 30, 3000, 100)
    lab.typing(14, other, "erin", 1, 30)
    lab.db.conn.commit()


def test_duplicate_login_is_scored_unlinked_with_a_reason(lab, db):
    _shared_login_session(lab)
    out = score_session(db, 14, v2=False)                  # used to raise ValueError (422 for the whole session)
    assert out["scored"] == 2
    assert out["ambiguous"] == [{"pc_id": 1, "user": "alice", "reason": "several_students", "students": 2, "pcs": 1}]
    rows = {r[0]: r for r in db.conn.execute("SELECT user, student_id, score, reasons, not_observable FROM scores")}
    assert rows["erin"][1] == 502                           # the other student is unaffected
    alice = rows["alice"]
    assert alice[1] is None                                 # not linked to either student
    assert any("matches 2 roster students" in x for x in json.loads(alice[4]))
    assert "largest_paste" in {r["signal"] for r in json.loads(alice[3])}


def test_duplicate_login_with_an_exempt_match_ignores_behaviour(lab, db):
    _shared_login_session(lab, second_exempt="speech-to-text tool")
    score_session(db, 14, v2=False)
    score, nobs = db.conn.execute("SELECT score, not_observable FROM scores WHERE user = 'alice'").fetchone()
    assert score == 0
    nobs = json.loads(nobs)
    assert any("exempt" in x for x in nobs)
    assert not any("speech-to-text" in x for x in nobs)    # which student's reason is not shown


class _ReadRecorder(dict):
    """A feature row that records which keys the scoring reads."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read = set()

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.read.add(k)
        return super().get(k, default)


def _computed_feature_columns(feats):
    """Per-student feature columns of compute() (the identity columns left out)."""
    return set(feats.columns) - {"pc_id", "user"}


def test_stored_features_are_exactly_FEATURES(lab, db):
    honest_and_suspicious(lab)
    score_session(db, 10, v2=False)
    for (stored,) in db.conn.execute("SELECT features FROM scores"):
        assert set(json.loads(stored)) == set(FEATURES)
    bob = json.loads(db.conn.execute("SELECT features FROM scores WHERE user = 'bob'").fetchone()[0])
    assert bob["net_flags"] == 0 and bob["ai_flags"] == 1       # net_flags is stored too (I-ANALYSIS-18)


def test_FEATURES_covers_every_computed_and_scored_feature(lab, db):
    honest_and_suspicious(lab)
    feats = compute(load_session(db, 10))
    row = _ReadRecorder({k: 1000.0 for k in _computed_feature_columns(feats)}, largest_paste_code=True)
    score_v1(row, mode="test", base={k: (1.0, 1.0, 5) for k in ("keys_per_min", "backspace_ratio", "burstiness")})
    assert set(V2_FEATURES) <= set(FEATURES)
    assert row.read <= set(FEATURES), f"scored but not stored: {sorted(row.read - set(FEATURES))}"
    assert _computed_feature_columns(feats) == set(FEATURES)


@pytest.fixture
def lists_from(tmp_path, monkeypatch):
    """Point XG_DATA_DIR at a temporary data/ with the given scoring.yaml text (cache cleared around the test)."""
    def use(text: str):
        (tmp_path / "analysis").mkdir(exist_ok=True)
        (tmp_path / "analysis" / "scoring.yaml").write_text(text, encoding="utf-8")
        monkeypatch.setenv("XG_DATA_DIR", str(tmp_path))
        scoring_lists.cache_clear()
    scoring_lists.cache_clear()
    yield use
    scoring_lists.cache_clear()


def test_scoring_lists_come_from_data_yaml():
    scoring_lists.cache_clear()
    lists = scoring_lists()
    assert (data_dir() / "analysis" / "scoring.yaml").is_file()
    assert {"code", "pycharm64", "windowsterminal", "javaw"} <= lists.ide_apps and "firefox" not in lists.ide_apps
    assert {"local_llm", "ai_editor", "extension"} <= lists.ai_categories and "tamper" not in lists.ai_categories


def test_ide_and_ai_lists_are_read_from_XG_DATA_DIR(lab, db, lists_from):
    lab.session(15, "test")
    pc = lab.pc(15, "F1")
    lab.typing(15, pc, "fay", 1, 20)
    lab.event(15, pc, "fay", 0.5, "window_focus", {"app": "MyIDE"})
    lab.alert(15, pc, "fay", 5, "proc.custom", "homegrown_ai")
    lab.alert(15, pc, "fay", 6, "proc.ollama", "local_llm")
    lab.db.conn.commit()
    lists_from("version: 1\nide_apps: [myide]\nai_categories: [homegrown_ai]\n")
    f = compute(load_session(db, 15)).iloc[0]
    assert f.time_outside_ide == 0.0          # MyIDE is an IDE in this file (case-insensitive)
    assert f.ai_flags == 1                    # only homegrown_ai counts; local_llm is not in this file


@pytest.mark.parametrize("text", ["version: 1\nai_categories: [local_llm]\n", "ide_apps: []\nai_categories: [x]\n",
                                  "ide_apps: [code, 3]\nai_categories: [x]\n", "just a string\n", "ide_apps: [code\n"])
def test_broken_scoring_yaml_is_an_error(lists_from, text):
    lists_from(text)
    with pytest.raises(RuntimeError, match="scoring.yaml"):
        scoring_lists()


def test_missing_scoring_yaml_stops_the_service(tmp_path, monkeypatch):
    from xg_analysis import service
    started = []
    monkeypatch.setattr(service, "ThreadingHTTPServer", lambda *a: started.append(a))
    monkeypatch.setenv("XG_DB_URL", "sqlite:///:memory:")
    monkeypatch.setenv("XG_DATA_DIR", str(tmp_path))
    scoring_lists.cache_clear()
    try:
        with pytest.raises(SystemExit, match="scoring.yaml"):
            service.main()
    finally:
        scoring_lists.cache_clear()
    assert started == []


def test_shared_and_generic_logins_are_flagged_not_guessed(lab, db):
    lab.session(21, "test")
    p1, p2, p3, p4 = (lab.pc(21, n) for n in ("L1", "L2", "L3", "L4"))
    lab.student(600, "mia")
    lab.student(601, "noah")
    db.conn.execute("UPDATE session_pcs SET student_id = 601 WHERE pc_id = ?", (p3,))   # CCC-filled column: ignored
    lab.typing(21, p1, "mia", 1, 10)
    lab.typing(21, p2, "LAB\\mia", 20, 10)                  # the same login on a second PC
    lab.typing(21, p3, "student", 1, 30)                     # generic lab account, no roster row
    lab.typing(21, p4, "noah", 1, 30)
    lab.db.conn.commit()
    out = score_session(db, 21, v2=False)
    assert sorted((a["pc_id"], a["reason"]) for a in out["ambiguous"]) == [
        (p1, "shared_login"), (p2, "shared_login"), (p3, "no_student")]
    rows = {r[0]: (r[1], json.loads(r[2])) for r in db.conn.execute("SELECT pc_id, student_id, not_observable FROM scores")}
    assert rows[p1][0] == rows[p2][0] == 600                 # still the one matching student, but flagged
    assert any("used on 2 PCs" in x for x in rows[p1][1]) and any("used on 2 PCs" in x for x in rows[p2][1])
    assert rows[p3][0] is None and any("matches no roster student" in x for x in rows[p3][1])
    assert rows[p4] == (601, rows[p4][1]) and not any(x.startswith("student identity") for x in rows[p4][1])


def test_cli_has_no_research_export():
    # The one research export is the server's ResearchExport (audited, hash-chained audit log; DECISIONS #30).
    with pytest.raises(SystemExit):
        main(["export", "--out", "/tmp/never-written"])
