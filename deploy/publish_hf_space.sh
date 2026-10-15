#!/usr/bin/env bash
# Publish the evaluation report to a Hugging Face **Static** Space.
#
# Why static, when M0 chose a Docker Space: Hugging Face now requires a PRO
# subscription to run Docker or Gradio Spaces on free hardware. Static Spaces
# remain free for everyone. The project has a hard zero-cost constraint, and
# M0's deciding criterion for the host was that the link must still work in six
# months — a Space that cannot be billed for is a Space that cannot lapse.
#
# What is lost: the live /ask endpoint on the public URL. What is not lost: the
# report, which M0 §9.3 already made the landing page because it is the
# project's evidence and the live form was always best-effort. The service
# itself is published as a container image instead, so anyone can run the whole
# thing with one command.
#
# PUBLISHING IS NOT AUTOMATIC. Dry run unless given --confirm.
#
#   SPACE_ID=youruser/dep-triage-agent ./deploy/publish_hf_space.sh
#   SPACE_ID=youruser/dep-triage-agent ./deploy/publish_hf_space.sh --confirm
#
# HF_TOKEN is read from the environment or from .env.deploy (gitignored). It is
# never echoed, never written to a tracked file, and the staged tree is scanned
# for token-shaped strings before anything is pushed.

set -euo pipefail

CONFIRM=0
[[ "${1:-}" == "--confirm" ]] && CONFIRM=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Convenience for local use; CI passes HF_TOKEN in the environment instead.
if [[ -z "${HF_TOKEN:-}" && -f .env.deploy ]]; then
  HF_TOKEN="$(grep -E '^HF_TOKEN=' .env.deploy | head -1 | cut -d= -f2- | tr -d "\"'" || true)"
fi

: "${SPACE_ID:?set SPACE_ID, e.g. youruser/dep-triage-agent}"
if [[ $CONFIRM -eq 1 ]]; then
  : "${HF_TOKEN:?set HF_TOKEN (write scope), or put it in .env.deploy}"
fi

if [[ ! -f results/report.html ]]; then
  echo "results/report.html is missing. Build it first:" >&2
  echo "  uv run dep-triage report --output results/report.html" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# A static Space serves index.html from the repository root. Only two files are
# needed, which is the entire security argument for this deployment: there is
# no code and no credential on the public host.
cp results/report.html "$STAGE/index.html"
cp deploy/hf-space/README.md "$STAGE/README.md"

echo "Staged for $SPACE_ID:"
du -sh "$STAGE" | sed 's/^/  total /'
(cd "$STAGE" && find . -type f | sort | sed 's/^/  /')

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

This publishes the evaluation report as a public page. No code, no model
backend and no credential are deployed, so there is nothing on the host that
can leak or be abused.

Re-run with --confirm to publish.
EOF
  exit 0
fi

cd "$STAGE"
git init -q
git checkout -q -b main
git add -A
git -c user.email="noreply@users.noreply.github.com" \
    -c user.name="dep-triage-agent deploy" \
    commit -q -m "Publish dependency triage agent evaluation report"

git push -q --force "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE_ID}" main
echo "Published: https://huggingface.co/spaces/${SPACE_ID}"
