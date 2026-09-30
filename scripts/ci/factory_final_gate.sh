#!/usr/bin/env bash
# Canonical FOUR-LAYER final gate for the content factory.
#
# ONE gate, run in ONE place, by EVERY consumer:
#   - .github/workflows/article-quality.yml (PR + push-to-main quality gate)
#   - .github/workflows/factory-operator.yml (before EVERY push of operator
#     outputs, again after every rebase, and once more on the EXACT final
#     main SHA after the push)
#
# GREEN here means: tests pass AND the semantic factory invariants hold on
# the EXACT tree that will be pushed. Workflow exit 0 alone is never
# "production success"; this gate is the deterministic definition of it.
#
# Layers covered:
#   L1 unit          python + node suites
#   L2 integration   matrix invariants + factory consistency + generators
#   L3 production    verify_factory_state.py (deploy gate, sitemap/hub
#                    truth, report truth, transaction cleanliness)
#   L4 long-run      the suites above include the hermetic soak and
#                    failure-injection tests (tests/test_factory_reliability.py)
#
# Deterministic only: no AI, no network, no secrets, no article writing.
# Usage: bash scripts/ci/factory_final_gate.sh   (from the repository root)

set -euo pipefail

if [ -n "${FACTORY_GATE_REPO_ROOT:-}" ]; then
  cd "$FACTORY_GATE_REPO_ROOT"
else
  cd "$(dirname "$0")/../.."
fi

REPO_ROOT="$(pwd)"
export FACTORY_GATE_REPO_ROOT="$REPO_ROOT"

echo "== [gate] repository root: $REPO_ROOT"

echo "== [gate L1] full python test suite"
python3 -m unittest discover tests

echo "== [gate L1] node test suite"
node --test "tests/js/**/*.test.mjs"

echo "== [gate L2] content matrix invariants"
python3 scripts/validate_content_matrix.py

echo "== [gate L2] factory consistency (matrix / hubs / sitemap / leaks)"
node scripts/js/factory.mjs --consistency

echo "== [gate L2] canonical generator freshness (sitemap + hubs + pages)"
python3 scripts/generate_sitemap.py --check
python3 scripts/generate_category_pages.py --check

echo "== [gate L2] working tree hygiene (whitespace/conflict markers)"
if [ -d .git ]; then
  git diff --check
else
  echo "(no .git directory present — git diff --check skipped)"
fi

echo "== [gate L3] production-invariant verifier"
python3 scripts/verify_factory_state.py --op consistency

echo "== [gate] FINAL GATE GREEN (tests + semantic invariants on this exact tree)"