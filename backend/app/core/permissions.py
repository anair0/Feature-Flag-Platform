"""Role-based access control. One place, pure functions, unit-tested in isolation."""

from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    reader = 0
    writer = 1
    admin = 2
    owner = 3


# Minimum role per action. Actions on protected environments (e.g. production) may
# require more; see _PROTECTED_MIN_ROLE.
_MIN_ROLE: dict[str, Role] = {
    "project.read": Role.reader,
    "project.create": Role.admin,
    "flag.create": Role.writer,
    "flag.update": Role.writer,
    "flag.archive": Role.admin,
    "config.update": Role.writer,
    "environment.create": Role.admin,
    "environment.update": Role.admin,
    "keys.read": Role.admin,
    "keys.rotate": Role.admin,
    "members.read": Role.reader,
    "members.manage": Role.admin,
    "audit.read": Role.reader,
    "experiments.read": Role.reader,
    "evaluate.test": Role.reader,
}

_PROTECTED_MIN_ROLE: dict[str, Role] = {
    "config.update": Role.admin,
}


def can(role: Role, action: str, *, protected_env: bool = False) -> bool:
    if action not in _MIN_ROLE:
        return False  # unknown actions are denied, never allowed by accident
    required = _MIN_ROLE[action]
    if protected_env:
        required = max(required, _PROTECTED_MIN_ROLE.get(action, required))
    return role >= required


def can_change_member(actor: Role, target_current: Role | None, target_new: Role | None) -> bool:
    """May `actor` move a member from target_current to target_new? (None = not a member)."""
    if actor == Role.owner:
        return True
    if actor < Role.admin:
        return False
    # Admins manage readers/writers/admins, but never touch owners or create them.
    if target_current == Role.owner or target_new == Role.owner:
        return False
    return True
