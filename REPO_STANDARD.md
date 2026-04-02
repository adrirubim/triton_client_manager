# Repository Standard (adrirubim)

This document defines the **non-negotiable repository standard** shared across:

- `triton_client_manager`
- `c41.ch-be`
- `laser-packaging-laravel`

The goal is to keep these repositories **homogeneous** in structure, community health files, and GitHub UX (templates + workflows), while allowing stack-specific implementation details.

## Required root files

Every repository **must** contain these files at the repository root (exact names):

- `README.md`
- `LICENSE`
- `CHANGELOG.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SUPPORT.md`
- `REPO_STANDARD.md`

## README contract

`README.md` must follow this section order (keep headings and anchors stable):

1. Title + tagline
2. Badges (same types + order)
3. Table of Contents
4. Operational Quickstart
5. Overview
6. Features
7. Tech Stack
8. Requirements
9. Installation
10. Security
11. Documentation
12. CI/CD
13. Testing
14. Architecture
15. Project Status
16. Default Users (development)
17. Useful Commands
18. Before Pushing to GitHub
19. Contributing
20. Author
21. License

If a section is not applicable, keep it and mark it as **N/A**.

### Badges (required types + order)

Badges must appear in this order (where applicable):

1. Primary runtime badge (Python / PHP)
2. Framework badge (FastAPI / Laravel)
3. UI/runtime badges (React / Docker) if applicable
4. **CI Tests** (GitHub Actions)
5. **CI Lint** (GitHub Actions)
6. License badge

## GitHub templates contract

These files must exist:

- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `.github/ISSUE_TEMPLATE/config.yml`

They should be identical across repos except for repo-specific links and commands.

## GitHub workflows contract

Workflows must exist (same filenames):

- `.github/workflows/lint.yml`
- `.github/workflows/tests.yml`
- `.github/workflows/security.yml`

Workflows may differ internally by stack, but must preserve:

- Job names (`lint`, `tests`, `security`) and top-level workflow name (Lint / Tests / Security)
- Triggers (`push`, `pull_request`)
- A deterministic local equivalent documented in README and/or `CONTRIBUTING.md`

## Dependabot

Use `.github/dependabot.yml` with:

- Weekly schedule by default
- Grouped updates where possible (pip/composer/npm)
- PR labels: `dependencies`

## Local quality gate (required)

Every repository must provide a CI-parity local entrypoint:

- `scripts/dev-verify.sh`

The README “Before Pushing to GitHub” section must reference this script as the canonical local verification step.

