"""The bulletin review by email: links to reviewers, publishers and the distribution list,
decisions from the links, and the same steps on the website."""

import email
import re
from email import policy
from pathlib import Path

import pytest

from backend.app.services import mail
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run


def inbox(folder: Path) -> list[email.message.EmailMessage]:
    messages = []
    for path in sorted(folder.glob("*.eml")):
        message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        messages.append(message)
        path.unlink()
    return messages


def body(message) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def link(message) -> str:
    found = re.search(r"/bulletins/action\?token=(\S+)", body(message))
    assert found is not None
    return found.group(1)


@pytest.fixture
def post_office(env, tmp_path, monkeypatch):
    outbox = tmp_path / "outbox"
    monkeypatch.setenv("MAIL_OUTBOX_DIR", str(outbox))
    monkeypatch.setenv("BULLETIN_REVIEWERS", "ruth@icpac.net, amos@icpac.net")
    monkeypatch.setenv("BULLETIN_PUBLISHERS", "pub@icpac.net")
    monkeypatch.setenv("BULLETIN_DISTRIBUTION", "list@icpac.net")
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://forecasts.example")
    return outbox


def test_a_bulletin_is_approved_and_published_from_the_emails(env, fast_maps, post_office):
    run(env)
    client = env.client
    assert client.get("/bulletins/email-status").json() == {
        "configured": True,
        "problem": None,
        "reviewers": 2,
        "publishers": 1,
        "distribution": 1,
    }
    draft = client.post("/bulletins/generate", json={}).json()
    review = {"actor": "Joe N", "confirmed": True, "comment": "Ready for review"}
    submitted = client.post(f"/bulletins/{draft['id']}/submit", json=review).json()
    assert submitted["notification"]["sent"] == ["ruth@icpac.net", "amos@icpac.net"]

    messages = inbox(post_office)
    assert [m["To"] for m in messages] == ["ruth@icpac.net", "amos@icpac.net"]
    first = messages[0]
    assert first["Subject"] == f"Approval requested: {draft['title']}"
    assert "https://forecasts.example/bulletins/action?token=" in body(first)
    attachment = next(first.iter_attachments())
    assert (attachment.get_filename() or "").endswith(".docx")
    token = link(first)

    # Opening the link shows the bulletin and the decisions; nothing changes.
    shown = client.get("/bulletins/email-action", params={"token": token}).json()
    assert shown["step"] == "review" and shown["email"] == "ruth@icpac.net"
    assert shown["decisions"] == ["approve", "reject"]
    assert shown["bulletin"]["status"] == "under_review"
    # A link cannot be altered, or used for a step it was not sent for.
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    assert client.get("/bulletins/email-action", params={"token": forged}).status_code == 422
    refused = client.post("/bulletins/email-action", json={"token": token, "decision": "publish"})
    assert refused.status_code == 422

    approved = client.post(
        "/bulletins/email-action",
        json={"token": token, "decision": "approve", "name": "Ruth K"},
    ).json()
    assert approved["status"] == "approved"
    assert approved["reviews"][-1]["actor"] == "Ruth K (ruth@icpac.net)"
    assert approved["reviews"][-1]["comment"] == "Approved by email"
    # Each link works once, and the other reviewer's link no longer applies.
    again = client.post("/bulletins/email-action", json={"token": token, "decision": "approve"})
    assert again.status_code == 422 and "already been used" in again.json()["detail"]
    other = client.get("/bulletins/email-action", params={"token": link(messages[1])}).json()
    assert other["decisions"] == [] and "approved" in other["reason"]

    # The publishers get a publish link with the approved document.
    publish_mail = inbox(post_office)
    assert [m["To"] for m in publish_mail] == ["pub@icpac.net"]
    assert publish_mail[0]["Subject"] == f"Ready to publish: {draft['title']}"
    published = client.post(
        "/bulletins/email-action",
        json={"token": link(publish_mail[0]), "decision": "publish"},
    ).json()
    assert published["status"] == "published"

    # The distribution list receives the published bulletin; its header names the decision.
    released = inbox(post_office)
    assert [m["To"] for m in released] == ["list@icpac.net"]
    assert released[0]["Subject"] == f"Published: {draft['title']}"
    document = next(released[0].iter_attachments()).get_content()
    assert b"DRAFT - NOT APPROVED" not in document
    record = client.get(f"/bulletins/{draft['id']}").json()
    assert [e["step"] for e in record["emails"]] == ["review", "publish", "published"]


def test_rejections_need_a_reason_and_the_web_steps_still_email(env, fast_maps, post_office):
    run(env)
    client = env.client
    draft = client.post("/bulletins/generate", json={}).json()
    review = {"actor": "Joe N", "confirmed": True, "comment": "Ready for review"}
    client.post(f"/bulletins/{draft['id']}/submit", json=review)
    token = link(inbox(post_office)[0])
    no_reason = client.post("/bulletins/email-action", json={"token": token, "decision": "reject"})
    assert no_reason.status_code == 422 and "reason" in no_reason.json()["detail"]
    # Approving on the website emails the publishers as well.
    approved = client.post(
        f"/bulletins/{draft['id']}/approve",
        json={"actor": "Amos", "confirmed": True, "comment": "Checked the maps"},
    ).json()
    assert approved["notification"]["sent"] == ["pub@icpac.net"]
    assert inbox(post_office)[0]["Subject"].startswith("Ready to publish")
    # Sending again gives new links; a reviewer link from before no longer applies.
    resent = client.post(f"/bulletins/{draft['id']}/resend", json={"actor": "Joe N"}).json()
    assert resent["sent"] == ["pub@icpac.net"]
    stale = client.post("/bulletins/email-action", json={"token": token, "decision": "approve"})
    assert stale.status_code == 422


def test_without_a_mail_server_decisions_still_work(env, fast_maps, monkeypatch):
    for name in ("MAIL_OUTBOX_DIR", "SMTP_HOST", "BULLETIN_REVIEWERS"):
        monkeypatch.delenv(name, raising=False)
    run(env)
    client = env.client
    assert client.get("/bulletins/email-status").json()["configured"] is False
    draft = client.post("/bulletins/generate", json={}).json()
    review = {"actor": "Joe N", "confirmed": True, "comment": "Ready"}
    submitted = client.post(f"/bulletins/{draft['id']}/submit", json=review).json()
    assert submitted["status"] == "under_review"
    assert submitted["notification"]["skipped"].startswith("Email is not set up")


def test_links_expire_and_are_signed(env):
    repo = env.platform.repo
    token = mail.make_link_token(repo, "b1", "review", "Ruth@ICPAC.net", now=1_000)
    assert mail.read_link_token(repo, token, now=1_000 + 3600)["e"] == "ruth@icpac.net"
    with pytest.raises(mail.InvalidLink, match="expired"):
        mail.read_link_token(repo, token, now=1_000 + 8 * 86400)
    with pytest.raises(mail.InvalidLink):
        mail.read_link_token(repo, "not-a-token")
