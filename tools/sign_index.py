#!/usr/bin/env python3
"""Signs index.json for the car, or verifies a signature.

usage: sign_index.py <index.json> (--key <private.pem> | --key-env VAR) [--keys-dir keys]
       sign_index.py --verify <index.json> [--sig <file>] [--keys-dir keys | --pubkey <pem>]

Signing writes <index.json>.sig: base64 of the SHA256withRSA (PKCS#1 v1.5) signature over the
exact bytes of the file, no trailing newline. It refuses a private key whose public half isn't
keys/<key_id>.pub.pem for the index's key_id, so a misconfigured secret can't publish an index
no car would accept, and it verifies its own output with the stdlib verifier below.

The verifier is plain Python on purpose: it is the same small computation the store app and
cabinwrightd do in Kotlin, independent of the library that signed.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# DER of DigestInfo{sha256, NULL} up to the 32-byte digest (RFC 8017 9.2 note 1)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
RSA_OID = bytes.fromhex("2a864886f70d010101")


class Fail(Exception):
    pass


# ---------------------------------------------------------------- stdlib verifier

def _der(d, p, tag):
    if d[p] != tag:
        raise Fail("bad public key (DER tag %02x, want %02x)" % (d[p], tag))
    n = d[p + 1]
    p += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(d[p:p + k], "big")
        p += k
    return d[p:p + n], p + n


def public_key(pem):
    """PEM (SubjectPublicKeyInfo or PKCS#1 RSAPublicKey) -> (n, e)."""
    if isinstance(pem, bytes):
        pem = pem.decode("ascii", "replace")
    m = re.search(r"-----BEGIN (RSA )?PUBLIC KEY-----(.+?)-----END", pem, re.S)
    if not m:
        raise Fail("no PUBLIC KEY block")
    der = base64.b64decode("".join(m.group(2).split()))
    if not m.group(1):
        spki, _ = _der(der, 0, 0x30)
        alg, p = _der(spki, 0, 0x30)
        oid, _ = _der(alg, 0, 0x06)
        if oid != RSA_OID:
            raise Fail("not an RSA key")
        bits, _ = _der(spki, p, 0x03)
        der = bits[1:]  # unused-bits byte
    seq, _ = _der(der, 0, 0x30)
    n, p = _der(seq, 0, 0x02)
    e, _ = _der(seq, p, 0x02)
    return int.from_bytes(n, "big"), int.from_bytes(e, "big")


def verify(data, sig_b64, key):
    """True if sig_b64 is a valid SHA256withRSA signature of data under key (n, e)."""
    n, e = key
    k = (n.bit_length() + 7) // 8
    try:
        sig = base64.b64decode("".join(sig_b64.split()), validate=True)
    except ValueError:
        return False
    if len(sig) != k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(data).digest()
    want = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, want)


def key_id_of(data):
    try:
        kid = json.loads(data.decode("utf-8"))["key_id"]
    except (ValueError, KeyError, TypeError):
        raise Fail("index has no key_id")
    if not re.match(r"^[a-z0-9][a-z0-9.-]*$", str(kid)):
        raise Fail("bad key_id %r" % kid)
    return kid


# ---------------------------------------------------------------- signing

def sign(data, private_pem, public_pem):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    priv = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(priv, rsa.RSAPrivateKey):
        raise Fail("the signing key isn't RSA")
    pn = priv.public_key().public_numbers()
    if (pn.n, pn.e) != public_key(public_pem):
        raise Fail("the signing key doesn't match the index's key_id public key")
    sig = base64.b64encode(priv.sign(data, padding.PKCS1v15(), hashes.SHA256())).decode()
    if not verify(data, sig, public_key(public_pem)):
        raise Fail("signature didn't verify")  # never publish something the car would reject
    return sig


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sign or verify index.json.")
    ap.add_argument("index")
    ap.add_argument("--key", help="private key PEM file")
    ap.add_argument("--key-env", help="environment variable holding the private key PEM")
    ap.add_argument("--keys-dir", default=str(ROOT / "keys"))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sig")
    ap.add_argument("--pubkey", help="verify against this public key instead of keys/<key_id>.pub.pem")
    a = ap.parse_args(argv)

    data = Path(a.index).read_bytes()
    sig_path = Path(a.sig or a.index + ".sig")
    try:
        kid = key_id_of(data)
        pub = Path(a.pubkey or os.path.join(a.keys_dir, kid + ".pub.pem")).read_text()
        if a.verify:
            good = verify(data, sig_path.read_text(), public_key(pub))
            print("%s: %s (key %s)" % (a.index, "good signature" if good else "BAD SIGNATURE", kid))
            return 0 if good else 1
        if a.key_env:
            priv = os.environ.get(a.key_env, "")
            if not priv.strip():
                raise Fail("$%s is empty" % a.key_env)
            priv = priv.encode()
        elif a.key:
            priv = Path(a.key).read_bytes()
        else:
            raise Fail("give --key or --key-env")
        sig_path.write_text(sign(data, priv, pub.encode()))
    except (Fail, OSError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    print("signed %s with %s -> %s" % (a.index, kid, sig_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
