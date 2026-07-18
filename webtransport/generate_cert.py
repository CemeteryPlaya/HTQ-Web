"""
Generate a self-signed TLS certificate for local development.

Uses the `cryptography` Python package — no external openssl binary required.
Works on Windows, macOS, and Linux.

Usage:
    pip install cryptography
    python generate_cert.py

How to trust it in Chrome (copy the printed fingerprint):
    chrome --origin-to-force-quic-on=localhost:4433 ^
           --ignore-certificate-errors-spki-list=<FINGERPRINT>

    Or simply (less secure, dev only):
    chrome --ignore-certificate-errors

For production: replace certs/cert.pem and certs/key.pem with a certificate
signed by a trusted CA (e.g. Let's Encrypt via certbot).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import sys
from pathlib import Path

CERT_DIR  = Path(__file__).parent / "certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE  = CERT_DIR / "key.pem"
DAYS_VALID = 365
WT_PORT = 4433


def _require_cryptography():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("The 'cryptography' package is required. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
        print("Installed. Re-run the script.\n")
        sys.exit(0)


def generate_cert() -> None:
    _require_cryptography()

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(parents=True, exist_ok=True)

    if CERT_FILE.exists() and KEY_FILE.exists():
        print(f"Certificate already exists: {CERT_FILE}")
        _print_fingerprint()
        return

    print("Generating self-signed RSA-2048 certificate...")

    # ── Private key ──────────────────────────────────────────────────────────
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # ── Certificate ───────────────────────────────────────────────────────────
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=DAYS_VALID))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # ── Write files ───────────────────────────────────────────────────────────
    KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Private key  : {KEY_FILE}")
    print(f"Certificate  : {CERT_FILE}")
    _print_fingerprint()


def _print_fingerprint() -> None:
    """Compute and print the SPKI SHA-256 fingerprint (base64) for Chrome."""
    _require_cryptography()

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())

    # DER-encoded SubjectPublicKeyInfo
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = base64.b64encode(hashlib.sha256(spki_der).digest()).decode()

    print()
    print("=" * 64)
    print("SPKI fingerprint (SHA-256 / base64):")
    print(f"  {fingerprint}")
    print()
    print("Start Chrome with these flags (Windows, one line):")
    print(
        f"  chrome.exe"
        f' --origin-to-force-quic-on=localhost:{WT_PORT}'
        f" --ignore-certificate-errors-spki-list={fingerprint}"
    )
    print()
    print("Or for quick local testing (skips ALL cert checks):")
    print("  chrome.exe --ignore-certificate-errors")
    print("=" * 64)


if __name__ == "__main__":
    generate_cert()
