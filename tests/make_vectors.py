#!/usr/bin/env python3
"""Regenerates tests/vectors/: a signed index for the Java verifier's tests.

usage: make_vectors.py      (needs the cryptography package; overwrites tests/vectors/)

The key here is a test key made for these vectors only: never pin it anywhere. The index
is built by build_index.py from two fixture apps at a fixed time, so verifiers should check
expiry against vectors.json's "now", not the real clock.
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Fetcher, entry, package, version, write  # noqa: E402

import build_index  # noqa: E402
import keygen  # noqa: E402
import sign_index  # noqa: E402
import validate  # noqa: E402

OUT = Path(__file__).resolve().parent / "vectors"
KEY_ID = "kia-apps-test"


def main():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        priv, pub, _ = keygen.keygen(KEY_ID, d / "private", d / "keys")
        apps, pages = d / "apps", d / "pages"
        apps.mkdir()
        pages.mkdir()
        z1 = package("kia.menu", "1.1", scripts={})
        z2 = package("ev6.fixes", "1.4", scripts={"svc/eth0-guard.sh": "#!/system/bin/sh\nsleep 5\n"})
        v1 = version("1.1", z1)
        v2 = version("1.4", z2, firmware=["CVEV.USA.0000.V015.012.260507"], requires=["kia.menu>=1.1"],
                     notes="Café \"quotes\" and a\nnewline.")
        write(apps, entry("kia.menu", versions=[v1], name="Edit Menu"))
        write(apps, entry("ev6.fixes", versions=[v2], name="EV6 fixes", category="fixes"))
        (pages / "index.json").write_text(json.dumps({"sequence": 41}))
        fetch = Fetcher({v1["url"]: z1, v2["url"]: z2})
        with mock.patch.object(validate, "find_aapt", lambda: None):
            build_index.build(apps, pages, KEY_ID, build_index.datetime.datetime(2026, 10, 25, 18, 0, 0),
                              fetcher=fetch)

        data = (pages / "index.json").read_bytes()
        sig = sign_index.sign(data, priv.read_bytes(), pub.read_bytes())
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir()
        shutil.copy(priv, OUT / "test-key.pem")
        shutil.copy(pub, OUT / "test-key.pub.pem")
        (OUT / "index.json").write_bytes(data)
        (OUT / "index.json.sig").write_text(sig)
        # a rolled-forward sequence: one byte different, same signature
        tampered = data.replace(b'"sequence": 42', b'"sequence": 43', 1)
        assert tampered != data
        (OUT / "index.tampered.json").write_bytes(tampered)
        (OUT / "vectors.json").write_text(json.dumps({
            "key_id": KEY_ID,
            "public_key": "test-key.pub.pem",
            "now": "2026-10-26T00:00:00Z",
            "cases": [
                {"index": "index.json", "sig": "index.json.sig", "valid": True,
                 "sha256": hashlib.sha256(data).hexdigest()},
                {"index": "index.tampered.json", "sig": "index.json.sig", "valid": False,
                 "sha256": hashlib.sha256(tampered).hexdigest()},
            ],
        }, indent=2) + "\n")
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
