"""The application's build, served from the API's origin (application spec §2.1)."""

from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.web import CACHE_IMMUTABLE, CONTENT_SECURITY_POLICY, file_in_build


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc.js").write_text("console.log('app')")
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    return tmp_path


@pytest.fixture
def web(make_context, dist):
    return TestClient(create_app(make_context(nullcontext), web_dist=dist))


@pytest.fixture
def api_without_web(make_context):
    return TestClient(create_app(make_context(nullcontext)))


def test_a_deep_link_gets_the_application(web):
    response = web.get("/settings")

    assert response.text == "<html>app</html>" and response.headers["cache-control"] == "no-cache"


def test_the_root_gets_the_application(web):
    assert web.get("/").text == "<html>app</html>"


def test_a_hashed_asset_is_cached_for_a_year(web):
    assert web.get("/assets/index-abc.js").headers["cache-control"] == CACHE_IMMUTABLE


def test_an_unhashed_file_is_not_cached(web):
    response = web.get("/sw.js")

    assert response.text.startswith("self.") and response.headers["cache-control"] == "no-cache"


def test_the_application_carries_the_security_policy(web):
    assert web.get("/").headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/api", "/api/", "/api/nothing-here"])
def test_an_unknown_api_path_is_a_json_404(web, method, path):
    response = web.request(method, path)

    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}


def test_the_api_keeps_answering(web):
    response = web.get("/api/health")

    assert response.json() == {"status": "ok"}
    assert "content-security-policy" not in response.headers


def test_the_application_is_not_in_the_api_document(web):
    paths = web.get("/api/openapi.json").json()["paths"]

    assert all(path.startswith("/api/") for path in paths) and "/api/{path}" not in paths


# The client normalises `..` before it sends a request, so the guard is tested on the
# function that applies it, not through HTTP.
@pytest.mark.parametrize("path", ["../secret.txt", "assets/../../secret.txt", "/etc/passwd", ""])
def test_nothing_outside_the_build_is_resolved(tmp_path, path):
    build = tmp_path / "dist"
    build.mkdir()
    (tmp_path / "secret.txt").write_text("secret")

    assert file_in_build(build, path) is None


def test_a_file_of_the_build_is_resolved(dist):
    assert file_in_build(dist, "sw.js") == (dist / "sw.js").resolve()


def test_without_a_build_nothing_but_the_api_answers(api_without_web):
    assert api_without_web.get("/settings").status_code == 404
    assert api_without_web.get("/api/health").json() == {"status": "ok"}
