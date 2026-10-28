"""Force IPv4 for this process.

On this network api.modal.com resolves to NAT64 IPv6 addresses (64:ff9b::/96) that
accept no connections, and Python's asyncio tries IPv6 first with no fallback.
curl falls back to IPv4, which is why the API looked "up" while the Modal client hung.
"""
import socket

_orig = socket.getaddrinfo


def _v4(host, *args, **kw):
    res = _orig(host, *args, **kw)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 or res


socket.getaddrinfo = _v4
