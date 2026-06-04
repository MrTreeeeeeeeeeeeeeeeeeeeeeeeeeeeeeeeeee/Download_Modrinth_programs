from modrinth_collection_downloader.auth import mask_token, normalize_token, resolve_token


def test_normalize_token_accepts_supported_forms():
    assert normalize_token("mrp_abc123") == "mrp_abc123"
    assert normalize_token("Authorization: mrp_abc123") == "mrp_abc123"
    assert normalize_token("Bearer mrp_abc123") == "mrp_abc123"
    assert normalize_token("Authorization: Bearer mrp_abc123") == "mrp_abc123"
    assert normalize_token("   ") is None


def test_mask_token_never_returns_full_token():
    assert mask_token("mrp_abcdefghijklmnopqrstuvwxyz") == "mrp_...wxyz"
    assert mask_token(None) == "(none)"


def test_resolve_token_precedence():
    env = {"MODRINTH_TOKEN": "env_token"}

    assert resolve_token(cli_token="cli_token", saved_token="saved_token", env=env).token == "cli_token"
    assert resolve_token(saved_token="saved_token", env=env).token == "env_token"
    assert resolve_token(saved_token="saved_token", env={}).token == "saved_token"
    assert resolve_token(cli_token="cli_token", saved_token="saved_token", env=env, no_token=True).token is None
