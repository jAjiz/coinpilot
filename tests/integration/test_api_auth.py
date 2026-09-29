import uuid
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select

from core.db.models import RefreshToken, User
from core.db.types import UserStatus
from core.db.users import create_user, get_user_by_identity, set_user_status
from core.google import code_challenge
from core.tokens import hash_refresh_token


def _start_login(api):
    response = api.get("/auth/login/google", follow_redirects=False)
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)


def _finish_login(api, query, code="the-code"):
    return api.get("/auth/callback/google", params={"code": code, "state": query["state"][0]})


def _sign_in(api):
    response = _finish_login(api, _start_login(api))
    assert response.status_code == 200
    return response.json()


def _refresh(api, token=None):
    """With no token, the browser path: the refresh cookie alone."""
    return api.post("/auth/refresh", json=None if token is None else {"refresh_token": token})


def test_health_needs_no_login(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_login_redirects_to_google_with_pkce_and_remembers_the_state(api):
    query = _start_login(api)

    assert query["code_challenge_method"] == ["S256"]
    assert api.cookies.get("coinpilot_login")


def test_an_unknown_provider_is_not_found(api):
    assert api.get("/auth/login/github", follow_redirects=False).status_code == 404


def test_a_completed_login_creates_the_user_and_returns_both_tokens(
    api, db_session, fake_google, app_context
):
    body = _sign_in(api)

    user = get_user_by_identity(db_session, "google", fake_google.subject)
    assert user.email == fake_google.email
    assert app_context.signer.verify(body["access_token"]) == user.id
    assert body["token_type"] == "bearer"
    assert body["refresh_expires_at"].startswith("2026-10-29T12:00:00")
    stored = db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)).scalar_one()
    assert stored.token_hash == hash_refresh_token(body["refresh_token"])
    assert api.cookies.get("coinpilot_token") == body["access_token"]
    assert api.cookies.get("coinpilot_refresh") == body["refresh_token"]


def test_the_verifier_sent_to_google_matches_the_challenge(api, fake_google):
    query = _start_login(api)
    _finish_login(api, query)

    assert code_challenge(fake_google.token_requests[0]["code_verifier"]) == query["code_challenge"][0]


def test_signing_in_twice_is_one_user(api, db_session, fake_google):
    _sign_in(api)
    _sign_in(api)

    count = db_session.execute(select(func.count()).where(User.subject == fake_google.subject)).scalar_one()
    assert count == 1


def test_a_state_that_does_not_match_is_refused(api, db_session, fake_google):
    """The state is what stops someone else's code being planted in this browser."""
    _start_login(api)

    response = api.get("/auth/callback/google", params={"code": "c", "state": "forged"})

    assert response.status_code == 400
    assert get_user_by_identity(db_session, "google", fake_google.subject) is None


def test_a_callback_with_no_login_started_is_refused(api):
    assert api.get("/auth/callback/google", params={"code": "c", "state": "s"}).status_code == 400


def test_a_login_google_did_not_grant_is_refused(api):
    _start_login(api)

    assert api.get("/auth/callback/google", params={"error": "access_denied"}).status_code == 400


def test_a_code_google_refuses_is_refused(api, fake_google):
    fake_google.refuse_code = True

    assert _finish_login(api, _start_login(api)).status_code == 400


def test_an_unverified_google_email_is_refused(api, db_session, fake_google):
    fake_google.email_verified = False

    assert _finish_login(api, _start_login(api)).status_code == 400
    assert get_user_by_identity(db_session, "google", fake_google.subject) is None


def test_a_refresh_returns_a_new_pair_for_the_same_user(api, app_context):
    signed_in = _sign_in(api)

    response = _refresh(api, signed_in["refresh_token"])

    assert response.status_code == 200
    renewed = response.json()
    assert renewed["refresh_token"] != signed_in["refresh_token"]
    assert renewed["refresh_expires_at"] == signed_in["refresh_expires_at"]
    assert app_context.signer.verify(renewed["access_token"]) == app_context.signer.verify(
        signed_in["access_token"]
    )
    assert api.cookies.get("coinpilot_refresh") == renewed["refresh_token"]


def test_the_refresh_cookie_alone_is_enough(api):
    _sign_in(api)

    assert _refresh(api).status_code == 200


def test_a_reused_refresh_token_ends_the_whole_sign_in(api):
    """The second assertion is the one that matters. It passes only if the revocation was
    committed although the request that made it was refused."""
    first = _sign_in(api)["refresh_token"]
    second = _refresh(api, first).json()["refresh_token"]

    assert _refresh(api, first).status_code == 401
    assert _refresh(api, second).status_code == 401


def test_a_refresh_token_nobody_issued_is_refused(api):
    assert _refresh(api, "never-issued").status_code == 401


def test_a_refresh_with_no_token_at_all_is_refused(api):
    assert _refresh(api).status_code == 401


def test_a_disabled_user_cannot_refresh_and_the_sign_in_is_ended(api, db_session, fake_google):
    token = _sign_in(api)["refresh_token"]
    user = get_user_by_identity(db_session, "google", fake_google.subject)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert _refresh(api, token).status_code == 403

    set_user_status(db_session, user.id, UserStatus.ACTIVE)
    assert _refresh(api, token).status_code == 401


def test_me_answers_to_a_bearer_token(api, make_user, login):
    user = make_user(email="alice@example.test")

    response = api.get("/auth/me", headers=login(user))

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.test"
    assert response.json()["id"] == str(user.id)


def test_me_answers_to_the_cookie_a_login_left(api):
    _sign_in(api)

    assert api.get("/auth/me").status_code == 200


def test_no_token_is_401(api):
    assert api.get("/auth/me").status_code == 401


def test_a_token_that_does_not_verify_is_401(api):
    assert api.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_a_token_for_a_user_that_does_not_exist_is_401(api, app_context):
    token = app_context.signer.issue(uuid.uuid4()).value

    assert api.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_disabled_user_with_a_valid_access_token_is_refused(api, db_session, make_user, login):
    """An access token cannot be revoked. This check makes disabling an account immediate."""
    user = make_user()
    headers = login(user)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert api.get("/auth/me", headers=headers).status_code == 403


def test_a_disabled_user_cannot_sign_in_again(api, db_session, fake_google):
    user = create_user(db_session, provider="google", subject=fake_google.subject, email=fake_google.email)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert _finish_login(api, _start_login(api)).status_code == 403


def test_logout_revokes_the_refresh_token_and_removes_both_cookies(api):
    token = _sign_in(api)["refresh_token"]

    assert api.post("/auth/logout").status_code == 204

    assert api.cookies.get("coinpilot_token") is None
    assert api.cookies.get("coinpilot_refresh") is None
    assert _refresh(api, token).status_code == 401


def test_an_application_logs_out_with_the_token_in_the_body(api):
    token = _sign_in(api)["refresh_token"]
    api.cookies.clear()

    assert api.post("/auth/logout", json={"refresh_token": token}).status_code == 204
    assert _refresh(api, token).status_code == 401


def test_an_access_token_outlives_logout_only_by_its_own_short_life(api):
    """Pinned on purpose. An access token is never looked up, so logout cannot reach it;
    its lifetime, 15 minutes by default, is the bound (spec §15)."""
    access = _sign_in(api)["access_token"]
    api.post("/auth/logout")

    assert api.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200
