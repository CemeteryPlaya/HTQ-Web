"""
Generate a self-signed TLS certificate for WebTransport (QUIC) development.

Uses the `cryptography` Python package — no external openssl binary required.
Works on Windows, macOS, and Linux.

Why ECDSA P-256 and a 13-day lifetime
-------------------------------------
A browser accepts a self-signed WebTransport certificate only through
`new WebTransport(url, { serverCertificateHashes })`, and that path has hard
constraints (see the WebTransport spec / Chrome implementation):

  * the key must be ECDSA on the secp256r1 (P-256) curve;
  * total validity must not exceed 14 days;
  * the hash is SHA-256 over the DER-encoded certificate.

So this script writes an ECDSA P-256 certificate valid for 13 days and stores
its DER SHA-256 next to it, in `certs/cert.sha256` — the backend serves that
value to the frontend as part of `GET /api/cms/v1/conference/config`
(`CONFERENCE_WT_CERT_HASH_FILE`), so nobody has to copy fingerprints by hand.
Because it expires, generation runs on every container start and refreshes the
certificate when it is close to expiry.

Production: mount a certificate from a trusted CA (certbot's live directory)
over `certs/`. A CA-signed certificate is left alone — this script only ever
replaces a self-signed one it could have written itself.

Usage:
    pip install cryptography
    python generate_cert.py
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import os
import sys
from pathlib import Path

CERT_DIR  = Path(os.environ.get("WT_CERT_DIR", Path(__file__).parent / "certs"))
CERT_FILE = Path(os.environ.get("CERT_FILE", CERT_DIR / "cert.pem"))
KEY_FILE  = Path(os.environ.get("KEY_FILE", CERT_DIR / "key.pem"))
HASH_FILE = CERT_DIR / "cert.sha256"

# 13 суток при лимите браузера в 14 — сутки запаса на перезапуск контейнера.
DAYS_VALID = 13
# Обновляем заранее, чтобы сессия не оборвалась на истёкшем сертификате.
RENEW_BEFORE_DAYS = 2
WT_PORT = int(os.environ.get("WT_PORT", "4433"))


def _require_cryptography():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("The 'cryptography' package is required. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
        print("Installed. Re-run the script.\n")
        sys.exit(0)


def _san_entries():
    """SAN: localhost + 127.0.0.1 + всё, что перечислено в WT_CERT_HOSTS."""
    from cryptography import x509

    raw_hosts = os.environ.get("WT_CERT_HOSTS", "")
    hosts = ["localhost", "127.0.0.1"] + [
        host.strip() for host in raw_hosts.split(",") if host.strip()
    ]

    entries = []
    seen = set()
    for host in hosts:
        if host in seen:
            continue
        seen.add(host)
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            entries.append(x509.DNSName(host))
    return entries


def _load_existing():
    """Разобранный существующий сертификат или None."""
    if not (CERT_FILE.exists() and KEY_FILE.exists()):
        return None

    from cryptography import x509

    try:
        return x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
    except ValueError as exc:
        print(f"Existing certificate is unreadable ({exc}) — regenerating.")
        return None


def _is_self_signed(cert) -> bool:
    return cert is not None and cert.issuer == cert.subject


def _needs_regeneration(cert) -> bool:
    if cert is None:
        return True

    # Сертификат от настоящего CA (issuer != subject) не трогаем никогда:
    # это прод-сценарий с смонтированным certbot'ом.
    if not _is_self_signed(cert):
        print("CA-signed certificate detected — leaving it untouched.")
        return False

    expires_at = cert.not_valid_after_utc
    remaining = expires_at - datetime.datetime.now(datetime.timezone.utc)
    if remaining < datetime.timedelta(days=RENEW_BEFORE_DAYS):
        print(f"Self-signed certificate expires in {remaining} — regenerating.")
        return True

    from cryptography.hazmat.primitives.asymmetric import ec

    public_key = cert.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve, ec.SECP256R1
    ):
        # RSA-сертификаты старого генератора браузер через
        # serverCertificateHashes не примет.
        print("Self-signed certificate is not ECDSA P-256 — regenerating.")
        return True

    print(f"Certificate is valid until {expires_at.isoformat()} — reusing it.")
    return False


def generate_cert() -> None:
    _require_cryptography()

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(parents=True, exist_ok=True)

    existing = _load_existing()
    if not _needs_regeneration(existing):
        _write_hash_file(self_signed=_is_self_signed(existing))
        _print_fingerprints()
        return

    print(f"Generating self-signed ECDSA P-256 certificate ({DAYS_VALID} days)...")

    private_key = ec.generate_private_key(ec.SECP256R1())

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
        # Минута назад — запас на рассинхрон часов хоста и контейнера.
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=DAYS_VALID))
        .add_extension(
            x509.SubjectAlternativeName(_san_entries()),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Private key  : {KEY_FILE}")
    print(f"Certificate  : {CERT_FILE}")
    _write_hash_file()
    _print_fingerprints()


def _cert_der_sha256_hex() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def _write_hash_file(self_signed: bool = True) -> None:
    """DER SHA-256 в hex — ровно то, что ждёт serverCertificateHashes.

    Только для самоподписанного сертификата. Для сертификата от настоящего
    CA отпечаток не просто бесполезен, а вреден: браузер откажет в сессии,
    если передать serverCertificateHashes для сертификата со сроком больше
    14 дней. Поэтому старый файл в таком случае удаляем — backend отдаёт
    фронту пустой список хэшей и подключение идёт по обычной цепочке
    доверия.
    """
    if not self_signed:
        if HASH_FILE.exists():
            HASH_FILE.unlink()
            print(f"Cert hash    : removed {HASH_FILE} (CA-signed certificate)")
        return

    digest = _cert_der_sha256_hex()
    HASH_FILE.write_text(digest, encoding="utf-8")
    print(f"Cert hash    : {HASH_FILE} ({digest[:16]}…)")


def _print_fingerprints() -> None:
    """DER SHA-256 (для serverCertificateHashes) и SPKI (для флагов Chrome)."""
    _require_cryptography()

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    spki_b64 = base64.b64encode(hashlib.sha256(spki_der).digest()).decode()

    print()
    print("=" * 64)
    print("Certificate SHA-256 (hex) — serverCertificateHashes:")
    print(f"  {_cert_der_sha256_hex()}")
    print()
    print("SPKI fingerprint (SHA-256 / base64) — only for the Chrome-flag route:")
    print(
        f"  chrome.exe --origin-to-force-quic-on=localhost:{WT_PORT}"
        f" --ignore-certificate-errors-spki-list={spki_b64}"
    )
    print("=" * 64)


if __name__ == "__main__":
    generate_cert()
