# Security notes

Satyapan is a hackathon prototype that runs entirely on one laptop. All data in the repository is synthetic (see `../docs/disclosure.md`); there are no real customers, accounts or credentials anywhere. The API binds to 127.0.0.1 by default and is meant for a local demo audience of one officer console. This file records what we checked, on which date, with which commands.

## Dependency audits (17 Oct 2026, commit 01e6d91)

- **npm audit, console**: `npm audit --prefix satyapan/console` ran against the registry and reported **0 vulnerabilities**.
- **npm audit, deck**: `npm audit --prefix deck` ran and reported **0 vulnerabilities**.
- **pip-audit: not run.** `pip-audit` is not installed in the project venv (`.venv/bin/python -m pip_audit` fails with "No module named pip_audit", and there is no `.venv/bin/pip-audit`), and installing it was not permitted in the environment this audit ran in. So the Python side is listed, and has not been audited. The installed surface (`.venv/bin/python -m pip list`, top-level packages from `pyproject.toml` plus extras actually present) is: pydantic 2.14.1, PyYAML 6.0.3, cryptography 50.0.2, fastapi 0.143.3, uvicorn 0.54.0, python-multipart 0.0.32, pillow 13.0.0, ImageHash 4.3.2, pytest 9.1.1, pytesseract 0.3.13, pymupdf 1.28.2 (plus their transitive dependencies). Run `pip install pip-audit && pip-audit` inside the venv before the finale to close this gap.

## Secrets

- A grep over all git-tracked files for likely secret patterns (`AKIA[0-9A-Z]{16}`, `BEGIN ... PRIVATE KEY`, `api_key`, `apikey`, `secret_key`, `secret=`, `token=`, `password=`) returns exactly one hit: `satyapan/evidence.py:56`, which is the code that reads the local demo signing key (`load_pem_private_key(..., password=None)`). No credential, API key or private-key material is tracked in the repository.
- **The Ed25519 demo keypair** lives at `evidence/keys/evidence-signing.key` (and `.pub`). It is generated on first run by `satyapan/evidence.py` if absent, it stands in for the production AWS KMS signer (the signer's label says so in `/api/meta` and in every evidence pack), and it protects nothing. The whole `evidence/` directory is gitignored (`satyapan/.gitignore` line 6), and `git ls-files` confirms the key is untracked. Deleting it just makes the next run generate a fresh one; packs signed with the old key then fail verification, which is the expected behaviour.

## API configuration (`satyapan/api.py`)

- **CORS**: `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]` (the Vite dev server), with `allow_methods=["*"]` and `allow_headers=["*"]` for those two origins only. In the demo configuration the built console is served from the same origin on :8000, so CORS is only exercised during development.
- **Bind address**: `satyapan serve` defaults to `host=127.0.0.1`, `port=8000` (`cli.py`). Exposing it beyond localhost requires passing `--host` explicitly.
- **Uploads** (hardened 17 Oct 2026): `POST /api/cases/{id}/media` rejects bodies over **25 MB** with a 413 and rejects file types outside the allow-list with a 415. The allow-list checks the file extension and, when the browser declares a specific one, the content-type: images (png/jpg/jpeg/webp), audio (ogg/opus/mp3/wav/m4a), video (mp4/webm), PDF and plain text (txt). The filename is reduced to its basename before writing (no path traversal), an over-limit partial write is deleted, files land under `evidence/uploads/<case_id>/`, and unsupported media without a transcript returns a 422. One honest caveat: the framework still reads the request body before the handler's limit applies, so the cap bounds disk use under `evidence/uploads/`, not bytes received; acceptable for a service bound to 127.0.0.1. Tests in `tests/test_api.py`.
- **Static files** (fixed 17 Oct 2026): the SPA catch-all (`GET /{path}`) resolves the requested path and returns 404 when the result falls outside `console/dist`, so a `../` or `..%2F` traversal path cannot read files outside the built console. Tests in `tests/test_api.py` request both forms and assert 404 with no file contents.
- **Demo reset**: `POST /api/demo/reset` clears the in-memory cases (and their uploaded files), campaign-memory entries added during the session, and session timings. Fixture data is restored byte-for-byte as it stood at server start. Like the rest of the API it is unauthenticated, which is fine only on 127.0.0.1.

## Known gaps

- No pip-audit run yet (above).
- Cases are held in memory with no authentication, which is acceptable for a single-laptop demo on 127.0.0.1 and for nothing else. The unauthenticated surface includes `POST /api/demo/reset`.
- (Closed 17 Oct 2026: the upload size limit and type allow-list now exist, and the SPA catch-all contains paths to `console/dist`; both above.)

## Reporting an issue

This is a two-person hackathon prototype, so there is no bug-bounty programme. If you find a security problem, tell the team directly: Aman Bihari and Bhawna (Team "Team", RAKSHAM finale), or open an issue in the repository.
