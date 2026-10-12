"""Manual routes cannot bypass the personal email review flow anonymously."""

from backend.app.services import bulletin_mail
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run


def test_manual_bulletin_writes_require_credentials_before_state_or_mail_changes(
    env, fast_maps, monkeypatch
):
    run(env)
    draft = env.client.post("/bulletins/generate", json={}).json()
    env.client.headers.pop("authorization", None)
    before_audit = env.platform.repo.list("audit")

    def must_not_mail(*args, **kwargs):
        raise AssertionError("An unauthorized request attempted to send email")

    monkeypatch.setattr(bulletin_mail, "notify", must_not_mail)
    body = {"actor": "Joe254h", "confirmed": True, "comment": "Pretended identity"}
    for action in ("submit", "approve", "reject", "publish", "resend"):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = env.client.post(
                f"/bulletins/{draft['id']}/{action}", json=body, headers=headers
            )
            assert response.status_code == 401
    assert env.client.post("/bulletins/generate", json={}).status_code == 401
    assert env.platform.repo.get("bulletin", draft["id"])["status"] == "draft"
    assert env.platform.repo.list("audit") == before_audit
    assert env.client.get(f"/bulletins/{draft['id']}/export").status_code == 200


def test_unconfigured_or_short_operator_key_fails_closed(env, monkeypatch):
    for key in ("", "short"):
        monkeypatch.setenv("BULLETIN_OPERATOR_KEY", key)
        response = env.client.post("/bulletins/generate", json={})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
    assert env.client.get("/bulletins").status_code == 200
