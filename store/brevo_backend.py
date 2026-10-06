"""
Sends the shop's emails through Brevo's HTTPS API instead of SMTP.

Render's free plan blocks the SMTP ports (25, 465 and 587), so
smtp-relay.brevo.com cannot be reached from there. HTTPS is never blocked.

It is switched on by setting BREVO_API_KEY (see settings.py). Every
send_mail() call in the project then works unchanged. A failed send is written
to the log (Render's Logs tab) and, like before, never stops an order.
"""

import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def _person(address):
    """'Bags & Beyond <orders@example.com>' -> {"name": ..., "email": ...}"""

    name, email = parseaddr(address)

    person = {"email": email}

    if name:
        person["name"] = name

    return person


class BrevoEmailBackend(BaseEmailBackend):

    def send_messages(self, email_messages):

        sent = 0

        for message in email_messages:

            try:

                if self._send(message):
                    sent += 1

            except Exception:

                logger.exception(
                    "Could not send the email %r through Brevo",
                    message.subject,
                )

                if not self.fail_silently:
                    raise

        return sent

    def _send(self, message):

        api_key = getattr(settings, "BREVO_API_KEY", "")

        if not api_key:
            raise RuntimeError("BREVO_API_KEY is not set")

        if not message.to:
            return False

        payload = {
            "sender": _person(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "to": [_person(address) for address in message.to],
            "subject": message.subject,
        }

        if message.cc:
            payload["cc"] = [_person(address) for address in message.cc]

        if message.bcc:
            payload["bcc"] = [_person(address) for address in message.bcc]

        if message.reply_to:
            payload["replyTo"] = _person(message.reply_to[0])

        # The text of the email, plus an HTML version when there is one.
        if message.content_subtype == "html":
            payload["htmlContent"] = message.body
        else:
            payload["textContent"] = message.body or " "

        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                payload["htmlContent"] = content
                break

        response = requests.post(
            BREVO_SEND_URL,
            json=payload,
            headers={"api-key": api_key, "accept": "application/json"},
            timeout=getattr(settings, "EMAIL_TIMEOUT", None) or 10,
        )

        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"Brevo answered {response.status_code}: {response.text[:300]}"
            )

        return True