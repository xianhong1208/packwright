# Contributing

## Set up

```bash
git clone https://github.com/xianhong1208/packwright.git
cd packwright
uv sync --locked --group dev            # Python 3.13+, backend + test tools
cd frontend && npm ci && cd ..          # Node.js 22.12+ (frontend/.nvmrc)
uv run python main.py                   # migrates the database, serves on :5018
```

Use another port when :5018 is taken: `PORT=5019 uv run python main.py`. For the console's dev
server with hot reload, `cd frontend && npm run dev`; it forwards `/api`, `/auth`, `/health` and `/ws`
to `http://localhost:5018`, or to `PACKWRIGHT_BACKEND` when set
(`PACKWRIGHT_BACKEND=http://localhost:5019 npm run dev`).

## Checks

Everything CI runs, locally:

```bash
uv run ruff check app tests main.py alembic scripts
uv run pytest -q                        # unit + integration (real app, temp SQLite)
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

- `tests/conftest.py` points every run at a throwaway SQLite database and test secrets; tests never
  touch `./data` or your `.env`.
- `tests/integration/` runs the real application through `TestClient`. Use it for anything that
  depends on which dependency or helper a route really calls (token types, client IPs, file paths):
  mocks cannot prove those.
- A model change needs an Alembic migration (`uv run alembic revision -m "..."`);
  `tests/integration/test_schema_drift.py` fails until the two agree.
- Backend tests use pytest-mock only, carry a TC id in the name and docstring, and are marked
  `@pytest.mark.unit` or `@pytest.mark.integration`.

## Branches, commits, pull requests

- Branch off `dev`, open the pull request into `dev`. `main` moves only at release time.
- Commit messages follow Conventional Commits with a scope (`fix(auth): …`, `feat(version): …`) and
  explain *why* in the body.
- Every user-visible change updates `README.md` and `README.zh-TW.md` together, and adds a line to
  `CHANGELOG.md` under `[Unreleased]`.
- Delete the branch after the merge.

## Releasing

1. On `dev`, bump `[project].version` in `pyproject.toml`: it is the single source of truth. Then run
   `cd frontend && npm run sync-version` and `uv lock`. (`npm run build` also syncs.)
2. Turn `[Unreleased]` in `CHANGELOG.md` into `## [x.y.z] — YYYY-MM-DD` and update the links at the
   bottom.
3. Open a pull request from `dev` to `main` and merge it.
4. Tag the merge commit: `git tag -a vx.y.z -m "Packwright x.y.z"` and `git push origin vx.y.z`.
5. Publish a GitHub Release for the tag; its notes mirror the CHANGELOG section.
6. Merge `main` back into `dev`.
