from test_sessions import bearer, login

from mod1_auth.database import create_session_factory
from mod1_auth.repositories import UserRepository
from mod1_auth.services import UserService


def test_directory_requires_consent_and_omits_email(client, user, engine):
    headers = bearer(login(client, user).json())
    assert client.get("/auth/directory", headers=headers).status_code == 200
    assert client.get("/auth/directory", headers=headers).json()["total"] == 0
    assert (
        client.patch(
            "/auth/profile",
            headers=headers,
            json={
                "share_for_recommendations": True,
                "skills": [{"name": "Python", "level": 3}],
                "weekly_availability_hours": 20,
            },
        ).status_code
        == 200
    )
    page = client.get("/auth/directory?q=python", headers=headers).json()
    assert page["total"] == 1
    assert page["items"][0]["user_id"] == str(user.id)
    assert page["items"][0]["display_name"] == "Caue"
    assert "email" not in page["items"][0]
    with create_session_factory(engine)() as session:
        other = UserService(UserRepository(session)).create_user(
            email="another@example.com", display_name="Another", password="other-password"
        )
    other_headers = bearer(
        client.post(
            "/auth/token", data={"username": other.email, "password": "other-password"}
        ).json()
    )
    assert client.get(f"/auth/directory/{user.id}", headers=other_headers).status_code == 200
    assert (
        client.patch(
            "/auth/profile", headers=headers, json={"share_for_recommendations": False}
        ).status_code
        == 200
    )
    assert client.get(f"/auth/directory/{user.id}", headers=other_headers).status_code == 404
    assert client.get(f"/auth/directory/{user.id}", headers=headers).status_code == 200
    assert client.get("/auth/directory", headers=other_headers).json()["total"] == 0
