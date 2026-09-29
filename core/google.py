"""Sign-in with Google: the authorization code flow with PKCE.

Two requests after the redirect: the code for an access token, and the access token for
the user's identity. The identity is the `sub` claim, which Google never reassigns; the
email is kept for display only and must be verified.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from core.config import GoogleConfig
from core.tokens import LoginState

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email"


class GoogleLoginFailed(Exception):
    """The login did not produce an identity. The message is safe to show."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str


def new_login() -> LoginState:
    # 64 bytes of randomness encode to 86 characters, inside PKCE's 43 to 128.
    return LoginState(state=secrets.token_urlsafe(32), verifier=secrets.token_urlsafe(64))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(config: GoogleConfig, login: LoginState) -> str:
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": login.state,
        "code_challenge": code_challenge(login.verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def exchange_code(http: httpx.Client, config: GoogleConfig, code: str, verifier: str) -> GoogleIdentity:
    try:
        token = http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if token.status_code != 200:
            raise GoogleLoginFailed("google refused the authorization code")
        access = token.json().get("access_token")
        if not access:
            raise GoogleLoginFailed("google returned no access token")

        userinfo = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
        if userinfo.status_code != 200:
            raise GoogleLoginFailed("google did not return the account")
        body = userinfo.json()
    except httpx.HTTPError:
        raise GoogleLoginFailed("google could not be reached") from None
    except ValueError:
        raise GoogleLoginFailed("google returned something that is not JSON") from None

    subject = body.get("sub")
    email = body.get("email")
    if not subject or not email:
        raise GoogleLoginFailed("google returned no account id or email")
    if body.get("email_verified") is not True:
        raise GoogleLoginFailed("the google account has no verified email")
    return GoogleIdentity(subject=str(subject), email=str(email))
