"""Package inspection: NEMESIS.data, APKs, and the script flags the owner reviews."""
import unittest
from unittest import mock

from helpers import AUTO_DST, FIXTURES, apk, axml, make_zip, nemesis_data, package, system_package, tweak_conf, tweak_package

import validate


def flags(text, own=()):
    return {f["line"]: f["rules"] for f in validate.scan_script(text, "s.sh", own)}


def script(*lines):
    return "#!/system/bin/sh\n" + "\n".join(lines) + "\n"


class Scripts(unittest.TestCase):
    def test_reads_of_system_are_not_writes(self):
        f = flags(script(
            "export PATH=/data/nemesis/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin",
            "/system/xbin/nemesis pkg-list",
            "cat /system/build.prop | grep ro.build",
            "cp /system/etc/hosts /data/nemesis/me/hosts",
            "ls /system/app > /data/nemesis/me/apps.txt",
        ))
        self.assertEqual(f, {})

    def test_spec_list(self):
        f = flags(script(
            "mount -o remount,rw /system",       # 2
            "dd if=/sdcard/x.img of=/dev/block/mmcblk0p5",
            "setprop persist.sys.foo 1",
            "pm disable com.hyundai.foo",
            "reboot",
            "iptables -A INPUT -j DROP",
            "chmod 777 /data/local.prop",
            "rm -rf /data/data/com.other.app/cache",
            "cat /dev/block/by-name/system > /sdcard/sys.img",
            "echo x > /system/etc/hosts",
        ))
        self.assertEqual(f[2], ["remount", "mount"])
        self.assertIn("block-dev", f[3])
        self.assertEqual(f[4], ["setprop-persist"])
        self.assertEqual(f[5], ["pm"])
        self.assertEqual(f[6], ["reboot"])
        self.assertEqual(f[7], ["iptables"])
        self.assertEqual(f[8], ["perms"])
        self.assertEqual(f[9], ["app-data"])
        self.assertEqual(f[10], ["block-dev"])
        self.assertEqual(f[11], ["system-path"])

    def test_variables_are_followed(self):
        f = flags(script("APP=/system/app", "D=$APP/x", "chmod 644 ${D}.apk", "cp a $APP/", "cp $APP/a b"))
        self.assertEqual(f, {4: ["system-path"], 5: ["system-path"]})

    def test_variable_with_two_values_is_unknown(self):
        f = flags(script("D=/system", "D=/sdcard", "chmod 644 $D/x", "cp a $D/x"))
        self.assertEqual(f, {4: ["perms-unknown"]})

    def test_own_dirs_are_fine(self):
        f = flags(script("DIR=/data/nemesis/status", "mkdir -p $DIR && chmod 755 $DIR",
                         "chmod 644 relative.txt", "chown 1000 /data/data/dev.test/files/x",
                         "echo hi >> /sdcard/log.txt 2>&1", "cmd > /dev/null"), own={"dev.test"})
        self.assertEqual(f, {})

    def test_words_in_strings_and_comments_dont_count(self):
        f = flags(script('echo "done - reboot to load it"', "# reboot here", 'log "remount rw failed"',
                         "x=1 # setprop persist.x 1", 'fail "launcher on /system isn\'t stock"'))
        self.assertEqual(f, {})

    def test_hash_inside_quotes_isnt_a_comment(self):
        self.assertEqual(flags(script('echo "a \\" # b"; reboot', "echo ${#x} 'it''s # x'; reboot")),
                         {2: ["reboot"], 3: ["reboot"]})

    def test_commands_inside_c_strings_count(self):
        f = flags(script('nemesis root 1000 -c "kill 123"', "su -c 'reboot'", 'sh -c "rm -rf /system/x"'))
        self.assertEqual(f[2], ["as-uid", "kill"])
        self.assertEqual(f[3], ["reboot", "as-uid"])
        self.assertEqual(f[4], ["system-path"])

    def test_function_bodies_and_continuations(self):
        f = flags(script("fail() { echo no; /system/xbin/nemesis remount ro >/dev/null 2>&1; exit 1; }",
                         "cp a \\", "  /system/app/b"))
        self.assertEqual(f, {2: ["remount"], 3: ["system-path"]})

    def test_heredoc_body_is_skipped(self):
        f = flags(script("cat > /sdcard/x <<EOF", "reboot", "EOF", "true"))
        self.assertEqual(f, {})

    def test_info_flags(self):
        f = flags(script("setprop ctl.start foo", "curl -o /sdcard/x https://example.com",
                         "settings put global x 1", "insmod /sdcard/x.ko", "setprop sys.powerctl reboot"))
        self.assertEqual(f, {2: ["setprop"], 3: ["network"], 4: ["settings"], 5: ["kmod"], 6: ["reboot"]})
        self.assertFalse(validate.RULES["setprop"][0])
        self.assertTrue(validate.RULES["kmod"][0])

    def test_root_service_scripts(self):
        # the store's service and the projection pack's receiver watchdog: no system writes
        got = {}
        for name in ("store-helper.sh", "aa-reconnect.sh"):
            for f in validate.scan_script((FIXTURES / "scripts" / name).read_text(), name, {"dev.cabinwright.store"}):
                got[(name, f["line"])] = f["rules"]
        self.assertEqual(got, {("store-helper.sh", 17): ["perms-unknown"], ("aa-reconnect.sh", 34): ["as-uid", "kill"]})

    def test_launcher_install_script(self):
        f = flags((FIXTURES / "scripts" / "install-launcher.sh").read_text())
        self.assertEqual(sorted(f), [21, 43, 44, 45, 46, 47, 49, 52, 55, 59])
        self.assertEqual(f[43], ["remount"])
        self.assertEqual(f[44], ["system-path"])
        self.assertEqual(f[49], ["system-path"])  # dalvik-cache

    def test_launcher_restore_script(self):
        f = flags((FIXTURES / "scripts" / "restore-launcher.sh").read_text())
        self.assertEqual(f[33], ["system-path"])  # dalvik-cache
        self.assertEqual(f[39], ["reboot"])


