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
