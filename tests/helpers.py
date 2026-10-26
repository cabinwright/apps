"""Builders for test packages: zips, APKs with a binary manifest, app entries."""
import hashlib
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
FIXTURES = HERE / "fixtures"
NONE = 0xFFFFFFFF


def axml(package, version_code, utf8=False, blank_names=False):
    """A minimal binary AndroidManifest.xml: <manifest package=.. android:versionCode=..>."""
    names = ["" if blank_names else "versionCode", "package", "manifest", package,
             "http://schemas.android.com/apk/res/android", "android"]
    data, offs = b"", []
    for s in names:
        offs.append(len(data))
        if utf8:
            b = s.encode()
            data += bytes([len(s), len(b)]) + b + b"\0"
        else:
            data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    data += b"\0" * (-len(data) % 4)
    start = 28 + 4 * len(names)
    pool = struct.pack("<HHIIIIII", 0x0001, 28, start + len(data), len(names), 0,
                       0x100 if utf8 else 0, start, 0)
    pool += struct.pack("<%dI" % len(names), *offs) + data
    resmap = struct.pack("<HHII", 0x0180, 8, 12, 0x0101021B)
    attrs = struct.pack("<IIIHBBI", 4, 0, NONE, 8, 0, 0x10, version_code)
    attrs += struct.pack("<IIIHBBI", NONE, 1, 3, 8, 0, 0x03, 3)
    elem = struct.pack("<HHIII", 0x0102, 16, 16 + 20 + len(attrs), 1, NONE)
    elem += struct.pack("<IIHHHHHH", NONE, 2, 20, 20, 2, 0, 0, 0) + attrs
    ns = struct.pack("<IIII", 1, NONE, 5, 4)
    end = struct.pack("<HHIIIII", 0x0103, 16, 24, 1, NONE, NONE, 2)
    body = (pool + resmap + struct.pack("<HHI", 0x0100, 16, 24) + ns + elem + end +
            struct.pack("<HHI", 0x0101, 16, 24) + ns)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def apk(package, version_code):
    return make_zip({"AndroidManifest.xml": axml(package, version_code), "classes.dex": b"dex\n035\0"})


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def nemesis_data(id="test.pkg", version="1.0", types="application,service", apps=(), services=(),
                 extra=""):
    out = ["[nemesis]", "version=" + version, "id=" + id, "name=Test", "types=" + types, ""]
    for i, (path, pkg) in enumerate(apps):
        out += ["[app.%d]" % i, "kind=apk", "path=" + path, "package=" + pkg, ""]
    for i, s in enumerate(services):
        out += ["[service.%d]" % i, "name=" + s[0], "kind=sh", "path=" + s[1]]
        if len(s) > 2 and s[2] is not None:
            out.append("uid=" + s[2])
        out += ["mode=restart", ""]
    return "\n".join(out) + extra


def package(id="test.pkg", version="1.0", scripts=None, extra=""):
    """A package zip with one top-level APK and the given {path: script} root services: tier app
    without scripts, tier system with them."""
    scripts = scripts or {}
    files = {
        "NEMESIS.data": nemesis_data(id, version, types="application,service" if scripts else "application",
                                     apps=[("t.apk", "dev.test")],
                                     services=[(p.split("/")[-1][:-3], p, "root") for p in scripts],
                                     extra=extra),
        "t.apk": apk("dev.test", 3),
    }
    files.update(scripts)
    return make_zip(files)


# the store's own package: the one id that may be tier system
SYSTEM = "cabinwright.store"


def system_package(version="1.0", scripts=None, extra=""):
    scripts = scripts if scripts is not None else {"svc/a.sh": "#!/system/bin/sh\necho hi\n"}
    return package(SYSTEM, version, scripts, extra)


AUTO_DST = """name=Automatic daylight saving time
summary=Changes the clock for daylight saving time
description=Moves the clock forward in March and back in November.
firmware=CVEV.USA.0000.V015.012.260507
kind=service
default=on
need=setting:system/summer_time | Turn the head unit's own daylight-saving switch
need=binder:com.hkmc.micom.time 3,4 | Set the clock through the head unit's time service
"""


def tweak_conf(name="X", kind="oneshot", default="off", firmware="*", extra=""):
    return "name=%s\nsummary=Does %s\nfirmware=%s\nkind=%s\ndefault=%s\n%s" % (
        name, name, firmware, kind, default, extra)


def tweak_package(id="tweaks.test", version="1.0", tweaks=None, files=None, with_apk=False):
    """A tweaks-tier zip: {tweak id: tweak.conf text} (enable.sh or run.sh added to match), plus files."""
    tweaks = tweaks if tweaks is not None else {"auto-dst": AUTO_DST}
    out = {"NEMESIS.data": nemesis_data(id, version, types="application")}
    for tid, conf in tweaks.items():
        out["tweaks/%s/tweak.conf" % tid] = conf
        script = "run.sh" if "kind=service" in conf else "enable.sh"
        out["tweaks/%s/%s" % (tid, script)] = "#!/system/bin/sh\nkt setting put system summer_time 1\n"
    if with_apk:
        out["tweaks.apk"] = apk("dev.test.tweaks", 1)
    out.update(files or {})
    return make_zip(out)


def entry(id="test.pkg", versions=None, **kw):
    doc = {"id": id, "name": "Test", "summary": "A test", "author": "someone", "category": "tools",
           "versions": versions or []}
    doc.update(kw)
    return doc


def version(v, data, firmware=("*",), tier=None, **kw):
    """A version entry for the zip; tier defaults to the one the zip is."""
    if tier is None:
        import validate
        tier = validate.inspect_zip(data)["review"]["tier"]
    d = {"version": v, "url": "https://github.com/o/r/releases/download/v%s/p-%s.zip" % (v, v),
         "sha256": hashlib.sha256(data).hexdigest(), "firmware": list(firmware), "tier": tier}
    d.update(kw)
    return d


def write(dir, doc, name=None):
    p = Path(dir) / ((name or doc["id"]) + ".json")
    p.write_text(json.dumps(doc, indent=2))
    return p


class Fetcher:
    """Stands in for downloads: url -> bytes."""
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.calls = []

    def __call__(self, url, limit):
        import validate
        self.calls.append(url)
        if url not in self.files:
            raise validate.Fail("download failed: %s: 404" % url)
        if len(self.files[url]) > limit:
            raise validate.Fail("too big")
        return self.files[url]


def png(w, h):
    import zlib
    raw = b"".join(b"\0" + b"\0\0\0" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
