# Submitting an app

An app in the store is one file, `apps/<id>.json`, added by a pull request (plus its icon,
`icons/<id>.png`, if it has one). The store never hosts packages: you publish your NEMESIS zip
as a GitHub release asset, and the entry pins its SHA-256. Once the PR is merged, the next
publish puts it in the signed index and every car running Cabinwright can install it.

## 1. Build and release the package

- The zip is a NEMESIS package: `NEMESIS.data` at the **root** of the zip (not in a folder),
  plus your files.
- `NEMESIS.data`'s `id` is your app's id (e.g. `tweaks.projection`) and its `version` is the
  version you list (numbers and dots only: `1.0`, `2.0.1`).
- Pick the tier your zip fits (CI works it out from the zip and checks it against the entry):
  - **`app`**: APKs at the top level of the zip (`myapp.apk`, not `app/myapp.apk`), nothing else.
  - **`tweaks`**: `tweaks/<id>/` folders, each with a `tweak.conf`, shared files in `lib/`, and
    optionally top-level APKs.
  - **`system`**: only `cabinwright.store`.

  For `app` and `tweaks` the store writes the package's manifest itself, so install hooks
  (`preinstall` and the rest), `[service.N]` sections, `kind=sh` entries, `type=execute` and
  any other files fail the check. Your app gets privileges through capabilities, and your
  tweaks through their `need=` lines.
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
  "id": "cabinwright.tweaks",
  "name": "Tweaks",
  "summary": "Small fixes, each with an on/off switch",
  "description": "Turn on fixes like automatic daylight saving time and skipping the start-up screen.",
  "author": "hazptr",
  "homepage": "https://github.com/cabinwright/tweaks",
  "category": "fixes",
  "versions": [
    {
      "version": "1.0",
      "url": "https://github.com/cabinwright/tweaks/releases/download/v1.0/cabinwright.tweaks-v1.0.zip",
      "sha256": "<64 hex digits>",
      "firmware": ["CVEV.USA.0000.V015.012.260507"],
      "tier": "tweaks",
      "capabilities": {"tweaks": "Shows and switches your tweaks"},
      "notes": "What changed."
    }
  ]
}
```

- `id`: the NEMESIS package id; the file must be named `<id>.json`.
- `category`: one of `fixes`, `apps`, `projection`, `system`, `tools`, `fun`.
- `summary` and `description` are for drivers, not developers: say what the app does for them, in
  plain words, a short phrase and one sentence. Leave out how it works; the store already shows
  what a package installs and changes from the review.
- `description` and `homepage` are optional.
- `versions`: newest first. You may keep older versions listed; the store installs the newest
  one that fits the car's firmware. Every version needs `version`, `url`, `sha256`,
  `firmware` and `tier`; `capabilities`, `requires` and `notes` are optional.
- `tier`: `app`, `tweaks` or `system`, as above.
- `capabilities` (apps only): what your app asks the store's broker for, each with the reason
  the driver reads at install, in plain words:

  | Capability | Lets your app | Asks the driver at first use |
  |---|---|---|
  | `tweaks` | list tweaks, read their status and log, switch them | no |
  | `logs` | read logcat | yes |
  | `settings` | change the settings and properties on the store's allowlist | no |
  | `root` | run commands as root; every command is logged and shown | yes, in red |

  ```json
  "capabilities": {"logs": "Shows why your phone didn't connect"}
  ```

  Ask only for what you use; unknown capabilities fail the check. An update that adds one asks
  the driver again before it installs.
- `firmware`: `["*"]` if the package writes nothing to the system. If it does (a tweak with a
  `file:` need, or anything else the review flags as a system write), list the exact firmware
  strings it was made and tested for.
- `requires`: other apps in the store, optionally with a minimum version (`id>=1.0`). The store
  installs them first.

The full schema is [schema/app.schema.json](schema/app.schema.json).

### Icon

Optional: add `icons/<id>.png` in the same PR, a PNG of at most 256x256 and 64 KiB. The index
serves it from `https://cabinwright.github.io/apps/icons/<id>.png`.

### Before the release exists

You can write the entry before tagging, with `"sha256": "pending"`. Every check refuses it
("sha256 is the placeholder"), so the entry can't be merged or published until you put in the
real hash.

## 3. Tweaks

