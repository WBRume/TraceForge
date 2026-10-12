"""Version-fenced transport patches; full immutable snapshots remain the recovery source."""

from .content import validate_path


def between(base: dict, target: dict) -> dict:
    if (base["task_id"], base["repository_set_digest"]) != (target["task_id"], target["repository_set_digest"]):
        return target
    old = {repo["task_repository_id"]: repo for repo in base["repositories"]}
    repositories = []
    for repo in target["repositories"]:
        previous = {file["path"]: file for file in old[repo["task_repository_id"]]["files"]}
        current = {file["path"]: file for file in repo["files"]}
        repositories.append(
            {
                **repo,
                "files": [file for name, file in current.items() if previous.get(name) != file],
                "deleted": sorted(previous.keys() - current.keys()),
            }
        )
    return {**target, "delta": {"base_snapshot_id": base["snapshot_id"]}, "repositories": repositories}


def expand(base: dict, incoming: dict) -> dict:
    header = incoming.get("delta")
    if not header:
        if any(repo.get("deleted") for repo in incoming["repositories"]):
            raise ValueError("Deleted paths require a delta base")
        return {
            key: (
                [{k: v for k, v in repo.items() if k != "deleted"} for repo in value]
                if key == "repositories"
                else value
            )
            for key, value in incoming.items()
            if key != "delta"
        }
    if (header["base_snapshot_id"], incoming["task_id"], incoming["repository_set_digest"]) != (
        base["snapshot_id"],
        base["task_id"],
        base["repository_set_digest"],
    ):
        raise ValueError("COLLABORATION_DELTA_BASE_MISMATCH")
    old = {repo["task_repository_id"]: repo for repo in base["repositories"]}
    seen, repositories = set(), []
    for repo in incoming["repositories"]:
        previous = old.get(repo["task_repository_id"])
        if (
            not previous
            or repo["task_repository_id"] in seen
            or any(repo.get(key) != previous.get(key) for key in previous if key != "files")
        ):
            raise ValueError("COLLABORATION_DELTA_REPOSITORY_MISMATCH")
        seen.add(repo["task_repository_id"])
        files = {file["path"]: file for file in previous["files"]}
        touched = set()
        for name in repo.get("deleted", []):
            validate_path(name)
            if name in touched or name not in files:
                raise ValueError("COLLABORATION_DELTA_PATH_MISMATCH")
            touched.add(name)
            del files[name]
        for file in repo["files"]:
            validate_path(file["path"])
            if file["path"] in touched:
                raise ValueError("COLLABORATION_DELTA_PATH_MISMATCH")
            touched.add(file["path"])
            files[file["path"]] = file
        repositories.append(
            {**{k: v for k, v in repo.items() if k not in {"files", "deleted"}}, "files": list(files.values())}
        )
    if seen != old.keys():
        raise ValueError("COLLABORATION_DELTA_REPOSITORY_MISMATCH")
    return {**{k: v for k, v in incoming.items() if k != "delta"}, "repositories": repositories}
