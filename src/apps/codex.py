"""Synchronize portable Codex settings while keeping excluded fields local."""

from collections.abc import Mapping
from fnmatch import fnmatchcase

import tomlkit

from ..config import path
from .base import App, write_if_changed

MISSING = object()


def merge(base, local, shared, prefix=(), initial=False):
    if local == shared:
        return local
    if not initial and local == base:
        return shared
    if not initial and shared == base:
        return local
    values = (base, local, shared)
    if all(v is MISSING or isinstance(v, Mapping) for v in values):
        base, local, shared = ({} if v is MISSING else v for v in values)
        result = {}
        for key in sorted(base.keys() | local.keys() | shared.keys()):
            value = merge(
                base.get(key, MISSING),
                local.get(key, MISSING),
                shared.get(key, MISSING),
                (*prefix, key),
                initial,
            )
            if value is not MISSING:
                result[key] = value
        return result
    if initial:
        return shared if local is MISSING else local
    raise ValueError(f"Conflicting Codex setting: {'.'.join(prefix)}")


class Codex(App):
    NAME = "codex"

    def excluded(self, keys):
        return any(
            len(rule) <= len(keys)
            and all(fnmatchcase(key, pattern) for key, pattern in zip(keys, rule))
            for rule in self.CONFIG["local_only"]
        )

    def portable(self, data, prefix=()):
        result = {}
        for key, value in data.items():
            keys = (*prefix, key)
            if not self.excluded(keys):
                if isinstance(value, Mapping):
                    value = self.portable(value, keys)
                    if not value:
                        continue
                result[key] = value
        return result

    def update(self, document, values, preserve_local=False, prefix=()):
        for key in list(document):
            keys = (*prefix, key)
            if preserve_local and self.excluded(keys):
                continue
            if key not in values:
                if preserve_local and isinstance(document[key], Mapping):
                    self.update(document[key], {}, True, keys)
                    if document[key]:
                        continue
                del document[key]
        for key, value in values.items():
            if isinstance(value, Mapping) and isinstance(document.get(key), Mapping):
                self.update(document[key], value, preserve_local, (*prefix, key))
            elif key not in document or document[key] != value:
                if (
                    preserve_local
                    and isinstance(document.get(key), Mapping)
                    and self.portable(document[key], (*prefix, key)) != document[key]
                ):
                    raise ValueError(f"Cannot replace table containing local fields: {key}")
                document[key] = value

    def install(self, *, copy_settings: bool = True) -> None:
        self.install_once(self.sync if copy_settings else self.adopt_settings, configured=False)

    def adopt_settings(self) -> None:
        destination = path(self.CONFIG["destination"])
        if not destination.exists():
            raise FileNotFoundError(
                "Codex has no settings yet; export will retry after first setup."
            )
        values = self.portable(tomlkit.parse(destination.read_text()))
        content = tomlkit.dumps(values)
        write_if_changed(self.SHARED, content)
        write_if_changed(path(self.CONFIG["baseline"]), content)

    def sync(self):
        destination = path(self.CONFIG["destination"])
        baseline = path(self.CONFIG["baseline"])
        files = (destination, self.SHARED, baseline)
        if any(p.is_symlink() for p in files):
            raise ValueError("Codex sync files must not be symlinks.")
        originals = [p.read_text() if p.exists() else None for p in files]
        if originals[2] is not None:
            missing = [str(p) for p, text in zip(files[:2], originals[:2]) if text is None]
            if missing:
                raise FileNotFoundError(
                    "Codex sync stopped: restore missing configuration file(s): "
                    + ", ".join(missing)
                    + ". To remove preferences intentionally, edit keys in the existing file."
                )
        local, shared, base = [tomlkit.parse(text or "") for text in originals]
        values = merge(
            self.portable(base),
            self.portable(local),
            self.portable(shared),
            initial=originals[2] is None,
        )
        self.update(local, values, preserve_local=True)
        self.update(shared, values)
        if any((p.read_text() if p.exists() else None) != old for p, old in zip(files, originals)):
            raise RuntimeError("Codex settings changed during sync; retry after edits finish.")
        self.write(destination, tomlkit.dumps(local))
        self.write(self.SHARED, tomlkit.dumps(shared))
        write_if_changed(baseline, tomlkit.dumps(values))

    def __init__(self):
        super().__init__()
        self.WATCH_PATHS = (self.SHARED, path(self.CONFIG["destination"]))
