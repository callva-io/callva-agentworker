"""`python -m callva.harness_runner profiles [show NAME] [--folder DIR ...]`

`profiles` prints, as JSON, every profile discovery can reach: its name, the
source it comes from, its path, the harness tables it defines, and the
same-named files it shadows. `profiles show NAME` prints the file a lookup of
NAME resolves to, exactly as it is, after a comment line naming its source and
path. `--folder` adds a search folder ahead of the machine folder and the
shipped profiles; give it once per folder, in search order.
"""

from __future__ import annotations

import argparse
import json
import sys

from .discovery import find_profile_file, list_profiles
from .profile import ProfileError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m callva.harness_runner",
                                     description="Harness profiles: list them, or show one.")
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
    args = parser.parse_args(argv)
    folders = list(args.folder) + list(getattr(args, "show_folder", None) or [])
    try:
        if args.action == "show":
            found = find_profile_file(args.name, folders)
            sys.stdout.write(f"# {found.source}: {found.path}\n{found.text}")
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
