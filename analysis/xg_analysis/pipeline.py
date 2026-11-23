"""Score a session end-to-end and write the `scores` table."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .db import Db
from .features import FEATURES, baseline, compute, load_session
from .scoring import score_v1, score_v2


def _clean(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def _match_student(students: pd.DataFrame, user: str) -> tuple[pd.Series | None, pd.DataFrame]:
    """Roster rows for this OS login: (the student if exactly one matches, else None; all matches).

    students.login is not unique, so a shared or reused login can match several students (I-ANALYSIS-3)."""
    login = user.split("\\")[-1] if user else ""
    if not login or students.empty:
        return None, students.iloc[0:0]
    matches = students[students.login == login]
    return (matches.iloc[0] if len(matches) == 1 else None), matches


def score_session(db: Db, session_id: int, v2: bool | None = None) -> dict[str, Any]:
    v2 = (os.environ.get("XG_SCORING_V2", "0") == "1") if v2 is None else v2
    sd = load_session(db, session_id)
    feats = compute(sd)
    if feats.empty:
        return {"session_id": session_id, "scored": 0, "flagged": [], "ambiguous": []}
    base = baseline(db, [u for u in feats.user.unique() if u], str(sd.session["starts_at"]), int(sd.session["lab_id"]))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    linked = []   # the matched student per feature row (None = no or several roster matches)
    cohort = []   # v2 rows: exempt students' behaviour is ignored, so they are not in the cohort (I-ANALYSIS-2)
    ambiguous = []
    for _, f in feats.iterrows():
        st, matches = _match_student(sd.students, f.user)
        b = {}
        if not base.empty and f.user in base.index:
            for feat in ("keys_per_min", "backspace_ratio", "burstiness"):
                b[feat] = (base.loc[f.user, (feat, "mean")], base.loc[f.user, (feat, "std")], int(base.loc[f.user, (feat, "count")]))
        if st is not None:
            exempt = (st.exempt_reason or "accommodation") if bool(st.exempt) else None
        else:
            # Ambiguous login: if any candidate is exempt, ignore behaviour (never apply it to an exempt
            # student), without saying which student or why.
            exempt = "a roster student with this login is exempt" if matches.exempt.astype(bool).any() else None
        res = score_v1(f.to_dict(), mode=sd.session["mode"], base=b, caps=sd.caps.get(int(f.pc_id), {}), exempt=exempt)
        if len(matches) > 1:
            res.not_observable.insert(0, f"student identity: OS login {f.user!r} matches {len(matches)} roster "
                                         "students; score not linked to a student")
            ambiguous.append({"pc_id": int(f.pc_id), "user": f.user, "students": len(matches)})
        rows.append(("v1", f, st, res))
        linked.append(st)
        cohort.append(exempt is None)
    if v2:
        members = [(f, st) for (_, f), st, keep in zip(feats.iterrows(), linked, cohort) if keep]
        for (f, st), res in zip(members, score_v2(feats[cohort])):
            rows.append(("v2", f, st, res))

    with db.transaction():
        db.execute("DELETE FROM scores WHERE lab_session_id = ?", (session_id,))
        for method, f, st, res in rows:
            feat_json = {k: _clean(f[k]) for k in FEATURES if k in f}
            db.execute(
                "INSERT INTO scores (lab_session_id, pc_id, student_id, `user`, method, score, confidence, reasons, features, "
                "not_observable, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, int(f.pc_id), int(st.student_id) if st is not None else None, f.user or None, method,
                 int(res.score), res.confidence, json.dumps([r.as_dict() for r in res.reasons]), json.dumps(feat_json),
                 json.dumps(res.not_observable), now, now))
    flagged = [{"pc_id": int(f.pc_id), "user": f.user, "score": res.score, "confidence": res.confidence}
               for m, f, _, res in rows if m == "v1" and res.score >= 30]
    return {"session_id": session_id, "scored": sum(1 for r in rows if r[0] == "v1"), "flagged": flagged,
            "ambiguous": ambiguous}
