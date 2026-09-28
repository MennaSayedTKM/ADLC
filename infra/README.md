# ADLC on AWS (Pulumi)

ADLC runs in its own Control Tower member account (**ADLC-Prod**,
`958295070544`) in **eu-central-1 (Frankfurt)**, the Control Tower home
region, so it's fully governed.

```
Internet ──HTTPS──> Load balancer ── Cognito login page (invite-only)
                        │
                        ▼  (only the load balancer can reach it, port 8080)
                    ECS Fargate — exactly one container
                    FastAPI API + built frontend (backend/app/serve.py)
                    data/ on EFS: encrypted, backed up daily
                        │
                        ├─> Amazon Bedrock: Cohere Embed v4 (design screens)
                        └─> OpenAI, Confluence (outbound only)

GitHub (push to main) ─> GitHub Actions: tests, build ─> Amazon ECR "adlc"
```

- **No servers to manage:** Fargate runs the container, and there's no EC2
  and no SSH.
- **No stored cloud keys:** GitHub Actions signs in to AWS with a
  short-lived OIDC token. Only the `main` branch of
  `MennaSayedTKM/ADLC` is trusted, and it may only push the image and
  redeploy the service.
- **Secrets** (OpenAI key, Confluence token) are stored encrypted in Pulumi
  config and SSM Parameter Store. ECS injects them into the container as
  environment variables. They're never in the repository or the image.
- **One container only:** SQLite is single-writer and the FAISS index lives
  in memory, so a deploy stops the old container before starting the new
  one. That means a short outage per deploy (about 1–2 minutes).
