from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only. It touches neither the database nor Kraken."""
    return {"status": "ok"}
