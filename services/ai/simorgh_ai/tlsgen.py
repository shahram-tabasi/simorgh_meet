"""Local CA + server certificate generation (installer fallback when the host has no openssl).

python -m simorgh_ai.tlsgen --out DIR --cn HOST --san "DNS:a,IP:1.2.3.4" [--org NAME]
Writes ca.key/ca.crt (kept if present) and server.key/server.crt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)


def _san(spec: str) -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        kind, _, value = item.partition(":")
        if kind.upper() == "IP":
            names.append(x509.IPAddress(ipaddress.ip_address(value)))
        else:
            names.append(x509.DNSName(value))
    return names


def generate(out: Path, cn: str, san: str, org: str = "Simorgh Meet") -> None:
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    ca_key_path, ca_crt_path = out / "ca.key", out / "ca.crt"
    if ca_key_path.exists() and ca_crt_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(ca_crt_path.read_bytes())
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Simorgh Meet"),
                          x509.NameAttribute(NameOID.COMMON_NAME, "Simorgh Meet Local CA")])
        ca_cert = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        _write_key(ca_key_path, ca_key)
        ca_crt_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org[:64] or "Simorgh Meet"),
                                 x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(_san(san)), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(out / "server.key", key)
    (out / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                                     + ca_cert.public_bytes(serialization.Encoding.PEM))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--cn", required=True)
    parser.add_argument("--san", required=True)
    parser.add_argument("--org", default="Simorgh Meet")
    args = parser.parse_args()
    generate(Path(args.out), args.cn, args.san, args.org)


if __name__ == "__main__":
    main()
