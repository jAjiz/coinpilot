"""The application's build, served from the API's origin (application spec §2.1).

`/api` belongs to the API: a path under it that no route answers is a JSON 404, whatever
the method, so a client calling a removed route gets an error it can read. Every other path
is the application: a file of the build when one exists, `index.html` otherwise, so a deep
link survives a reload.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Vite names every file under `assets/` after its content: a new build is a new name.
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
# Everything else, `index.html` and the service worker included, is checked on every load,
# so a deploy reaches the browser at once.
CACHE_NONE = "no-cache"
# Scripts from this origin only. Inline styles are allowed: shadcn/ui's Radix primitives and
# its toasts insert `<style>` elements at run time, and a style cannot run code.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

_EVERY_METHOD = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def file_in_build(dist: Path, path: str) -> Path | None:
    """The file of the build `path` names, or None when it names none or leaves the build."""
    root = dist.resolve()
    resolved = (root / path).resolve()
    if resolved.is_file() and resolved.is_relative_to(root):
        return resolved
    return None


def _served(file: Path, cache: str) -> FileResponse:
    return FileResponse(
        file, headers={"Cache-Control": cache, "Content-Security-Policy": CONTENT_SECURITY_POLICY}
    )


def mount_application(app: FastAPI, dist: Path) -> None:
    """Called after every router of the API, so these routes only catch what none answered."""
    root = dist.resolve()
    index = root / "index.html"
    assets = root / "assets"

    # Without it `/api` would fall through to the application, and a POST to an unknown
    # path would meet the application's GET route and answer 405.
    @app.api_route("/api", methods=_EVERY_METHOD, include_in_schema=False)
    @app.api_route("/api/{path:path}", methods=_EVERY_METHOD, include_in_schema=False)
    def no_such_route() -> None:
        raise HTTPException(404)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def application(path: str) -> FileResponse:
        file = file_in_build(root, path)
        if file is None:
            return _served(index, CACHE_NONE)
        return _served(file, CACHE_IMMUTABLE if file.is_relative_to(assets) else CACHE_NONE)
