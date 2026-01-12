from app.integrations.state import add_notified, load_state, prune_known, save_state


def test_state_store_roundtrip(tmp_path) -> None:
    path = tmp_path / "notified.json"
    state = load_state(str(path))
    add_notified(state, {"https://example.com/a"}, "source1")
    save_state(str(path), state)

    loaded = load_state(str(path))
    assert "https://example.com/a" in loaded["notified"]

    prune_known(loaded, {"https://example.com/a"})
    assert loaded["notified"] == {}
