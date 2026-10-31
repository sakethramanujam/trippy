"""Optional built-in SMTP receiver for email-in (TRIPPY_INBOUND_MODE=smtp). Off by default.

It only accepts mail addressed to this server's per-user addresses (see TRIPPY_INBOUND_ADDRESS_TEMPLATE),
so it can't be used as a relay. It speaks plain SMTP on TRIPPY_INBOUND_SMTP_PORT (2525 by default);
receiving mail from the internet needs an MX record pointing here and port 25 forwarded to it, which
puts this port on the open internet. SELF_HOSTING.md explains the trade-offs and the IMAP alternative.
"""
from __future__ import annotations

import logging

from . import inbound

log = logging.getLogger("trippy.inbound")


class Handler:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not inbound.accepts_recipient(address):
            return "550 5.1.1 No such mailbox here"
        if len(envelope.rcpt_tos) >= 10:
            return "452 4.5.3 Too many recipients"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        raw = envelope.original_content or envelope.content
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        if len(raw) > inbound.max_bytes():
            return "552 5.3.4 Message too big"
        db = self.session_factory()
        try:
            inbound.receive(db, raw, tuple(envelope.rcpt_tos))
            inbound.STATUS["last_poll"] = inbound.datetime.utcnow()
            inbound.STATUS["last_error"] = None
        except Exception:
            log.exception("inbound: SMTP message failed")
            return "451 4.3.0 Try again later"
        finally:
            db.close()
        return "250 OK"


def start(session_factory):
    from aiosmtpd.controller import Controller
    host = inbound._env("SMTP_HOST", "0.0.0.0") or "0.0.0.0"
    port = int(inbound._env("SMTP_PORT") or 2525)
    ctl = Controller(Handler(session_factory), hostname=host, port=port,
                     data_size_limit=inbound.max_bytes(), server_hostname="trippy")
    ctl.start()
    log.info("inbound: SMTP receiver listening on %s:%s", host, port)
    return ctl
