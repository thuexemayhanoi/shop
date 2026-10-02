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
# Node 20 (pinned by the CI workflows) does NOT support glob patterns in
# --test — test-runner glob support landed in Node 21 as a SEMVER-MAJOR
# change, so a quoted glob is treated as a literal path and fails there.
# Expand the file list in bash so the gate behaves identically on every
# supported Node version, and fail CLOSED if no test files are found.
shopt -s nullglob globstar
NODE_TEST_FILES=(tests/js/**/*.test.mjs)
shopt -u nullglob globstar
if [ "${#NODE_TEST_FILES[@]}" -eq 0 ]; then
  echo "node test suite missing: no tests/js/**/*.test.mjs files" >&2
  exit 1
fi
node --test "${NODE_TEST_FILES[@]}"

echo "== [gate L2] content matrix invariants"
python3 scripts/validate_content_matrix.py

echo "== [gate L2] factory consistency (matrix / hubs / sitemap / leaks)"
node scripts/js/factory.mjs --consistency

echo "== [gate L2] canonical generator freshness (sitemap + hubs + pages)"
python3 scripts/generate_sitemap.py --check
python3 scripts/generate_category_pages.py --check

echo "== [gate L2] working tree hygiene (whitespace/conflict markers)"
if [ -d .git ]; then
  ws_findings="$(mktemp)"
  if ! git diff --check > "$ws_findings"; then
    echo "== [gate L2] git diff --check FAILED — whitespace/conflict-marker findings:"
    cat "$ws_findings"
    # Self-instrumenting evidence (behavior unchanged: still fail-closed
    # exit 2 on findings): surface the findings AND the working-tree diff
    # of the first implicated file as CI annotations, so a red run
    # pinpoints the exact offending file:line even without raw-log access.
    ws_msg=""
    ws_count=0
    while IFS= read -r fline; do
      [ -n "$fline" ] || continue
      ws_msg="${ws_msg}${fline}%0A"
      ws_count=$((ws_count + 1))
      if [ "$ws_count" -ge 15 ]; then break; fi
    done < "$ws_findings"
    echo "::error::[gate L2 whitespace] git diff --check failed. Findings: $ws_msg"
    first_file="$(grep -oE '^[^:]+:' "$ws_findings" | head -1 | cut -d: -f1 || true)"
    if [ -n "$first_file" ]; then
      diff_excerpt="$(git diff -- "$first_file" 2>/dev/null | head -c 5000 || true)"
      if [ -n "$diff_excerpt" ]; then
        enc="$(printf '%s' "$diff_excerpt" | python3 -c 'import sys
data = sys.stdin.read()
data = data.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
sys.stdout.write(data[:5500])')"
        echo "::error::[gate L2 whitespace] working-tree diff of $first_file (first 5500 chars): $enc"
      fi
    fi
    rm -f "$ws_findings"
    exit 2
  fi
  rm -f "$ws_findings"
else
  echo "(no .git directory present — git diff --check skipped)"
fi

echo "== [gate L3] production-invariant verifier"
python3 scripts/verify_factory_state.py --op consistency

echo "== [gate] FINAL GATE GREEN (tests + semantic invariants on this exact tree)"