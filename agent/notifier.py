"""
Notifier — dispatches alerts via email, Slack, and/or generic webhook.
All credentials are sourced exclusively from AgentConfig (loaded from .env).
"""

from __future__ import annotations

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Sequence

import httpx

from agent.config import AgentConfig
from agent.models import RecallRecord

logger = logging.getLogger(__name__)


def _should_notify(record: RecallRecord, config: AgentConfig) -> bool:
    nc = config.notifications
    if nc.notify_all:
        return True
    if nc.notify_class_i and record.is_class_i:
        return True
    if nc.notify_class_ii and "II" in record.classification.upper() and "III" not in record.classification.upper():
        return True
    return False


def _summarise(records: Sequence[RecallRecord]) -> str:
    lines = [f"• [{r.class_label}] {r.recalling_firm}: {r.product_description[:80]}" for r in records]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────────────────────

class EmailNotifier:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def send(self, records: Sequence[RecallRecord]) -> None:
        if not records:
            return
        ec = self.config.notifications.email
        if not ec.enabled:
            return
        if not self.config.smtp_user or not self.config.smtp_password:
            logger.warning("Email notifications enabled but SMTP credentials not set in .env")
            return

        to_list = self.config.email_to
        if not to_list:
            logger.warning("Email notifications enabled but EMAIL_TO is empty.")
            return

        class_i = [r for r in records if r.is_class_i]
        subject = (
            f"🚨 FDA RECALL ALERT — {len(class_i)} Class I recall(s) detected"
            if class_i
            else f"FDA Recall Monitor — {len(records)} new recall(s)"
        )
        body_text = (
            f"FDA Recall Monitor detected {len(records)} new recall(s):\n\n"
            + _summarise(records)
            + "\n\nCheck your dashboard or the attached report for details."
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.email_from
        msg["To"] = ", ".join(to_list)
        msg.attach(MIMEText(body_text, "plain"))

        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.sendmail(self.config.email_from, to_list, msg.as_string())
            logger.info("Email notification sent to %s", to_list)
        except Exception as exc:
            logger.error("Failed to send email notification: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Slack
# ─────────────────────────────────────────────────────────────────────────────

class SlackNotifier:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def send(self, records: Sequence[RecallRecord]) -> None:
        if not records:
            return
        if not self.config.notifications.slack.enabled:
            return
        url = self.config.slack_webhook_url
        if not url:
            logger.warning("Slack notifications enabled but SLACK_WEBHOOK_URL not set in .env")
            return

        class_i = [r for r in records if r.is_class_i]
        emoji = "🚨" if class_i else "⚠️"
        header = (
            f"{emoji} *{len(class_i)} Class I recall(s)* detected by FDA Recall Monitor"
            if class_i
            else f"{emoji} *{len(records)} new recall(s)* detected"
        )

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "FDA Recall Monitor Alert"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "divider"},
        ]
        for r in records[:10]:   # Slack block limit
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{r.class_label}* | _{r.category.capitalize()}_ | {r.report_date}\n"
                        f"*Firm:* {r.recalling_firm}\n"
                        f"*Product:* {r.product_description[:120]}"
                    ),
                },
            })
        if len(records) > 10:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"… and {len(records) - 10} more."}],
            })

        payload = {"blocks": blocks}
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("Slack notification sent (%d records).", len(records))
        except Exception as exc:
            logger.error("Failed to send Slack notification: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Generic webhook
# ─────────────────────────────────────────────────────────────────────────────

class WebhookNotifier:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def send(self, records: Sequence[RecallRecord]) -> None:
        if not records:
            return
        if not self.config.notifications.webhook.enabled:
            return
        url = self.config.webhook_url
        if not url:
            logger.warning("Webhook notifications enabled but WEBHOOK_URL not set in .env")
            return

        payload = {
            "event": "fda_recalls_detected",
            "count": len(records),
            "recalls": [r.to_dict() for r in records],
        }
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("Webhook notification sent (%d records).", len(records))
        except Exception as exc:
            logger.error("Failed to send webhook notification: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Composite notifier
# ─────────────────────────────────────────────────────────────────────────────

class Notifier:
    """Fan-out notifier that dispatches to all configured channels."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._email = EmailNotifier(config)
        self._slack = SlackNotifier(config)
        self._webhook = WebhookNotifier(config)

    def notify(self, records: Sequence[RecallRecord]) -> None:
        """Send notifications for records that meet alert thresholds."""
        to_notify = [r for r in records if _should_notify(r, self._config)]
        if not to_notify:
            logger.debug("No records met notification threshold.")
            return
        logger.info("Dispatching notifications for %d qualifying record(s).", len(to_notify))
        self._email.send(to_notify)
        self._slack.send(to_notify)
        self._webhook.send(to_notify)
