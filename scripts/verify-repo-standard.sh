#!/usr/bin/env bash
set -euo pipefail

required_root_files=(
  "README.md"
  "LICENSE"
  "CHANGELOG.md"
  "SECURITY.md"
  "CONTRIBUTING.md"
  "CODE_OF_CONDUCT.md"
  "SUPPORT.md"
  "REPO_STANDARD.md"
)

required_github_files=(
  ".github/PULL_REQUEST_TEMPLATE.md"
  ".github/ISSUE_TEMPLATE/bug_report.yml"
  ".github/ISSUE_TEMPLATE/feature_request.yml"
  ".github/ISSUE_TEMPLATE/config.yml"
  ".github/workflows/lint.yml"
  ".github/workflows/tests.yml"
  ".github/workflows/security.yml"
  ".github/dependabot.yml"
)

echo "==> verify-repo-standard: checking required files"

missing=0
for f in "${required_root_files[@]}"; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; missing=1; }
done
for f in "${required_github_files[@]}"; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; missing=1; }
done

echo "==> verify-repo-standard: checking README entrypoint"
if ! grep -Fq "./scripts/dev-verify.sh" README.md; then
  echo "MISSING: README.md must reference ./scripts/dev-verify.sh"
  missing=1
fi

if [[ "$missing" -ne 0 ]]; then
  echo "==> verify-repo-standard: FAILED"
  exit 1
fi

echo "==> verify-repo-standard: OK"

