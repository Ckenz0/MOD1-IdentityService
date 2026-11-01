from concurrent.futures import ThreadPoolExecutor


def login(client, user):
    return client.post(
        "/auth/token", data={"username": user.email, "password": "  password12345  "}
    )


def bearer(data):
    return {"Authorization": "Bearer " + data["access_token"]}


def test_refresh_rotation_replay_revokes_whole_session(client, user):
    first = login(client, user).json()
    assert "refresh_token" in first
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    assert second.json()["session_id"] == first["session_id"]
    assert (
        client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code
        == 401
    )
    assert client.get("/auth/me", headers=bearer(second.json())).status_code == 401


def test_concurrent_refresh_only_one_wins_then_replay_invalidates(client, user):
    first = login(client, user).json()
    assert "refresh_token" in first

    def rotate(_):
        return client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, range(2)))
    assert sorted(r.status_code for r in results) == [200, 401]
    winner = next(r.json() for r in results if r.status_code == 200)
    assert client.get("/auth/me", headers=bearer(winner)).status_code == 401


def test_sessions_activity_logout_and_flags(client, user):
    first = login(client, user).json()
    assert "session_id" in first
    headers = bearer(first)
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_admin"] is False and me["email_verified"] is False
    page = client.get("/auth/sessions", headers=headers).json()
    assert page["total"] == 1 and page["items"][0]["is_current"] is True
    assert "refresh_token" not in str(page)
    active = client.post("/auth/session/activity", headers=headers, json={})
    assert active.status_code == 200
    assert active.json()["absolute_expires_at"] == first["absolute_expires_at"]
    assert client.post("/auth/logout", headers=headers, json={}).status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_lockout_is_persistent_and_uniform(client, user):
    for _ in range(5):
        assert (
            client.post(
                "/auth/token", data={"username": user.email, "password": "wrong"}
            ).status_code
            == 401
        )
    assert login(client, user).status_code == 401
    assert (
        client.post(
            "/auth/token", data={"username": "missing@example.com", "password": "wrong"}
        ).json()
        == login(client, user).json()
    )


def test_nonadmin_denied_and_secret_validation_sanitized(client, user):
    headers = bearer(login(client, user).json())
    assert client.get("/admin/users", headers=headers).status_code == 403
    response = client.post("/auth/refresh", json={"refresh_token": {"secret": "do-not-echo"}})
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
