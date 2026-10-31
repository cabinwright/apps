#!/usr/bin/env python3
"""Builds index.json from apps/*.json, for the car.

usage: build_index.py --pages <dir> --key-id <id> [--apps apps] [--icons icons] [--first]
                      [--now <ISO time>] [--base-url https://cabinwright.github.io/apps/]

<dir> is a checkout of the gh-pages branch. Reads its index.json for the last sequence
(--first when there is none yet, which makes this one 1); the new one is the next. Reuses its
reviews/<sha256>.json so unchanged zips aren't downloaded again, and writes back index.json,
icons/<id>.png (copied from this repo's icons/) and new reviews. Any app that fails the checks
fails the build: nothing is published until it's fixed.

Sign the result with sign_index.py; the index is only valid together with its .sig.
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate  # noqa: E402

FORMAT = 1
LIFETIME = datetime.timedelta(days=90)
BASE_URL = "https://cabinwright.github.io/apps/"


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def previous_sequence(pages, first):
    p = Path(pages) / "index.json"
    if not p.exists():
        if not first:
            raise validate.Fail("%s doesn't exist; pass --first for the very first index" % p)
        return 0
    try:
        seq = json.loads(p.read_text())["sequence"]
    except (ValueError, KeyError, TypeError):
        raise validate.Fail("can't read the sequence from %s" % p)
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise validate.Fail("bad sequence in %s" % p)
    return seq


def icon(app_id, icons_dir, pages, base_url):
    """Publishes icons/<id>.png from the repo, if the app has one: {"url", "sha256"} or None."""
    src = validate.icon_path(icons_dir, app_id)
    if not src.exists():
        return None
    data = validate.check_icon(src)
    out = Path(pages) / "icons" / src.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {"url": base_url + "icons/" + out.name, "sha256": hashlib.sha256(data).hexdigest()}


def build(apps_dir, pages, key_id, now, first=False, base_url=BASE_URL, fetcher=validate.fetch, icons_dir=None):
    seq = previous_sequence(pages, first) + 1
    icons_dir = Path(icons_dir) if icons_dir else Path(apps_dir).parent / "icons"
    cache = Path(pages) / "reviews"
    files = sorted(Path(apps_dir).glob("*.json"))
    reps = [validate.check_app(f, None, cache, None, apps_dir, fetcher, icons_dir=icons_dir) for f in files]
    msgs = []
    for r in reps:
        msgs += ["%s: %s" % (r["file"], e) for e in r["errors"]]
        msgs += ["%s %s: %s" % (r["file"], v["version"], e) for v in r["versions"] for e in v["errors"]]
    ids = {f.stem for f in files}
    for p in sorted(icons_dir.glob("*.png")) if icons_dir.is_dir() else []:
        if p.stem not in ids:
            msgs.append("%s: no apps/%s.json for this icon" % (p, p.stem))
    if msgs:
        raise validate.Fail("\n".join(msgs))

    apps, icons = [], set()
    for r in sorted(reps, key=lambda r: r["app"]["id"]):
        a = r["app"]
        entry = {k: a.get(k, "") for k in ("id", "name", "summary", "description", "author",
                                           "homepage", "category")}
        ic = icon(a["id"], icons_dir, pages, base_url)
        if ic:
            entry["icon"] = ic
            icons.add(a["id"] + ".png")
        # retired apps stay listed, so cars that have one can show why and offer its removal
        for k in ("deprecated", "withdrawn", "replaced_by"):
            if k in a:
                entry[k] = a[k]
        entry["versions"] = []
        for v, rv in zip(a["versions"], r["versions"]):
            entry["versions"].append({
                "version": v["version"], "url": v["url"], "sha256": v["sha256"], "size": rv["size"],
                "firmware": v["firmware"], "requires": v.get("requires", []), "tier": v["tier"],
                "capabilities": v.get("capabilities", {}), "notes": v.get("notes", ""),
                "review": rv["review"],
            })
        apps.append(entry)

    # icons of apps that left the index
    for p in (Path(pages) / "icons").glob("*.png"):
        if p.name not in icons:
            p.unlink()

    index = {"format": FORMAT, "sequence": seq, "generated": iso(now), "expires": iso(now + LIFETIME),
             "key_id": key_id, "apps": apps}
    # ASCII-only so every JSON reader on the car sees the same bytes the same way
    data = (json.dumps(index, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    (Path(pages) / "index.json").write_bytes(data)
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build index.json from apps/*.json.")
    ap.add_argument("--apps", default=str(Path(__file__).resolve().parent.parent / "apps"))
    ap.add_argument("--icons", help="icons/<id>.png (default: icons/ next to --apps)")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--key-id", required=True)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--first", action="store_true")
    ap.add_argument("--now", help="build time, e.g. 2026-10-25T18:00:00Z (default: now)")
    a = ap.parse_args(argv)
    if a.now:
        now = datetime.datetime.strptime(a.now, "%Y-%m-%dT%H:%M:%SZ")
    else:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    base = a.base_url if a.base_url.endswith("/") else a.base_url + "/"
    try:
        index = build(a.apps, a.pages, a.key_id, now, a.first, base, icons_dir=a.icons)
    except validate.Fail as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    print("index.json: sequence %d, %d app(s), expires %s" % (
        index["sequence"], len(index["apps"]), index["expires"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