@mock.patch.object(validate, "find_aapt", lambda: None)
class Packages(unittest.TestCase):
    def test_review_record(self):
        r = validate.inspect_zip(package(scripts={
            "svc/a.sh": script("sleep 1"), "svc/b.sh": script("mount -o remount,rw /system")}))
        self.assertEqual(r["nemesis"], {"id": "test.pkg", "version": "1.0"})
        rv = r["review"]
        self.assertEqual(rv["tier"], "system")
        self.assertEqual(rv["files"], ["NEMESIS.data", "svc/a.sh", "svc/b.sh", "t.apk"])
        self.assertEqual(r["system_reasons"], ["the service a", "the service b",
                                               "files other than top-level APKs, tweaks/ and lib/: svc/a.sh, svc/b.sh"])
        self.assertEqual(rv["types"], ["application", "service"])
        self.assertEqual(rv["apps"], [{"package": "dev.test", "version_code": 3}])
        self.assertEqual(rv["services"], [{"name": "a", "uid": "root", "mode": "restart"},
                                          {"name": "b", "uid": "root", "mode": "restart"}])
        self.assertEqual(rv["root_services"], ["a", "b"])
        self.assertTrue(rv["system_writes"])
        self.assertFalse(rv["execute"])
        self.assertEqual([(f["file"], f["line"]) for f in r["flags"]], [("svc/b.sh", 2)])

    def test_uid_and_missing_uid(self):
        z = make_zip({"NEMESIS.data": nemesis_data(types="service", services=[
            ("a", "a.sh", None), ("b", "b.sh", "1000"), ("c", "c.sh", "0")]),
            "a.sh": "", "b.sh": "", "c.sh": ""})
        self.assertEqual(validate.inspect_zip(z)["review"]["root_services"], ["a", "c"])

    def test_hooks_and_sh_entries_run_as_root(self):
        nd = nemesis_data(types="application").replace("types=application\n", "types=application\npreinstall=s/pre.sh\npreuninstall=s/un.sh\n")
        nd += "\n[app.0]\nkind=sh\npath=bin/st.sh\n\n[app.1]\nkind=sh\npath=bin/me.sh\nuid=1000\n"
        z = make_zip({"NEMESIS.data": nd, "s/pre.sh": script("mount -o remount,rw /system"), "s/un.sh": "",
                      "bin/st.sh": "", "bin/me.sh": ""})
        r = validate.inspect_zip(z)
        rv = r["review"]
        self.assertEqual(rv["hooks"], [{"hook": "preinstall", "path": "s/pre.sh"},
                                       {"hook": "preuninstall", "path": "s/un.sh"}])
        self.assertEqual(rv["sh_entries"], [{"path": "bin/st.sh", "uid": "root"}, {"path": "bin/me.sh", "uid": "1000"}])
        self.assertEqual(rv["root"], ["preinstall hook s/pre.sh", "preuninstall hook s/un.sh", "script bin/st.sh"])
        self.assertEqual([f["file"] for f in r["flags"]], ["s/pre.sh"])
        self.assertEqual(r["warnings"], [])
        z = make_zip({"NEMESIS.data": nemesis_data(types="application").replace(
            "types=application\n", "types=application\npostinstall=missing.sh\n")})
        with self.assertRaisesRegex(validate.Fail, "postinstall"):
            validate.inspect_zip(z)

    def test_tweaks_package(self):
        z = tweak_package(tweaks={"auto-dst": AUTO_DST}, files={"lib/common.sh": script("true")}, with_apk=True)
        r = validate.inspect_zip(z)
        self.assertEqual((r["errors"], r["system_reasons"]), ([], []))
        rv = r["review"]
        self.assertEqual(rv["tier"], "tweaks")
        self.assertEqual(rv["apps"], [{"package": "dev.test.tweaks", "version_code": 1}])
        self.assertEqual(rv["tweaks"], [{
            "id": "auto-dst", "name": "Automatic daylight saving time",
            "summary": "Changes the clock for daylight saving time",
            "description": "Moves the clock forward in March and back in November.",
            "kind": "service", "default": "on", "firmware": ["CVEV.USA.0000.V015.012.260507"], "conflicts": [],
            "needs": [
                {"need": "setting:system/summer_time", "reason": "Turn the head unit's own daylight-saving switch"},
                {"need": "binder:com.hkmc.micom.time 3,4", "reason": "Set the clock through the head unit's time service"},
            ],
            "changes": "settings", "disable": False}])
        self.assertEqual(rv["root"], [])
        self.assertFalse(rv["system_writes"])

    def test_file_need_is_a_system_write(self):
        conf = tweak_conf(extra="need=file:/system/app/X.apk@%s,%s | Replace X\n" % ("a" * 32, "b" * 32))
        rv = validate.inspect_zip(tweak_package(tweaks={"x": conf}))["review"]
        self.assertEqual(rv["tweaks"][0]["changes"], "files")
        self.assertTrue(rv["system_writes"])
        text = "\n".join(validate.describe({"review": rv}))
        self.assertIn("replaces the file `/system/app/X.apk`, only when it is one of 2 known versions", text)

    def test_tweak_layout(self):
        r = validate.inspect_zip(tweak_package(tweaks={}, files={"tweaks/loose.sh": "", "tweaks/a/run.sh": ""}))
        self.assertEqual(r["errors"], ["tweaks/loose.sh isn't in a tweak's folder (tweaks/<id>/)",
                                       "tweaks/a has no tweak.conf"])
        r = validate.inspect_zip(make_zip({"NEMESIS.data": nemesis_data(types="application")}))
        self.assertEqual(r["errors"], ["the package installs nothing: no APKs, tweaks/ or lib/"])

    def test_system_package(self):
        r = validate.inspect_zip(system_package())
        self.assertEqual(r["review"]["tier"], "system")
        self.assertEqual(r["review"]["root"], ["service a"])


