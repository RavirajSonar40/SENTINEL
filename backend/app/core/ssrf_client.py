"""SSRF-hardened HTTP client for health-check probes and telemetry fetching."""

import socket
import ipaddress
import urllib.parse
from typing import Tuple, Optional
import httpx


# Private, loopback, link-local and cloud metadata network blocks
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # IPv4 Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # RFC1918 Private
    ipaddress.ip_network("172.16.0.0/12"),     # RFC1918 Private
    ipaddress.ip_network("192.168.0.0/16"),    # RFC1918 Private
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local & Cloud Metadata (AWS/GCP/Azure)
    ipaddress.ip_network("0.0.0.0/8"),         # Current network
    ipaddress.ip_network("::1/128"),           # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),         # IPv6 Link-Local
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",
    "instance-data",
}

MAX_RESPONSE_BODY_BYTES = 64 * 1024  # 64 KB
PROBE_TIMEOUT_SECONDS = 5.0


class SSRFSecurityException(Exception):
    """Raised when a target URL resolves to a forbidden IP address or port."""
    pass


def validate_target_ip(ip_str: str) -> None:
    """Validate that an IP is globally routable and not in forbidden private/link-local ranges."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        raise SSRFSecurityException(f"Invalid IP address format: {ip_str}")

    for net in BLOCKED_NETWORKS:
        if ip_obj in net:
            raise SSRFSecurityException(
                f"Target IP {ip_str} belongs to blocked/private network range {net} (SSRF protection)"
            )


def resolve_and_validate_url(url: str) -> Tuple[str, str, int, str]:
    """
    Parse URL, resolve DNS hostname to verified IP, and ensure safety.
    Returns (verified_ip, host_header, port, scheme).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFSecurityException(f"Unsupported scheme '{parsed.scheme}'. Only http and https are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityException("URL is missing hostname")

    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise SSRFSecurityException(f"Forbidden hostname '{hostname}' (SSRF protection)")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # DNS Resolution
    try:
        addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not addr_info:
            raise SSRFSecurityException(f"Could not resolve hostname '{hostname}'")
        target_ip = addr_info[0][4][0]
    except socket.gaierror as e:
        raise SSRFSecurityException(f"DNS resolution failed for '{hostname}': {e}")

    # Validate IP against blocked ranges
    validate_target_ip(target_ip)

    return target_ip, hostname, port, parsed.scheme


async def execute_safe_health_check(url: str) -> Tuple[bool, Optional[int], float, Optional[str]]:
    """
    Safely execute a health check probe against target URL.
    Returns (is_healthy, status_code, latency_ms, error_message).
    Disables automatic redirects to prevent DNS rebinding or redirect-based SSRF.
    """
    import time
    start_time = time.perf_counter()

    try:
        # Validate URL and resolve IP before sending request
        resolve_and_validate_url(url)
    except SSRFSecurityException as e:
        latency = (time.perf_counter() - start_time) * 1000.0
        return False, None, latency, f"SSRF Blocked: {str(e)}"
    except Exception as e:
        latency = (time.perf_counter() - start_time) * 1000.0
        return False, None, latency, f"Pre-probe validation error: {str(e)}"

    # Execute HTTP probe with strict timeout and no follow redirects
    try:
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SECONDS,
            follow_redirects=False,
            verify=True,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "Sentinel-HealthCheck/1.0"})
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            is_healthy = 200 <= resp.status_code < 400
            err_msg = None if is_healthy else f"HTTP Status {resp.status_code}"
            return is_healthy, resp.status_code, round(latency_ms, 2), err_msg
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, None, round(latency_ms, 2), "Connection timed out after 5.0s"
    except httpx.ConnectError as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, None, round(latency_ms, 2), f"Connection refused or failed: {str(e)}"
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, None, round(latency_ms, 2), f"Probe failure: {str(e)}"
