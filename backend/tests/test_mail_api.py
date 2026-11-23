"""Email through a provider's HTTPS API, for hosts that block SMTP ports."""

import httpx

from backend.app.services import mail


def test_drafts_are_mailed_through_resend_or_brevo(monkeypatch):
    sent = []

    def post(url, json, headers, timeout):
        sent.append((url, json, headers))
        return httpx.Response(200, json={"id": "x"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.delenv("MAIL_OUTBOX_DIR", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("MAIL_API", "resend")
    monkeypatch.setenv("MAIL_FROM", "onboarding@resend.dev")
    monkeypatch.delenv("MAIL_API_KEY", raising=False)
    assert mail.Mailer().problem() == "no resend API key is set up"
    monkeypatch.setenv("MAIL_API_KEY", "re_test")
    sender = mail.Mailer()
    assert sender.configured
    attachment = mail.Attachment("bulletin.docx", b"doc", "application", "octet-stream")
    sender.send("forecaster@example.org", "Draft", "text", "<p>html</p>", [attachment])
    url, body, headers = sent[-1]
    assert url == "https://api.resend.com/emails" and headers["Authorization"] == "Bearer re_test"
    assert body["to"] == ["forecaster@example.org"] and body["attachments"][0]["content"] == "ZG9j"
    monkeypatch.setenv("MAIL_API", "brevo")
    mail.Mailer().send("forecaster@example.org", "Draft", "text", "<p>html</p>")
    url, body, headers = sent[-1]
    assert url.startswith("https://api.brevo.com") and headers["api-key"] == "re_test"
    assert body["to"] == [{"email": "forecaster@example.org"}]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, text="bad key"))
    try:
        mail.Mailer().send("forecaster@example.org", "Draft", "text", "<p>html</p>")
    except RuntimeError as exc:
        assert "refused the message (401)" in str(exc)
    else:
        raise AssertionError("a refused message must raise")
