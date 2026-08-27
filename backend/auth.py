"""Optional authentication, with an *arr-style local-network bypass.

Cleanarr deletes files. Until now it had no authentication at all and an
unrestricted CORS policy, so anything able to reach the port could issue a
delete - including a page open in a browser on the same network.

This adds HTTP Basic auth with the same shape Sonarr and Radarr use:
"authentication required, except for local addresses". Requests from trusted
subnets skip the prompt; anything else must authenticate.

Auth is OFF unless credentials are configured, so an existing deployment keeps
working exactly as before after an upgrade and nobody gets locked out of their
own tool. A warning is logged at startup when it is off.

Configuration:

    AUTH_USERNAME / AUTH_PASSWORD   set BOTH to enable auth. Unset = disabled.
    AUTH_LOCAL_BYPASS   (default 1) skip auth for AUTH_TRUSTED_SUBNETS
    AUTH_TRUSTED_SUBNETS            comma-separated CIDRs treated as "local".
                                    Defaults to loopback + RFC1918 + unique
                                    local IPv6, which is what an *arr means by
                                    a local address.
    AUTH_TRUSTED_PROXIES            comma-separated CIDRs whose
                                    X-Forwarded-For header is honoured. Empty
                                    by default: X-Forwarded-For is trivially
                                    spoofable, so it is ignored unless the
                                    request actually arrives from a proxy you
                                    have named here.
    CORS_ORIGINS                    comma-separated origins allowed to call the
                                    API cross-origin. Empty by default, which
                                    means same-origin only.
"""

import ipaddress
import os
from functools import wraps

from flask import Response, request

from logger import get_logger

logger = get_logger(__name__)

# What an *arr calls a "local address".
DEFAULT_TRUSTED_SUBNETS = (
    "127.0.0.0/8,::1/128,"          # loopback
    "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,"  # RFC1918
    "169.254.0.0/16,fe80::/10,"    # link-local
    "fc00::/7"                     # unique local IPv6
)

# Loopback is always trusted regardless of AUTH_LOCAL_BYPASS: the container's
# own healthcheck calls in on 127.0.0.1, and a process inside the container is
# already past any boundary auth could defend.
ALWAYS_TRUSTED = ("127.0.0.0/8", "::1/128")


def _parse_networks(raw):
    networks = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid CIDR in configuration: %s", entry)
    return networks


class Auth:
    def __init__(self):
        self.username = os.environ.get("AUTH_USERNAME", "").strip()
        self.password = os.environ.get("AUTH_PASSWORD", "").strip()
        self.local_bypass = os.environ.get("AUTH_LOCAL_BYPASS", "1") != "0"
        self.trusted = _parse_networks(
            os.environ.get("AUTH_TRUSTED_SUBNETS", DEFAULT_TRUSTED_SUBNETS))
        self.always_trusted = _parse_networks(",".join(ALWAYS_TRUSTED))
        self.trusted_proxies = _parse_networks(os.environ.get("AUTH_TRUSTED_PROXIES", ""))

        if self.enabled:
            logger.info(
                "Auth enabled for user '%s' (local bypass: %s, %s trusted subnet(s))",
                self.username, "on" if self.local_bypass else "off", len(self.trusted))
        else:
            logger.warning(
                "AUTH IS DISABLED - set AUTH_USERNAME and AUTH_PASSWORD to require "
                "a login. Anyone who can reach this port can delete media.")

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password)

    def client_ip(self) -> str:
        """The caller's address, honouring X-Forwarded-For only behind a proxy
        we were explicitly told to trust."""
        peer = request.remote_addr or ""
        if self.trusted_proxies and self._in(peer, self.trusted_proxies):
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                # Left-most entry is the original client.
                return forwarded.split(",")[0].strip()
        return peer

    @staticmethod
    def _in(addr, networks) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return any(ip in net for net in networks)

    def is_local(self, addr) -> bool:
        if self._in(addr, self.always_trusted):
            return True
        return self.local_bypass and self._in(addr, self.trusted)

    def check(self):
        """Return a 401 response when the request must authenticate and has not."""
        if not self.enabled:
            return None

        addr = self.client_ip()
        if self.is_local(addr):
            return None

        creds = request.authorization
        if creds and creds.username == self.username and creds.password == self.password:
            return None

        logger.warning("Rejected unauthenticated request from %s for %s",
                       addr or "unknown", request.path)
        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="Cleanarr"'})


_auth = None


def get_auth() -> Auth:
    global _auth
    if _auth is None:
        _auth = Auth()
    return _auth


def requires_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        denied = get_auth().check()
        if denied is not None:
            return denied
        return view(*args, **kwargs)
    return wrapped