def tweak_errors(conf, files=("enable.sh",), tid="x"):
    return validate.parse_tweak(tid, conf, set(files))[1]


class TweakConf(unittest.TestCase):
    def test_good(self):
        t, errs = validate.parse_tweak("auto-dst", AUTO_DST, {"run.sh", "status.sh"})
        self.assertEqual(errs, [])
        self.assertEqual([n["need"] for n in t["needs"]], ["setting:system/summer_time", "binder:com.hkmc.micom.time 3,4"])
        t, errs = validate.parse_tweak("x", "# comment\n\n" + tweak_conf(extra="conflicts=a, b.c\n"), {"enable.sh"})
        self.assertEqual((errs, t["conflicts"], t["firmware"]), ([], ["a", "b.c"], ["*"]))

    def test_retired_keys(self):
        for k, v, msg in [("risk", "system", "a tweak changes system files when it has a file: need"),
                          ("retired", "1", "leave its folder out of the package"),
                          ("replaces", "aa-recover", "replaces= isn't a tweak.conf key")]:
            errs = tweak_errors(tweak_conf(extra="%s=%s\n" % (k, v)))
            self.assertEqual(len(errs), 1, errs)
            self.assertIn("tweaks/x/tweak.conf:6: %s= isn't a tweak.conf key" % k, errs[0])
            self.assertIn(msg, errs[0])

    def test_unknown_and_malformed_keys(self):
        self.assertIn("unknown key colour", tweak_errors(tweak_conf(extra="colour=red\n"))[0])
        self.assertIn("not key=value", tweak_errors(tweak_conf(extra="just words\n"))[0])
        self.assertIn("name= is set twice", tweak_errors(tweak_conf(extra="name=Y\n"))[0])
        self.assertEqual(tweak_errors(""), ["tweaks/x/tweak.conf: missing %s=" % k
                                            for k in ("name", "summary", "firmware", "kind", "default")])
        self.assertIn("kind=daemon, should be oneshot or service", tweak_errors(tweak_conf(kind="daemon"))[0])
        self.assertIn("default=yes, should be on or off", tweak_errors(tweak_conf(default="yes"))[0])
        self.assertIn("firmware= is * or exact", tweak_errors(tweak_conf(firmware="*,CVEV.X"))[0])
        self.assertIn("firmware= is * or exact", tweak_errors(tweak_conf(firmware="bad fw"))[0])
        self.assertIn("conflicts with itself", tweak_errors(tweak_conf(extra="conflicts=x\n"))[0])
        self.assertIn("isn't a tweak id", tweak_errors(tweak_conf(extra="conflicts=a b\n"))[0])
        self.assertIn("a tweak id is letters", tweak_errors(tweak_conf(), tid="bad id")[0])

    def test_scripts_for_kind(self):
        self.assertIn("a kind=oneshot tweak needs enable.sh", tweak_errors(tweak_conf(), files=())[0])
        self.assertIn("a kind=service tweak needs run.sh", tweak_errors(tweak_conf(kind="service"), files=("enable.sh",))[0])

    def test_needs(self):
        good = ["file:/system/app/A.apk@" + "0" * 32, "file:/system/b@" + "0" * 32 + "," + "f" * 32,
                "prop:persist.sys.x", "setting:global/adb_enabled", "setting:secure/x_y",
                "service:adbd", "kill:com.google.android.projection.sink", "kill:com.x:remote",
                "binder:com.hkmc.micom.time 4", "binder:media.audio_flinger 1,22,3", "root"]
        for need in good:
            conf = tweak_conf(kind="service", extra="need=%s | Because\n" % need)
            self.assertEqual(tweak_errors(conf, files=("run.sh",)), [], need)
        bad = [("file:/system/app/A.apk", "should be file:<path>@<md5>"),
               ("file:/system/app/A.apk@ABC", "should be file:"),
               ("file:relative@" + "0" * 32, "should be file:"),
               ("file:/system/a b@" + "0" * 32, "should be file:"),
               ("file:/system/../x@" + "0" * 32, "the path must name a file"),
               ("prop:", "should be prop:<name>"),
               ("setting:system", "should be setting:<system|secure|global>/<name>"),
               ("setting:other/x", "should be setting:"),
               ("binder:svc", "should be binder:<service> <code>"),
               ("binder:svc a,b", "should be binder:"),
               ("root:x", "should be root"),
               ("sudo:x", "unknown need 'sudo'"),
               ("SETTING:system/x", "unknown need")]
        for need, msg in bad:
            errs = tweak_errors(tweak_conf(kind="service", extra="need=%s | Because\n" % need), files=("run.sh",))
            self.assertEqual(len(errs), 1, (need, errs))
            self.assertIn(msg, errs[0], need)
        for line in ("need=prop:x", "need=prop:x |", "need=prop:x |   "):
            self.assertIn("give a reason for the driver", tweak_errors(tweak_conf(extra=line + "\n"))[0])
        errs = tweak_errors(tweak_conf(extra="need=prop:x | A\nneed=prop:x | B\n"))
        self.assertIn("need prop:x is listed twice", errs[0])

    def test_reason_keeps_its_words(self):
        t, _ = validate.parse_tweak("x", tweak_conf(extra="need=prop:a.b|  Keep the \"switch\" | in step  \n"),
                                    {"enable.sh"})
        self.assertEqual(t["needs"], [{"need": "prop:a.b", "reason": "Keep the \"switch\" | in step"}])

    def test_oneshot_without_undo_needs_disable(self):
        for need in ("binder:svc 3", "kill:proc", "service:adbd", "root"):
            conf = tweak_conf(extra="need=%s | Because\n" % need)
            errs = tweak_errors(conf)
            self.assertEqual(len(errs), 1, errs)
            self.assertIn("must ship disable.sh", errs[0])
            self.assertEqual(tweak_errors(conf, files=("enable.sh", "disable.sh")), [])
            self.assertEqual(tweak_errors(tweak_conf(kind="service", extra="need=%s | B\n" % need), files=("run.sh",)), [])
        # the journal undoes files, props and settings
        conf = tweak_conf(extra="need=prop:a | A\nneed=setting:system/b | B\nneed=file:/system/c@%s | C\n" % ("0" * 32))
        self.assertEqual(tweak_errors(conf), [])

    def test_execute(self):
        for extra in ("\ntype=execute\n", ""):
            nd = nemesis_data(types="application") + extra
            z = make_zip({"NEMESIS.data": nd})
            self.assertEqual(validate.inspect_zip(z)["review"]["execute"], bool(extra))
        z = make_zip({"NEMESIS.data": nemesis_data(types="execute")})
        self.assertTrue(validate.inspect_zip(z)["review"]["execute"])

    def test_malformed(self):
        cases = {
            b"not a zip": "not a zip",
            make_zip({"pkg/NEMESIS.data": "x"}): "zip the package's contents",
            make_zip({"NEMESIS.data": "[app.0]\npath=x\n"}): "no [nemesis]",
            make_zip({"NEMESIS.data": nemesis_data(apps=[("app/x.apk", "a.b")])}): "isn't in the zip",
            make_zip({"NEMESIS.data": nemesis_data(), "../evil": "x"}): "unsafe path",
            make_zip({"NEMESIS.data": nemesis_data(apps=[("x.apk", "a.b")]), "x.apk": apk("c.d", 1)}):
                "package=a.b but x.apk is c.d",
        }
        for data, msg in cases.items():
            with self.assertRaises(validate.Fail) as c:
                validate.inspect_zip(data)
            self.assertIn(msg, str(c.exception))

    def test_binary_is_noted(self):
        z = make_zip({"NEMESIS.data": nemesis_data(types="service"), "bin/tool": b"\x7fELF\x01\x01"})
        r = validate.inspect_zip(z)
        self.assertEqual(r["flags"], [{"file": "bin/tool", "line": 0, "text": "", "rules": ["binary"]}])
        self.assertFalse(r["review"]["system_writes"])


class Axml(unittest.TestCase):
    def test_utf16_and_utf8(self):
        for utf8 in (False, True):
            self.assertEqual(validate.parse_axml_manifest(axml("dev.x", 42, utf8)),
                             {"package": "dev.x", "version_code": 42})

    def test_blank_attribute_names_use_resource_ids(self):
        self.assertEqual(validate.parse_axml_manifest(axml("dev.x", 7, blank_names=True))["version_code"], 7)

    def test_real_manifest(self):
        # Edit Menu's manifest (versionCode 1), built with aapt
        m = validate.parse_axml_manifest((FIXTURES / "edit-menu.AndroidManifest.xml").read_bytes())
        self.assertEqual(m, {"package": "dev.cabinwright.menu", "version_code": 1})

    def test_aapt_agrees(self):
        aapt = validate.find_aapt()
        if not aapt:
            self.skipTest("no aapt (set ANDROID_HOME)")
        a = apk("dev.x", 42)
        self.assertEqual(validate.apk_info_aapt(aapt, a), {"package": "dev.x", "version_code": 42})


if __name__ == "__main__":
    unittest.main()
