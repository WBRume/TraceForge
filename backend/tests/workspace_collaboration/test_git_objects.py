from app.domains.workspace_collaboration.git_objects import GitObjects


def test_export_reuses_existing_mappings_and_only_registers_a_new_git_location(tmp_path, monkeypatch):
    store = GitObjects(tmp_path)
    oid, sha, content = "a" * 40, "b" * 64, "c" * 64
    store.register([("first.git", oid, sha, content, 5)])
    saved, register = [], store.register

    def recording(rows):
        saved.extend(rows)
        register(rows)

    monkeypatch.setattr(store, "register", recording)
    entry = {"git_dir": "first.git", "oid": oid, "size": 5}
    mapped, metrics = store.export([entry])
    assert mapped["first.git", oid] == (sha, content, 5)
    assert metrics == {"hashed_blobs": 0, "hashed_bytes": 0}
    assert saved == []
    moved = {**entry, "git_dir": "second.git"}
    store.export([moved])
    assert saved == [("second.git", oid, sha, content, 5)]
    saved.clear()
    store.export([entry, moved])
    assert saved == []
