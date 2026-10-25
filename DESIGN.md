# kia-apps: an app store for NEMESIS head units

Status: design, 2026-10-25. Target: the 2023 Kia EV6 head unit (Gen5W, Android 4.4.2,
`wp_daudioplus_cvev_us`, firmware `CVEV.USA.0000.V015.012.260507`) running
[NEMESIS](https://github.com/xwtk/hmg_nemesis), and other Gen5W units where packages allow it.

## Goals

- Anyone can publish a NEMESIS package by opening a PR that adds one file to the index repo.
- The repo owner reviews and merges; that merge is the only trust decision.
- On the car, an **App Store** app in All Menus lists the apps, installs, updates and removes
  them, with no ADB or USB stick.
- The car never installs anything the owner didn't merge, even if the network, GitHub's TLS,
  the sdcard or another app on the car is hostile.

Not goals: payments, ratings, user accounts, hosting the packages (developers host their own
zips on GitHub Releases), or protecting a car from its owner.

## Pieces

| Piece | Where | What |
|---|---|---|
| Index repo | `hazptr/kia-apps` (this repo) | `apps/<id>.json` per app, CI that checks every PR, and a publish job that builds and **signs** `index.json` |
| Published index | GitHub Pages, `https://hazptr.github.io/kia-apps/` | `index.json`, `index.json.sig`, icons |
| App Store app | `kia-store/app`, NEMESIS package `kia.store` | Browses the index, downloads zips, asks the helper to install |
| Install helper | `kia-store/helper`, a service in `kia.store` | Runs as root, re-verifies everything itself, runs `nemesis install` |

`kia.store` is itself listed in the index, so it updates the same way as everything else.

## Trust model

The index is signed with the **index signing key** (RSA-3072, `SHA256withRSA`, PKCS#1 v1.5).
Its public key is pinned in both the app and the helper. The private key exists only in the
repo's Actions secret `INDEX_SIGNING_KEY` and an offline copy of the owner's.

Each version in the index carries the zip's SHA-256 and size, so signing the index covers every
package it lists. Developers sign their APKs with their own keys as usual; the store doesn't
rely on that.

Why RSA/PKCS#1 v1.5 and not Ed25519: Android 4.4's `java.security` has no Ed25519, while
`SHA256withRSA` works on every Android version. `SHA256withECDSA` would also work, but RSA
keeps the verifier trivially portable to the helper and to Python.

What each attacker gets:

| Attacker | Can | Can't |
|---|---|---|
| Network / bad TLS (the car's 2014-era CA store may force a lenient TLS fallback) | Block updates; replay an **old** signed index | Forge an index or a zip (signature + SHA-256) |
| Replay of an old index | Nothing, as long as it's newer than the last one seen | Roll back: `sequence` must not decrease, and `expires` bounds staleness to 90 days |
| Another app on the car / the sdcard (world-writable to sdcard_rw apps) | Plant requests or swap files | Get anything installed that the signed index doesn't list with that exact hash: the helper copies to private storage first, then verifies |
| A developer whose PR was merged | Whatever their package does, as root | Ship a different zip later: the hash is pinned; a new zip needs a new PR |
| Someone with write access to the repo but not the secret | Change `apps/` | Publish: only the publish job can sign, and only from `main` |

The owner's review is the real security boundary: a merged package with a root service owns
every car that installs it. CI exists to make that review fast and hard to get wrong (below).

### Key handling

- Generate with `tools/keygen.py` → `index-signing.pem` (private, never committed) and
  `keys/<key_id>.pub.pem` (committed). `key_id` names the key, e.g. `kia-apps-2026a`.
- The app and helper pin a **list** of accepted `{key_id, public key}`, so a key can be rotated
  by shipping a `kia.store` update that trusts the new key before the index switches over.
- Lost or leaked key: ship a `kia.store` update that drops it (the update itself must still be
  signed by a trusted key, so keep a second, offline key in the pinned list from day one).

## Index repo layout

```
apps/<id>.json            one per app, written by the developer (the PR)
keys/<key_id>.pub.pem     public signing keys
schema/app.schema.json    JSON Schema for apps/*.json
tools/validate.py         checks one or more apps/*.json (used by CI, runnable locally)
tools/build_index.py      apps/*.json + review data -> index.json
tools/sign_index.py       index.json -> index.json.sig
tools/keygen.py           new signing key
.github/workflows/check.yml     on pull_request
.github/workflows/publish.yml   on push to main, weekly schedule, workflow_dispatch
CONTRIBUTING.md           how to submit an app
```

### `apps/<id>.json` (what a developer writes)

```json
{
  "id": "ev6.fixes",
  "name": "EV6 fixes",
  "summary": "eth0 guard, Android Auto recovery and a Status app",
  "description": "Longer text, plain, shown on the app's page.",
  "author": "hazptr",
  "homepage": "https://github.com/hazptr/ev6-fixes",
  "category": "fixes",
  "icon": "https://raw.githubusercontent.com/hazptr/ev6-fixes/v1.4/status/icon.png",
  "versions": [
    {
      "version": "1.4",
      "url": "https://github.com/hazptr/ev6-fixes/releases/download/v1.4/ev6.fixes-v1.4.zip",
      "sha256": "…64 hex…",
      "firmware": ["CVEV.USA.0000.V015.012.260507"],
      "requires": ["kia.menu>=1.1"],
      "notes": "What changed."
    }
  ]
}
```

- `id` is the NEMESIS package id and must equal the filename and `NEMESIS.data`'s `id`.
- `versions` is newest first. Older versions may stay listed; the store installs the newest
  one that fits the car's firmware.
- `firmware` is a list of exact firmware strings, or `["*"]` for packages that only install
  ordinary apps or services. A package that writes `/system` must list exact firmware.
- `category`: one of `fixes`, `apps`, `projection`, `system`, `tools`, `fun`.
- `icon` optional: a PNG, at most 256x256, at most 64 KiB, `https` only.

### CI on a PR (`check.yml`)

The PR may change only files under `apps/` (one app per PR is the norm; several is allowed).
For each changed app, `validate.py`:

1. Validates against the schema; checks the `id` against the filename; checks the version
   strings are unique and newest first.
2. For each **new or changed** version: downloads `url` (must be `https://github.com/<owner>/<repo>/releases/download/…`,
   at most 64 MiB, following GitHub's redirect) and checks `sha256`.
3. Opens the zip: `NEMESIS.data` at the root, its `id` and `version` match the entry.
4. Inspects what the package does and writes a **review** record:
   - `types` from `NEMESIS.data`; every `[app.N]` (package name and versionCode, read from the
     APK with `aapt dump badging` or a Python AXML parser); every `[service.N]` with its `uid`
     and `mode`.
   - `root_services`: services with `uid=root` (or no uid).
   - `system_writes`: any script containing `remount`, `/system/`, `mount -o`, `dd `, `setprop persist.`,
     `pm disable`, `reboot`, `iptables`, `chmod`/`chown` outside its own dir, `/data/data/` of other apps,
     `/dev/block`.
   - `execute`: `type=execute` (USB autorun-style), which the store **refuses outright**.
   - Every flagged line, with file and line number.
5. Posts (or updates) one PR comment with the review: what the package installs, what runs as
   root, and every flagged line. It labels the PR `root`, `system-writes` and `needs-firmware-match`
   as they apply. `system_writes` with `firmware: ["*"]` is an error.

Checks fail on anything malformed or mismatched. Flags don't fail the check: they're for the owner.

### Publishing (`publish.yml`)

On push to `main` (and weekly, so `expires` never lapses, and on manual dispatch):

1. Re-run the checks over every `apps/*.json` and compute the review records (cached by sha256
   in the `gh-pages` branch so unchanged zips aren't downloaded again).
2. `build_index.py`: read the currently published `index.json` from `gh-pages` and set
   `sequence` = old + 1; `generated` = now; `expires` = now + 90 days.
3. `sign_index.py` with `INDEX_SIGNING_KEY` → `index.json.sig`.
4. Commit `index.json`, `index.json.sig` and icons to `gh-pages`. GitHub Pages serves it.

### `index.json` (what the car reads)

```json
{
  "format": 1,
  "sequence": 42,
  "generated": "2026-10-25T18:00:00Z",
  "expires": "2027-01-23T18:00:00Z",
  "key_id": "kia-apps-2026a",
  "apps": [
    {
      "id": "ev6.fixes", "name": "…", "summary": "…", "description": "…", "author": "…",
      "homepage": "…", "category": "fixes",
      "icon": {"url": "https://hazptr.github.io/kia-apps/icons/ev6.fixes.png", "sha256": "…"},
      "versions": [
        {
          "version": "1.4", "url": "…", "sha256": "…", "size": 123456,
          "firmware": ["CVEV.USA.0000.V015.012.260507"], "requires": ["kia.menu>=1.1"], "notes": "…",
          "review": {
            "types": ["application", "service"],
            "apps": [{"package": "dev.ev6fixes.status", "version_code": 12}],
            "services": [{"name": "eth0-guard", "uid": "root"}],
            "root_services": ["eth0-guard", "aa-recover", "status"],
            "system_writes": false,
            "execute": false
          }
        }
      ]
    }
  ]
}
```

`index.json.sig` is the base64 of the `SHA256withRSA` signature over the **exact bytes** of
`index.json` as served. Verifiers must check the bytes they have, never a re-serialization.

Version comparison everywhere: split on `.`, compare numerically part by part, with missing
parts counting as 0 (`1.10` > `1.9`, `1.0` == `1`).

## On the car: `kia.store`

### Firmware and installed state

- Firmware string: the system property that holds `CVEV.USA.0000.V015.012.260507` on this car
  (find the exact property; fall back to showing "unknown firmware" and treating only `["*"]`
  versions as compatible).
- Installed packages and versions: the helper writes `nemesis pkg-list` output to the status
  file (below) every time it runs a request and once at start.

### The App Store app (`dev.kiastore`)

Built with kia-menu's `build-app.sh --ui` on `KiaPage` (Kia's colours, Mobis font, day/night,
split-screen aware, slim title row). Shows up in All Menus via `MenuContract`.

- **Browse**: a grid/list of apps with icon, name, summary, an "Installed 1.3 / Update to 1.4"
  state, and category filter chips. Incompatible firmware greys the install button with a reason.
- **App page**: description, author, homepage (as text), version notes, and the review spelled
  out in plain words: "Installs the app Status", "Runs 3 services as root", "Writes to /system
  (firmware-locked)". Root and `/system` items get a confirmation step on install.
- **Install / Update / Remove**, with progress (download %, verifying, installing) and the
  helper's result or error message. `requires` is resolved first: missing requirements are
  offered as part of the same install, in dependency order.
- **Refresh**: fetch the index from Pages. Never accept an index whose signature fails, whose
  `sequence` is lower than the last accepted one, or that has expired; say which.
- Remembers the last accepted index in app storage and **also** in `/sdcard/kia-store/` (app
  data is wiped on every NEMESIS update, as kia-menu found).

Networking on Android 4.4: force TLS 1.2 on `HttpsURLConnection` (it's off by default on API
16-19 clients). The car's root CA store may not trust GitHub's current chains; bundle the roots
that `hazptr.github.io`, `github.com` and `objects.githubusercontent.com` chain to, and use
them in addition to the system's. Security never depends on TLS, only on the signature and
hashes, so if a host can't be validated, fail with a clear message rather than disable checking.

### Requests: app → helper

The app can't run `nemesis install` (it needs root), so it hands requests to the helper through
the sdcard, which both can reach:

```
/sdcard/kia-store/index.json, index.json.sig   the index the app accepted (helper re-checks)
/sdcard/kia-store/downloads/<id>-<version>.zip
/sdcard/kia-store/requests/<uuid>.json          {"op": "install", "id": "ev6.fixes", "version": "1.4",
                                                  "zip": "/sdcard/kia-store/downloads/ev6.fixes-1.4.zip"}
                                                 {"op": "uninstall", "id": "ev6.fixes"}
/sdcard/kia-store/results/<uuid>.json           {"state": "working" | "ok" | "failed",
                                                  "step": "verifying", "message": "…", "log": "…"}
/sdcard/kia-store/status.json                   helper heartbeat + `nemesis pkg-list` + firmware
```

The app writes a request as `<uuid>.json.tmp` then renames it. It polls `results/` and the
heartbeat (and says so plainly if the helper isn't running).

### The helper

A NEMESIS service in `kia.store` (`uid=root`, `mode=restart`). Its shell script launches a small
Java program as root (with `dalvikvm` or `app_process`, the way Leafia runs Java on the car),
because verifying RSA signatures in `sh` isn't possible here. For each request, oldest first:

1. Move the request out of `requests/` (so it runs once) and write `results/<uuid>.json` as
   `working`.
2. Copy `index.json` and `.sig` into private storage, `/data/nemesis/kia-store/`, and verify
   the signature against the **helper's own** pinned keys, the `sequence` against its own
   last-accepted sequence (stored in `/data/nemesis/kia-store/state.json`), and `expires`.
3. For install: find `id` + `version` in the index; refuse `execute`; check firmware
   compatibility. Copy the zip into private storage, then check size and SHA-256 **of the copy**,
   then open it and check `NEMESIS.data`'s `id` and `version`.
4. Run `nemesis install --update <private copy>` (or `nemesis uninstall <id>`, only for ids
   present in the index). Capture its output into the result.
5. Write the result and refresh `status.json`. Delete the private zip copy.

The helper never trusts anything the app or the sdcard says beyond "which id and version":
every check is repeated against its own pinned keys and its own copy of the bytes.

## Seed content

`apps/kia.menu.json`, `apps/ev6.fixes.json` and `apps/kia.store.json`, filled in once those
repos have CI-built releases (their release zips' SHA-256 come from the releases, not local
builds).

## Testing on the car

- Unit tests for the Python tools (schema, versions, review flags, index build, sign/verify
  round trip) and for the Java verifier (the same test vectors on both sides).
- An index served from a local file for development: the app and helper accept a debug index
  location only when a file `/data/nemesis/kia-store/debug-index` exists (root-only to create),
  and still verify it with a separate **test key** that is pinned only in debug builds.
- End-to-end on the car over ADB: install, update, remove, refusal of a tampered zip, of a bad
  signature and of a rolled-back sequence.
