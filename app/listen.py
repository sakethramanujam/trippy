"""Serve Trippy on specific host addresses that may come up after the container starts.

Used with `network_mode: host` and TRIPPY_LISTEN="192.168.1.20:8840,100.64.0.10:8840,127.0.0.1:8840".
Docker's own port publishing fails the whole container if one of those addresses doesn't exist
yet (Tailscale typically gets its 100.x address a minute or more after Docker starts at boot),
and `restart: unless-stopped` doesn't retry that. Here each address is bound on its own, retried
every few seconds until it exists, and served as soon as it does. A bound listener keeps working
if the address disappears and comes back (for example Tailscale reconnecting).
"""
from __future__ import annotations

import asyncio
import contextlib
import errno
import ipaddress
import logging
import os
import signal
import socket

import uvicorn

log = logging.getLogger("trippy.listen")
RETRY_SECONDS = 5.0


def parse(spec: str) -> list[tuple[str, int]]:
    out = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        host, _, port = part.rpartition(":")
        host = host.strip("[]")
        ipaddress.ip_address(host)  # a literal IP: binding to a name or 0.0.0.0 would defeat the point
        if host in ("0.0.0.0", "::"):
            raise ValueError("TRIPPY_LISTEN takes specific addresses, not 0.0.0.0 or ::")
        out.append((host, int(port)))
    if not out:
        raise ValueError("TRIPPY_LISTEN is empty")
    return out


def try_bind(host: str, port: int) -> socket.socket | None:
    """A listening socket on host:port, or None while that address isn't on this machine yet."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(2048)
        sock.setblocking(False)
        return sock
    except OSError as exc:
        sock.close()
        if exc.errno in (errno.EADDRNOTAVAIL, errno.EADDRINUSE):
            return None
        raise


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):  # main() handles signals for every server at once
        yield


def _config() -> uvicorn.Config:
    return uvicorn.Config("app.main:app", proxy_headers=True, server_header=False,
                          forwarded_allow_ips=os.getenv("TRIPPY_FORWARDED_ALLOW_IPS", "127.0.0.1"))


async def serve_address(host: str, port: int, servers: list, stop: asyncio.Event,
                        retry: float = RETRY_SECONDS) -> None:
    waited = False
    while not stop.is_set():
        sock = try_bind(host, port)
        if sock is not None:
            break
        if not waited:
            log.warning("trippy: %s:%d isn't available yet; retrying every %.0fs", host, port, retry)
            waited = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), retry)
    else:
        return
    log.warning("trippy: listening on %s:%d", host, port)
    server = _Server(_config())
    servers.append(server)
    await server.serve(sockets=[sock])


async def main(spec: str) -> None:
    addresses = parse(spec)
    stop, servers = asyncio.Event(), []

    def _exit(*_):
        stop.set()
        for s in servers:
            s.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _exit)
    await asyncio.gather(*(serve_address(h, p, servers, stop) for h, p in addresses))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main(os.environ["TRIPPY_LISTEN"]))
