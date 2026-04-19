from app.storage import Storage


def test_touch_secret_missing_row_raises_key_error(temp_paths):
    storage = Storage(str(temp_paths / "secrets.db"))
    storage.initialize()
    storage.create_vault("dev")

    try:
        storage.touch_secret("dev", "missing")
    except KeyError as exc:
        assert str(exc) == "'missing'"
    else:
        raise AssertionError("Expected missing secret touch to raise KeyError")


def test_reset_removes_existing_database_file(temp_paths):
    db_path = temp_paths / "secrets.db"
    storage = Storage(str(db_path))
    storage.initialize()

    assert db_path.exists() is True

    storage.reset()

    assert db_path.exists() is False
