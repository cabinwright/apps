# Cabinwright apps

The index for **Cabinwright**, the app store for Kia/Hyundai Gen5W head units running
[NEMESIS](https://github.com/xwtk/hmg_nemesis): one `apps/<id>.json` per app, checked on every
PR and published as a signed `index.json` at <https://cabinwright.github.io/apps/>.

This index took over from `hazptr/kia-apps` (frozen) when the project became Cabinwright: the
store, Edit Menu and Tweaks have new ids (`cabinwright.store`, `cabinwright.menu`,
`cabinwright.tweaks`), the tweak packs kept theirs, and the signing keys are the same. Moving a
car over: the store's [docs/migrating-from-kia.md](https://github.com/cabinwright/store/blob/main/docs/migrating-from-kia.md).

- Submitting an app: [CONTRIBUTING.md](CONTRIBUTING.md).
- How it fits together and the trust model: [DESIGN.md](DESIGN.md).

| Path | What |
|---|---|
| `apps/` | One entry per app, written by its developer. |
| `keys/` | Public index signing keys (`kia-apps-2026a` signs; `kia-apps-2026b` is the offline backup). |
| `schema/app.schema.json` | Schema for `apps/*.json`. |
| `tools/validate.py` | Checks entries, downloads and reviews packages (CI and local). |
| `tools/build_index.py`, `tools/sign_index.py` | Build and sign `index.json` (the publish job). |
| `tools/keygen.py` | A new signing key. |
| `tests/` | `python3 -m unittest discover -s tests`; `tests/vectors/` are shared with the Java verifier. |
| `seed/` | First entries, waiting for their release hashes before moving to `apps/`. |

The repo needs one secret, `INDEX_SIGNING_KEY` (the PEM of the key named in
`.github/workflows/publish.yml`), and GitHub Pages serving the `gh-pages` branch.
