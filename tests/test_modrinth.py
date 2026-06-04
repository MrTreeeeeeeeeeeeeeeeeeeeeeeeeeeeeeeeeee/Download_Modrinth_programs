import pytest

from modrinth_collection_downloader.modrinth import ModrinthClient, parse_collection_id


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = {} if data is None else data
        self.status_code = status_code
        self.headers = {}
        self.text = ""

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({})


def test_parse_collection_id_from_supported_inputs():
    assert parse_collection_id("gRlE8phg") == "gRlE8phg"
    assert parse_collection_id("https://modrinth.com/collection/gRlE8phg") == "gRlE8phg"
    assert parse_collection_id("https://modrinth.com/collection/gRlE8phg/mods") == "gRlE8phg"
    assert parse_collection_id("https://modrinth.com/collection/gRlE8phg/mods?x=1") == "gRlE8phg"


@pytest.mark.parametrize("value", ["", "https://modrinth.com/project/sodium", "../bad"])
def test_parse_collection_id_rejects_invalid_inputs(value):
    with pytest.raises(ValueError):
        parse_collection_id(value)


def test_authorization_header_is_included_when_token_exists():
    session = FakeSession()
    client = ModrinthClient(token="mrp_saved", session=session)

    client.get_json("https://example.test")

    headers = session.calls[0][2]["headers"]
    assert headers["Authorization"] == "mrp_saved"
    assert "User-Agent" in headers


def test_authorization_header_is_omitted_without_token():
    session = FakeSession()
    client = ModrinthClient(session=session)

    client.get_json("https://example.test")

    headers = session.calls[0][2]["headers"]
    assert "Authorization" not in headers
