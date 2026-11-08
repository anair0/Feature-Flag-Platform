"""The RBAC policy as a pure function."""

import pytest

from app.core.permissions import Role, can, can_change_member


@pytest.mark.parametrize(
    "role,action,protected,allowed",
    [
        (Role.reader, "project.read", False, True),
        (Role.reader, "config.update", False, False),
        (Role.writer, "config.update", False, True),
        (Role.writer, "config.update", True, False),  # production needs admin
        (Role.admin, "config.update", True, True),
        (Role.writer, "flag.create", False, True),
        (Role.writer, "flag.archive", False, False),
        (Role.writer, "keys.read", False, False),
        (Role.admin, "keys.rotate", False, True),
        (Role.admin, "members.manage", False, True),
        (Role.owner, "anything.unknown", False, False),  # unknown actions are denied
    ],
)
def test_can(role, action, protected, allowed):
    assert can(role, action, protected_env=protected) is allowed


def test_member_changes():
    assert can_change_member(Role.owner, Role.admin, Role.owner)
    assert can_change_member(Role.admin, Role.reader, Role.admin)
    assert not can_change_member(Role.admin, Role.owner, Role.admin)  # can't demote owners
    assert not can_change_member(Role.admin, Role.reader, Role.owner)  # can't mint owners
    assert not can_change_member(Role.writer, Role.reader, Role.writer)
