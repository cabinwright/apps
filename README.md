# Cabinwright apps

The index for **Cabinwright**, the store for Kia/Hyundai Gen5W head units running
[NEMESIS](https://github.com/xwtk/hmg_nemesis): one `apps/<id>.json` per app, checked on every
PR and published as a signed `index.json` at <https://cabinwright.github.io/apps/>.

- Submitting an app: [CONTRIBUTING.md](CONTRIBUTING.md).
- How the index works and the trust model: [DESIGN.md](DESIGN.md). The whole system (tiers,
  tweaks, capabilities, the broker) is in the store's
  [docs/design.md](https://github.com/cabinwright/store/blob/main/docs/design.md).

| Path | What |
|---|---|
| `apps/` | One entry per app, written by its developer. |
| `icons/` | `<id>.png` per app that has an icon, published with the index. |
| `keys/` | Public index signing keys (`cabinwright-2026a` signs; `cabinwright-2026b` is the offline backup). |
| `schema/app.schema.json` | Schema for `apps/*.json`. |
| `tools/validate.py` | Checks entries, downloads and reviews packages (CI and local). |
| `tools/build_index.py`, `tools/sign_index.py` | Build and sign `index.json` (the publish job). |
| `tools/keygen.py` | A new signing key. |
| `tests/` | `python3 -m unittest discover -s tests`; `tests/vectors/` are shared with the store's verifier tests. |

The repo needs a GitHub environment `publish` that only `main` may deploy to, holding one
secret, `INDEX_SIGNING_KEY` (the PEM of the key named in `.github/workflows/publish.yml`), and
GitHub Pages serving the `gh-pages` branch.
