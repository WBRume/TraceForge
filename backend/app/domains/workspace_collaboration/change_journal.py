"""Native filesystem events are path hints; a witnessed barrier fences each drain.

Never replace an unavailable native watcher with polling. Loss, restart or a
barrier timeout invalidates the cached cut and requests a full Git inventory.
"""

from __future__ import annotations

import atexit
import re
import threading
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

from watchfiles import watch


class Journal:
    def __init__(self, root: Path):
        self.root = root
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.paths: dict[str, set[int]] = {}
        self.failed = False
        self.barriers: dict[str, threading.Event] = {}
        self.thread = threading.Thread(target=self._watch, daemon=True, name="collaboration-paths")
        self.thread.start()
        if not self.ready.wait(2):
            self.failed = True

    def _watch(self):
        try:
            for events in watch(
                self.root,
                watch_filter=None,
                force_polling=False,
                debounce=20,
                step=5,
                rust_timeout=50,
                yield_on_timeout=True,
                stop_event=self.stop,
            ):
                with self.lock:
                    completed = []
                    for kind, raw in events:
                        relative = Path(raw).relative_to(self.root).as_posix()
                        if relative == ".":
                            if int(kind) != 2:
                                self.failed = True
                            continue
                        if ".git/" in relative:
                            control = relative.split(".git/", 1)[1]
                            if not re.fullmatch(r"HEAD|index|config|packed-refs|refs/.*|info/exclude", control):
                                continue
                        if relative.startswith(".traceforge-sync-barrier-"):
                            if relative in self.barriers:
                                completed.append(self.barriers[relative])
                        elif not any(p.startswith(".traceforge-sync") for p in relative.split("/")):
                            self.paths.setdefault(relative, set()).add(int(kind))
                            if len(self.paths) > 100000:
                                self.failed = True
                    for event in completed:
                        event.set()
                self.ready.set()
        except Exception:
            self.failed = True
            self.ready.set()

    def drain(self) -> dict[str, set[int]] | None:
        if self.failed or not self.thread.is_alive():
            return None
        name = ".traceforge-sync-barrier-" + str(uuid4())
        event = threading.Event()
        with self.lock:
            self.barriers[name] = event
        try:
            (self.root / name).touch(exist_ok=False)
            if not event.wait(1):
                self.failed = True
                return None
            with self.lock:
                paths, self.paths = self.paths, {}
                return paths if not self.failed else None
        finally:
            with self.lock:
                self.barriers.pop(name, None)
            (self.root / name).unlink(missing_ok=True)

    def close(self):
        self.stop.set()


class CachedCut:
    def __init__(self, root: Path, identity: str):
        self.journal = Journal(root)
        self.identity = identity
        self.payload: dict | None = None
        self.repositories: list[dict] | None = None


_cuts: OrderedDict[str, CachedCut] = OrderedDict()
_lock = threading.Lock()


def get(root: Path, identity: str) -> CachedCut:
    key = str(root)
    with _lock:
        saved = _cuts.pop(key, None)
        if saved and (saved.identity != identity or saved.journal.failed):
            saved.journal.close()
            saved = None
        saved = saved or CachedCut(root, identity)
        _cuts[key] = saved
        while len(_cuts) > 32:
            _, expired = _cuts.popitem(last=False)
            expired.journal.close()
        return saved


@atexit.register
def close_all():
    with _lock:
        for saved in _cuts.values():
            saved.journal.close()
        _cuts.clear()
