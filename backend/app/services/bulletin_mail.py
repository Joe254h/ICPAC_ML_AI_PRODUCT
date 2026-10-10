"""The bulletin review by email.

Submitting a draft emails each reviewer a personal link; approving it (by email or on the
website) emails the publishers a publish link; publishing it sends the approved Word
bulletin to the distribution list; a rejection is reported to the reviewers. A link opens
the bulletin on the website with the decision buttons (see backend.app.services.mail).
"""

from __future__ import annotations

import html
import re
from typing import Any

from backend.app.db import now
from backend.app.schemas import ReviewRequest
from backend.app.services import mail
from backend.app.services.bulletins import WEEKLY, BulletinService

DOCX = ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")

#: The step a link allows, the status it needs and the decisions it offers.
STEPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "review": ("under_review", ("approve", "reject")),
    "publish": ("approved", ("publish",)),
}


def headline(bulletin: dict) -> str:
    for section in (bulletin.get("facts") or {}).get("sections") or []:
        if section.get("key") == "headline" and section.get("text"):
            return str(section["text"][0])
    return ""


def latest_review(bulletin: dict) -> dict:
    return (bulletin.get("reviews") or [{}])[-1]


def email_status() -> dict[str, Any]:
    """Whether the review emails can go out, and to how many people, in words."""
    mailer = mail.Mailer()
    return {
        "configured": mailer.configured,
        "problem": mailer.problem(),
        "reviewers": len(mail.reviewers()),
        "publishers": len(mail.publishers()),
        "distribution": len(mail.distribution()),
    }


def _page(title: str, paragraphs: list[str], button: tuple[str, str] | None, link: str) -> str:
    body = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55">{html.escape(p)}</p>' for p in paragraphs
    )
    action = (
        f'<p style="margin:22px 0"><a href="{html.escape(button[1])}" '
        'style="background:#1d6b3d;color:#fff;text-decoration:none;padding:12px 22px;'
        f'border-radius:6px;font-weight:600;display:inline-block">{html.escape(button[0])}</a></p>'
        if button
        else ""
    )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#212529;max-width:600px">'
        '<p style="margin:0 0 4px;font-size:13px;color:#2a7f4b;font-weight:700">'
        "ICPAC · IGAD Climate Prediction and Applications Centre</p>"
        f'<h1 style="font-size:20px;margin:0 0 18px">{html.escape(title)}</h1>'
        f"{body}{action}"
        f'<p style="margin:18px 0 0;font-size:13px;color:#6b7176">Bulletin page: '
        f'<a href="{html.escape(link)}" style="color:#1d6b3d">{html.escape(link)}</a></p>'
        "</div>"
    )


def compose(
    bulletin: dict, step: str, link: str | None
) -> tuple[str, list[str], tuple[str, str] | None]:
    """Subject, paragraphs and button of the email for a bulletin's new status."""
    title = bulletin["title"]
    review = latest_review(bulletin)
    who = review.get("actor", "a forecaster")
    note = (review.get("comment") or "").strip()
    lead = headline(bulletin)
    if step == "review":
        paragraphs = [
            f"{who} has submitted the {title} for review.",
            *([f"Headline: {lead}"] if lead else []),
            "Open the link to read the bulletin and approve or reject it. The Word document "
            "is attached. The link is personal, works once and expires in 7 days.",
        ]
        return f"Approval requested: {title}", paragraphs, ("Review the bulletin", link or "")
    if step == "publish":
        paragraphs = [
            f"{who} approved the {title}." + (f' Their note: "{note}"' if note else ""),
            "The approved text and maps are sealed. Open the link to publish it; the Word "
            "document is attached. The link is personal, works once and expires in 7 days.",
        ]
        return f"Ready to publish: {title}", paragraphs, ("Publish the bulletin", link or "")
    if step == "published":
        paragraphs = [
            f"The {title} has been published by ICPAC.",
            *([lead] if lead else []),
            "The approved bulletin is attached.",
        ]
        return f"Published: {title}", paragraphs, None
    paragraphs = [
        f"{who} rejected the {title}." + (f' Reason: "{note}"' if note else ""),
        "A revised draft can be made from the same forecast on the bulletin page.",
    ]
    return f"Rejected: {title}", paragraphs, None


