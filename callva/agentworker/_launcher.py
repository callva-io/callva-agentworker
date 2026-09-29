"""The launcher the library puts in front of an engine CLI.

The SDKs start the CLI themselves and only ever add to the environment they
inherit. This script sits where the SDK expects the CLI, and on every start:
removes the variables the profile removes, records its pid and argv when this
is the turn's engine and not a version probe, starts a new session so the
engine and everything it starts can be killed as one, refuses to start when the
turn has already been stopped, and then becomes the real CLI.

It runs with `python -I -S` and imports nothing from the package, so it starts
fast and the package's dependencies never load in it. It takes one argument
before the engine's own: the path of the spec the library wrote for this turn.
The spec holds names and paths only, never a variable's value.
"""

import contextlib
import fnmatch
import json
import os
import sys


def main() -> None:
    with open(sys.argv[1]) as fh:
        spec = json.load(fh)
    argv = sys.argv[2:]
    keep = set(spec["keep"])
    names = set(spec["remove_names"])
    patterns = spec["remove_patterns"]
    env = {
        key: value
        for key, value in os.environ.items()
        if key in keep or not (key in names or any(fnmatch.fnmatchcase(key, p) for p in patterns))
    }
    if spec["marker"] in argv:
        # Recorded before the stop check: the library writes the stop file before
        # it reads this record, so an engine is either recorded in time to be
        # killed or sees the stop file and never starts.
        with open(spec["pidfile"], "a") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "argv": [spec["binary"], *argv]}) + "\n")
        with contextlib.suppress(OSError):
            os.setsid()
    if os.path.exists(spec["stop"]):
        sys.exit(143)
    os.execve(spec["binary"], [spec["binary"], *argv], env)


main()
