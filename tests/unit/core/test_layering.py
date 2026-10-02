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


EXECUTOR = ROOT / "core" / "execution.py"


def test_only_the_executor_places_an_order():
    """Phase 5 adds the order path, in one module. A second caller of `add_order` would be
    a second place money leaves from, with its own idea of the unknown-result protocol."""
    offenders = [
        str(path.relative_to(ROOT))
        for package in ("api", "core")
        for path in sorted((ROOT / package).rglob("*.py"))
        if path != EXECUTOR and "add_order" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
