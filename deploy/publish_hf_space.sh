#!/usr/bin/env bash
# Publish the service to a Hugging Face Space (Docker SDK).
#
# Why HF Spaces: M0 scope §9 ranks survivability above every other property,
# because a dead demo link is worse than no link. Spaces needs no card, cannot
# bill, and does not delete an idle Space — it sleeps and wakes. Railway,
# Render and Fly were rejected for exactly that reason.
#
# Why the Space repository carries the build context rather than pulling a
# published image: fewer moving parts. No registry, no cross-service auth,
# nothing else to keep alive. The context is ~6 MB, almost all of it the frozen
# fixture.
#
# PUBLISHING IS NOT AUTOMATIC. This script is a dry run unless given --confirm,
# because a Space is public the moment it exists and that is the repository
# owner's decision, not a build step's.
#
#   HF_TOKEN=hf_xxx SPACE_ID=youruser/dep-triage-agent ./deploy/publish_hf_space.sh
#   HF_TOKEN=hf_xxx SPACE_ID=youruser/dep-triage-agent ./deploy/publish_hf_space.sh --confirm
#
# The token needs write access to Spaces. It is read from the environment and
# never written to disk, never echoed, and never committed.

set -euo pipefail

CONFIRM=0
[[ "${1:-}" == "--confirm" ]] && CONFIRM=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

: "${SPACE_ID:?set SPACE_ID, e.g. youruser/dep-triage-agent}"
if [[ $CONFIRM -eq 1 ]]; then
  : "${HF_TOKEN:?set HF_TOKEN (write scope) to publish}"
fi

# The landing page ships pre-rendered, so it must exist before packaging.
if [[ ! -f results/report.html ]]; then
  echo "results/report.html is missing. Build it first:" >&2
  echo "  uv run dep-triage report --output results/report.html" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Explicit allowlist. Anything not named here does not reach a public Space —
# notably .env, .git, tests, and saved evaluation runs.
mkdir -p "$STAGE/src" "$STAGE/data" "$STAGE/results"
cp Dockerfile .dockerignore pyproject.toml uv.lock LICENSE "$STAGE/"
cp deploy/hf-space/README.md "$STAGE/README.md"
cp -r src/dep_triage "$STAGE/src/"
cp -r data/fixture "$STAGE/data/"
cp data/tasks.json "$STAGE/data/"
cp results/report.html "$STAGE/results/report.html"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Staged for $SPACE_ID:"
du -sh "$STAGE" | sed 's/^/  total /'
(cd "$STAGE" && find . -type f | sort | sed 's/^/  /')

# Fail loudly rather than publish a secret.
if grep -rIlqE 'hf_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}|gsk_[A-Za-z0-9]{20}' "$STAGE" 2>/dev/null; then
  echo "ABORT: a token-shaped string is present in the staged tree." >&2
  exit 1
fi
if [[ -e "$STAGE/.env" || -e "$STAGE/.git" ]]; then
  echo "ABORT: .env or .git reached the staged tree." >&2
  exit 1
fi
echo "  secret scan: clean"

if [[ $CONFIRM -eq 0 ]]; then
  cat <<'EOF'

DRY RUN — nothing was published.

Before publishing, be aware this makes the report, the agent and the frozen
fixture publicly readable, and exposes a live model endpoint behind the demo
rate limits.

Re-run with --confirm to publish. Then, in the Space's Settings:
  - add any backend credential as a Space secret (never in the repository)
  - set DEP_TRIAGE_LLM_BACKEND / DEP_TRIAGE_LLM_BASE_URL / DEP_TRIAGE_LLM_NAME
    for whichever hosted open-weight backend is in use
Leaving them unset is safe: /ask then returns 503 with a notice and the report
still serves.
EOF
  exit 0
fi

cd "$STAGE"
git init -q
git checkout -q -b main
git add -A
git -c user.email="noreply@users.noreply.github.com" \
    -c user.name="dep-triage-agent deploy" \
    commit -q -m "Publish dependency triage agent service and evaluation report"

# Token goes in the remote URL for one push and the directory is deleted on
# exit, so it never persists in a tracked config.
git push -q --force "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE_ID}" main
echo "Published: https://huggingface.co/spaces/${SPACE_ID}"
echo "First build takes a few minutes. Check the Space's Logs tab."
