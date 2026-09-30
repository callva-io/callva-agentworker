"""`python -m callva.harness_runner profiles [show NAME | check FILE] [--folder DIR ...]`
and `python -m callva.harness_runner knobs [--harness claude|codex]`.

`profiles` prints, as JSON, every profile discovery can reach: its name, the
source it comes from, its path, its harness, and the same-named files it
shadows. `profiles show NAME` prints the file a lookup of NAME resolves to,
exactly as it is, after a comment line naming its source and path and a comment
line naming its harness (or why the file cannot be read as a profile).
`--folder` adds a search folder ahead of the machine folder and the shipped
profiles; give it once per folder, in search order. `profiles check FILE` reads
one profile file and prints `ok` with its harness, or the refusal naming the
knob and exits 2.

`knobs` prints every Profile knob with its type, allowed values, default and
what it does on each harness, or on the one `--harness` names.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import ProfileFile, find_profile_file, list_profiles
from .knobs import describe, render
from .profile import HARNESSES, ProfileError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m callva.harness_runner",
                                     description="Harness profiles: list, show and check "
                                                 "them, and describe their knobs.")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("profiles", help="list every profile discovery can reach")
    listing.add_argument("--folder", action="append", default=[], metavar="DIR",
                         help="a search folder, before the machine and shipped profiles; "
                              "repeat for more, in search order")
    shows = listing.add_subparsers(dest="action")
    show = shows.add_parser("show", help="print the file a profile name resolves to")
    show.add_argument("name")
    show.add_argument("--folder", action="append", default=[], metavar="DIR",
                      dest="show_folder", help="as for profiles")
    check = shows.add_parser("check", help="validate one profile file")
    check.add_argument("file")
    knobs = commands.add_parser("knobs", help="describe every profile knob")
    knobs.add_argument("--harness", choices=HARNESSES,
                       help="only what each knob does on this harness")
    args = parser.parse_args(argv)
    if args.command == "knobs":
        sys.stdout.write(render(describe(args.harness)))
        return 0
    folders = list(args.folder) + list(getattr(args, "show_folder", None) or [])
    try:
        if args.action == "check":
            path = Path(args.file)
            try:
                text = path.read_text()
            except OSError as unreadable:
                raise ProfileError(f"{path}: {unreadable.strerror or unreadable}") from None
            checked = ProfileFile(name=path.stem, source="file", path=str(path), text=text)
            print(f"ok: {path}: harness {checked.profile().harness}")
            return 0
        if args.action == "show":
            found = find_profile_file(args.name, folders)
            try:
                about = f"harness: {found.harness}"
            except ProfileError as refused:
                about = f"error: {refused}"
            sys.stdout.write(f"# {found.source}: {found.path}\n# {about}\n{found.text}")
            if not found.text.endswith("\n"):
                sys.stdout.write("\n")
            return 0
        print(json.dumps([entry.to_dict() for entry in list_profiles(folders)], indent=2))
        return 0
    except ProfileError as refused:
        print(f"error: {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
