import pytest

from codeask.ingest import content_hash, parse_github_url, validate_ref
from codeask.search import first_rank


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/pallets/itsdangerous", ("pallets", "itsdangerous")),
    ("https://github.com/pallets/itsdangerous.git", ("pallets", "itsdangerous")),
    ("https://github.com/pallets/itsdangerous/", ("pallets", "itsdangerous")),
    ("https://github.com/psf/requests", ("psf", "requests")),
    ("https://github.com/umarjaved204/TableTalk", ("umarjaved204", "TableTalk")),
    ("https://github.com/a-b/x.y_z", ("a-b", "x.y_z")),
])
def test_accepts_github_https_urls(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://github.com/pallets/itsdangerous",  # not https
    "https://gitlab.com/pallets/itsdangerous",
    "git@github.com:pallets/itsdangerous.git",  # ssh
    "file:///C:/Users/me/secret-repo",
    "https://github.com/pallets",  # no repo
    "https://github.com/pallets/itsdangerous/tree/main",  # extra path
    "https://github.com/-bad/repo",  # owner can't start with "-"
    "https://github.com/pallets/..",
    "--upload-pack=calc.exe",
    "https://github.com/pallets/itsdangerous --upload-pack=x",
])
def test_rejects_everything_else(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


@pytest.mark.parametrize("ref", [
    "0123456789abcdef0123456789abcdef01234567",  # full SHA
    "main", "v2.2.0", "release/2.x", "abc123",  # names (a short SHA is just a name to git)
])
def test_valid_refs(ref):
    assert validate_ref(ref) == ref


@pytest.mark.parametrize("ref", [
    "-x", "--upload-pack=x",  # would be read as git options
    "main..dev", "a b", "branch.lock", "x/", "", "/main", "a;rm -rf", "x" * 101,
])
def test_invalid_refs(ref):
    with pytest.raises(ValueError):
        validate_ref(ref)


def test_content_hash_depends_on_space_and_text():
    a = content_hash("voyage-code-3:1024:document", "def f(): pass")
    assert a == content_hash("voyage-code-3:1024:document", "def f(): pass")
    assert a != content_hash("voyage-code-3:1024:document", "def g(): pass")
    assert a != content_hash("gemini:768:document", "def f(): pass")  # spaces never collide
    assert len(a) == 64


def test_first_rank():
    rows = [{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}]
    assert first_rank(rows, ["b.py"]) == 2
    assert first_rank(rows, ["c.py", "a.py"]) == 1
    assert first_rank(rows, ["z.py"]) is None
