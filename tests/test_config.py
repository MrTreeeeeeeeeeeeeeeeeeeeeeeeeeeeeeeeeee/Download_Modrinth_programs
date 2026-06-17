from modrinth_collection_downloader.config import (
    AppConfig,
    forget_token,
    load_config,
    remember_collection,
    remember_download_inputs,
    remember_download_options,
    save_config,
    set_token,
)


def test_missing_config_loads_empty_config(tmp_path):
    config = load_config(tmp_path / "missing.json")

    assert config.last_collection is None
    assert config.last_download_dir is None
    assert config.modrinth_token is None
    assert config.last_download_inputs == {}
    assert config.last_download_options == {}


def test_save_and_load_config_with_folder_and_token(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig(
        last_collection="gRlE8phg",
        last_download_dir="C:/Downloads/Mods",
        modrinth_token="mrp_saved",
        last_download_inputs={
            "start_action": "1",
            "token_option": "4",
            "types": "mod,modpack",
            "minecraft_version": "1.21.1",
            "mod_loaders": "fabric",
            "channels": "release",
            "log_file": "C:/Logs",
        },
        last_download_options={
            "server_required": True,
            "type_subfolders": False,
            "modpack_zip": True,
            "strict_metadata": True,
            "dry_run": True,
        },
        extra={"other": True},
    )

    save_config(config, config_path)
    loaded = load_config(config_path)

    assert loaded.last_collection == "gRlE8phg"
    assert loaded.last_download_dir == "C:/Downloads/Mods"
    assert loaded.modrinth_token == "mrp_saved"
    assert loaded.last_download_inputs == {
        "start_action": "1",
        "token_option": "4",
        "types": "mod,modpack",
        "minecraft_version": "1.21.1",
        "mod_loaders": "fabric",
        "channels": "release",
        "log_file": "C:/Logs",
    }
    assert loaded.last_download_options == {
        "server_required": True,
        "type_subfolders": False,
        "modpack_zip": True,
        "strict_metadata": True,
        "dry_run": True,
    }
    assert loaded.extra == {"other": True}


def test_remember_download_choices_normalizes_supported_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig()

    remember_collection(config, " gRlE8phg ")
    remember_download_inputs(
        config,
        {
            "types": "all",
            "token_option": "4",
            "minecraft_version": "1.21.1",
            "unknown": "ignored",
        },
    )
    remember_download_options(
        config,
        {
            "server_required": True,
            "type_subfolders": False,
            "dry_run": "not-a-bool",
        },
    )
    save_config(config, config_path)
    loaded = load_config(config_path)

    assert loaded.last_collection == "gRlE8phg"
    assert loaded.last_download_inputs == {
        "types": "all",
        "token_option": "4",
        "minecraft_version": "1.21.1",
    }
    assert loaded.last_download_options == {
        "server_required": True,
        "type_subfolders": False,
    }


def test_remember_download_inputs_merges_with_existing_values():
    config = AppConfig(last_download_inputs={"start_action": "1", "token_option": "4"})

    remember_download_inputs(config, {"types": "modpack"})

    assert config.last_download_inputs == {
        "start_action": "1",
        "token_option": "4",
        "types": "modpack",
    }


def test_forget_token_preserves_other_config_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig(
        last_collection="gRlE8phg",
        last_download_dir="C:/Downloads/Mods",
        last_download_inputs={"types": "mod"},
        last_download_options={"dry_run": True},
        extra={"other": True},
    )
    set_token(config, "mrp_saved")
    forget_token(config)
    save_config(config, config_path)

    loaded = load_config(config_path)

    assert loaded.modrinth_token is None
    assert loaded.last_collection == "gRlE8phg"
    assert loaded.last_download_dir == "C:/Downloads/Mods"
    assert loaded.last_download_inputs == {"types": "mod"}
    assert loaded.last_download_options == {"dry_run": True}
    assert loaded.extra == {"other": True}