- **HTTPS** uses a **self-signed certificate** until there's a domain, so
  browsers show a warning once. See [Moving to a real domain](#moving-to-a-real-domain).

| File | Purpose |
|---|---|
| `adlc_stack.py` | Every AWS resource |
| `legacy_ec2.py` | The old EC2 setup. Now only keeps the old EBS data disk (see [Old EC2 data disk](#old-ec2-data-disk)) |
| `Pulumi.prod.yaml` | Settings for the `prod` stack, plus encrypted secrets |
| `bootstrap.ps1` | One-time: creates Pulumi's state bucket and secrets key, creates the stack |
| `scripts/migrate_data_to_efs.sh` | One-time copy of `data/` from EC2 to EFS (already done on 2026-09-28) |
| `tests/` | Runs the whole program offline under Pulumi mocks |
| `../Dockerfile`, `../docker/entrypoint.sh` | The container image |
| `../.github/workflows/docker-publish.yml` | Test, build and push to ECR (and optional redeploy) |

## Logging in

AWS commands need an active SSO session. Run this whenever you see
"token has expired":
```powershell
aws sso login --profile adlc
```
The console is at the access portal, `https://d-9067c485f3.awsapps.com/start`,
under **ADLC-Prod → AWSAdministratorAccess**, region **Europe (Frankfurt)**.

## Deploying new code

1. Push to `main`. GitHub Actions runs the backend tests, builds the image,
   and pushes it to ECR as `adlc:latest` and `adlc:<commit sha>` (about
   3–8 minutes). Changes only under `infra/`, `docs/` or `*.md` don't
   trigger a build.
2. Roll it out, either by:
   - **GitHub:** Actions → *Build and push image* → **Run workflow**, with
     **deploy** ticked (build + roll-out in one go), or
   - **your terminal:**
     ```powershell
     aws ecs update-service --cluster adlc-prod --service adlc-prod-app --force-new-deployment --profile adlc
     ```

The new container applies any database migrations (`alembic upgrade head`)
on start. If it doesn't become healthy, ECS automatically rolls back to
the previous version.

To pin a specific build instead of `latest`:
```powershell
cd infra
pulumi config set adlc:imageTag <commit sha>
pulumi up
```

## Day-to-day

| Task | How |
|---|---|
| Container logs | `aws logs tail /ecs/adlc-prod --follow --profile adlc` |
| Is it healthy? | `aws ecs describe-services --cluster adlc-prod --services adlc-prod-app --query "services[0].[runningCount,deployments[0].rolloutState]" --profile adlc` |
| Shell inside the container | Install the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html), then `pulumi stack output shellCommand` |
| Invite a user | `pulumi stack output addUserCommand`, replace `NAME@tkmind.net` (twice), run it |
| Rotate the OpenAI key | `pulumi config set --secret adlc:openaiApiKey`, `pulumi up`, then redeploy (above) |
| Image vulnerability scan | ECR console → `adlc` → image → *Vulnerabilities* (scanned on every push) |
| Container size | `adlc:taskCpu` / `adlc:taskMemory` in `Pulumi.prod.yaml` (default 1 vCPU / 4 GB), then `pulumi up` |

### Work-hours only (optional)
To run the container only Mon–Fri 08:00–19:00 Dubai time (about $16/month
instead of about $50, with the site unavailable outside those hours):
```powershell
cd infra
pulumi config set adlc:appScheduleEnabled true
pulumi up
```
Change the times with `adlc:appStartCron` / `adlc:appStopCron` /
`adlc:scheduleTimezone`.

## Data and backups

- `data/` (SQLite DB, FAISS index, tiles, uploads) lives on **EFS**,
  mounted at `/app/data` in the container through an access point as uid
  1000. The file system is **protected**: `pulumi destroy` refuses to
  delete it.
- **AWS Backup** takes a daily backup of EFS and keeps it for 35 days. To
  restore, go to the AWS Backup console → *Protected resources* → the EFS
  file system → *Restore*.

### Old EC2 data disk
The EBS disk from the EC2 era (`vol-07409efa0e2ccab95`, 50 GB, detached) and
its 4 snapshots are kept as an extra backup. They cost about $4/month. When
you no longer need them:
```powershell
cd infra
pulumi state unprotect "urn:pulumi:prod::adlc::aws:ebs/volume:Volume::adlc-prod-data"
pulumi config set adlc:keepLegacyDataVolume false
pulumi up
```
Then delete the 4 snapshots in the EC2 console (**Snapshots**, tag
`adlc-prod-data`).

## Rough monthly cost (eu-central-1)

| Item | ≈ USD/month |
|---|---|
| Fargate, 1 vCPU / 4 GB, 24/7 (≈16 with work-hours schedule) | 50 |
| Load balancer | 20 |
| Public IPv4 addresses (load balancer + container) | 11 |
| EFS + backups, ECR, logs, KMS, S3, Cognito | < 5 |
| Old EC2 data disk + snapshots (until deleted) | 4 |
| **Total** | **≈ 90** |

These are estimates. Bedrock embeddings (fractions of a cent per screen)
and OpenAI usage are billed per use and tracked in the `ai_calls` table.

## Moving to a real domain

When a domain such as `adlc.tkmind.net` is available:
1. Request an ACM certificate for it in eu-central-1 (DNS validation).
2. In `adlc_stack.py`, replace the self-signed `tls_*` / `certificate` block
   with that certificate's ARN, and change the Cognito `callback_urls` to
   `https://adlc.tkmind.net/oauth2/idpresponse`.
3. Point the domain at the load balancer's DNS name with a CNAME record.
4. Run `pulumi up`.

## First-time setup (already done, for reference)

1. ADLC-Prod account created with Control Tower Account Factory (OU
   `ADLC`); Identity Center user assigned **AWSAdministratorAccess**.
2. `aws configure sso --profile adlc`. Identity Center itself is in
   **us-east-1**, so the profile uses `sso_region = us-east-1`.
3. `powershell -ExecutionPolicy Bypass -File infra\bootstrap.ps1` created
   the state bucket, the KMS key and the `prod` stack.
4. `pulumi config set --secret adlc:openaiApiKey` and the Confluence
   settings, then `pulumi up`.
5. GitHub repository variable `AWS_ROLE_ARN` = `pulumi stack output githubActionsRoleArn`.

## Tests

The tests run the Pulumi program offline under mocks. No AWS account is needed.
```powershell
cd infra
venv\Scripts\python -m pytest tests
```
