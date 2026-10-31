"""app.listen: serve on specific addresses, waiting for ones that appear late (Tailscale at boot)."""
import asyncio
import json
import socket
import urllib.request

import pytest

from app import listen


def test_parse_takes_specific_ips_only():
    assert listen.parse("192.168.1.20:8840, 100.64.0.10:8840,[::1]:9") == [
        ("192.168.1.20", 8840), ("100.64.0.10", 8840), ("::1", 9)]
    for bad in ("0.0.0.0:8840", "myserver.local:8840", ""):
        with pytest.raises(ValueError):
            listen.parse(bad)


def test_missing_address_is_retried_while_others_serve(monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert listen.try_bind("192.0.2.1", port) is None  # TEST-NET: not on this machine

    async def scenario():
        stop, servers = asyncio.Event(), []
        late = asyncio.create_task(listen.serve_address("192.0.2.1", port, servers, stop, retry=0.05))
        live = asyncio.create_task(listen.serve_address("127.0.0.1", port, servers, stop, retry=0.05))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if servers and servers[0].started:
                break
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5).read())
        assert not late.done() and len(servers) == 1  # still waiting for the missing address
        stop.set()
        for srv in servers:
            srv.should_exit = True
        await asyncio.wait_for(asyncio.gather(late, live), 10)
        return json.loads(body)

    assert asyncio.run(scenario())["status"] == "healthy"
