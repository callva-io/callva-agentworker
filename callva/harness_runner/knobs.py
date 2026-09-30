"""Every Profile knob as an author needs it, read at runtime from the homes that own it.

The type, the allowed values and the constraints come from `profile.schema.json`; the default
comes from the `Profile` field; what the knob does on each harness comes from the field's
docstring on `Profile`, split at its `Claude:`, `Codex:` and `Both:` labels. Nothing here is a
second copy of any of them.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import json
import re
from typing import Any

from . import profile as profile_module
from .profile import HARNESSES, PROFILE_SCHEMA, Profile

_LABEL = re.compile(r"\b(Claude|Codex|Both):\s+")


def docstrings() -> dict[str, str]:
    """Each Profile field's docstring, the string literal written under the field."""
    tree = ast.parse(inspect.getsource(profile_module))
    [cls] = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Profile"]
    found: dict[str, str] = {}
    for node, after in itertools.pairwise(cls.body):
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and isinstance(after, ast.Expr) and isinstance(after.value, ast.Constant)
                and isinstance(after.value.value, str)):
            found[node.target.id] = " ".join(inspect.cleandoc(after.value.value).split())
    return found


def meaning(doc: str, harness: str) -> str:
    """What a docstring says for one harness: its unlabelled opening, its `Both:` part and
    the part labelled with the harness."""
    parts = _LABEL.split(doc)
    kept = [parts[0].strip()]
    for label, text in zip(parts[1::2], parts[2::2], strict=True):
        if label.lower() in (harness, "both") and text.strip():
            kept.append(text.strip()[0].upper() + text.strip()[1:])
    return " ".join(t for t in kept if t)


def _type(schema: dict) -> str:
    kinds = schema.get("type", "any")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    named = []
    for kind in kinds:
        if kind == "array" and "items" in schema:
            kind = f"array of {_type(schema['items'])}"
        elif kind == "object" and isinstance(schema.get("additionalProperties"), dict):
            kind = f"object of {_type(schema['additionalProperties'])}"
        named.append(kind)
    return " or ".join(named)


def _allowed(schema: dict) -> str:
    rules = []
    for where in (schema, schema.get("items") or {}):
        if "enum" in where:
            rules.append(", ".join(json.dumps(v) for v in where["enum"] if v is not None))
        if "exclusiveMinimum" in where:
            rules.append(f"greater than {where['exclusiveMinimum']}")
        if "minimum" in where:
            rules.append(f"at least {where['minimum']}")
    return "; ".join(rules) or "any"


def _default(field: dataclasses.Field) -> Any:
    if field.default is not dataclasses.MISSING:
        value = field.default
    elif field.default_factory is not dataclasses.MISSING:
        value = field.default_factory()
    else:
        return None
    return list(value) if isinstance(value, tuple) else value


def describe(harness: str | None = None) -> list[dict[str, Any]]:
    """Every Profile knob, in field order: name, type, allowed values, default, whether it is
    required, and its meaning on each harness (only `harness` when one is named)."""
    if harness is not None and harness not in HARNESSES:
        raise ValueError(f"harness must be one of {list(HARNESSES)}, got {harness!r}")
    docs = docstrings()
    props = PROFILE_SCHEMA.get("properties", {})
    required = set(PROFILE_SCHEMA.get("required", ()))
    knobs = []
    for field in dataclasses.fields(Profile):
        schema = props.get(field.name, {})
        doc = docs.get(field.name, "")
        knobs.append({
            "name": field.name,
            "type": _type(schema),
            "allowed": _allowed(schema),
            "required": field.name in required,
            "default": _default(field),
            "meaning": {h: meaning(doc, h) for h in HARNESSES if harness in (None, h)},
        })
    return knobs


def render(knobs: list[dict[str, Any]]) -> str:
    lines = []
    for knob in knobs:
        lines.append(knob["name"])
        lines.append(f"  type: {knob['type']}")
        lines.append(f"  allowed: {knob['allowed']}")
        default = "required" if knob["required"] else json.dumps(knob["default"])
        lines.append(f"  default: {default}")
        for harness, text in knob["meaning"].items():
            lines.append(f"  {harness}: {text}")
        lines.append("")
    return "\n".join(lines)
