"""Smoke test: the package layout is importable as installed."""


def test_package_imports() -> None:
    import voicebench

    assert voicebench.__name__ == "voicebench"
