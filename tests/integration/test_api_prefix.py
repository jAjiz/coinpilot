"""Every route of the platform answers under `/api` (application spec §2.1)."""


def test_health_answers_under_the_prefix(api):
    assert api.get("/api/health").json() == {"status": "ok"}


def test_nothing_answers_at_the_old_paths(api):
    assert api.get("/health").status_code == 404
    assert api.get("/auth/login/google", follow_redirects=False).status_code == 404


def test_the_openapi_document_moves_with_the_api(api):
    paths = api.get("/api/openapi.json").json()["paths"]
    assert "/api/portfolio" in paths and "/portfolio" not in paths
    assert api.get("/api/docs").status_code == 200


def test_the_login_cookie_is_scoped_to_the_callback(api):
    response = api.get("/api/auth/login/google", follow_redirects=False)
    assert "Path=/api/auth/callback" in response.headers["set-cookie"]
