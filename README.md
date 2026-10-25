# kia-apps

The index for the **App Store** on Kia/Hyundai Gen5W head units running
[NEMESIS](https://github.com/xwtk/hmg_nemesis): one `apps/<id>.json` per app, checked on every
PR and published as a signed `index.json` at <https://hazptr.github.io/kia-apps/>.

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
