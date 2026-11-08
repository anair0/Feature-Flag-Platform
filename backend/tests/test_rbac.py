from .conftest import ON


def _join(owner, make_account, role):
    member = make_account()
    owner.invite(member, role)
    member.org_id = owner.org_id
    return member


def test_reader_can_read_but_not_write(account, make_account):
    account.create_flag()
    reader = _join(account, make_account, "reader")
    assert reader.get("/projects/default/flags").status_code == 200
    assert reader.set_config("new-checkout", "development", ON).status_code == 403
    assert reader.post("/projects/default/flags", {"key": "x", "name": "x"}).status_code == 403


def test_writer_edits_dev_but_not_production(account, make_account):
    account.create_flag()
    writer = _join(account, make_account, "writer")
    assert writer.set_config("new-checkout", "development", ON).status_code == 200
    r = writer.set_config("new-checkout", "production", ON)
    assert r.status_code == 403 and "protected" in r.json()["detail"]


def test_admin_edits_production(account, make_account):
    account.create_flag()
    admin = _join(account, make_account, "admin")
    assert admin.set_config("new-checkout", "production", ON).status_code == 200


def test_unprotecting_production_lets_writers_edit(account, make_account):
    account.create_flag()
    writer = _join(account, make_account, "writer")
    assert (
        account.patch("/projects/default/environments/production", {"protected": False}).status_code
        == 200
    )
    assert writer.set_config("new-checkout", "production", ON).status_code == 200


def test_writer_cannot_see_sdk_keys(account, make_account):
    writer = _join(account, make_account, "writer")
    assert writer.get("/projects/default/environments/production/keys").status_code == 403


def test_admin_cannot_create_or_demote_owners(account, make_account):
    admin = _join(account, make_account, "admin")
    other = make_account()
    assert admin.post("/members", {"email": other.email, "role": "owner"}).status_code == 403
    assert admin.patch(f"/members/{account.user_id}", {"role": "reader"}).status_code == 403
    assert admin.delete(f"/members/{account.user_id}").status_code == 403


def test_last_owner_cannot_leave(account):
    assert account.patch(f"/members/{account.user_id}", {"role": "admin"}).status_code == 409
    assert account.delete(f"/members/{account.user_id}").status_code == 409


def test_removed_member_loses_access(account, make_account):
    member = _join(account, make_account, "writer")
    assert account.delete(f"/members/{member.user_id}").status_code == 204
    assert member.get("/projects").status_code == 404
