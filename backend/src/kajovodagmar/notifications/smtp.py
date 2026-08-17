from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True, slots=True)
class SMTPConfiguration:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    use_starttls: bool = True

    @property
    def use_implicit_tls(self) -> bool:
        return self.port == 465 and not self.use_starttls


class SMTPMailer:
    def __init__(self, config: SMTPConfiguration) -> None:
        self.config = config

    async def send(self, recipient: str, subject: str, text: str) -> str:
        return await asyncio.to_thread(self._send_sync, recipient, subject, text)

    def _send_sync(self, recipient: str, subject: str, text: str) -> str:
        message = EmailMessage()
        message["From"] = self.config.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)
        context = ssl.create_default_context()
        if self.config.use_implicit_tls:
            smtp = smtplib.SMTP_SSL(self.config.host, self.config.port, timeout=20, context=context)
        else:
            smtp = smtplib.SMTP(self.config.host, self.config.port, timeout=20)
        with smtp:
            if self.config.use_starttls:
                smtp.starttls(context=context)
            if self.config.username and self.config.password:
                smtp.login(self.config.username, self.config.password)
            refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("SMTP server odmítl jednoho nebo více příjemců.")
        return message["Message-ID"] or "accepted"
