"""The repo's own apps/*.json and icons/: well formed, apart from sha256s still pending a release."""
import json
import unittest
from pathlib import Path

from helpers import HERE

import validate

ROOT = HERE.parent
APPS = sorted((ROOT / "apps").glob("*.json"))


class Entries(unittest.TestCase):
    def test_entries(self):
        self.assertTrue(APPS)
        for p in APPS:
            doc = json.loads(p.read_text())
            pending = validate.pending_errors(doc)
            errs = [e for e in validate.check_schema(doc, validate.load_schema())
                    if not (pending and ".sha256: " in e)]
            self.assertEqual(errs, [], p.name)
            self.assertEqual(doc["id"], p.stem)
            for v in doc["versions"]:
                self.assertRegex(v["url"], validate.RELEASE_URL)
                if v["tier"] == "system":
                    self.assertIn(doc["id"], validate.SYSTEM_IDS)
                for r in v.get("requires", []):
                    self.assertTrue((ROOT / "apps" / ("%s.json" % validate.REQUIRE.match(r).group(1))).exists(), r)

    def test_icons(self):
        ids = {p.stem for p in APPS}
        for p in sorted((ROOT / "icons").glob("*.png")):
            self.assertIn(p.stem, ids, "icon without an entry")
            validate.check_icon(p)

    def test_tiers(self):
        tiers = {p.stem: [v["tier"] for v in json.loads(p.read_text())["versions"]] for p in APPS}
        self.assertEqual(tiers["cabinwright.store"], ["system"])
        self.assertEqual(tiers["cabinwright.menu"], ["app"])
        self.assertEqual(tiers["cabinwright.tweaks"], ["tweaks"])


if __name__ == "__main__":
    unittest.main()
