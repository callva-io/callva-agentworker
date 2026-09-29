"""The names 0.3.0 replaced. There are no aliases: each old name is refused
with a message that names what replaced it."""

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
