def test_signup_creates_org_with_default_project_and_environments(account):
    me = account.client.get("/api/me", headers=account.headers).json()
    assert [o["role"] for o in me["orgs"]] == ["owner"]
    projects = account.get("/projects").json()
    assert [p["key"] for p in projects] == ["default"]
    envs = {e["key"]: e["protected"] for e in projects[0]["environments"]}
    assert envs == {"development": False, "staging": False, "production": True}


def test_login(account):
    r = account.client.post(
        "/api/auth/login", json={"email": account.email, "password": "correct horse"}
    )
    assert r.status_code == 200
    assert (
        account.client.get(
            "/api/me", headers={"Authorization": f"Bearer {r.json()['token']}"}
        ).status_code
        == 200
    )


def test_login_wrong_password(account):
    r = account.client.post("/api/auth/login", json={"email": account.email, "password": "nope"})
    assert r.status_code == 401


def test_duplicate_signup(account, client):
    r = client.post(
        "/api/auth/signup",
        json={"email": account.email.upper(), "password": "12345678", "name": "x", "org_name": "y"},
    )
    assert r.status_code == 409


def test_unauthenticated(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/signup",
        json={"email": "a@b.co", "password": "short", "name": "x", "org_name": "y"},
    )
    assert r.status_code == 422
