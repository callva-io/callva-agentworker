"""Profile files, and finding one by name.

A profile file is TOML with one table per harness (`[claude]`, `[codex]`); each
table holds that harness's knobs. A name resolves to the first `NAME.toml` found
in, in order: the folders the caller passes, the machine folder, and the
profiles shipped inside this package. The file found is used whole: there is no
merging and no inheritance, and a file without the requested harness's table is
an error rather than a reason to look further.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from .profile import HARNESSES, Profile, ProfileError

MACHINE_DIR_NAME = "callva-harness-runner"

# A name is one path segment of letters, digits, dot, dash and underscore that
# does not start with a dot: it can never climb out of a folder or name a hidden file.
_SAFE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")


class ProfileNotFound(ProfileError):
    """No source holds a profile with that name."""


def machine_folder(environ: Mapping[str, str] | None = None) -> Path:
    """The machine-wide profile folder: `$XDG_CONFIG_HOME/callva-harness-runner/profiles`,
    with `~/.config` when XDG_CONFIG_HOME is unset, empty or not absolute."""
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME") or ""
    if not os.path.isabs(base):
        home = env.get("HOME") or os.path.expanduser("~")
        base = os.path.join(home, ".config")
    return Path(base) / MACHINE_DIR_NAME / "profiles"


def shipped_folder() -> Traversable:
    """The profiles shipped inside the package."""
    return resources.files(__package__).joinpath("profiles")


def check_name(name: str) -> str:
    """Refuse a profile name that is not one plain file-name segment."""
    if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name) or ".." in name:
        raise ProfileError(
            f"profile name {name!r} is not allowed: use letters, digits, '.', '-' and '_', "
            "not starting with '.', at most 64 characters")
    return name


@dataclass(frozen=True)
class ProfileFile:
    """One profile file a source holds."""

    name: str
    source: str
    """`folder` (a folder the caller passed), `machine` or `shipped`."""
    path: str
    text: str
    shadows: tuple[str, ...] = ()
    """Paths of same-named files in later sources, which this one hides."""

    def tables(self) -> dict[str, Any]:
        """The file's harness tables, refusing a file that is anything else."""
        return _tables(self.text, self.path)

    def harnesses(self) -> tuple[str, ...]:
        return tuple(self.tables())

    def profile(self, harness: str) -> Profile:
        """The Profile this file defines for `harness`."""
        if harness not in HARNESSES:
            raise ProfileError(f"harness must be one of {list(HARNESSES)}, got {harness!r}")
        tables = self.tables()
        if harness not in tables:
            raise ProfileError(
                f"profile {self.name!r} at {self.path} has no [{harness}] table "
                f"(it defines {sorted(tables) or 'none'})")
        table = dict(tables[harness])
        if "harness" in table and table["harness"] != harness:
            raise ProfileError(
                f"profile {self.name!r} at {self.path}: [{harness}] says "
                f"harness = {table['harness']!r}; the table name is the harness")
        table["harness"] = harness
        try:
            return Profile.from_dict(table)
        except ProfileError as refused:
            raise ProfileError(f"{self.path} [{harness}]: {refused}") from None


def _tables(text: str, path: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: not valid TOML: {exc}") from None
    for key, value in data.items():
        if key not in HARNESSES or not isinstance(value, dict):
            raise ProfileError(
                f"{path}: {key!r} is not a harness table; a profile file holds only "
                f"{', '.join(f'[{h}]' for h in HARNESSES)}")
    return data


@dataclass(frozen=True)
class _Source:
    kind: str
    folder: Path | Traversable


def _sources(folders: Iterable[str | os.PathLike[str]],
             environ: Mapping[str, str] | None) -> list[_Source]:
    return ([_Source("folder", Path(f)) for f in folders]
            + [_Source("machine", machine_folder(environ)), _Source("shipped", shipped_folder())])


def _read(source: _Source, name: str) -> tuple[str, str] | None:
    entry = source.folder.joinpath(f"{name}.toml")
    try:
        if not entry.is_file():
            return None
        return str(entry), entry.read_text(encoding="utf-8")
    except OSError:
        return None


def _names(source: _Source) -> list[str]:
    try:
        if not source.folder.is_dir():
            return []
        entries = list(source.folder.iterdir())
    except OSError:
        return []
    names = []
    for entry in entries:
        stem = entry.name[:-5] if entry.name.endswith(".toml") else None
        if stem and _SAFE_NAME.fullmatch(stem) and ".." not in stem and entry.is_file():
            names.append(stem)
    return sorted(names)


def find_profile_file(name: str, folders: Iterable[str | os.PathLike[str]] = (), *,
                      environ: Mapping[str, str] | None = None) -> ProfileFile:
    """The first `NAME.toml` in the caller's folders, the machine folder, then the shipped set."""
    check_name(name)
    found: list[tuple[str, str, str]] = []
    for source in _sources(list(folders), environ):
        hit = _read(source, name)
        if hit is not None:
            found.append((source.kind, *hit))
    if not found:
        raise ProfileNotFound(
            f"no profile named {name!r} in the given folders, {machine_folder(environ)}, "
            "or the shipped profiles")
    kind, path, text = found[0]
    return ProfileFile(name, kind, path, text, tuple(p for _, p, _ in found[1:]))


def find_profile(name: str, harness: str, folders: Iterable[str | os.PathLike[str]] = (), *,
                 environ: Mapping[str, str] | None = None) -> Profile:
    """Resolve (name, harness) to a Profile from the first file that has the name.

    To change a knob for one run, such as the model, pass the result through
    `dataclasses.replace`."""
    return find_profile_file(name, folders, environ=environ).profile(harness)


@dataclass(frozen=True)
class ProfileListing:
    """One visible profile, as `list_profiles` reports it."""

    name: str
    source: str
    path: str
    harnesses: tuple[str, ...]
    shadows: tuple[str, ...] = ()
    error: str | None = None
    """Why the file cannot be read as a profile file; its harnesses are then empty."""

    def to_dict(self) -> dict:
        data = {"name": self.name, "source": self.source, "path": self.path,
                "harnesses": list(self.harnesses), "shadows": list(self.shadows)}
        if self.error is not None:
            data["error"] = self.error
        return data


def list_profiles(folders: Iterable[str | os.PathLike[str]] = (), *,
                  environ: Mapping[str, str] | None = None) -> list[ProfileListing]:
    """Every profile a lookup can reach, by name, with the same-named files each one shadows."""
    folders = list(folders)
    names: list[str] = []
    for source in _sources(folders, environ):
        for name in _names(source):
            if name not in names:
                names.append(name)
    listing = []
    for name in sorted(names):
        file = find_profile_file(name, folders, environ=environ)
        try:
            harnesses, error = file.harnesses(), None
        except ProfileError as refused:
            harnesses, error = (), str(refused)
        listing.append(ProfileListing(file.name, file.source, file.path, harnesses,
                                      file.shadows, error))
    return listing


__all__ = [
    "ProfileFile",
    "ProfileListing",
    "ProfileNotFound",
    "check_name",
    "find_profile",
    "find_profile_file",
    "list_profiles",
    "machine_folder",
    "shipped_folder",
]
