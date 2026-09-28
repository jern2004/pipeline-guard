# PipelineGuard: Project Documentation

A secure CI/CD pipeline on Azure with infrastructure drift detection and scoped auto-remediation. This document explains what the system does, how every component works, and the order to build it in. Plain-language explanations come first, technical terms are named as they appear, and everything is defined in the glossary at the end.

## Project status

Work in progress, built in phases (see [15. Build order](#15-build-order)). The rest of this document describes the target design; this table is the source of truth for what exists today.

| Component | Status |
|---|---|
| FastAPI incident API: 4 endpoints, SQLAlchemy + Pydantic, SQLite locally | Built |
| pytest suite and ruff lint | Built |
| Dockerfile: Python slim, multi-stage uv build, non-root user | Built |
| GitHub Actions CI: lint, test, image build tagged with the commit SHA, Trivy gate on fixable HIGH/CRITICAL (full report logged), container smoke test | Built |
| Terraform for Azure (ACR, App Service, PostgreSQL, VNet + NSG, Key Vault) with remote state | Designed, not built |
| Deployment: push to ACR, dev -> staging -> manual approval -> prod | Designed, not built |
| OIDC federation (GitHub -> Azure) and Key Vault references | Designed, not built |
| Drift watchdog and scoped NSG auto-remediation | Designed, not built |

Run it locally (needs [uv](https://docs.astral.sh/uv/)):

```
cd app
uv run uvicorn app.main:app --reload --port 8080
uv run pytest
```

The interactive API docs are then at http://127.0.0.1:8080/docs.

---

## 1. What it is

PipelineGuard is a small incident-tracker API that gets built, security-scanned, and deployed to Azure automatically on every code push. Around it sits the part that makes the project interesting: a scheduled watchdog that compares the live Azure infrastructure against its Terraform definition, raises an alert when someone changes infrastructure manually (this is called **configuration drift**), and automatically reverts one specific class of dangerous change (an opened network port), logging the event as an incident inside the app itself.

The app is deliberately boring/plain. The pipeline, the infrastructure code, and the drift tooling are the point.

---

## 2. Architecture overview

Three planes, kept mentally separate:

- The **application plane**: the FastAPI app and its database. What gets deployed.
- The **delivery plane**: GitHub Actions pipelines. How code becomes a running service.
- The **control plane**: Terraform plus the drift watchdog. What keeps reality matching the code.

```
        developer pushes code
                 |
                 v
   +----------------------------+
   |     GitHub repository      |
   +-------------+--------------+
                 |
                 v
   +----------------------------+       OIDC (no stored secrets)
   |  GitHub Actions: CI/CD     | ----------------------------+
   |  lint/test -> build ->     |                             |
   |  Trivy scan -> push ACR -> |                             v
   |  deploy dev -> staging ->  |            +----------------------------------+
   |  [manual gate] -> prod     |            |  Azure (provisioned by Terraform)|
   +----------------------------+            |  ACR | App Service | Postgres    |
                                             |  VNet + NSG | Key Vault          |
   +----------------------------+            +----------------+-----------------+
   |  GitHub Actions: watchdog  |                             ^
   |  (cron schedule)           |                             |
   |  terraform plan against    | ----------------------------+
   |  live infra                |
   |  drift found?              |
   |    -> alert (GitHub issue) |
   |    -> if NSG rule opened:  |
   |       targeted revert      |
   |    -> POST incident to the |
   |       app's own API        |
   +----------------------------+
```

---

## 3. Tech stack

| Layer | Tool | Why this one |
|---|---|---|
| Application | FastAPI + PostgreSQL | Small and fast to build, with auto-generated OpenAPI docs at `/docs` |
| Container | Docker | Industry-standard packaging and runtime |
| Registry | Azure Container Registry (ACR) | Where built images live |
| Compute | Azure App Service for Containers | Cheap, simple, free-tier friendly. AKS is a later upgrade, not the starting point |
| Infrastructure as Code | Terraform | Declarative, widely used, and `terraform plan` doubles as a drift detector |
| CI/CD | GitHub Actions | Built into GitHub, free for public repos |
| Image scanning | Trivy | Free, one-line pipeline integration, real CVE detection |
| Secrets | Azure Key Vault + managed identity | No credentials in code or in GitHub, ever |
| Pipeline auth | OIDC federated credentials | Short-lived tokens instead of stored passwords |
| Monitoring | Azure Monitor (+ optional Application Insights) | Enough visibility without extra cost |

---

## 4. Repository layout

```
pipeline-guard/
  app/                        # FastAPI service (uv project, src layout)
    pyproject.toml            # dependencies; exact versions pinned in uv.lock
    uv.lock
    Dockerfile                # multi-stage build, non-root runtime user
    src/app/
      main.py                 # FastAPI app and routes
      models.py               # SQLAlchemy Incident model
      schemas.py              # Pydantic request/response schemas
      database.py             # engine, session factory, get_db dependency
    tests/                    # pytest suite
  infra/                      # Terraform (placeholder files: designed, not built)
    main.tf                   # all Azure resources
    variables.tf
    outputs.tf
    backend.tf                # remote state config (Azure Storage)
    envs/
      dev.tfvars.example      # per-environment values; real .tfvars files are gitignored
      staging.tfvars.example
      prod.tfvars.example
  .github/
    workflows/
      ci-cd.yml               # lint, test, build, Trivy gate, smoke test
  docs/
    architecture.md           # placeholder
```

---

## 5. The application layer

A minimal incident tracker. Four endpoints:

```
POST   /incidents                # create an incident
GET    /incidents                # list incidents
PATCH  /incidents/{id}/resolve   # mark resolved
GET    /health                   # used by the pipeline's smoke test
```

Backed by Azure Database for PostgreSQL (Flexible Server) in the cloud, SQLite locally for development. FastAPI gives you auto-generated Swagger docs at `/docs` for free, which makes the deployed app easy to demo.

The `/health` endpoint matters more than it looks: after every deployment, the pipeline calls it and fails the run if it does not return 200. This is called a **smoke test**, the minimum check that a deployment actually works before promoting it further.

The app is also the destination for the watchdog's remediation logs (section 11), which makes the whole system self-referential in a satisfying way: the security tooling files its own incidents into the app it protects.

---

## 6. Containerization

A multi-stage Dockerfile: a build stage installs the locked dependencies with uv, and only the resulting virtual environment is copied into a clean Python slim runtime image. The process runs as a **non-root user**, so a compromised app process does not have root privileges inside the container.

Every image is tagged with the git commit SHA rather than `latest`. This gives you **immutable tags**: any running container can be traced back to the exact commit that produced it, and rollbacks are just "deploy the previous SHA."

Images are pushed to **ACR** (Azure Container Registry), and App Service pulls from ACR using a **managed identity** rather than a stored registry password.

---

## 7. Infrastructure as Code (Terraform)

Terraform declares every Azure resource in code: resource group, ACR, App Service plan and web app, a VNet with a **delegated subnet** for the Postgres server, a **Network Security Group (NSG)** on that subnet, and a Key Vault.

Key concepts at work here:

**Remote state.** Terraform tracks what it has built in a state file. That file lives in an Azure Storage Account (not on your laptop) so the pipeline and your machine see the same truth. Azure Storage also provides **state locking**, which stops two runs from modifying infrastructure at the same time. The storage account itself is the one thing you create manually once, before Terraform takes over everything else (the bootstrap step).

**Environments.** Dev, staging, and prod are the same Terraform code with different variable files (`dev.tfvars`, `staging.tfvars`, `prod.tfvars`), selected via **Terraform workspaces**. The environments differ only in size and instance count, never in shape. This is what "environment parity" means in practice.

**Idempotency.** Running `terraform apply` twice in a row changes nothing the second time. If it does, something is wrong. This property is what makes drift detection (section 10) possible at all.

---

## 8. The CI/CD pipeline

One workflow file (`ci-cd.yml`), triggered on push to main. Stages run in order and each one is a **quality gate**: if it fails, nothing downstream runs.

1. **Lint and test.** `ruff` for linting, `pytest` for unit tests. Fail fast on broken code.
2. **Build.** `docker build`, tagged with the commit SHA.
3. **Scan.** Trivy scans the built image for known vulnerabilities (**CVEs**). It runs twice: a report step lists every high and critical finding, then the gate runs with `--exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed`, meaning any high or critical finding that has a fix available fails the build. Findings with no fix released yet cannot be resolved by upgrading, so they are reported but do not block; the next build picks up the fix once it exists, and the gate then enforces it. This is the DevSecOps gate. Catching vulnerabilities at build time rather than in production is what "**shift-left security**" means.
4. **Push.** The scanned image goes to ACR.
5. **Deploy to dev.** Terraform applies the dev workspace, App Service picks up the new image, then the smoke test hits `/health`.
6. **Deploy to staging.** Automatic, only if dev passed.
7. **Deploy to prod.** Blocked behind a **manual approval gate** using GitHub Environments protection rules: a human clicks approve before prod changes. This dev -> staging -> prod sequence is called **environment promotion**.

---

## 9. Secrets and identity

There are zero passwords stored anywhere in this project. Two mechanisms make that true:

**Pipeline to Azure: OIDC federated credentials.** Instead of storing an Azure service principal secret in GitHub, GitHub Actions proves its identity to Azure with a short-lived OIDC token minted per run. Azure is configured to trust tokens from this specific repo and branch. Nothing long-lived exists to leak.

**App to database: Key Vault + managed identity.** The database connection string lives in Azure Key Vault. The App Service has a managed identity with permission to read that one secret, and the app setting uses a **Key Vault reference** (`@Microsoft.KeyVault(SecretUri=...)`) so the value never appears in Terraform code, pipeline logs, or the portal config screen.

---

## 10. Drift detection

**Configuration drift** is when live infrastructure no longer matches its code, usually because someone made a manual change in the portal. Drift is how "temporary" firewall openings become permanent and how environments quietly diverge.

A second workflow (`drift.yml`) runs on a cron schedule (every 6 hours, plus a manual trigger button for demos). It runs:

```
terraform plan -detailed-exitcode
```

The `-detailed-exitcode` flag makes the exit code meaningful: **0** means live infra matches the code, **1** means an error, **2** means drift exists. On exit code 2, the workflow:

1. Runs `terraform show -json` on the plan to extract exactly which resources changed and how.
2. Opens a GitHub issue containing the diff summary (who should look, what changed).
3. POSTs an incident to the deployed app's own API, so drift events accumulate in the incident tracker.

---

## 11. Auto-remediation (deliberately scoped)

The key policy decision: the watchdog does **not** blindly `terraform apply` everything back on any drift. Blanket auto-revert can destroy a legitimate emergency change someone made at 2am for a reason. Uncontrolled automation has a large **blast radius**; good automation constrains it.

Instead, remediation runs from an **allow-list** with exactly one entry: NSG rules on the database subnet. If the drift diff shows that subnet's NSG changed (the classic case: someone added an inbound allow rule from `0.0.0.0/0` in the portal), the workflow runs a targeted revert:

```
terraform apply -target=azurerm_network_security_rule.db_inbound -auto-approve
```

restoring the declared rule set, then logs a high-severity incident with the before and after state. Everything outside the allow-list stays alert-only for a human to review.

(`-target` is normally discouraged in day-to-day Terraform use because it applies partial state. Using it here is a deliberate, surgical choice with a small, known blast radius.)

**The demo script:** open the Azure portal, add an inbound allow-all rule to the database NSG by hand, trigger the watchdog manually, and screenshot the sequence: drift alert raised, rule reverted, incident logged in the app. Those screenshots will be added to this README when this phase is built.

---

## 12. Monitoring

App Service streams logs to Azure Monitor. Optionally, Application Insights adds request tracing on the API. The watchdog's run history in GitHub Actions doubles as an **audit trail** of every drift check and remediation. Keep this layer light; it exists so you can answer "how would you know if it broke" with something concrete.

---

## 13. End-to-end flows

**Flow A: a normal code change**

1. You push a commit to main.
2. Lint and tests run, then the image builds tagged with the commit SHA.
3. Trivy scans the image; a high/critical CVE with an available fix kills the run here.
4. Image pushes to ACR, dev deploys, smoke test passes.
5. Staging deploys automatically.
6. Prod waits for your manual approval, then deploys.

**Flow B: someone changes infra by hand**

1. A rule allowing inbound traffic from anywhere is added to the database NSG in the portal.
2. The watchdog's next scheduled run executes `terraform plan -detailed-exitcode`, which returns 2.
3. The workflow extracts the diff and opens a GitHub issue.
4. The diff matches the allow-list (database NSG), so a targeted apply reverts the rule.
5. A high-severity incident is POSTed to the app with the before/after details.
6. Anything that had drifted outside the allow-list would stop at step 3, alert-only.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| CI/CD | Continuous Integration / Continuous Delivery: automatically testing, building, and deploying code on every change |
| IaC | Infrastructure as Code: defining cloud resources in files (Terraform) instead of clicking in a portal |
| Terraform state | Terraform's record of what it has built; the source of truth it diffs against |
| State locking | Preventing two Terraform runs from modifying infra simultaneously |
| Workspace | Terraform mechanism for running the same code against separate environments |
| Configuration drift | Live infrastructure diverging from its code definition, usually via manual changes |
| Idempotency | Applying the same config twice produces no change the second time |
| Container image | The packaged, runnable snapshot of the app produced by `docker build` |
| Immutable tag | Tagging images by commit SHA so each image maps to exactly one code version |
| ACR | Azure Container Registry, where images are stored |
| CVE | A publicly catalogued software vulnerability |
| Trivy | Open-source scanner that finds CVEs inside container images |
| NSG | Network Security Group: Azure's subnet/NIC-level firewall rules |
| OIDC federated credential | Short-lived, per-run token auth between GitHub and Azure; replaces stored secrets |
| Managed identity | An Azure-managed identity a resource uses to access other resources without credentials |
| Key Vault reference | App Service setting that pulls a secret from Key Vault at runtime |
| Smoke test | Minimal post-deploy check (here: `/health` returns 200) |
| Environment promotion | Moving a release through dev, staging, prod with gates between |
| Quality gate | A pipeline stage that blocks everything downstream if it fails |
| Blast radius | How much damage an action (or automation) can cause; good design keeps it small |

---

## 15. Build order

Build in phases and keep each phase working before starting the next. A finished phase 3 beats a half-built phase 5.

1. **App + Docker (days 1-2).** FastAPI app running locally in a container against SQLite. Done when `docker run` serves `/docs`.
2. **Terraform dev environment (week 1).** Remote state bootstrap, then all core resources in the dev workspace. Deploy the container manually once. Done when the app is live on Azure and `terraform apply` run twice changes nothing.
3. **CI/CD with scanning (week 2).** Pipeline through the dev deploy: lint, test, build, Trivy gate, push, deploy, smoke test. Done when a push to main lands in dev untouched by hand.
4. **Promotion + secrets (weeks 2-3).** Staging and prod workspaces, OIDC federation, Key Vault references, prod approval gate. Done when a release walks dev -> staging -> approval -> prod.
5. **Watchdog + remediation (weeks 3-4).** Drift detection on cron, GitHub issue alerts, the NSG allow-list revert, incident logging into the app. Done when the demo script in section 11 produces its screenshots.
6. **Optional later: AKS.** Swap App Service for AKS only after everything above works, and only if target job postings demand Kubernetes. It roughly doubles the infra complexity for one extra keyword.

---

## 16. Cost control

Use the smallest SKUs everywhere: B1 App Service plan, B1ms burstable Postgres. Run `terraform destroy` on the dev environment whenever you are not actively working (that is IaC's superpower: rebuilding it is one command). With Azure free credit and disciplined teardown, this project costs close to nothing.
