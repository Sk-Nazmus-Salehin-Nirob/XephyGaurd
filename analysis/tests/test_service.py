from xg_analysis.service import authorized


def test_score_endpoint_accepts_only_the_analysis_token(monkeypatch):
    monkeypatch.setenv("XG_ANALYSIS_TOKEN", "analysis-token-1234")
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "internal-token-5678")
    assert authorized("Bearer analysis-token-1234")
    assert not authorized("Bearer internal-token-5678")   # the proxy's token (I-ANALYSIS-17)
    assert not authorized("Bearer ")
    assert not authorized("")


def test_unset_analysis_token_refuses_everyone(monkeypatch):
    monkeypatch.delenv("XG_ANALYSIS_TOKEN", raising=False)
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "internal-token-5678")
    assert not authorized("Bearer internal-token-5678")
    assert not authorized("Bearer ")
