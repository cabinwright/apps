"""apps/<id>.json checks: schema, versions, downloads, hashes, labels, the PR comment."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (AUTO_DST, SYSTEM, Fetcher, apk, entry, make_zip, nemesis_data, package, png, system_package,
                     tweak_conf, tweak_package, version, write)

import validate


class Versions(unittest.TestCase):
    def test_compare(self):
        for a, b, want in [("1.10", "1.9", 1), ("1.0", "1", 0), ("1", "1.0.0", 0), ("1.1", "1.0.9", 1),
                           ("2", "10", -1), ("1.0.1", "1", 1), ("01.2", "1.2", 0)]:
            self.assertEqual(validate.vcmp(a, b), want, (a, b))
            self.assertEqual(validate.vcmp(b, a), -want, (b, a))


@mock.patch.object(validate, "find_aapt", lambda: None)
class Apps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.zip = package(version="1.1")
        self.v = version("1.1", self.zip)
        self.fetch = Fetcher({self.v["url"]: self.zip})

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, doc, name=None, **kw):
        kw.setdefault("fetcher", self.fetch)
        kw.setdefault("icons_dir", False)
        return validate.check_app(write(self.dir, doc, name), **kw)

    def errors(self, rep):
        return rep["errors"] + [e for v in rep["versions"] for e in v["errors"]]

    def add(self, data, v="1.1", **kw):
        """A version for this zip, served at its own URL."""
        ver = version(v, data, **kw)
        ver["url"] = ver["url"].replace(".zip", "-%s.zip" % ver["sha256"][:12])
        self.fetch.files[ver["url"]] = data
        return ver

    def test_good(self):
        rep = self.check(entry(versions=[self.v]))
        self.assertEqual(self.errors(rep), [])
        v = rep["versions"][0]
        self.assertEqual(v["size"], len(self.zip))
        self.assertEqual(v["tier"], "app")
        self.assertEqual(v["review"]["tier"], "app")
        self.assertEqual(v["review"]["apps"], [{"package": "dev.test", "version_code": 3}])
        self.assertEqual(v["review"]["files"], ["NEMESIS.data", "t.apk"])
        self.assertEqual(validate.labels([rep]), [])

    def test_system_tier(self):
        v = self.add(system_package("1.1"))
        rep = self.check(entry(SYSTEM, versions=[v]))
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(rep["versions"][0]["review"]["root_services"], ["a"])
        self.assertEqual(validate.labels([rep]), ["root"])
        # only the store may be tier system
        v = self.add(package(version="1.1", scripts={"svc/a.sh": "#!/system/bin/sh\n"}))
        errs = self.errors(self.check(entry(versions=[dict(v, tier="system")])))
        self.assertEqual(len(errs), 1)
        self.assertIn("tier system is only for cabinwright.store", errs[0])

    def test_tier_must_match_the_zip(self):
        svc = self.add(package(version="1.1", scripts={"svc/a.sh": "#!/system/bin/sh\n"}))
        for tier in ("app", "tweaks"):
            errs = self.errors(self.check(entry(versions=[dict(svc, tier=tier)])))
            self.assertTrue(any("tier %s, but the package has the service a" % tier in e for e in errs), errs)
            self.assertTrue(any("has files other than top-level APKs, tweaks/ and lib/: svc/a.sh" in e
                                for e in errs), errs)
        hook = self.add(hook_package())
        errs = self.errors(self.check(entry(versions=[dict(hook, tier="app")])))
        self.assertTrue(any("a preinstall hook" in e for e in errs), errs)
        tw = self.add(tweak_package("test.pkg", "1.1"))
        self.assertEqual(tw["tier"], "tweaks")
        self.assertEqual(self.errors(self.check(entry(versions=[tw]))), [])
        self.assertIn("that's tier tweaks", self.errors(self.check(entry(versions=[dict(tw, tier="app")])))[0])
        self.assertIn("that's tier app", self.errors(self.check(entry(versions=[dict(self.v, tier="tweaks")])))[0])
        store_app = self.add(package(SYSTEM, "1.1"))
        self.assertIn("declare app", self.errors(self.check(entry(SYSTEM, versions=[dict(store_app, tier="system")])))[0])
        # an APK under a folder isn't one the store keeps
        nested = self.add(nested_apk_package())
        self.assertEqual(nested["tier"], "system")
        errs = self.errors(self.check(entry(versions=[dict(nested, tier="app")])))
        self.assertTrue(any("app/t.apk" in e for e in errs), errs)

    def test_capabilities(self):
        caps = {"tweaks": "Shows and switches your tweaks", "root": "Runs your scripts"}
        rep = self.check(entry(versions=[dict(self.v, capabilities=caps)]))
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(rep["versions"][0]["capabilities"], caps)
        self.assertEqual(validate.labels([rep]), ["root"])
        text = validate.comment([rep])
        self.assertIn("asks to list your tweaks, read their status and log, and switch them: "
                      "\u201cShows and switches your tweaks\u201d", text)
        self.assertIn("asks to **run commands as root", text)
        for bad, msg in [({"camera": "x"}, "unknown field camera"), ({"logs": ""}, "too short"),
                         ({"logs": 1}, "should be a string"), (["logs"], "should be a object")]:
            rep = self.check(entry(versions=[dict(self.v, capabilities=bad)]))
            self.assertTrue(any(msg in e for e in rep["errors"]), (bad, rep["errors"]))
        # a pack has no app to grant them to
        tw = self.add(tweak_package("test.pkg", "1.1"))
        errs = self.errors(self.check(entry(versions=[dict(tw, capabilities={"logs": "x"})])))
        self.assertIn("capabilities are for apps", errs[0])
        tw = self.add(tweak_package("test.pkg", "1.1", with_apk=True))
        self.assertEqual(self.errors(self.check(entry(versions=[dict(tw, capabilities={"tweaks": "x"})]))), [])

    def test_tier_is_required(self):
        v = dict(self.v)
        del v["tier"]
        rep = self.check(entry(versions=[v]))
        self.assertIn("missing tier", rep["errors"][0])
        rep = self.check(entry(versions=[dict(self.v, tier="kernel")]))
        self.assertIn("isn't one of", rep["errors"][0])

    def test_tweak_errors_fail_the_version(self):
        tw = self.add(tweak_package("test.pkg", "1.1", tweaks={"x": tweak_conf(extra="risk=system\n")}))
        errs = self.errors(self.check(entry(versions=[tw])))
        self.assertEqual(len(errs), 1)
        self.assertIn("risk= isn't a tweak.conf key", errs[0])

    def test_tweak_review_in_comment(self):
        tw = self.add(tweak_package("test.pkg", "1.1", tweaks={
            "auto-dst": AUTO_DST,
            "skip": tweak_conf("Skip", firmware="CVEV.USA.0000.V015.012.260507", extra=(
                "need=file:/system/priv-app/SystemUI.apk@512fa1835649e710d91deeb37c90433d | Change the start-up screen\n"
                "need=kill:com.android.systemui | Restart the status bar\n")),
        }, files={"tweaks/skip/disable.sh": "#!/system/bin/sh\n"}), firmware=["CVEV.USA.0000.V015.012.260507"])
        rep = self.check(entry(versions=[tw]))
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(validate.labels([rep]), ["system-writes", "needs-firmware-match"])
        text = validate.comment([rep])
        self.assertIn("tier **tweaks**", text)
        self.assertIn("adds the tweak `auto-dst`, Automatic daylight saving time: Changes the clock for daylight "
                      "saving time (service, on by default, changes system settings)", text)
        self.assertIn("  - changes the system setting `summer_time`: \u201cTurn the head unit's own "
                      "daylight-saving switch\u201d", text)
        self.assertIn("  - calls the binder service `com.hkmc.micom.time` (codes 3, 4): \u201cSet the clock", text)
        self.assertIn("(oneshot, off by default, changes system files, has disable.sh)", text)
        self.assertIn("  - replaces the file `/system/priv-app/SystemUI.apk`, only when it is the stock version: "
                      "\u201cChange the start-up screen\u201d", text)
        self.assertIn("  - restarts the process `com.android.systemui`", text)
        self.assertIn("writes to the system: **yes**", text)
        self.assertIn("`tweaks/skip/disable.sh`", text)
        self.assertIn("runs as root: nothing", text)

    def test_root_need(self):
        tw = self.add(tweak_package("test.pkg", "1.1", tweaks={"r": tweak_conf(kind="service", extra="need=root | Anything\n")}))
        rep = self.check(entry(versions=[tw]))
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(rep["versions"][0]["review"]["root"], ["tweak r (need=root)"])
        self.assertEqual(validate.labels([rep]), ["root"])
        self.assertIn("**runs anything as root**", validate.comment([rep]))

    def test_pending_sha256(self):
        rep = self.check(entry(versions=[dict(self.v, sha256=validate.PENDING)]))
        self.assertEqual(rep["errors"], ['1.1: sha256 is the placeholder "pending": put in the SHA-256 of the '
                                         "release's zip"])
        self.assertEqual(self.fetch.calls, [])

    def test_schema_errors(self):
        bad = [
            (dict(category="games"), "isn't one of"),
            (dict(extra=1), "unknown field extra"),
            (dict(name=""), "too short"),
            (dict(versions=[]), "at least 1"),
            (dict(versions=[dict(self.v, sha256="TODO")]), "sha256"),
            (dict(versions=[dict(self.v, url="https://example.com/x.zip")]), "url"),
            (dict(versions=[dict(self.v, version="1.1-beta")]), "version"),
            (dict(versions=[dict(self.v, firmware=[])]), "firmware"),
            (dict(icon="http://x/y.png"), "icon"),
        ]
        for kw, msg in bad:
            rep = self.check(entry(**dict({"versions": [self.v]}, **kw)))
            self.assertTrue(any(msg in e for e in rep["errors"]), (kw, rep["errors"]))
            self.assertEqual(self.fetch.calls, [], "nothing is downloaded for a malformed file")

    def test_id_must_match_file_name(self):
        rep = self.check(entry(versions=[self.v]), name="other.pkg")
        self.assertIn("doesn't match the file name", rep["errors"][0])

    def test_version_order(self):
        z2 = package(version="1.2")
        v2 = version("1.2", z2)
        self.fetch.files[v2["url"]] = z2
        self.assertIn("newest first", self.check(entry(versions=[self.v, v2]))["errors"][0])
        self.assertEqual(self.errors(self.check(entry(versions=[v2, self.v]))), [])
        self.assertIn("listed twice", self.check(entry(versions=[self.v, dict(self.v, version="1.1.0")]))["errors"][0])

    def test_firmware_star_alone(self):
        rep = self.check(entry(versions=[dict(self.v, firmware=["*", "CVEV.X"])]))
        self.assertIn("either", rep["errors"][0])

    def test_hash_mismatch(self):
        rep = self.check(entry(versions=[dict(self.v, sha256="0" * 64)]))
        self.assertIn("sha256 mismatch: the zip is " + self.v["sha256"], self.errors(rep)[0])

    def test_id_and_version_must_match_zip(self):
        z = package(id="other.pkg", version="1.0")
        v = version("1.1", z)
        self.fetch.files[v["url"]] = z
        errs = self.errors(self.check(entry(versions=[v])))
        self.assertTrue(any("id is other.pkg" in e for e in errs))
        self.assertTrue(any("version is 1.0" in e for e in errs))

    def test_system_writes_need_exact_firmware(self):
        v = self.add(system_package("1.1", scripts={"svc/a.sh": "remount\nmount -o remount,rw /system\n"}))
        self.assertIn("firmware is [\"*\"]", self.errors(self.check(entry(SYSTEM, versions=[v])))[0])
        rep = self.check(entry(SYSTEM, versions=[dict(v, firmware=["CVEV.USA.0000.V015.012.260507"])]))
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(validate.labels([rep]), ["root", "system-writes", "needs-firmware-match"])

    def test_execute_is_refused(self):
        v = self.add(system_package("1.1", extra="\ntype=execute\n"))
        self.assertEqual(self.errors(self.check(entry(SYSTEM, versions=[v]))),
                         ["type=execute (USB autorun) packages are refused by the store"])
        errs = self.errors(self.check(entry(versions=[dict(v, tier="app")])))
        self.assertTrue(any("tier app, but the package has type=execute" in e for e in errs), errs)

    def test_requires(self):
        rep = self.check(entry(versions=[dict(self.v, requires=["cabinwright.menu>=1.1"])]))
        self.assertIn("requires cabinwright.menu", rep["errors"][0])
        write(self.dir, entry("cabinwright.menu", versions=[dict(self.v, version="1.0")]))
        rep = self.check(entry(versions=[dict(self.v, requires=["cabinwright.menu>=1.1"])]))
        self.assertEqual(rep["errors"], [])
        self.assertIn("newest listed version is 1.0", rep["warnings"][0])

    def test_local_zip(self):
        p = self.dir / "local.zip"
        p.write_bytes(self.zip)
        rep = self.check(entry(versions=[self.v]), local_zips={"": str(p)}, fetcher=Fetcher())
        self.assertEqual(self.errors(rep), [])
        rep = self.check(entry(versions=[self.v]), local_zips={"test.pkg@1.1": str(p)}, fetcher=Fetcher())
        self.assertEqual(self.errors(rep), [])

    def test_base_skips_unchanged_versions(self):
        z0 = package(version="1.0")
        v0 = version("1.0", z0)
        base = json.dumps(entry(versions=[v0]))
        rep = self.check(entry(versions=[self.v, v0]), base=base)
        self.assertEqual([v["status"] for v in rep["versions"]], ["new", "unchanged"])
        self.assertEqual(self.fetch.calls, [self.v["url"]])
        changed = json.dumps(entry(versions=[dict(self.v, sha256="1" * 64)]))
        rep = self.check(entry(versions=[self.v]), base=changed)
        self.assertEqual(rep["versions"][0]["status"], "changed")
        self.assertIn("different zip", rep["versions"][0]["warnings"][0])

    def test_cache(self):
        cache = self.dir / "reviews"
        self.check(entry(versions=[self.v]), cache=cache)
        self.assertTrue((cache / (self.v["sha256"] + ".json")).exists())
        fetch = Fetcher()
        rep = self.check(entry(versions=[self.v]), cache=cache, fetcher=fetch)
        self.assertEqual(self.errors(rep), [])
        self.assertEqual(fetch.calls, [])

    def test_an_app_needs_an_icon(self):
        icons = self.dir / "icons"
        icons.mkdir()
        self.assertIn("needs an icon", self.errors(self.check(entry(versions=[self.v]), icons_dir=icons))[0])
        (icons / "test.pkg.png").write_bytes(png(64, 64))
        self.assertEqual(self.errors(self.check(entry(versions=[self.v]), icons_dir=icons)), [])

    def test_icon(self):
        icons = self.dir / "icons"
        icons.mkdir()
        for data, msg in [(png(64, 64), None), (png(300, 64), "300x64"), (b"GIF89a" + b"\0" * 30, "not a PNG"),
                          (png(64, 64) + b"\0" * (64 << 10), "at most 65536")]:
            (icons / "test.pkg.png").write_bytes(data)
            rep = self.check(entry(versions=[self.v]), icons_dir=icons)
            if msg:
                self.assertIn(msg, rep["errors"][0])
            else:
                self.assertEqual(rep["errors"], [])
        self.assertEqual(self.check(entry(versions=[self.v]), icons_dir=False)["errors"], [])
        # an icon field in the entry is refused: the icon is icons/<id>.png
        rep = self.check(entry(versions=[self.v], icon="https://example.com/i.png"))
        self.assertIn("unknown field icon", rep["errors"][0])

    def test_icon_without_entry(self):
        rep = validate.check_app(self.dir / "gone.pkg.json")
        self.assertIn("doesn't exist", rep["errors"][0])

    def test_url_must_be_a_release(self):
        for url in ("https://github.com/o/r/archive/v1.zip", "https://raw.githubusercontent.com/o/r/x.zip"):
            rep = self.check(entry(versions=[dict(self.v, url=url)]))
            self.assertTrue(rep["errors"] or self.errors(rep))

    def test_comment(self):
        v = self.add(system_package("1.1", scripts={"svc/a.sh": "#!/system/bin/sh\nreboot\n"}), firmware=["CVEV.X"])
        rep = self.check(entry(SYSTEM, versions=[v], name="Evil `name` @someone [x](http://e)"))
        text = validate.comment([rep])
        self.assertTrue(text.startswith(validate.MARKER))
        self.assertIn("All checks passed", text)
        self.assertIn("svc/a.sh:2", text)
        self.assertIn("reboots or shuts down", text)
        self.assertIn("writes to the system: **yes**", text)
        bad = validate.comment([self.check(entry(versions=[dict(self.v, sha256="0" * 64)]))])
        self.assertIn("Checks failed", bad)
        self.assertNotIn("@someone", validate.md("@someone"))

    def test_retired_needs_a_reason(self):
        for k in ("deprecated", "withdrawn"):
            rep = self.check(entry(versions=[self.v], **{k: "  "}))
            self.assertIn("%s needs a reason" % k, rep["errors"][0])
            rep = self.check(entry(versions=[self.v], **{k: True}))
            self.assertIn("should be a string", rep["errors"][0])
            rep = self.check(entry(versions=[self.v], **{k: "Built into Tweaks now."}))
            self.assertEqual(self.errors(rep), [])
            self.assertIn("**%s**" % k, validate.comment([rep]))

    def test_replaced_by(self):
        rep = self.check(entry(versions=[self.v], deprecated="Old.", replaced_by="other.new"))
        self.assertIn("replaced_by names other.new, which isn't in the index", rep["errors"][0])
        write(self.dir, entry("other.new", versions=[self.v]))
        rep = self.check(entry(versions=[self.v], deprecated="Old.", replaced_by="other.new"))
        self.assertEqual(self.errors(rep), [])
        self.assertIn("replaced by `other.new`", validate.comment([rep]))
        rep = self.check(entry(versions=[self.v], replaced_by="other.new"))
        self.assertIn("only goes with deprecated or withdrawn", rep["errors"][0])
        rep = self.check(entry(versions=[self.v], deprecated="Old.", replaced_by="test.pkg"))
        self.assertIn("names the app itself", rep["errors"][0])
        write(self.dir, entry("other.new", versions=[self.v], withdrawn="Unsafe."))
        rep = self.check(entry(versions=[self.v], deprecated="Old.", replaced_by="other.new"))
        self.assertIn("withdrawn too", rep["warnings"][0])

    def test_no_new_versions_on_a_retired_app(self):
        z2 = package(version="1.2")
        v2 = version("1.2", z2)
        self.fetch.files[v2["url"]] = z2
        base = json.dumps(entry(versions=[self.v]))
        for k in ("deprecated", "withdrawn"):
            # retiring as it is: fine, and nothing is downloaded
            calls = len(self.fetch.calls)
            rep = self.check(entry(versions=[self.v], **{k: "Old."}), base=base)
            self.assertEqual(self.errors(rep), [])
            self.assertEqual(self.fetch.calls[calls:], [])
            rep = self.check(entry(versions=[v2, self.v], **{k: "Old."}), base=base)
            self.assertIn("no new versions", rep["versions"][0]["errors"][0])
            self.assertEqual(rep["versions"][1]["errors"], [])
            rep = self.check(entry(versions=[dict(self.v, sha256="1" * 64)], **{k: "Old."}), base=base)
            self.assertIn("no new versions", rep["versions"][0]["errors"][0])
        # a new file can't start out retired; without --base (publish) every version is checked
        rep = self.check(entry(versions=[self.v], deprecated="Old."), base="")
        self.assertIn("no new versions", rep["versions"][0]["errors"][0])
        self.assertEqual(self.errors(self.check(entry(versions=[self.v], deprecated="Old."))), [])
        # un-retiring is the owner's call, and the comment says so
        rep = self.check(entry(versions=[v2, self.v]), base=json.dumps(entry(versions=[self.v], deprecated="x")))
        self.assertEqual(self.errors(rep), [])
        self.assertIn("offers it again", rep["warnings"][0])

    def test_requiring_a_retired_app_warns(self):
        write(self.dir, entry("cabinwright.menu", versions=[dict(self.v, version="1.0")], deprecated="Old."))
        rep = self.check(entry(versions=[dict(self.v, requires=["cabinwright.menu"])]))
        self.assertEqual(self.errors(rep), [])
        self.assertIn("which is deprecated", rep["warnings"][0])
        rep = self.check(entry("cabinwright.menu", versions=[self.v], deprecated="Old."))
        self.assertIn("test.pkg requires this app", rep["warnings"][0])


def hook_package():
    nd = nemesis_data(version="1.1", types="application", apps=[("t.apk", "dev.test")]).replace(
        "types=application\n", "types=application\npreinstall=pre.sh\n")
    return make_zip({"NEMESIS.data": nd, "t.apk": apk("dev.test", 3), "pre.sh": "#!/system/bin/sh\n"})


def nested_apk_package():
    return make_zip({"NEMESIS.data": nemesis_data(version="1.1", types="application", apps=[("app/t.apk", "dev.test")]),
                     "app/t.apk": apk("dev.test", 3)})


class Fetch(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(validate.Fail):
            validate.fetch("http://github.com/x", 10)


class Cli(unittest.TestCase):
    @mock.patch.object(validate, "find_aapt", lambda: None)
    def test_main_with_local_zip(self):
        with tempfile.TemporaryDirectory() as d:
            z = system_package("1.1")
            (Path(d) / "p.zip").write_bytes(z)
            f = write(d, entry(SYSTEM, versions=[version("1.1", z)]))
            icons = Path(d) / "icons"
            icons.mkdir()
            (icons / (f.stem + ".png")).write_bytes(png(64, 64))
            out = Path(d) / "c.md"
            lab = Path(d) / "labels"
            self.assertEqual(validate.main([str(f), "--local-zip", str(Path(d) / "p.zip"), "--icons-dir", str(icons),
                                            "--comment", str(out), "--labels", str(lab)]), 0)
            self.assertIn("runs as root", out.read_text())
            self.assertEqual(lab.read_text(), "root\n")


if __name__ == "__main__":
    unittest.main()
