"""Review batches retain per-version modes and never transfer oversized blobs."""

from app.domains.task.services.repository_updates import git


def test_review_reads_duplicate_binary_and_large_versions_in_bounded_batches(tmp_path, monkeypatch):
    git.git(tmp_path, "init")
    payloads = {
        "empty": b"",
        "text": "文本\nline\n".encode(),
        "binary": b"\xff\0\n",
        "large": b"x" * (2 * 1024 * 1024 + 1),
    }
    entries = {
        side: {"mode": "100644", "oid": git.git(tmp_path, "hash-object", "-w", "--stdin", data=data)}
        for side, data in payloads.items()
    }
    entries.update(
        duplicate={**entries["text"], "mode": "100755"},
        symlink={**entries["text"], "mode": "120000"},
        submodule={"mode": "160000", "oid": "a" * 40},
        absent=None,
    )
    original, calls = git.command, []

    def measured(root, *args, **kwargs):
        calls.append((args, kwargs.get("data")))
        return original(root, *args, **kwargs)

    monkeypatch.setattr(git, "command", measured)
    actual = git.read_versions(tmp_path, entries)
    assert actual["text"]["text"] == payloads["text"].decode()
    assert actual["empty"] == {"exists": True, "text": "", "binary": False, "mode": "100644"}
    assert actual["binary"]["binary"] and actual["binary"]["text"] == ""
    assert actual["large"]["binary"] and actual["large"]["text"] == ""
    assert actual["duplicate"]["mode"] == "100755" and actual["duplicate"]["text"] == actual["text"]["text"]
    assert actual["symlink"]["mode"] == "120000"
    assert actual["submodule"]["text"] == "a" * 40 and actual["submodule"]["binary"]
    assert not actual["absent"]["exists"]
    assert len(calls) == 2
    requested = calls[1][1].decode().splitlines()
    assert entries["large"]["oid"] not in requested
    assert requested.count(entries["text"]["oid"]) == 1
