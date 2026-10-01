from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[3] / "core" / "db"


def test_no_domain_module_imports_the_facade():
    """The facade points at the domains, never the other way.

    A cycle here would make the import order load-bearing, and the failure would appear
    as an unrelated ImportError much later.
    """
    offenders = [
        path.name
        for path in sorted(DOMAIN_DIR.glob("*.py"))
        if "core.database" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


ROOT = Path(__file__).resolve().parents[3]


def test_nothing_outside_the_exchange_layer_places_an_order_yet():
    """Phase 4 reads a real account and must have no way to spend from it.

    Phase 5 removes this test on purpose, in the commit that adds the order path.
    """
    offenders = [
        str(path.relative_to(ROOT))
        for package in ("api", "core")
        for path in sorted((ROOT / package).rglob("*.py"))
        if "add_order" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
