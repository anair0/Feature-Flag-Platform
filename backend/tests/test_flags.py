from .conftest import ON


def test_create_flag_starts_off_everywhere(account):
    flag = account.create_flag()
    assert flag["variations"] == [True, False]
    assert set(flag["environments"]) == {"development", "staging", "production"}
    for cfg in flag["environments"].values():
        assert cfg["on"] is False and cfg["version"] == 1


def test_duplicate_flag_key(account):
    account.create_flag()
    assert (
        account.post("/projects/default/flags", {"key": "new-checkout", "name": "x"}).status_code
        == 409
    )


def test_invalid_flag_definitions(account):
    bad = [
        {"key": "Has Spaces", "name": "x"},
        {"key": "ok", "name": "x", "kind": "boolean", "variations": [1, 2]},
        {"key": "ok", "name": "x", "kind": "string", "variations": ["only-one"]},
        {"key": "ok", "name": "x", "kind": "string", "variations": ["a", 2]},
        {"key": "ok", "name": "x", "kind": "number", "variations": [1, True]},
        {"key": "ok", "name": "x", "kind": "string", "variations": ["a", "a"]},
    ]
    for body in bad:
        assert account.post("/projects/default/flags", body).status_code == 422, body


def test_string_flag(account):
    flag = account.create_flag("theme", kind="string", variations=["light", "dark", "auto"])
    assert flag["environments"]["development"]["off_variation"] == 0


def test_update_config_increments_version_and_sets_etag(account):
    account.create_flag()
    r = account.set_config("new-checkout", "development", ON)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["on"] is True
    assert r.headers["ETag"] == '"2"'


def test_concurrent_edit_is_rejected_with_409(account):
    account.create_flag()
    assert account.set_config("new-checkout", "development", ON, version=1).status_code == 200
    # A teammate who loaded version 1 saves afterwards: must not silently overwrite.
    r = account.set_config("new-checkout", "development", {**ON, "on": False}, version=1)
    assert r.status_code == 409
    assert r.json()["detail"]["current"]["version"] == 2
    assert account.config("new-checkout", "development")["on"] is True


def test_if_match_required(account):
    account.create_flag()
    r = account.put("/projects/default/flags/new-checkout/environments/development", ON)
    assert r.status_code == 428


def test_semantic_validation(account):
    account.create_flag()
    cases = [
        {**ON, "fallthrough": {"variation": 5}},
        {**ON, "off_variation": 2},
        {**ON, "fallthrough": {"rollout": {"variations": [{"variation": 0, "weight": 50000}]}}},
        {
            **ON,
            "fallthrough": {
                "variation": 0,
                "rollout": {"variations": [{"variation": 0, "weight": 100000}]},
            },
        },
        {
            **ON,
            "rules": [
                {
                    "clauses": [{"attribute": "country", "op": "regex", "values": ["x"]}],
                    "serve": {"variation": 0},
                }
            ],
        },
        {**ON, "rules": [{"clauses": [], "serve": {"variation": 0}}]},
        {
            **ON,
            "rules": [
                {
                    "clauses": [{"attribute": "c", "op": "in", "values": []}],
                    "serve": {"variation": 0},
                }
            ],
        },
        {**ON, "targets": [{"variation": 0, "values": ["u1"]}, {"variation": 1, "values": ["u1"]}]},
        {
            **ON,
            "rules": [
                {
                    "id": "a",
                    "clauses": [{"attribute": "c", "op": "in", "values": ["x"]}],
                    "serve": {"variation": 0},
                },
                {
                    "id": "a",
                    "clauses": [{"attribute": "c", "op": "in", "values": ["y"]}],
                    "serve": {"variation": 0},
                },
            ],
        },
        {**ON, "unexpected": 1},
    ]
    for body in cases:
        r = account.set_config("new-checkout", "development", body)
        assert r.status_code == 422, (body, r.text)
    assert account.config("new-checkout", "development")["version"] == 1


def test_rule_ids_generated_and_targets_merged(account):
    account.create_flag()
    body = {
        **ON,
        "targets": [{"variation": 0, "values": ["a"]}, {"variation": 0, "values": ["b", "a"]}],
        "rules": [
            {
                "clauses": [{"attribute": "country", "op": "in", "values": ["CA"]}],
                "serve": {
                    "rollout": {
                        "kind": "rollout",
                        "variations": [
                            {"variation": 0, "weight": 10000},
                            {"variation": 1, "weight": 90000},
                        ],
                    }
                },
            }
        ],
    }
    cfg = account.set_config("new-checkout", "development", body).json()
    assert cfg["targets"] == [{"variation": 0, "values": ["a", "b"]}]
    assert len(cfg["rules"][0]["id"]) == 8
    assert "variation" not in cfg["rules"][0]["serve"]


def test_test_evaluator_explains_result(account):
    account.create_flag()
    account.set_config(
        "new-checkout",
        "development",
        {
            **ON,
            "fallthrough": {"variation": 1},
            "rules": [
                {
                    "id": "canada",
                    "clauses": [{"attribute": "country", "op": "in", "values": ["CA"]}],
                    "serve": {"variation": 0},
                }
            ],
        },
    )
    r = account.post(
        "/projects/default/flags/new-checkout/environments/development/evaluate",
        {"user": {"id": "u1", "country": "CA"}},
    )
    assert r.json() == {
        "value": True,
        "variation_index": 0,
        "reason": {"kind": "RULE_MATCH", "rule_index": 0, "rule_id": "canada"},
    }


def test_audit_records_before_and_after(account):
    account.create_flag()
    account.set_config("new-checkout", "production", ON)
    entries = account.get("/audit", params={"flag_key": "new-checkout"}).json()
    assert [e["action"] for e in entries] == ["config.updated", "flag.created"]
    change = entries[0]
    assert change["environment_key"] == "production"
    assert change["actor_email"] == account.email
    assert change["before"]["on"] is False and change["after"]["on"] is True
    assert change["before"]["version"] == 1 and change["after"]["version"] == 2


def test_failed_change_writes_no_audit(account):
    account.create_flag()
    account.set_config("new-checkout", "development", ON, version=99)
    entries = account.get("/audit", params={"flag_key": "new-checkout"}).json()
    assert [e["action"] for e in entries] == ["flag.created"]


def test_archive_hides_flag_and_blocks_edits(account):
    account.create_flag()
    assert account.post("/projects/default/flags/new-checkout/archive").status_code == 200
    assert account.get("/projects/default/flags").json() == []
    assert (
        len(account.get("/projects/default/flags", params={"include_archived": True}).json()) == 1
    )
    assert account.set_config("new-checkout", "development", ON).status_code == 409


def test_new_environment_gets_configs_for_existing_flags(account):
    account.create_flag()
    r = account.post("/projects/default/environments", {"key": "qa", "name": "QA"})
    assert r.status_code == 201
    assert r.json()["server_key"].startswith("srv-")
    assert "qa" in account.get("/projects/default/flags/new-checkout").json()["environments"]


def test_new_project(account):
    r = account.post("/projects", {"key": "mobile", "name": "Mobile app"})
    assert r.status_code == 201
    assert len(r.json()["environments"]) == 3
