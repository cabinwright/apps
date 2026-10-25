#!/usr/bin/env python3
"""Makes a new index signing key (RSA-3072).

usage: keygen.py <key_id> [--private-dir ~/.config/kia-apps] [--keys-dir keys]

Writes the private key to <private-dir>/<key_id>.pem (PKCS#8, unencrypted so it can go
straight into the INDEX_SIGNING_KEY secret; mode 600 in a 700 directory) and the public key
to <keys-dir>/<key_id>.pub.pem, which is committed and pinned in kia.store. Never overwrites
either. The private key is never printed.
"""
import argparse
import base64
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fingerprint(pub_pem):
    der = base64.b64decode("".join(l for l in pub_pem.decode().splitlines() if "-----" not in l))
    return hashlib.sha256(der).hexdigest()


def keygen(key_id, private_dir, keys_dir):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if not re.match(r"^[a-z0-9][a-z0-9.-]*$", key_id):
        raise SystemExit("key_id: lowercase letters, digits, '.' and '-'")
    priv_path = Path(private_dir).expanduser() / (key_id + ".pem")
    pub_path = Path(keys_dir) / (key_id + ".pub.pem")
    for p in (priv_path, pub_path):
        if p.exists():
            raise SystemExit("%s already exists" % p)

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo)

    priv_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(priv_path.parent, 0o700)
    # created with 600 from the start: no window where it is readable
    fd = os.open(str(priv_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv)
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    pub_path.write_bytes(pub)
    return priv_path, pub_path, fingerprint(pub)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Make a new index signing key.")
    ap.add_argument("key_id")
    ap.add_argument("--private-dir", default="~/.config/kia-apps")
    ap.add_argument("--keys-dir", default=str(ROOT / "keys"))
    a = ap.parse_args(argv)
    priv, pub, fp = keygen(a.key_id, a.private_dir, a.keys_dir)
    print("private key: %s (mode 600; keep an offline copy, and put the active key in the "
          "INDEX_SIGNING_KEY secret)" % priv)
    print("public key:  %s" % pub)
    print("sha256 of the public key (DER): %s" % fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
