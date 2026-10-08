# M1 — Repo hygiene

**Status:** green, 2026-10-08 · day 1 of 14
**Commits:** `d67b03f`

---

## Definition of done — all seven met

| # | Criterion | Result |
|---|---|---|
| 1 | `uv sync` works from a clean clone; Python 3.12 pinned | ✅ `requires-python = ">=3.12,<3.13"` |
| 2 | Package layout exists | ✅ `src/dep_triage/{agent,tools,eval,service}/`, `tests/`, `scripts/`, `docs/`, `deploy/`, `data/` |
| 3 | `ruff check` + `ruff format --check` clean | ✅ |
| 4 | `mypy src/` clean | ✅ **strict**, 11 files |
| 5 | `pytest` passes — real tests | ✅ 27 tests, 0.20 s |
| 6 | CI: lint + types + tests, under 60 s, no model, no network | ✅ **10 s cold** |
| 7 | `.env.example` committed, `.env` gitignored, verified | ✅ asserted by test, not by eyeball |

---

## Built

**Config layer** — `src/dep_triage/config.py`. A `pydantic-settings` model
covering the model backend, determinism settings, agent step limit, fixture
path, logging, and the public-demo rate caps. Every field is overridable by a
`DEP_TRIAGE_*` environment variable.

Chosen over empty package stubs because "tests pass" has to mean something at
M1, and config is the one thing every later milestone depends on.

**CLI** — `dep-triage version` and `dep-triage config`. The latter prints
resolved configuration as JSON with the secret redacted, which is how you find
out what a container actually resolved at startup instead of guessing.

`ask`, `eval` and `report` are absent rather than stubbed. A stub raising
`NotImplementedError` would make `--help` advertise an interface that does
nothing.

**27 tests**, three of which are load-bearing:

| Test | What it prevents |
|---|---|
| `test_every_setting_is_documented` | `.env.example` silently drifting from the real settings |
| `test_no_stale_keys_documented` | `.env.example` advertising settings that no longer exist |
| `test_redacted_dump_covers_every_field` | a newly added field escaping redaction and reaching a log line |

**CI** — `.github/workflows/ci.yml`. `uv sync --frozen` so CI tests the
committed dependency set rather than silently re-resolving. Concurrency group
cancels superseded runs.

---

## Decided

**mypy runs strict, which exceeds what the M1 definition of done asked for.**
Adopting strict typing across 200 lines is cheap; adopting it across a grown
codebase is not. Third-party packages with incomplete stubs get per-module
`ignore_missing_imports` overrides as they arrive.

**Dependencies arrive at the milestone that needs them.** M1 installs 25
packages — `pydantic`, `pydantic-settings`, `typer`, plus dev tooling.
LangGraph lands at M2; FastAPI, structlog and `prometheus-client` at M6.
Pre-installing the heavy half of the tree works against the clone-to-green
goal that is the entire point of this milestone.

**Fields are named `llm_*`, not `model_*`.** Pydantic reserves the `model_`
namespace on `BaseModel`, so `model_name` would collide with it.

**License: MIT.** Assumed, not confirmed — see Still weak.

---

## Measured

| Metric | Cold cache | Warm cache |
|---|---|---|
| `uv sync --frozen` | 6 s | 0 s |
| Full gate (ruff + format + mypy + pytest) | 4 s | 3 s |
| **Clone to green** | **10 s** | **3 s** |

Measured by cloning the repository into `/tmp` and running against a fresh
`UV_CACHE_DIR`, not by timing the working tree. 25 packages, 101 MB of cache.

Secret scan before commit: no key-shaped strings anywhere in the tree, `.env`
untracked and absent, `.env.example` confirmed trackable despite the `.env`
ignore rule.

---

## Found a real bug

`test_unknown_env_var_is_rejected` was written asserting that a mistyped
`DEP_TRIAGE_MAX_STEP` fails loudly. It did not — the test failed, and **the
test was right**.

`extra="forbid"` does not cover environment variables. pydantic-settings looks
up only the variables it already has fields for, so an unrecognised one is
never seen at all. Deployed to HF Spaces, a mistyped secret name would mean a
setting you believe you configured having no effect, with nothing in the logs
to say so.

Fixed with a `model_validator(mode="before")` that scans `os.environ` for
`DEP_TRIAGE_*` keys matching no field and raises. The test now passes against
behaviour that actually exists.

---

## Still weak

1. **CI has never run on GitHub.** There is no remote yet, so the workflow is
   untested in its real environment. `astral-sh/setup-uv@v5` is pinned by major
   version and unverified. First push is the real test.
2. **No coverage measurement.** "27 tests pass" says nothing about what
   fraction of `config.py` is exercised. Deliberately skipped — coverage
   tooling at M1 is polish, and this project has a stopping line.
3. **`Settings()` is not a pure function of its arguments.** The unknown-env-var
   validator reads `os.environ` on every construction. Correct for a service
   that resolves config once at startup; mildly surprising if constructed in a
   loop.
4. **License assumed.** MIT was chosen without confirmation. One commit to
   change.
5. **Python pinned to 3.12 exactly** (`<3.13`). Deliberate, for reproducibility
   over a benchmark's lifetime, but it will need a conscious bump rather than
   drifting forward.
6. **`uv` is now a machine prerequisite** and installs to `~/.local/bin`. The
   README's target interface assumes it is on `PATH`.

## Day 1 is not finished

Two installs still outstanding, both needing `sudo`, both blocking later
milestones rather than M1:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER   # log out and back in
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
```

Docker blocks M5. Ollama blocks M2. Neither blocks M1, which is why M1 went
first.

---

## Next: M2 — agent working locally

Definition of done to be stated before starting. Carries three gates from the
M0 scope, all due end of day 5 (Sun 12 Oct):

- **Reproducibility** (§6) — `temperature=0` + fixed seed, dev subset twice,
  metrics byte-identical. Failure means repeats and variance reporting.
- **Model switch** (§7.1) — under 30% dev `task_accuracy` → Qwen2.5-7B-Instruct.
- **`create_react_agent` walkthrough** (§10) — document the loop it actually
  generates, in the M2 report.
