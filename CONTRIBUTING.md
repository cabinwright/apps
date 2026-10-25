# Submitting an app

An app in the store is one file, `apps/<id>.json`, added by a pull request. The store never
hosts packages: you publish your NEMESIS zip as a GitHub release asset, and the entry pins
its SHA-256. Once the PR is merged, the next publish puts it in the signed index and every
car running the App Store can install it.

## 1. Build and release the package

- The zip is an ordinary NEMESIS package: `NEMESIS.data` at the **root** of the zip (not in a
  folder), plus the files it points to.
- `NEMESIS.data`'s `id` is your app's id (e.g. `ev6.fixes`) and its `version` is the version
  you list (numbers and dots only: `1.4`, `2.0.1`).
- `type=execute` (USB autorun) packages are refused: the store only installs.
- Publish it as a release asset: `https://github.com/<you>/<repo>/releases/download/<tag>/<file>.zip`.
  At most 64 MiB. Don't replace the asset later: cars check the hash, so a changed zip needs
  a new version and a new PR. Building releases in CI (from a tag) makes this easy to keep.

Get the hash of the exact file you uploaded:

```sh
curl -sL -o pkg.zip https://github.com/<you>/<repo>/releases/download/v1.0/<file>.zip
sha256sum pkg.zip          # macOS: shasum -a 256 pkg.zip
```

## 2. Write `apps/<id>.json`

```json
{
  "id": "ev6.fixes",
  "name": "EV6 fixes",
  "summary": "eth0 guard, Android Auto recovery and a Status app",
  "description": "Longer plain text, shown on the app's page.",
  "author": "hazptr",
  "homepage": "https://github.com/hazptr/ev6-fixes",
  "category": "fixes",
  "icon": "https://raw.githubusercontent.com/hazptr/ev6-fixes/v1.4/status/icon.png",
  "versions": [
    {
      "version": "1.4",
      "url": "https://github.com/hazptr/ev6-fixes/releases/download/v1.4/ev6.fixes-v1.4.zip",
      "sha256": "<64 hex digits>",
      "firmware": ["CVEV.USA.0000.V015.012.260507"],
      "requires": ["kia.menu>=1.1"],
      "notes": "What changed."
    }
  ]
}
```

- `id`: the NEMESIS package id; the file must be named `<id>.json`.
- `category`: one of `fixes`, `apps`, `projection`, `system`, `tools`, `fun`.
- `description`, `homepage`, `icon` are optional. The icon is a PNG of at most 256x256 and
  64 KiB, over https.
- `versions`: newest first. You may keep older versions listed; the store installs the newest
  one that fits the car's firmware. Every version needs `version`, `url`, `sha256` and
  `firmware`; `requires` and `notes` are optional.
- `firmware`: `["*"]` if the package only installs ordinary apps and services. If it changes
  `/system` (or anything else the review flags as a system write), list the exact firmware
  strings it was made and tested for.
- `requires`: other apps in the store, optionally with a minimum version (`id>=1.1`). The store
  installs them first.

The full schema is [schema/app.schema.json](schema/app.schema.json).

## 3. Check it locally

```sh
python3 tools/validate.py apps/<id>.json
python3 tools/validate.py apps/<id>.json --local-zip dist/pkg.zip   # before uploading
python3 tools/validate.py --inspect dist/pkg.zip                    # just the review
```

Python 3.8+, nothing to install. It prints the same review CI will post.

## 4. Open the PR

Change only files under `apps/` (one app per PR is easiest to review). CI downloads every new
or changed version, checks the hash and `NEMESIS.data`, and posts a review comment:

- what the package installs: apps (package and versionCode) and services (uid and mode);
- what runs as **root**;
- whether it **writes to the system**, and every flagged script line with its file and line
  number. Flags never fail the check; they tell the reviewer where to look.

Labels: `root` (a service runs as root), `system-writes`, and `needs-firmware-match` (a version
lists exact firmware, so the reviewer checks the strings are right).

The check fails on anything malformed or mismatched: bad JSON or schema, an id that doesn't
match the file name or the zip, a hash mismatch, versions out of order, a missing
`requires` target, `type=execute`, or system writes with `firmware: ["*"]`.

The owner reads the review and the scripts and merges or doesn't. A package with a root
service controls every car that installs it, so expect questions about anything flagged.

## Updates

Add the new version at the top of `versions` in a new PR (keep or drop the old ones). Same
checks, same review.
