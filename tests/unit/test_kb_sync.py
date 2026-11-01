from scripts.kb_sync import (
    load_client_map,
    normalize_client,
    resolve_shard,
    strip_html_and_decode,
    validate_actions,
)


def client_map():
    return {
        "default_shard": "generic_other",
        "refuse_upload_at": 195,
        "shards": [
            {"shard_id": "comanche", "client_keys": ["comanche"], "aliases": ["Comanche"], "folder_id": None, "active": True, "article_count": 0},
            {"shard_id": "generic_other", "client_keys": ["generic_other"], "aliases": ["Managed Services"], "folder_id": None, "active": True, "article_count": 0},
        ],
    }


def test_normalize_client_key():
    assert normalize_client("Marin General - Ambulatory") == "marin_general_ambulatory"


def test_strip_html_decodes_entities_and_preserves_image_alt():
    assert strip_html_and_decode("<ul><li>Hello &amp; goodbye</li></ul><img alt='diagram' src='x'>") == "- Hello & goodbye\ndiagram"


def test_resolve_alias_and_unknown_fallback():
    mapped = client_map()
    assert resolve_shard("Comanche", mapped)["shard_id"] == "comanche"
    assert resolve_shard("Unknown Client", mapped)["shard_id"] == "generic_other"
    assert resolve_shard("Unknown Client", mapped)["fallback"] is True


def test_unmapped_clients_are_rejected_when_no_default():
    mapped = {"default_shard": "missing", "shards": []}
    result = validate_actions([{"action": "upload", "client_key": "Unknown"}], mapped)
    assert result["ok"] is False
    assert result["errors"] == ["Unmapped client"]


def test_republished_article_is_planned_as_upload():
    mapped = client_map()
    result = validate_actions([
        {"action": "upload", "client_key": "Comanche", "was_retired": True},
    ], mapped)
    assert result["ok"] is True
    assert result["planned"][0]["action"] == "upload"


def test_client_change_plans_old_and_new_shards():
    mapped = client_map()
    result = validate_actions([
        {"action": "replace", "old_client_key": "Comanche", "client_key": "Managed Services"},
    ], mapped)
    assert result["ok"] is True
    assert result["planned"][0]["old_shard_id"] == "comanche"
    assert result["planned"][0]["shard_id"] == "generic_other"


def test_capacity_refuses_upload():
    mapped = client_map()
    mapped["shards"][0]["article_count"] = 195
    result = validate_actions([{"action": "upload", "client_key": "Comanche"}], mapped)
    assert result["ok"] is False
    assert result["errors"] == ["Shard refuses upload at configured capacity"]


def test_repository_client_map_loads():
    mapped = load_client_map("flows/power-automate/kb-sync/client-map.json")
    assert len(mapped["shards"]) == 12
