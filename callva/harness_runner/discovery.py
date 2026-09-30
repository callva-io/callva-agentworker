"""Profile files, and finding one by name.

A profile is one harness with its settings, and a profile file holds exactly
one: flat TOML with a required top-level `harness = "claude"` or `"codex"` and
that harness's knobs beside it. A caller names a profile and never a harness. A
name resolves to the first `NAME.toml` found in, in order: the folders the
caller passes, the machine folder, and the profiles shipped inside this package.
The file found is used whole: there is no merging and no inheritance, and a file
that cannot be read as a profile is an error rather than a reason to look
further.
"""

from __future__ import annotations

import inspect
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
from .renamed import SPLIT_PROFILES, harness_argument, refuse_file_attribute, split_profile

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

    def knobs(self) -> dict[str, Any]:
        """The file's knobs, `harness` included, refusing a file that is not one flat profile."""
        return _knobs(self.text, self.path)

    @property
    def harness(self) -> str:
        """The harness the file's top-level `harness` names."""
        return self.knobs()["harness"]

    def profile(self) -> Profile:
        """The Profile this file defines."""
        knobs = self.knobs()
        try:
            return Profile.from_dict(knobs)
        except ProfileError as refused:
            raise ProfileError(f"{self.path}: {refused}") from None

    def __getattr__(self, name: str):
        raise refuse_file_attribute("ProfileFile", name)


_FLAT_FORM = ('a profile file is flat: `harness = "claude"` or `harness = "codex"` at the top, '
              "and that harness's knobs beside it")


def _knobs(text: str, path: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: not valid TOML: {exc}") from None
    tables = [key for key in HARNESSES if isinstance(data.get(key), dict)]
    if tables:
        raise ProfileError(
            f"{path}: {', '.join(f'[{t}]' for t in tables)} is a harness table, which 0.5.0 "
            f"no longer reads; {_FLAT_FORM}, one file per harness")
    if "harness" not in data:
        raise ProfileError(f"{path}: no top-level `harness`; {_FLAT_FORM}")
    if data["harness"] not in HARNESSES:
        raise ProfileError(
            f"{path}: harness must be one of {list(HARNESSES)}, got {data['harness']!r}; "
            f"{_FLAT_FORM}")
    return data


@dataclass(frozen=True)
class _Source:
    kind: str
    folder: Path | Traversable


def _folder_list(folders: Iterable[str | os.PathLike[str]]) -> list[str | os.PathLike[str]]:
    # A single string is iterable, and would be searched as one folder per character.
    if isinstance(folders, (str, bytes, os.PathLike)):
        raise TypeError(
            f"folders is a list of folders, got the single value {folders!r}; pass [folder]")
    return list(folders)


def _sources(folders: Iterable[str | os.PathLike[str]],
             environ: Mapping[str, str] | None) -> list[_Source]:
    folders = _folder_list(folders)
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
    for source in _sources(folders, environ):
        hit = _read(source, name)
        if hit is not None:
            found.append((source.kind, *hit))
    if not found:
        where = (f"no profile named {name!r} in the given folders, {machine_folder(environ)}, "
                 "or the shipped profiles")
        if name in SPLIT_PROFILES:
            where = f"{where}; {split_profile(name)}"
        raise ProfileNotFound(where)
    kind, path, text = found[0]
    return ProfileFile(name, kind, path, text, tuple(p for _, p, _ in found[1:]))


def _find_profile(name: str, folders: Iterable[str | os.PathLike[str]] = (), *,
                  environ: Mapping[str, str] | None = None) -> Profile:
    """Resolve a name to the Profile its first file defines; the file names the harness.

    To change a knob for one run, such as the model, pass the result through
    `dataclasses.replace`."""
    return find_profile_file(name, folders, environ=environ).profile()


def find_profile(name: str, *args: Any, environ: Mapping[str, str] | None = None,
                 **kwargs: Any) -> Profile:
    # A harness passed as 0.4.0 did, `find_profile(name, harness, folders)`, would
    # otherwise land in `folders` and be searched as one folder per character.
    if "harness" in kwargs:
        raise TypeError(harness_argument(name, kwargs["harness"]))
    if args and (len(args) > 1 or (isinstance(args[0], str) and args[0] in HARNESSES)):
        raise TypeError(harness_argument(name, args[0]))
    return _find_profile(name, *args, environ=environ, **kwargs)


find_profile.__doc__ = _find_profile.__doc__
find_profile.__signature__ = inspect.signature(_find_profile)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ProfileListing:
    """One visible profile, as `list_profiles` reports it."""

    name: str
    source: str
    path: str
    harness: str | None
    """The harness the file names; `None` when the file cannot be read as a profile file."""
    shadows: tuple[str, ...] = ()
    error: str | None = None
    """Why the file cannot be read as a profile file."""

    def to_dict(self) -> dict:
        data = {"name": self.name, "source": self.source, "path": self.path,
                "harness": self.harness, "shadows": list(self.shadows)}
        if self.error is not None:
            data["error"] = self.error
        return data

    def __getattr__(self, name: str):
        raise refuse_file_attribute("ProfileListing", name)


def list_profiles(folders: Iterable[str | os.PathLike[str]] = (), *,
                  environ: Mapping[str, str] | None = None) -> list[ProfileListing]:
    """Every profile a lookup can reach, by name, with its harness and the same-named files
    it shadows."""
    folders = _folder_list(folders)
    names: list[str] = []
    for source in _sources(folders, environ):
        for name in _names(source):
            if name not in names:
                names.append(name)
    listing = []
    for name in sorted(names):
        file = find_profile_file(name, folders, environ=environ)
        try:
            harness, error = file.harness, None
        except ProfileError as refused:
            harness, error = None, str(refused)
        listing.append(ProfileListing(file.name, file.source, file.path, harness,
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
