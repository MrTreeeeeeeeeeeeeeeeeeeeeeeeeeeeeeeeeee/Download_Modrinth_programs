from modrinth_collection_downloader.config import (
    AppConfig,
    forget_token,
    load_config,
    save_config,
    set_token,
)


def test_missing_config_loads_empty_config(tmp_path):
    config = load_config(tmp_path / "missing.json")

    assert config.last_download_dir is None
    assert config.modrinth_token is None


def test_save_and_load_config_with_folder_and_token(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig(
        last_download_dir="C:/Downloads/Mods",
        modrinth_token="mrp_saved",
        extra={"other": True},
    )

    save_config(config, config_path)
    loaded = load_config(config_path)

    assert loaded.last_download_dir == "C:/Downloads/Mods"
    assert loaded.modrinth_token == "mrp_saved"
    assert loaded.extra == {"other": True}


def test_forget_token_preserves_other_config_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig(last_download_dir="C:/Downloads/Mods", extra={"other": True})
    set_token(config, "mrp_saved")
    forget_token(config)
    save_config(config, config_path)

    loaded = load_config(config_path)

    assert loaded.modrinth_token is None
    assert loaded.last_download_dir == "C:/Downloads/Mods"
    assert loaded.extra == {"other": True}
