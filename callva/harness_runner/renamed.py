"""The names and calls earlier releases replaced. There are no aliases: each old
name or call is refused with a message that names what replaced it.

0.3.0 renamed engine to harness. 0.5.0 made a profile one harness: a caller names
a profile and never a harness, a profile file is flat with a top-level `harness`,
and each shipped profile carries its harness in its name."""

RENAMED = {
    "engine": "harness",
    "engine_version": "harness_version",
    "ENGINES": "HARNESSES",
    "INCOMPATIBLE_ENGINE": "INCOMPATIBLE_HARNESS",
    "incompatible_engine": "incompatible_harness",
}


def renamed(old: str, owner: str = "") -> str:
    prefix = f"{owner}." if owner else ""
    return f"{prefix}{old} was renamed {prefix}{RENAMED[old]} in 0.3.0"


def refuse_module_attribute(module: str, name: str) -> Exception:
    """What a module's `__getattr__` raises for `name`.

    A renamed name raises ImportError: `from module import OLD` turns an
    AttributeError into a generic "cannot import name" and loses the message,
    while an ImportError reaches the caller as it was raised."""
    if name in RENAMED:
        return ImportError(renamed(name, module), name=module)
    return AttributeError(f"module {module!r} has no attribute {name!r}")


def refuse_attribute(owner: str, name: str) -> AttributeError:
    if name in RENAMED:
        return AttributeError(renamed(name, owner))
    return AttributeError(f"{owner} has no attribute {name!r}")


# The shipped profiles 0.5.0 split, one file per harness.
SPLIT_PROFILES = ("read", "act", "read-sandboxed")


def split_profile(name: str) -> str:
    """Where a shipped profile 0.5.0 split went."""
    return (f"the shipped {name!r} was split in 0.5.0 into {f'claude-{name}'!r} and "
            f"{f'codex-{name}'!r}, one harness each")


def harness_argument(name: object, harness: object) -> str:
    """The refusal of a harness passed to `find_profile`, with the call that replaces it."""
    if isinstance(name, str) and name in SPLIT_PROFILES and harness in ("claude", "codex"):
        instead = f"find_profile({f'{harness}-{name}'!r})"
    else:
        instead = "find_profile(name) with a profile whose file names that harness"
    return (f"find_profile takes no harness since 0.5.0: a profile is one harness, named in its "
            f"file; call {instead}")


# Attributes of profile files and listings 0.5.0 replaced, by owner.
ONE_HARNESS = {
    "ProfileFile": {"harnesses": "harness", "tables": "knobs"},
    "ProfileListing": {"harnesses": "harness"},
}


def refuse_file_attribute(owner: str, name: str) -> AttributeError:
    replaced = ONE_HARNESS.get(owner, {})
    if name in replaced:
        return AttributeError(
            f"{owner}.{name} was replaced by {owner}.{replaced[name]} in 0.5.0: "
            "a profile file is one harness")
    return AttributeError(f"{owner} has no attribute {name!r}")
