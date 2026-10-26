# Cabinwright apps: the index

The signed list of what the Cabinwright store offers on Gen5W head units running
[NEMESIS](https://github.com/xwtk/hmg_nemesis) (target: the 2023 Kia EV6, Android 4.4.2,
firmware `CVEV.USA.0000.V015.012.260507`). The system as a whole (tiers, tweaks and their
needs, capabilities, the broker, `cabinwrightd`) is described in the store's
[docs/design.md](https://github.com/cabinwright/store/blob/main/docs/design.md); this document
covers the index: what developers write, what CI checks, and what the car reads.

## Goals

- Anyone can publish a NEMESIS package by opening a PR that adds one file to this repo.
- The repo owner reviews and merges; that merge is the only trust decision.
- The car never installs anything the owner didn't merge, even if the network, GitHub's TLS,
  the sdcard or another app on the car is hostile.
- The review the owner merges is the one the driver sees: each tweak's needs and each app's
  capabilities are in the signed index, and the store refuses a zip that says otherwise.

Not goals: payments, ratings, user accounts, hosting the packages (developers host their own
zips on GitHub Releases), or protecting a car from its owner.

## Pieces

| Piece | Where | What |
|---|---|---|
| Index repo | `cabinwright/apps` (this repo) | `apps/<id>.json` and `icons/<id>.png` per app, CI that checks every PR, and a publish job that builds and **signs** `index.json` |
| Published index | GitHub Pages, `https://cabinwright.github.io/apps/` | `index.json`, `index.json.sig`, `icons/`, `reviews/` (the review cache) |
| Store | `cabinwright/store`, NEMESIS package `cabinwright.store` | The store app shows the index; `cabinwrightd` re-verifies it and installs |

`cabinwright.store` is itself listed in the index, so it updates the same way as everything else.

## Trust model

The index is signed with the **index signing key** (RSA-3072, `SHA256withRSA`, PKCS#1 v1.5).
Its public key is pinned in the store, in both the app and `cabinwrightd`. The private key
exists only in the `publish` environment's secret `INDEX_SIGNING_KEY` and in the owner's
offline copy.

Each version in the index carries the zip's SHA-256 and size, so signing the index covers every
package it lists. Developers sign their APKs with their own keys as usual; the store records
those certificates at install for the broker, but the index doesn't rely on them.

Why RSA/PKCS#1 v1.5 and not Ed25519: Android 4.4's `java.security` has no Ed25519, while
`SHA256withRSA` works on every Android version and is a few lines to verify in Python.

| Attacker | Can | Can't |
|---|---|---|
| Network / bad TLS (the car's CA store may force a lenient TLS fallback) | Block updates; replay an **old** signed index | Forge an index or a zip (signature + SHA-256) |
| Replay of an old index | Nothing, as long as it's newer than the last one seen | Roll back: `sequence` must not decrease, and `expires` bounds staleness to 90 days |
| Another app on the car / the sdcard | Swap or delete downloads in progress: at worst a failed install | Get anything installed that the signed index doesn't list with that exact hash: `cabinwrightd` copies the zip to private storage, then verifies it |
| A developer whose PR was merged | What the review says their package may do: an app's capabilities, a tweak's needs; a `system` package (only `cabinwright.store`) anything | Ship a different zip later: the hash is pinned; a new zip needs a new PR |
| Someone with write access to the repo but not the secret | Change `apps/` | Publish: only the publish job can sign, only from `main`, only through the `publish` environment |

The owner's review is the real security boundary. CI exists to make that review fast and hard
to get wrong (below).

### Key handling

- `tools/keygen.py <key_id>` writes the private key to `~/.config/cabinwright/<key_id>.pem`
  (never committed) and the public key to `keys/<key_id>.pub.pem` (committed). Key ids:
  `cabinwright-2026a` signs, `cabinwright-2026b` is the offline backup.
- The store pins a **list** of accepted `{key_id, public key}`, so a key is rotated by shipping
  a `cabinwright.store` update that trusts the new key before the index switches over.
- Lost or leaked key: ship a `cabinwright.store` update that drops it, signed by the other key.
- `sign_index.py` refuses a private key whose public half isn't `keys/<key_id>.pub.pem`, and
  verifies its own signature before anything is published.

## Repo layout

```
apps/<id>.json            one per app, written by the developer (the PR)
icons/<id>.png            the app's icon, optional
keys/<key_id>.pub.pem     public signing keys
schema/app.schema.json    JSON Schema for apps/*.json
tools/validate.py         checks apps/*.json and reviews their zips (CI, and locally)
tools/build_index.py      apps/*.json + icons/ + reviews -> index.json
tools/sign_index.py       index.json -> index.json.sig, and --verify
tools/keygen.py           new signing key
tests/                    unit tests; tests/vectors/ is shared with the store's verifier tests
.github/workflows/check.yml           on pull_request: computes the review (no secrets)
.github/workflows/review-comment.yml  posts it on the PR
.github/workflows/publish.yml         on push to main, weekly, workflow_dispatch
```

### `apps/<id>.json`

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
      "sha256": "…64 hex…",
      "firmware": ["CVEV.USA.0000.V015.012.260507"],
      "tier": "tweaks",
      "capabilities": {"tweaks": "Shows and switches your tweaks"},
      "notes": "First release."
    }
  ]
}
```

- `id` is the NEMESIS package id and must equal the file name and `NEMESIS.data`'s `id`.
- `versions` is newest first. Older versions may stay listed; the store installs the newest
  one that fits the car's firmware.
- `firmware` is a list of exact firmware strings, or `["*"]` for packages that write nothing to
  the system. A package that does (a script line flagged as a system write, or a tweak with a
  `file:` need) must list exact firmware.
- `tier`: `app`, `tweaks` or `system` (below). Required; CI derives it from the zip and fails
  if the entry says otherwise.
- `capabilities`: optional, `{capability: reason}`, the reason in plain words for the driver.
  Known capabilities: `tweaks`, `logs`, `settings`, `root`. Only packages with an APK may ask.
- `requires`: other apps in the index, optionally with a minimum version (`id>=1.0`).
- `category`: one of `fixes`, `apps`, `projection`, `system`, `tools`, `fun`.
- `deprecated`, `withdrawn`, `replaced_by`: retirement, below.
- The icon isn't a field: it is `icons/<id>.png` in this repo, a PNG of at most 256x256 and
  64 KiB. The publish job copies it to Pages, so its URL never depends on another repo's history.

### Tiers

CI opens the zip and works out the tier from what it holds:

| Tier | The zip holds | Who writes the manifest |
|---|---|---|
| `app` | `NEMESIS.data` and top-level `*.apk` | the store |
| `tweaks` | `NEMESIS.data`, `tweaks/<id>/**`, `lib/**`, and top-level `*.apk` | the store |
| `system` | anything | the package (only for ids in `SYSTEM_IDS`: `cabinwright.store`) |

A zip with an install hook (`preinstall` and the rest), a `[service.N]`, `type=execute`, an
`[app.N]` that isn't `kind=apk`, or any file outside those paths can only be `system`. For an
`app` or `tweaks` entry, each of those is an error naming what was found. The store keeps
`SYSTEM_IDS` compiled in and never takes it from the index.

### Tweaks in the review

Every `tweaks/<id>/tweak.conf` is parsed (format in the store's design.md). CI fails on:

- a key other than `name`, `summary`, `description`, `firmware`, `kind`, `default`,
  `conflicts` and `need` (`risk=`, `retired=` and `replaces=` each get their own explanation),
  a key set twice, a line that isn't `key=value`, or a missing `name`, `summary`, `firmware`,
  `kind` or `default`;
- `kind` other than `oneshot`/`service`, `default` other than `on`/`off`, a malformed
  `firmware=` or `conflicts=`, or a missing `enable.sh` (oneshot) or `run.sh` (service);
- a `need=` that isn't `<need> | <reason>` with a known need in its exact form, or is listed
  twice;
- a oneshot tweak with a `binder:`, `kill:`, `service:` or `root` need and no `disable.sh`: the
  runner can't undo those steps from its journal.

The review lists, per tweak, its needs in `tweak.conf` order, as `{need, reason}` with both
sides trimmed. The store compares them exactly with the zip it downloaded.

### Retiring an app

Entries are **never deleted**: a car that installed an app needs its entry to say it's gone and
offer its removal. An entry is retired instead, by the owner, in a PR:

- `"deprecated": "<plain reason>"`: no longer offered. The store shows it only to cars that
  have it, with the reason and Remove; no install, no update.
- `"withdrawn": "<plain reason>"`: pulled for safety. The same, plus a warning urging removal.
- `"replaced_by": "<id>"`, with either: the store offers that app instead.

A retired entry keeps its versions (so the store can still describe what's installed) but
can't gain new ones. Un-retiring is a PR that drops the field.

### CI on a PR (`check.yml`)

The PR may change only `apps/<id>.json` and `icons/<id>.png` (the owner may change anything;
the comment lists it). The tools run from the base branch, so a PR can't change how it is
reviewed. For each changed entry, and the entry of each changed icon, `validate.py`:

1. Validates against the schema; checks the `id` against the file name; checks the versions are
   unique and newest first, `requires` exist, and the icon is a PNG within the limits.
2. For each **new or changed** version: downloads `url` (must be a GitHub release asset, at most
   64 MiB, https all the way) and checks `sha256`.
3. Opens the zip: `NEMESIS.data` at the root, `id` and `version` match the entry; derives the
   tier and checks it and the capabilities against the entry; parses every `tweak.conf`.
4. Writes the **review**: the tier, every file, the APKs (package and versionCode), services,
   hooks and script entries, each tweak with its needs, what runs as root, whether the package
   writes to the system, and every flagged script line with file and line number.
5. Posts one PR comment with the review in plain words (`review-comment.yml`) and labels the PR
   `root` (something runs as root, a tweak needs `root`, or the app asks for `root`),
   `system-writes` and `needs-firmware-match`.
6. Retirement: a PR that deletes (or renames) an `apps/*.json` fails, pointing at
   `deprecated`. So do an empty `deprecated` or `withdrawn`, a `replaced_by` without either or
   naming an id missing from `apps/`, and a new or changed version on a retired entry.

Checks fail on anything malformed or mismatched. Flags don't fail the check: they're for the owner.

### Release placeholders

An entry can be written before its release exists with `"sha256": "pending"`. The url is
known in advance (`…/releases/download/v<version>/<id>-v<version>.zip`); the hash isn't. Every
check refuses `pending` with a plain message ("sha256 is the placeholder"), so neither a PR
nor the publish job can let one through: the index isn't rebuilt until the real hashes are in.
`tests/test_entries.py` checks the repo's entries are otherwise well formed.

### Publishing (`publish.yml`)

On push to `main`, weekly (so `expires` never lapses), and on manual dispatch, in the
`publish` environment:

1. Run the tests, then `build_index.py`: re-check every `apps/*.json` (reviews are cached by
   sha256 in `gh-pages/reviews/`, so unchanged zips aren't downloaded again); copy
   `icons/<id>.png` to `gh-pages/icons/`; `sequence` = the published one + 1 (1 for the first
   index); `generated` = now; `expires` = now + 90 days.
2. `sign_index.py` with `INDEX_SIGNING_KEY` → `index.json.sig`, then verify it.
3. Commit `index.json`, `index.json.sig`, `icons/` and `reviews/` to `gh-pages`. Pages serves it.

### `index.json` (what the car reads)

```json
{
  "format": 1,
  "sequence": 1,
  "generated": "2026-10-25T18:00:00Z",
  "expires": "2027-01-23T18:00:00Z",
  "key_id": "cabinwright-2026a",
  "apps": [
    {
      "id": "cabinwright.tweaks", "name": "…", "summary": "…", "description": "…", "author": "…",
      "homepage": "…", "category": "fixes",
      "icon": {"url": "https://cabinwright.github.io/apps/icons/cabinwright.tweaks.png", "sha256": "…"},
      "deprecated": "…", "withdrawn": "…", "replaced_by": "…",   (only when set)
      "versions": [
        {
          "version": "1.0", "url": "…", "sha256": "…", "size": 153894,
          "firmware": ["CVEV.USA.0000.V015.012.260507"], "requires": [],
          "tier": "tweaks",
          "capabilities": {"tweaks": "Shows and switches your tweaks"},
          "notes": "First release.",
          "review": {
            "tier": "tweaks",
            "types": ["application"],
            "files": ["NEMESIS.data", "lib/tweakpatch.jar", "tweaks.apk", "tweaks/auto-dst/run.sh", "…"],
            "apps": [{"package": "dev.cabinwright.tweaks", "version_code": 1}],
            "services": [], "root_services": [], "hooks": [], "sh_entries": [],
            "tweaks": [
              {
                "id": "auto-dst", "name": "…", "summary": "…", "description": "…",
                "kind": "service", "default": "on",
                "firmware": ["CVEV.USA.0000.V015.012.260507"], "conflicts": [],
                "needs": [
                  {"need": "binder:com.hkmc.micom.time 3,4", "reason": "…"},
                  {"need": "setting:system/summer_time", "reason": "…"}
                ],
                "changes": "settings", "disable": false
              }
            ],
            "root": [],
            "system_writes": true,
            "execute": false
          }
        }
      ]
    }
  ]
}
```

- `capabilities` is always an object (`{}` when the app asks for nothing).
- `review.tweaks[].changes` is `files` when the tweak has a `file:` need, else `settings`;
  `disable` says whether it ships `disable.sh`.
- `review.root` lists what runs as root: services, hooks, `kind=sh` entries (all `system` only)
  and tweaks with the `root` need.

`index.json` is ASCII-only JSON. `index.json.sig` is the base64 of the `SHA256withRSA`
signature over its **exact bytes** as served. Verifiers must check the bytes they have, never a
re-serialization.

Version comparison everywhere: split on `.`, compare numerically part by part, with missing
parts counting as 0 (`1.10` > `1.9`, `1.0` == `1`).

## Testing

- `python3 -m unittest discover -s tests`: schema, versions, the review and its flags, tiers,
  `tweak.conf`, the index build, sign/verify round trips (those need the `cryptography`
  package and are skipped without it), and the repo's own entries. Nothing touches the network.
- `tests/make_vectors.py` regenerates `tests/vectors/`: an index signed with a test key at a
  fixed time, and a tampered copy. The store's host tests verify the same bytes.
- `python3 tools/validate.py --inspect <zip>` reviews a local zip without an entry.
