#!/usr/bin/env python3
"""Find out why DeepSeek is unreachable from this machine.

The OpenAI SDK collapses everything -- blocked DNS, closed TCP port, TLS
mismatch, wrong key, geo-block -- into one message: "Connection error." That
tells you nothing about the fix. This runs each layer as its own test and
reports the one that failed, with the fix for it.

Reads the key from --api-key, DEEPSEEK_API_KEY, or deepseek-key.txt.
"""

import argparse
import socket
import ssl
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HOST = "api.deepseek.com"
PORT = 443
TIMEOUT = 15.0

class _Tee:
    """Write every print to the console AND to a log file.

    Simpler than teaching everyone to pipe stdout, and works the same way
    whether the script is double-clicked, run in a terminal, or called from
    another Python process.
    """

    def __init__(self, stream, path):
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8", newline="")

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def close(self):
        try:
            self.file.close()
        except Exception:
            pass


LOG_FILE = Path(__file__).resolve().parent / "diagnose_deepseek.log"

OK, FAIL, SKIP = "OK  ", "FAIL", "skip"


def line(status, name, detail=""):
    print(f"  [{status}] {name}" + (f"  --  {detail}" if detail else ""))


def check_dns():
    """Can this box resolve api.deepseek.com?"""
    try:
        infos = socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM)
        addrs = sorted({info[4][0] for info in infos})
        line(OK, "DNS resolves " + HOST, ", ".join(addrs))
        return addrs
    except socket.gaierror as e:
        line(FAIL, "DNS resolves " + HOST, str(e))
        print("\n  DNS is broken on this box. Check:")
        print("    ping 8.8.8.8   (basic network)")
        print("    nslookup api.deepseek.com")
        return None


def check_tcp(addrs):
    """Can we actually reach 443, or is a firewall dropping it?"""
    for addr in addrs:
        start = time.time()
        sock = socket.socket(
            socket.AF_INET6 if ":" in addr else socket.AF_INET, socket.SOCK_STREAM
        )
        sock.settimeout(TIMEOUT)
        try:
            sock.connect((addr, PORT))
            ms = (time.time() - start) * 1000
            line(OK, f"TCP connect to {addr}:{PORT}", f"{ms:.0f} ms")
            sock.close()
            return addr
        except (socket.timeout, OSError) as e:
            line(FAIL, f"TCP connect to {addr}:{PORT}", str(e))
        finally:
            try:
                sock.close()
            except Exception:
                pass

    print("\n  A firewall is blocking outbound HTTPS to " + HOST + ".")
    print("  If this is a cloud VPS, some providers block outbound ports on")
    print("  new accounts, or region-block certain destinations. Check the")
    print("  provider's firewall / security group.")
    return None


def check_tls():
    """Does the TLS handshake complete and does the cert verify?"""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as raw:
            with ctx.wrap_socket(raw, server_hostname=HOST) as tls:
                cert = tls.getpeercert()
        cn = dict(x[0] for x in cert.get("subject", [])).get("commonName", "?")
        line(OK, "TLS handshake and cert verify", "CN=" + str(cn))
        return True
    except ssl.SSLCertVerificationError as e:
        line(FAIL, "TLS certificate verification", str(e))
        print("\n  A TLS-inspecting proxy is intercepting the connection and")
        print("  its root is not trusted here. On Windows the cure is usually:")
        print("    set SSL_CERT_FILE=")
        print("  and let Python use the OS trust store.")
        return False
    except Exception as e:
        line(FAIL, "TLS handshake", type(e).__name__ + ": " + str(e))
        return False


def check_https_get():
    """Actually speak HTTPS to the host."""
    try:
        import httpx
    except ImportError:
        line(SKIP, "HTTPS GET /", "httpx not installed - pip install httpx")
        return None
    try:
        ctx = ssl.create_default_context()
        with httpx.Client(verify=ctx, timeout=TIMEOUT) as client:
            r = client.get("https://" + HOST + "/")
        line(OK, "HTTPS GET /", f"HTTP {r.status_code}")
        return r.status_code
    except Exception as e:
        line(FAIL, "HTTPS GET /", type(e).__name__ + ": " + str(e))
        return None


def check_auth(api_key):
    """Try one real API call. Distinguishes 'unreachable' from 'unauthorised'."""
    if not api_key:
        line(SKIP, "API auth", "no key found (--api-key / DEEPSEEK_API_KEY / deepseek-key.txt)")
        return None
    try:
        import httpx
    except ImportError:
        line(SKIP, "API auth", "httpx not installed")
        return None
    try:
        ctx = ssl.create_default_context()
        with httpx.Client(verify=ctx, timeout=TIMEOUT) as client:
            r = client.get(
                "https://" + HOST + "/v1/models",
                headers={"Authorization": "Bearer " + api_key},
            )
    except Exception as e:
        line(FAIL, "API auth", type(e).__name__ + ": " + str(e))
        return None

    if r.status_code == 200:
        line(OK, "API auth", "200 OK - the key works and the pipeline should run")
        return True
    if r.status_code == 401:
        line(FAIL, "API auth", "401 Unauthorized - the key is wrong or revoked")
        print("\n  Check deepseek-key.txt: no stray spaces, no line breaks in the middle,")
        print("  and confirm the key is active in the DeepSeek dashboard.")
        return False
    if r.status_code == 403:
        line(FAIL, "API auth", "403 Forbidden - key valid but this call is blocked")
        print("\n  DeepSeek geo-blocks some regions. If this VPS is in one of them,")
        print("  the pipeline needs to run from somewhere else, or through a proxy.")
        return False
    line(FAIL, "API auth", f"HTTP {r.status_code}: {r.text[:200]}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Diagnose DeepSeek connectivity from this machine.")
    parser.add_argument("--api-key")
    args = parser.parse_args()

    # Everything printed from here on goes to the log file as well.
    tee_out = _Tee(sys.stdout, LOG_FILE)
    tee_err = _Tee(sys.stderr, LOG_FILE)  # same file, appended in order
    sys.stdout, sys.stderr = tee_out, tee_err

    print("\n  " + "=" * 66)
    print(f"   DEEPSEEK CONNECTIVITY CHECK  -  {HOST}:{PORT}")
    print("  " + "=" * 66)

    import caption_text
    key = caption_text.load_api_key(args.api_key)

    addrs = check_dns()
    if not addrs:
        return 1
    if not check_tcp(addrs):
        return 1
    if not check_tls():
        return 1
    if check_https_get() is None:
        return 1

    print()
    result = check_auth(key)
    print("\n  " + "=" * 66)
    print("  Log written to: " + str(LOG_FILE))
    print("  " + "=" * 66)
    sys.stdout, sys.stderr = tee_out.stream, tee_err.stream
    tee_out.close(); tee_err.close()
    return 0 if result else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
