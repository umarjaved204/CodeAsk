def test_package_imports():
    # Proves the editable install works: pytest from the repo root can import codeask.
    import codeask

    assert codeask.__doc__
