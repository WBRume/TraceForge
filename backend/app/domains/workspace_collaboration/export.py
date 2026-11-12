"""Package selected immutable task files using their original relative paths."""

import re
from tempfile import SpooledTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field

from . import content


class ExportFile(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExportRequest(BaseModel):
    files: list[ExportFile] = Field(min_length=1, max_length=10_000)


def archive(store: content.ObjectStore, files: list[ExportFile]):
    paths = set()
    directories = set()
    for file in files:
        path = content.validate_path(file.path)
        if re.search(r'[<>|?*"\x00-\x1f]', path):
            raise ValueError("Unsupported ZIP member name")
        parts = path.casefold().split("/")
        folded = "/".join(parts)
        if folded in paths:
            raise ValueError("Duplicate ZIP member name")
        paths.add(folded)
        directories.update("/".join(parts[:n]) for n in range(1, len(parts)))
    if paths & directories:
        raise ValueError("ZIP member names collide with directories")
    known = store.git_objects.known(list({file.sha256 for file in files}))
    if any(file.sha256 not in known for file in files):
        raise FileNotFoundError("A selected task file is unavailable")
    if sum(known[file.sha256][2] for file in files) > content.MAX_MANIFEST_BYTES:
        raise OverflowError("Selected task files exceed the 512 MiB export limit")

    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115 - closed by the response
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
            batch = {}
            size = 0
            for file in files:
                item = known[file.sha256]
                batch.setdefault(file.sha256, []).append(file.path)
                size += item[2]
                if size >= 8 * 1024 * 1024 or len(batch) >= 250:
                    _write_batch(archive, store, known, batch)
                    batch, size = {}, 0
            _write_batch(archive, store, known, batch)
        output.seek(0)
    except BaseException:
        output.close()
        raise
    return output


def _write_batch(archive, store, known, paths) -> None:
    for sha, raw in store.git_objects.read_many({sha: known[sha] for sha in paths}).items():
        for path in paths[sha]:
            archive.writestr(path, raw)