Each `tweaks/<id>/tweak.conf` is checked (the format is in the store's
[docs/design.md](https://github.com/cabinwright/store/blob/main/docs/design.md#tweaks)):

```
name=Automatic daylight saving time
summary=Changes the clock for daylight saving time
description=Moves the clock forward in March and back in November.
firmware=CVEV.USA.0000.V015.012.260507
kind=service
default=on
need=setting:system/summer_time | Turn the head unit's own daylight-saving switch
need=binder:com.hkmc.micom.time 3,4 | Set the clock through the head unit's time service
```

- Keys: `name`, `summary`, `firmware`, `kind` (`oneshot` or `service`) and `default` (`on` or
  `off`) are required; `description` and `conflicts` are optional. Any other key fails the
  check. There is no `risk=`: a tweak "changes system files" when it has a `file:` need.
- A oneshot tweak has `enable.sh` (and optionally `disable.sh`, `status.sh`); a service tweak
  has `run.sh`.
- Each `need=` is `<need> | <reason>`. The reason is what the driver reads, so say what it is
  for, in plain words. Needs: `file:<path>@<md5>[,<md5>…]`, `prop:<name>`,
  `setting:<system|secure|global>/<name>`, `service:<name>`, `kill:<process>`,
  `binder:<service> <code>[,<code>…]`, and `root` (first-party only).
- A oneshot tweak with a `binder:`, `kill:`, `service:` or `root` need must ship `disable.sh`:
  the runner can undo files, properties and settings by itself, but not those.

In the review, each need shows in plain words with its reason, for example:

- adds the tweak `auto-dst`, Automatic daylight saving time: Changes the clock for daylight saving time (service, on by default, changes system settings)
  - changes the system setting `summer_time`: “Turn the head unit's own daylight-saving switch”
  - calls the binder service `com.hkmc.micom.time` (codes 3, 4): “Set the clock through the head unit's time service”

The store shows the driver the same needs at install, and refuses a zip whose `tweak.conf`
needs differ from the review.

## 4. Check it locally

```sh
python3 tools/validate.py apps/<id>.json
python3 tools/validate.py apps/<id>.json --local-zip dist/pkg.zip   # before uploading
python3 tools/validate.py --inspect dist/pkg.zip                    # just the review
```

Python 3.8+, nothing to install. It prints the same review CI will post.

## 5. Open the PR

Change only `apps/<id>.json` and `icons/<id>.png` (one app per PR is easiest to review). CI
downloads every new or changed version, checks the hash, `NEMESIS.data`, the tier and every
`tweak.conf`, and posts a review comment:

- the tier, and every file in the zip;
- the capabilities the app asks for, with your reasons;
- what the package installs: apps (package and versionCode), and each tweak with its needs;
- what runs as **root**;
- whether it **writes to the system**, and every flagged script line with its file and line
  number. Flags never fail the check; they tell the reviewer where to look.

Labels: `root` (something runs as root, a tweak needs `root`, or the app asks for `root`),
`system-writes`, and `needs-firmware-match` (a version lists exact firmware, so the reviewer
checks the strings are right).

The check fails on anything malformed or mismatched: bad JSON or schema, an id that doesn't
match the file name or the zip, a hash mismatch (or a `pending` one), versions out of order, a
missing `requires` target, a tier that doesn't match the zip, an unknown capability, a bad
`tweak.conf`, `type=execute`, system writes with `firmware: ["*"]`, or a deleted
`apps/*.json` (see [Retiring an app](#retiring-an-app)).

The owner reads the review and the scripts and merges or doesn't. Expect questions about
anything flagged, and about every need and capability.

## Updates

Add the new version at the top of `versions` in a new PR (keep or drop the old ones). Same
checks, same review.

## Retiring an app

Entries are never deleted: a car that installed an app needs its entry to tell the driver it's
gone and to offer its removal. A PR that deletes (or renames) an `apps/*.json` fails the check.
The owner retires an app with a PR that keeps the file and sets:

```json
  "deprecated": "Built into Tweaks now.",
  "replaced_by": "cabinwright.tweaks",
```

- `deprecated`: why, in plain words for drivers. It can't be empty. The store stops offering
  the app (no install, no update) and shows it, only to cars that have it, as "No longer
  offered" with this reason and a Remove button.
- `replaced_by` (optional): the id of another app in the index, which the store offers as
  "Get <name> instead". It must exist in `apps/`.
- `withdrawn`: for an app pulled for safety, with the reason. Everything `deprecated` does, plus
  a warning on the store's front page, on cars that have it, urging its removal.

Leave `versions` as they are: a retired entry can't gain new versions or new zips (the check
fails). To offer an app again, drop `deprecated`/`withdrawn` in a PR; the review says so.