def notify(platform, bulletin: dict) -> dict[str, Any]:
    """Email the people the bulletin's new status concerns, and record what was sent."""
    status = bulletin["status"]
    step, recipients = {
        "under_review": ("review", mail.reviewers()),
        "approved": ("publish", mail.publishers()),
        "published": ("published", mail.distribution()),
        "rejected": ("rejected", mail.reviewers()),
    }.get(status, ("", []))
    result: dict[str, Any] = {"step": step, "at": now(), "sent": [], "failed": [], "skipped": None}
    mailer = mail.Mailer()
    if not step:
        return result
    if not mailer.configured:
        result["skipped"] = f"Email is not set up ({mailer.problem()})."
    elif not recipients:
        result["skipped"] = {
            "review": "No reviewers' addresses are set up.",
            "publish": "No publishers' addresses are set up.",
            "published": "No distribution list is set up.",
            "rejected": "No reviewers' addresses are set up.",
        }[step]
    else:
        page = f"{mail.site_url()}/bulletins?id={bulletin['id']}"
        attachments = []
        if bulletin.get("kind") == WEEKLY and step != "rejected":
            name = re.sub(r"[^A-Za-z0-9-]+", "_", bulletin["title"]).strip("_") + ".docx"
            document = BulletinService(platform).released(bulletin)
            attachments = [mail.Attachment(name, document, *DOCX)]
        for address in recipients:
            link = None
            if step in STEPS:
                token = mail.make_link_token(platform.repo, bulletin["id"], step, address)
                link = f"{mail.site_url()}/bulletins/action?token={token}"
            subject, paragraphs, button = compose(bulletin, step, link)
            text = "\n\n".join(
                paragraphs + ([f"{button[0]}: {button[1]}"] if button else []) + [page]
            )
            try:
                mailer.send(
                    address,
                    subject,
                    text,
                    _page(subject, paragraphs, button, page),
                    attachments,
                )
                result["sent"].append(address)
            except Exception as exc:  # one bad address or a mail-server hiccup
                result["failed"].append({"to": address, "reason": type(exc).__name__})
    record = platform.repo.get("bulletin", bulletin["id"])
    record.setdefault("emails", []).append(result)
    platform.repo.save("bulletin", record, bulletin["id"])
    bulletin["emails"] = record["emails"]
    return result


def describe_link(platform, token: str) -> dict[str, Any]:
    """What a link allows, for the page it opens; nothing changes."""
    link = mail.read_link_token(platform.repo, token)
    bulletin = platform.repo.get("bulletin", link["b"])
    needed, decisions = STEPS[link["s"]]
    allowed = bulletin["status"] == needed and _still_listed(link)
    return {
        "step": link["s"],
        "email": link["e"],
        "decisions": list(decisions) if allowed else [],
        "reason": None
        if allowed
        else (
            "This address is no longer on the list for this step."
            if bulletin["status"] == needed
            else f"The bulletin is {bulletin['status'].replace('_', ' ')}; this link no longer "
            "applies."
        ),
        "bulletin": {
            "id": bulletin["id"],
            "title": bulletin["title"],
            "status": bulletin["status"],
            "headline": headline(bulletin),
            "period": (bulletin.get("facts") or {}).get("period"),
            "reviews": bulletin.get("reviews") or [],
        },
    }


def _still_listed(link: dict) -> bool:
    listed = mail.reviewers() if link["s"] == "review" else mail.publishers()
    return link["e"] in {a.lower() for a in listed}


def act_on_link(platform, token: str, decision: str, name: str | None, comment: str | None) -> dict:
    """Apply the decision a link allows, as the person it was sent to."""
    link = mail.read_link_token(platform.repo, token)
    needed, decisions = STEPS[link["s"]]
    if decision not in decisions:
        raise ValueError("This link does not allow that decision")
    if not _still_listed(link):
        raise mail.InvalidLink("This address is no longer on the list for this step.")
    bulletin = platform.repo.get("bulletin", link["b"])
    if bulletin["status"] != needed:
        raise mail.InvalidLink(
            f"The bulletin is {bulletin['status'].replace('_', ' ')}; this link no longer applies."
        )
    note = (comment or "").strip()
    if decision == "reject" and not note:
        raise ValueError("Give a reason for the rejection")
    default = {"approve": "Approved by email", "publish": "Published by email"}
    who = f"{name.strip()} ({link['e']})" if name and name.strip() else link["e"]
    review = ReviewRequest(
        actor=who[:80], confirmed=True, comment=note or default.get(decision, "By email")
    )
    mail.spend_link(platform.repo, link)
    return BulletinService(platform).transition(link["b"], decision, review)
