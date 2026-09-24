# ADLC on AWS (Pulumi)

Deploys ADLC into its own Control Tower member account (**ADLC-Prod**) in
**eu-central-1 (Frankfurt)**, the Control Tower home region, so it is fully governed.

```
Internet ──HTTPS──> Load balancer ── Cognito login page (invite-only)
                        │
                        ▼  (only the load balancer can reach it)
                    App server  t3.large, Ubuntu 24.04
                    nginx + FastAPI (1 worker) + built frontend
                    data/ on its own encrypted EBS volume, snapshotted daily
                        │
                        ▼  (only the app server can reach it)
                    Embedding server  g4dn.xlarge GPU
                    Qwen3-VL, running Mon–Fri 08:00–19:00 Dubai time
```

- No SSH. You reach the servers through **SSM Session Manager**.
- Secrets (OpenAI key, GitHub deploy key) are stored encrypted in Pulumi
  config and SSM Parameter Store, never in the repository or user-data.
- HTTPS uses a **self-signed certificate** until there's a domain, so
  browsers show a warning once. See [Moving to a real domain](#moving-to-a-real-domain).

| File | Purpose |
|---|---|
| `adlc_stack.py` | Every AWS resource |
| `Pulumi.prod.yaml` | Settings for the `prod` stack (instance sizes, schedule, …) plus encrypted secrets |
| `userdata/app.sh` | First-boot setup of the app server; installs the `adlc-deploy` command |
| `userdata/embed.sh` | First-boot setup of the GPU server (runs `embed_server/server.py`) |
| `bootstrap.ps1` | One-time: creates Pulumi's state bucket and secrets key, creates the stack |
| `tests/` | Runs the whole program offline under Pulumi mocks |

## Before you start

1. The **ADLC-Prod** account exists in Control Tower, and you have
   **AWSAdministratorAccess** on it through IAM Identity Center.
2. **eu-central-1** is a governed region in Control Tower (it is the home region).
3. GPU quota: in ADLC-Prod, **eu-central-1**, go to Service Quotas → EC2 →
   *Running On-Demand G and VT instances*. The value must be at least **4**
   (8 is recommended).
4. Installed: AWS CLI v2, Pulumi, Python 3.12, and the
   [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
   (only needed to open a shell on a server).
5. An AWS CLI profile named `adlc` for ADLC-Prod (`aws configure sso --profile adlc`).

## First deployment

Run everything from the repository root in PowerShell unless it says `infra\`.

**1. Log in** (repeat whenever the session expires):
```powershell
aws sso login --profile adlc
```

**2. Check that the region has what we need.** The first command should
print `g4dn.xlarge`. The second should succeed, even if it prints no pools.
```powershell
aws ec2 describe-instance-type-offerings --location-type region --filters Name=instance-type,Values=g4dn.xlarge --region eu-central-1 --profile adlc --query "InstanceTypeOfferings[].InstanceType"
aws cognito-idp list-user-pools --max-results 1 --region eu-central-1 --profile adlc
```

**3. Create Pulumi's state storage and the `prod` stack** (one time):
```powershell
powershell -ExecutionPolicy Bypass -File infra\bootstrap.ps1
```

**4. Install the Pulumi program's packages and set the OpenAI key.** The
`config set --secret` command prompts for the value, so it never appears in
your shell history.
```powershell
cd infra
pulumi install
pulumi config set --secret adlc:openaiApiKey
```
Optional, only if you use "Publish to Confluence":
```powershell
pulumi config set adlc:confluenceBaseUrl https://tk-mind.atlassian.net/wiki
pulumi config set adlc:confluenceEmail you@tkmind.net
pulumi config set adlc:confluenceSpaceKey ADLC
pulumi config set --secret adlc:confluenceApiToken
```

**5. Preview.** This shows everything that would be created. Nothing is
created and nothing is billed yet.
```powershell
pulumi preview
```

**6. Create it** (about 10 minutes):
```powershell
pulumi up
```

**7. Give the server read access to the code.** Copy the key this prints:
```powershell
pulumi stack output githubDeployPublicKey
```
On GitHub, open **MennaSayedTKM/ADLC → Settings → Deploy keys → Add deploy
key**. Paste the key, name it `adlc-prod-server`, and leave **Allow write
access unticked**. The server retries the first deploy every minute for 2
hours, so it picks the key up by itself.

**8. Invite users.** Print the command, replace `NAME@tkmind.net` in it, and
run it. Each person gets an email with a temporary password.
```powershell
pulumi stack output addUserCommand
```

**9. Open the app:**
```powershell
pulumi stack output url
```
The browser shows a certificate warning (self-signed). Choose
*Advanced → Continue*, then sign in on the login page.

The first boot installs everything and builds the app, which takes about
10–15 minutes after `pulumi up` finishes. Until then the page may show
**502/503**. The GPU server downloads the model on its first start, which
takes a few more minutes.

## Deploying new code

Commit and push to `main` as usual, then run the command this prints:
```powershell
pulumi stack output deployCommand
```
It pulls the latest `main` on the server, refreshes `.env` from Parameter
Store, installs dependencies, builds the frontend, runs `alembic upgrade
head` and restarts the backend. The backend is down for a few seconds while
migrations run.

To change the embedding server (`embed_server/server.py` or its
`requirements.txt`), run `pulumi up`. The GPU instance is replaced, since it
holds no data.

## Day-to-day

| Task | How |
|---|---|
| Open a shell on the app server | `pulumi stack output shellCommand`, then run it |
| First-boot log | `sudo less /var/log/adlc-bootstrap.log` |
| Backend log | `sudo journalctl -u adlc-backend -f` |
| Redeploy by hand (on the server) | `sudo adlc-deploy` |
| GPU server log | shell into `embedInstanceId`, then `sudo journalctl -u adlc-embed -f` |
| Use the GPU outside work hours | start the `adlc-prod-embed` instance in the EC2 console; the schedule stops it at 19:00 |
| Change the GPU schedule | edit `adlc:embedStartCron` / `adlc:embedStopCron` in `Pulumi.prod.yaml`, then `pulumi up` |
| Rotate the OpenAI key | `pulumi config set --secret adlc:openaiApiKey`, `pulumi up`, then run the deploy command |

Outside work hours, design-screen ingestion fails with an "embedding server"
error. That's expected: requirements extraction doesn't use the GPU, but
design uploads do.

## Data and backups

- The data volume (SQLite DB, FAISS index, tiles, uploads) is **protected**:
  `pulumi destroy` refuses to delete it.
- A snapshot is taken every night at 02:00 Dubai time, and the last 14 are kept.
- The Cognito user pool has deletion protection on.
- To restore: create a volume from a snapshot, then either swap it in or
  mount it on the app server and copy the files back.

## Rough monthly cost (eu-central-1, on-demand)

| Item | ≈ USD/month |
|---|---|
| App server t3.large, 24/7 | 75 |
| GPU g4dn.xlarge, about 240 h (work hours) | 150 |
| Load balancer | 25 |
| EBS 180 GB gp3 + snapshots | 20 |
| Public IPv4 addresses | 15 |
| Cognito, SSM, KMS, S3 | < 5 |
| **Total** | **≈ 290** |

These are estimates. Check the AWS Pricing Calculator for eu-central-1. OpenAI
usage is billed separately; the `ai_calls` table tracks it.

## Moving to a real domain

When a domain such as `adlc.tkmind.net` is available:
1. Request an ACM certificate for it in eu-central-1 (DNS validation).
2. In `adlc_stack.py`, replace the self-signed `tls_*` / `certificate` block
   with that certificate's ARN, and change the Cognito `callback_urls` to
   `https://adlc.tkmind.net/oauth2/idpresponse`.
3. Point the domain at the load balancer's DNS name with a CNAME record.
4. Run `pulumi up`.

## Tests

The tests run the Pulumi program offline under mocks. No AWS account is needed.
```powershell
cd infra
venv\Scripts\python -m pytest tests
```
