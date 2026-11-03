"""API and static-serving tests."""

from __future__ import annotations

from dataclasses import replace

from server.app import create_app
from server.ontology import OntologyStore
from tests.conftest import FAKE_KEY, FakeLLM


def test_health(client_factory):
    response = client_factory().get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_reports_rules_mode_without_key(client_factory):
    response = client_factory().get("/api/agent/status")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules"
    assert data["llm"]["configured"] is False
    assert data["llm"]["model"] is None
    assert data["limits"]["maxQuestionChars"] == 500
    assert len(data["companies"]) >= 4
    assert {
        "company-huachen",
        "company-ningyuan",
        "company-jingkang",
        "company-st-demo",
    } <= {item["id"] for item in data["companies"]}
    assert "keyHandling" in data


def test_status_never_returns_key(client_factory):
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=FakeLLM())
    response = client.get("/api/agent/status")
    assert response.status_code == 200
    assert response.json()["llm"]["configured"] is True
    assert FAKE_KEY not in response.text
    assert "Authorization" not in response.text


def test_company_analysis_rules_mode(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    assert response.headers["x-agent-mode"] == "rules"
    data = response.json()
    assert data["mode"] == "rules"
    assert data["summary"]["recommendation"] == "增持"
    assert "华辰智造" in data["answer"]
    assert "R01" in data["answer"]
    assert "R06" in data["answer"]
    assert "不构成投资建议" in data["answer"]
    assert data["steps"][0]["tool"] == "get_company_analysis"
    assert any(item["kind"] == "individual" for item in data["citations"])
    assert any(item["kind"] == "rule" for item in data["citations"])


def test_unknown_company_lists_available(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "分析贵州茅台"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules"
    assert "没有找到" in data["answer"] or "没有找到对应公司" in data["answer"]
    assert "华辰智造" in data["answer"]


def test_screen_value_candidates(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "哪些公司是价值候选？"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "screen_companies"
    assert "华辰智造" in data["answer"]
    assert "R01" in data["answer"]
    assert "宁源新能源" in data["answer"]


def test_portfolio_analysis(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "组合的集中度风险如何？"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "get_portfolio_analysis"
    assert "12.0%" in data["answer"]
    assert "R06" in data["answer"]


def test_rule_explanation(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "R02 是什么规则？"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "get_rule"
    assert "高财务风险" in data["answer"]
    assert "70" in data["answer"]
    assert "示例 ST 公司" in data["answer"]


def test_invalid_rule_is_reported(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "R99 是什么规则？"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "get_rule"
    assert "R99" in data["answer"]
    assert "R01" in data["answer"]


def test_policy_analysis(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "ODRL 政策有哪些？"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "get_policies"
    assert "policy-decision-use" in data["answer"]
    assert "人工批准" not in data["answer"] or "订单意图" in data["answer"]


def test_search_term(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "解释价值候选"})
    assert response.status_code == 200
    data = response.json()
    assert data["steps"][0]["tool"] == "search_ontology"
    assert "价值候选" in data["answer"]
    assert "R01" in data["answer"]


def test_empty_question(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_question"


def test_invalid_question_type(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": 123})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_question_too_long(client_factory):
    response = client_factory().post("/api/agent/analyze", json={"question": "龙" * 501})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "question_too_long"


def test_request_body_too_large(client_factory):
    client = client_factory({"max_request_bytes": 1_500})
    response = client.post(
        "/api/agent/analyze",
        json={"question": "分析华辰智造", "history": [{"role": "user", "content": "x" * 3000}]},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_rate_limit_per_minute(client_factory):
    client = client_factory({"rate_limit_per_minute": 2, "rate_limit_per_hour": 100, "daily_request_budget": 100})
    first = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    second = client.post("/api/agent/analyze", json={"question": "分析宁源新能源"})
    third = client.post("/api/agent/analyze", json={"question": "分析景康生物"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("retry-after")
    assert third.json()["error"]["code"] == "rate_limited"


def test_daily_budget(client_factory):
    client = client_factory(
        {"rate_limit_per_minute": 100, "rate_limit_per_hour": 100, "daily_request_budget": 1}
    )
    first = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    second = client.post("/api/agent/analyze", json={"question": "分析宁源新能源"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_cors_allows_configured_origin(client_factory):
    client = client_factory()
    response = client.options(
        "/api/agent/analyze",
        headers={
            "Origin": "https://beiluo.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://beiluo.github.io"


def test_cors_headers_on_actual_post(client_factory):
    client = client_factory()
    response = client.post(
        "/api/agent/analyze",
        json={"question": "分析华辰智造"},
        headers={"Origin": "https://beiluo.github.io"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://beiluo.github.io"


def test_cors_does_not_allow_unknown_origin(client_factory):
    client = client_factory()
    response = client.options(
        "/api/agent/analyze",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


def test_static_page_and_assets(client_factory):
    client = client_factory()
    assert client.get("/").status_code == 200
    assert client.get("/index.html").status_code == 200
    assert client.get("/assets/js/agent.js").status_code == 200
    assert client.get("/assets/js/agent-config.js").status_code == 200
    assert client.get("/ontology/a-share.ttl").status_code == 200
    assert client.get("/docs/design.md").status_code == 200


def test_static_server_does_not_expose_secrets(client_factory):
    client = client_factory()
    for path in ("/.env", "/server/settings.py", "/server/app.py", "/requirements.txt", "/.git/config"):
        assert client.get(path).status_code == 404, path


def test_static_server_ignores_a_local_env_file(tmp_path, store: OntologyStore, base_settings):
    (tmp_path / "assets" / "js").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (tmp_path / "assets" / "js" / "agent.js").write_text("// public", encoding="utf-8")
    (tmp_path / ".env").write_text("LLM_API_KEY=not-a-real-key\n", encoding="utf-8")
    app = create_app(
        settings=replace(base_settings, root=tmp_path, llm_api_key=""),
        store=store,
    )
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/assets/js/agent.js").status_code == 200
    assert client.get("/.env").status_code == 404


def test_security_headers(client_factory):
    client = client_factory()
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers.get("x-request-id")


def test_analyze_response_never_contains_key(client_factory):
    client = client_factory({"llm_api_key": FAKE_KEY}, llm=FakeLLM())
    response = client.post("/api/agent/analyze", json={"question": "分析华辰智造"})
    assert response.status_code == 200
    assert FAKE_KEY not in response.text
    assert "Authorization" not in response.text
