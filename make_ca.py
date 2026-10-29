"""A small certificate authority for installations without a public one.

    python make_ca.py ca                      new CA, as JSON on stdout
    python make_ca.py cert CA.json HOST...    server certificate for HOSTs

Used by the installer (deploy/locanoto-setup.py) when an installation is
only reachable inside the company network: it creates the CA once, keeps
it, and the web server (Caddy) or cert-manager issues and renews the
server certificates with it. People import the CA certificate (ca.crt)
once into their browsers or the company's device management, and every
LocaNoto address is trusted.

Output is JSON ({"crt": PEM, "key": PEM}) so the installer can run this
anywhere the image runs -- locally, in Docker or in a Kubernetes pod --
and read the result from stdout. Nothing is written to disk here.

HOSTs may be names or IP addresses.
"""
import datetime
import ipaddress
import json
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
CERT_DAYS = 397          # what browsers accept for a server certificate


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def new_ca(name="LocaNoto internal CA"):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME,
                                            "LocaNoto")])
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(minutes=5))
            .not_valid_after(_now() + datetime.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0),
                           critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(
                key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return {"crt": cert.public_bytes(serialization.Encoding.PEM).decode(),
            "key": _pem_key(key)}


def server_cert(ca, hosts):
    ca_cert = x509.load_pem_x509_certificate(ca["crt"].encode())
    ca_key = serialization.load_pem_private_key(ca["key"].encode(), None)
    key = ec.generate_private_key(ec.SECP256R1())
    names = []
    for h in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            names.append(x509.DNSName(h))
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                                        hosts[0])]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(minutes=5))
            .not_valid_after(_now() + datetime.timedelta(days=CERT_DAYS))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .add_extension(x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return {"crt": cert.public_bytes(serialization.Encoding.PEM).decode(),
            "key": _pem_key(key)}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "ca":
        print(json.dumps(new_ca()))
        return 0
    if len(sys.argv) >= 4 and sys.argv[1] == "cert":
        with open(sys.argv[2], encoding="utf-8") as f:
            ca = json.load(f)
        print(json.dumps(server_cert(ca, sys.argv[3:])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
