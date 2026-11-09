"""Public refresh admission policy and trusted peer extraction."""
import hashlib
import hmac
import ipaddress
from typing import Any, Dict, Optional


def source_key(peer, forwarded, trusted_proxies, secret):
    if not secret:
        raise ValueError("missing source limit secret")
    networks = [ipaddress.ip_network(value.strip()) for value in trusted_proxies.split(",") if value.strip()]
    address = ipaddress.ip_address(peer)
    # Walk from the actual connected peer through only explicitly trusted proxy hops.
    if any(address in network for network in networks):
        hops = [part.strip() for part in (forwarded or "").split(",") if part.strip()]
        if len(hops) > 16:
            raise ValueError("too many forwarded hops")
        for hop in reversed(hops):
            if not any(address in network for network in networks):
                break
            address = ipaddress.ip_address(hop)
    return hmac.new(secret.encode(), str(address).encode(), hashlib.sha256).hexdigest()


async def submit_refresh(service, *, server, name, peer, forwarded, trusted_proxies, secret):
    if not service.enabled():
        return {"state": "disabled"}, 200
    if not server or not name or len(server) > 64 or len(name) > 128:
        return {"state": "invalid_params"}, 400
    try:
        key = source_key(peer, forwarded, trusted_proxies, secret)
        if not await service.repo.allow_source(key):
            return {"state": "rate_limited", "retry_after_seconds": 60}, 429
        return await service.submit(server=server, name=name), 200
    except Exception:
        return {"state": "storage_unavailable", "retry_after_seconds": 60}, 503
