# PipelineGuard project context

Read this fully before doing anything. It captures the design decisions already made and how I want to work.

## Who I am and why this project exists

I'm Jay, a Cybersecurity + Computer Science graduate (UWA, graduated August 2026), based in Perth. I hold AZ-900 and am working toward AZ-104. My goal is a DevOps / cloud engineering career. This project is a portfolio piece built to demonstrate operational cloud skills (IaC, CI/CD, security scanning, drift detection) to hiring managers for junior support/sysadmin/cloud roles, which are the realistic entry point in the current market. It also needs to be something I can explain end to end in interviews, so understanding matters more than speed.

## What PipelineGuard is

A small FastAPI incident-tracker API that gets built, security-scanned, and deployed to Azure automatically on every push, plus a scheduled "watchdog" that detects infrastructure drift with Terraform and auto-remediates one scoped class of dangerous change (an opened NSG rule on the database subnet), logging the event as an incident inside the app itself.

The app is deliberately simple. The pipeline, Terraform, secrets handling, and drift tooling are the point.

## Locked-in design decisions (do not change without asking me)

* App: Python, FastAPI, SQLAlchemy (ORM), Pydantic (validation). SQLite locally, Azure Database for PostgreSQL Flexible Server in the cloud.
* Package management: uv (already initialised with `uv init --package`, src layout). No requirements.txt; dependencies live in `pyproject.toml` + `uv.lock`.
* Container: Docker, python slim base, run as a non-root user, images tagged with the git commit SHA (never `latest`).
* Registry: Azure Container Registry (ACR).
* Compute: Azure App Service for Containers. NOT AKS. AKS is an optional last phase only if everything else works.
* IaC: Terraform, remote state in an Azure Storage Account with state locking. Environments (dev/staging/prod) via Terraform workspaces + per-env `.tfvars`.
* CI/CD: GitHub Actions. Stages in order: lint (ruff) + test (pytest) -> build -> Trivy scan (fail on HIGH/CRITICAL) -> push to ACR -> deploy dev + smoke test on `/health` -> deploy staging -> manual approval gate -> deploy prod.
* Secrets: zero stored credentials. GitHub -> Azure via OIDC federated credentials. App -> database connection string via Azure Key Vault reference using a managed identity.
* Drift detection: scheduled workflow (cron every 6h + manual trigger) running `terraform plan -detailed-exitcode`. Exit code 2 = drift: open a GitHub issue with the diff and POST an incident to the app's own API.
* Auto-remediation: allow-list with exactly one entry, the database subnet NSG rules. Targeted revert with `terraform apply -target=...`. Everything else is alert-only. Never blanket auto-apply.
* Monitoring: Azure Monitor, optional Application Insights. Keep light.

## Repository layout (target)

```
pipeline-guard/
  .gitignore
  README.md
  CLAUDE.md
  app/
    .python-version
    pyproject.toml
    uv.lock
    README.md            # placeholder required by uv package metadata
    Dockerfile
    .dockerignore
    src/
      app/
        __init__.py
        main.py          # FastAPI app + routes
        models.py        # SQLAlchemy Incident model
        schemas.py       # Pydantic IncidentCreate / IncidentResponse
        database.py      # engine, SessionLocal, Base, get_db
  infra/
    main.tf
    variables.tf
    outputs.tf
    backend.tf
    envs/
      dev.tfvars.example
      staging.tfvars.example
      prod.tfvars.example
  .github/
    workflows/
      ci-cd.yml
      drift.yml
  docs/
    architecture.md
```

## API contract (Phase 1)

```
GET    /health                    -> {"status": "ok"}
POST   /incidents                 -> create (title, description, severity)
GET    /incidents                 -> list all
PATCH  /incidents/{id}/resolve    -> set status=resolved, resolved_at=now
```

Incident fields: id, title, description, severity (default "medium"), status (default "open"), created_at, resolved_at.

Run locally with: `cd app && uv run uvicorn app.main:app --reload` (module path is `app.main:app` because of the src layout).

## Build phases

1. App + Docker running locally against SQLite. Done when `docker run` serves `/docs` and all four endpoints work.
2. Terraform dev environment with remote state bootstrap. Done when the app is live on Azure and `terraform apply` run twice changes nothing.
3. CI/CD through the dev deploy with the Trivy gate and smoke test.
4. Staging/prod promotion, OIDC federation, Key Vault references, prod approval gate.
5. Drift watchdog + scoped NSG remediation + demo screenshots.
6. (Optional, last) swap App Service for AKS.

Finish each phase properly before starting the next. A working phase 3 beats a half-built phase 5.

## Current status

Phase 1, just started. The uv skeleton exists and is committed (`pyproject.toml`, `uv.lock`, `.python-version`, `src/app/__init__.py`, `app/README.md`). `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `pydantic` have been added with `uv add`. None of the four Python source files exist yet. No Dockerfile yet. `.gitignore` is in place at the repo root and `.venv/` is confirmed ignored.

## How I want you to work with me

* I want to write the code myself where I can. Before generating a full file, ask whether I want to attempt it first or want you to write it. Default to guiding, reviewing, and explaining.
* When you do write something, explain the technical concept briefly (what an ORM does, why the src layout changes the module path, why non-root in Docker), because I need to be able to explain this in interviews.
* Prefer small steps with a check after each one over large multi-file dumps.
* Never commit secrets, `.tfstate`, real `.tfvars`, `.venv/`, or `*.db` files. Use `.example` files for anything environment-specific.
* Do not introduce tools outside the locked-in stack without asking (no Helm, no Kubernetes, no extra frameworks) unless I bring them up.
* Windows / PowerShell environment. Watch for CRLF and UTF-16 encoding gotchas (PowerShell `echo >` writes UTF-16; use `Set-Content -Encoding utf8`).
* Keep explanations concise. Do not use the em dash character anywhere.
