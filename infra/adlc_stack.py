"""
adlc_stack.py
ADLC on AWS, in one Control Tower member account:

  Internet ──HTTPS──> ALB (Cognito login, self-signed cert for now)
                        │ HTTP :8080, from the ALB only
                        ▼
                      ECS Fargate service — exactly one task running the
                      image from ECR (FastAPI API + built frontend,
                      backend/app/serve.py); data/ on an encrypted EFS
                      volume (SQLite DB, FAISS index, tiles, uploads)

GitHub Actions builds the image and pushes it to ECR, signing in to AWS
with a short-lived OIDC token (no AWS keys stored in GitHub).
                        │
                        ├─> Amazon Bedrock — Cohere Embed v4 (design screens)
                        └─> OpenAI, Confluence (outbound only)

No NAT gateway: the task runs in a public subnet with a public IP for
outbound traffic, but its security group accepts nothing except the ALB.
Secrets live in SSM Parameter Store (SecureString), set from encrypted
Pulumi config, and are injected into the container by ECS.

Migration from the original EC2 deployment is driven by three settings:
  adlc:serveFrom            ec2 | fargate — where the ALB sends traffic
  adlc:ec2AppEnabled        keep the EC2 app server (until the move is confirmed)
  adlc:keepLegacyDataVolume keep the EC2 data disk (protected) until deleted on purpose
"""

import json
from pathlib import Path

import pulumi
import pulumi_aws as aws
import pulumi_random as random
import pulumi_tls as tls

_ROOT = Path(__file__).resolve().parent

cfg = pulumi.Config("adlc")
stack = pulumi.get_stack()
region = aws.config.region
prefix = f"adlc-{stack}"
param_prefix = f"/adlc/{stack}"


def _flag(key: str, default: bool) -> bool:
    value = cfg.get_bool(key)
    return default if value is None else value


vpc_cidr = cfg.get("vpcCidr") or "10.40.0.0/16"
login_session_hours = cfg.get_int("loginSessionHours") or 12

# Custom domain (DNS hosted outside AWS, at OVH). Two phases: set
# adlc:domain → `pulumi up` requests the certificate and prints the DNS
# records to add; once ACM has issued it, set adlc:domainCertValidated=true
# → `pulumi up` switches the HTTPS listener to it.
domain = cfg.get("domain")  # e.g. adlc.tkmind.net
domain_cert_validated = cfg.get_bool("domainCertValidated") or False

# Login: self sign-up and "Sign in with Microsoft", both limited to these
# email domains by the pre sign-up Lambda (every signed-in user sees every
# project — the app has no per-user permissions).
self_signup_enabled = cfg.get_bool("selfSignUpEnabled")
self_signup_enabled = True if self_signup_enabled is None else self_signup_enabled
allowed_email_domains = cfg.get("allowedEmailDomains") or "tkmind.net"
entra_tenant_id = cfg.get("entraTenantId")  # Microsoft Entra ID (Microsoft 365) tenant
entra_client_id = cfg.get("entraClientId")
entra_client_secret = cfg.get_secret("entraClientSecret")

# Fargate
serve_from = (cfg.get("serveFrom") or "fargate").strip().lower()
if serve_from not in ("ec2", "fargate"):
    raise ValueError(f"adlc:serveFrom must be 'ec2' or 'fargate', not {serve_from!r}")
image_override = cfg.get("image")  # default: this stack's ECR repository, tag adlc:imageTag
image_tag = cfg.get("imageTag") or "latest"
task_cpu = cfg.get("taskCpu") or "1024"  # 1 vCPU
task_memory = cfg.get("taskMemory") or "4096"  # 4 GB
ecr_keep_images = cfg.get_int("ecrKeepImages") or 20
app_schedule_enabled = _flag("appScheduleEnabled", False)
app_start_cron = cfg.get("appStartCron") or "cron(0 8 ? * MON-FRI *)"
app_stop_cron = cfg.get("appStopCron") or "cron(0 19 ? * MON-FRI *)"
schedule_timezone = cfg.get("scheduleTimezone") or "Asia/Dubai"
log_retention_days = cfg.get_int("logRetentionDays") or 30

# Legacy EC2 deployment (kept only while migrating)
ec2_app_enabled = _flag("ec2AppEnabled", False)
keep_legacy_data_volume = _flag("keepLegacyDataVolume", True)
github_repo = cfg.get("githubRepo") or "MennaSayedTKM/ADLC"
git_branch = cfg.get("gitBranch") or "main"
# GitHub's OIDC subject may carry immutable owner/repo IDs
# ("repo:Owner@123/Repo@456:ref:..."), which a renamed or re-created repo
# can't impersonate. Both IDs come from a CloudTrail AssumeRoleWithWebIdentity
# event (or the GitHub API).
github_owner_id = cfg.get("githubOwnerId")
github_repo_id = cfg.get("githubRepoId")
app_instance_type = cfg.get("appInstanceType") or "t3.large"
data_volume_gb = cfg.get_int("dataVolumeGb") or 50
snapshot_retain_count = cfg.get_int("snapshotRetainCount") or 14

if serve_from == "ec2" and not ec2_app_enabled:
    raise ValueError("adlc:serveFrom is 'ec2' but adlc:ec2AppEnabled is false — nothing would serve traffic")

tags = {"Project": "ADLC", "Stack": stack, "ManagedBy": "pulumi"}


def _name(suffix: str) -> dict:
    return {**tags, "Name": f"{prefix}-{suffix}"}


def _assume_role(service: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}],
        }
    )


# Design-screen embeddings: Cohere Embed v4 on Bedrock (config.yaml
# embed_provider: bedrock). The EU inference profile may route to any EU
# region's copy of the model.
BEDROCK_EMBED_STATEMENT = {
    "Effect": "Allow",
    "Action": "bedrock:InvokeModel",
    "Resource": [
        "arn:aws:bedrock:*::foundation-model/cohere.embed-v4*",
        "arn:aws:bedrock:*:*:inference-profile/*cohere.embed-v4*",
    ],
}

# ── Network ──────────────────────────────────────────────────────────────────
azs = aws.get_availability_zones(state="available").names[:2]  # the ALB needs two AZs

vpc = aws.ec2.Vpc(
    f"{prefix}-vpc",
    cidr_block=vpc_cidr,
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags=_name("vpc"),
)
igw = aws.ec2.InternetGateway(f"{prefix}-igw", vpc_id=vpc.id, tags=_name("igw"))
public_rt = aws.ec2.RouteTable(
    f"{prefix}-public-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id)],
    tags=_name("public-rt"),
)
subnets = []
for i, az in enumerate(azs):
    subnet = aws.ec2.Subnet(
        f"{prefix}-public-{i}",
        vpc_id=vpc.id,
        cidr_block=f"{vpc_cidr.split('.')[0]}.{vpc_cidr.split('.')[1]}.{i}.0/24",
        availability_zone=az,
        map_public_ip_on_launch=True,
        tags=_name(f"public-{az}"),
    )
    aws.ec2.RouteTableAssociation(f"{prefix}-public-{i}-rta", subnet_id=subnet.id, route_table_id=public_rt.id)
    subnets.append(subnet)

# ── Security groups ──────────────────────────────────────────────────────────
alb_sg = aws.ec2.SecurityGroup(f"{prefix}-alb-sg", vpc_id=vpc.id, description="ADLC load balancer", tags=_name("alb-sg"))
task_sg = aws.ec2.SecurityGroup(
    f"{prefix}-task-sg", vpc_id=vpc.id, description="ADLC Fargate task", tags=_name("task-sg")
)
efs_sg = aws.ec2.SecurityGroup(f"{prefix}-efs-sg", vpc_id=vpc.id, description="ADLC data (EFS)", tags=_name("efs-sg"))

for port in (80, 443):  # 80 only redirects to 443; Cognito guards 443
    aws.vpc.SecurityGroupIngressRule(
        f"{prefix}-alb-in-{port}",
        security_group_id=alb_sg.id,
        cidr_ipv4="0.0.0.0/0",
        ip_protocol="tcp",
        from_port=port,
        to_port=port,
        description=f"HTTP(S) from anywhere on {port}",
    )
aws.vpc.SecurityGroupIngressRule(
    f"{prefix}-task-in-alb",
    security_group_id=task_sg.id,
    referenced_security_group_id=alb_sg.id,
    ip_protocol="tcp",
    from_port=8080,
    to_port=8080,
    description="App container, from the ALB only",
)
aws.vpc.SecurityGroupIngressRule(
    f"{prefix}-efs-in-task",
    security_group_id=efs_sg.id,
    referenced_security_group_id=task_sg.id,
    ip_protocol="tcp",
    from_port=2049,
    to_port=2049,
    description="NFS, from the app container only",
)
# Outbound: the ALB reaches Cognito's token endpoint; the task reaches
# OpenAI, Confluence, Bedrock, ECR and other AWS APIs.
for sg_name, sg in (("alb", alb_sg), ("task", task_sg)):
    aws.vpc.SecurityGroupEgressRule(
        f"{prefix}-{sg_name}-out", security_group_id=sg.id, cidr_ipv4="0.0.0.0/0", ip_protocol="-1"
    )

# ── Secrets → SSM Parameter Store ────────────────────────────────────────────
# Every parameter under {param_prefix}/env/ becomes an environment variable
# in the container (and a line in the EC2 server's .env while it exists).
_env_secrets = {
    "OPENAI_API_KEY": cfg.require_secret("openaiApiKey"),
    "ANTHROPIC_API_KEY": cfg.get_secret("anthropicApiKey"),
    "CONFLUENCE_API_TOKEN": cfg.get_secret("confluenceApiToken"),
}
_env_plain = {
    "CONFLUENCE_BASE_URL": cfg.get("confluenceBaseUrl"),
    "CONFLUENCE_EMAIL": cfg.get("confluenceEmail"),
    "CONFLUENCE_SPACE_KEY": cfg.get("confluenceSpaceKey"),
}
env_params: dict[str, aws.ssm.Parameter] = {}
for key, value in _env_secrets.items():
    if value is not None:
        env_params[key] = aws.ssm.Parameter(
            f"{prefix}-env-{key.lower()}",
            name=f"{param_prefix}/env/{key}",
            type="SecureString",
            value=value,
            tags=tags,
        )
for key, value in _env_plain.items():
    if value:
        env_params[key] = aws.ssm.Parameter(
            f"{prefix}-env-{key.lower()}", name=f"{param_prefix}/env/{key}", type="String", value=value, tags=tags
        )

# ── Persistent data: EFS ─────────────────────────────────────────────────────
data_fs = aws.efs.FileSystem(
    f"{prefix}-data-fs",
    encrypted=True,
    performance_mode="generalPurpose",
    throughput_mode="elastic",
    tags=_name("data"),
    # Holds the DB, FAISS index and client uploads: `pulumi destroy` must
    # never delete it. Unprotect deliberately if it really has to go.
    opts=pulumi.ResourceOptions(protect=True),
)
aws.efs.BackupPolicy(  # AWS Backup: daily, kept 35 days
    f"{prefix}-data-fs-backup",
    file_system_id=data_fs.id,
    backup_policy=aws.efs.BackupPolicyBackupPolicyArgs(status="ENABLED"),
)
mount_targets = [
    aws.efs.MountTarget(f"{prefix}-data-mt-{i}", file_system_id=data_fs.id, subnet_id=s.id, security_groups=[efs_sg.id])
    for i, s in enumerate(subnets)
]
# The container runs as uid/gid 1000 (Dockerfile); the access point pins
# that identity and roots the mount at /adlc-data.
data_access_point = aws.efs.AccessPoint(
    f"{prefix}-data-ap",
    file_system_id=data_fs.id,
    posix_user=aws.efs.AccessPointPosixUserArgs(uid=1000, gid=1000),
    root_directory=aws.efs.AccessPointRootDirectoryArgs(
        path="/adlc-data",
        creation_info=aws.efs.AccessPointRootDirectoryCreationInfoArgs(owner_uid=1000, owner_gid=1000, permissions="750"),
    ),
    tags=_name("data-ap"),
)

# ── Container images: ECR ────────────────────────────────────────────────────
# GitHub Actions pushes :latest and :<commit sha>; ECS pulls with its
# execution role (AmazonECSTaskExecutionRolePolicy covers ECR pulls).
ecr_repo = aws.ecr.Repository(
    f"{prefix}-ecr",
    name="adlc",
    image_tag_mutability="MUTABLE",  # :latest moves with every build; :<sha> tags never change
    image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(scan_on_push=True),
    encryption_configurations=[aws.ecr.RepositoryEncryptionConfigurationArgs(encryption_type="AES256")],
    tags=tags,
)
aws.ecr.LifecyclePolicy(
    f"{prefix}-ecr-lifecycle",
    repository=ecr_repo.name,
    policy=json.dumps(
        {
            "rules": [
                {
                    "rulePriority": 1,
                    "description": "Drop untagged layers after a week",
                    "selection": {"tagStatus": "untagged", "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 7},
                    "action": {"type": "expire"},
                },
                {
                    "rulePriority": 2,
                    "description": f"Keep the newest {ecr_keep_images} images",
                    "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": ecr_keep_images},
                    "action": {"type": "expire"},
                },
            ]
        }
    ),
)
# The registry-level scanning configuration overrides the repository's
# scan_on_push, and in this account it defaults to BASIC with no rules — i.e.
# nothing is scanned. Basic scanning (free) on every push of the adlc repo.
aws.ecr.RegistryScanningConfiguration(
    f"{prefix}-ecr-scanning",
    scan_type="BASIC",
    rules=[
        aws.ecr.RegistryScanningConfigurationRuleArgs(
            scan_frequency="SCAN_ON_PUSH",
            repository_filters=[
                aws.ecr.RegistryScanningConfigurationRuleRepositoryFilterArgs(filter="adlc", filter_type="WILDCARD")
            ],
        )
    ],
)
image = pulumi.Output.from_input(image_override) if image_override else ecr_repo.repository_url.apply(
    lambda url: f"{url}:{image_tag}"
)

# GitHub Actions signs in with a short-lived OIDC token — no AWS keys stored
# in GitHub. Only the main branch of this repository can assume the role.
_owner, _repo = github_repo.split("/", 1)
github_oidc_subjects = [f"repo:{github_repo}:ref:refs/heads/{git_branch}"]
if github_owner_id and github_repo_id:
    github_oidc_subjects.append(f"repo:{_owner}@{github_owner_id}/{_repo}@{github_repo_id}:ref:refs/heads/{git_branch}")
github_oidc = aws.iam.OpenIdConnectProvider(
    f"{prefix}-github-oidc",
    url="https://token.actions.githubusercontent.com",
    client_id_lists=["sts.amazonaws.com"],
    tags=tags,
)
github_role = aws.iam.Role(
    f"{prefix}-github-actions-role",
    description=f"GitHub Actions ({github_repo}, {git_branch}): push the ADLC image, redeploy the service",
    assume_role_policy=github_oidc.arn.apply(
        lambda provider_arn: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Federated": provider_arn},
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                "token.actions.githubusercontent.com:sub": github_oidc_subjects,
                            }
                        },
                    }
                ],
            }
        )
    ),
    max_session_duration=3600,
    tags=tags,
)

# ── ECS: cluster, roles, logs ────────────────────────────────────────────────
cluster = aws.ecs.Cluster(
    f"{prefix}-cluster",
    name=prefix,  # fixed names: .github/workflows/docker-publish.yml redeploys by name
    settings=[aws.ecs.ClusterSettingArgs(name="containerInsights", value="disabled")],
    tags=tags,
)
log_group = aws.cloudwatch.LogGroup(f"{prefix}-app-logs", name=f"/ecs/{prefix}", retention_in_days=log_retention_days, tags=tags)

# Execution role: what ECS itself needs to start the task — pull the image,
# read the secrets it injects, write logs.
execution_role = aws.iam.Role(
    f"{prefix}-task-exec-role", assume_role_policy=_assume_role("ecs-tasks.amazonaws.com"), tags=tags
)
aws.iam.RolePolicyAttachment(
    f"{prefix}-task-exec-managed",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)
aws.iam.RolePolicy(
    f"{prefix}-task-exec-policy",
    role=execution_role.id,
    policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "ssm:GetParameters",
                    "Resource": [f"arn:aws:ssm:*:*:parameter{param_prefix}/env/*"],
                }
            ],
        }
    ),
)

aws.iam.RolePolicy(
    f"{prefix}-github-actions-policy",
    role=github_role.id,
    policy=pulumi.Output.all(ecr_repo.arn, cluster.name).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ecr:BatchCheckLayerAvailability",
                            "ecr:BatchGetImage",
                            "ecr:GetDownloadUrlForLayer",
                            "ecr:InitiateLayerUpload",
                            "ecr:UploadLayerPart",
                            "ecr:CompleteLayerUpload",
                            "ecr:PutImage",
                        ],
                        "Resource": args[0],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["ecs:UpdateService", "ecs:DescribeServices"],
                        "Resource": f"arn:aws:ecs:{region}:*:service/{args[1]}/*",
                    },
                ],
            }
        )
    ),
)

# Task role: what the app itself may do — Bedrock embeddings, its own EFS
# data, and ECS Exec (a shell into the running container for debugging).
task_role = aws.iam.Role(f"{prefix}-task-role", assume_role_policy=_assume_role("ecs-tasks.amazonaws.com"), tags=tags)
aws.iam.RolePolicy(
    f"{prefix}-task-policy",
    role=task_role.id,
    policy=pulumi.Output.all(data_fs.arn, data_access_point.arn).apply(
        lambda arns: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    BEDROCK_EMBED_STATEMENT,
                    {
                        "Effect": "Allow",
                        "Action": ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"],
                        "Resource": arns[0],
                        "Condition": {"StringEquals": {"elasticfilesystem:AccessPointArn": arns[1]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ssmmessages:CreateControlChannel",
                            "ssmmessages:CreateDataChannel",
                            "ssmmessages:OpenControlChannel",
                            "ssmmessages:OpenDataChannel",
                        ],
                        "Resource": "*",
                    },
                ],
            }
        )
    ),
)

# ── Load balancer + Cognito login ────────────────────────────────────────────
alb = aws.lb.LoadBalancer(
    f"{prefix}-alb",
    load_balancer_type="application",
    subnets=[s.id for s in subnets],
    security_groups=[alb_sg.id],
    idle_timeout=300,  # requirements extraction / alignment calls can run for minutes
    drop_invalid_header_fields=True,
    tags=_name("alb"),
)

# Self-signed for now (no domain yet): browsers warn once. Swap for an ACM
# certificate on a real domain later — only this block and the Cognito
# callback URL change.
tls_key = tls.PrivateKey(f"{prefix}-tls-key", algorithm="RSA", rsa_bits=2048)
tls_cert = tls.SelfSignedCert(
    f"{prefix}-tls-cert",
    private_key_pem=tls_key.private_key_pem,
    subject=tls.SelfSignedCertSubjectArgs(common_name=alb.dns_name, organization="TKMiND"),
    dns_names=[alb.dns_name],
    validity_period_hours=24 * 365 * 3,
    allowed_uses=["key_encipherment", "digital_signature", "server_auth"],
)
certificate = aws.acm.Certificate(
    f"{prefix}-cert",
    private_key=tls_key.private_key_pem,
    certificate_body=tls_cert.cert_pem,
    tags=_name("self-signed"),
)

# Pre sign-up trigger: refuses any email outside adlc:allowedEmailDomains,
# for self sign-up, Microsoft sign-in and admin-created users alike.
pre_signup_role = aws.iam.Role(
    f"{prefix}-pre-signup-role", assume_role_policy=_assume_role("lambda.amazonaws.com"), tags=tags
)
aws.iam.RolePolicyAttachment(
    f"{prefix}-pre-signup-logs-policy",
    role=pre_signup_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
)
pre_signup_logs = aws.cloudwatch.LogGroup(
    f"{prefix}-pre-signup-logs", name=f"/aws/lambda/{prefix}-pre-signup", retention_in_days=log_retention_days, tags=tags
)
pre_signup_fn = aws.lambda_.Function(
    f"{prefix}-pre-signup",
    name=f"{prefix}-pre-signup",
    runtime="python3.12",
    architectures=["arm64"],
    handler="pre_signup.handler",
    code=pulumi.AssetArchive({"pre_signup.py": pulumi.FileAsset(str(_ROOT / "lambdas" / "pre_signup.py"))}),
    role=pre_signup_role.arn,
    timeout=5,
    memory_size=128,
    environment=aws.lambda_.FunctionEnvironmentArgs(variables={"ALLOWED_EMAIL_DOMAINS": allowed_email_domains}),
    tags=tags,
    opts=pulumi.ResourceOptions(depends_on=[pre_signup_logs]),
)

user_pool = aws.cognito.UserPool(
    f"{prefix}-users",
    name=f"{prefix}-users",
    username_attributes=["email"],
    auto_verified_attributes=["email"],  # self sign-up confirms with an emailed code
    admin_create_user_config=aws.cognito.UserPoolAdminCreateUserConfigArgs(
        allow_admin_create_user_only=not self_signup_enabled
    ),
    lambda_config=aws.cognito.UserPoolLambdaConfigArgs(pre_sign_up=pre_signup_fn.arn),
    account_recovery_setting=aws.cognito.UserPoolAccountRecoverySettingArgs(
        recovery_mechanisms=[aws.cognito.UserPoolAccountRecoverySettingRecoveryMechanismArgs(name="verified_email", priority=1)]
    ),
    password_policy=aws.cognito.UserPoolPasswordPolicyArgs(
        minimum_length=12,
        require_lowercase=True,
        require_uppercase=True,
        require_numbers=True,
        require_symbols=False,
        temporary_password_validity_days=7,
    ),
    deletion_protection="ACTIVE",
    tags=tags,
)
aws.lambda_.Permission(
    f"{prefix}-pre-signup-invoke",
    action="lambda:InvokeFunction",
    function=pre_signup_fn.name,
    principal="cognito-idp.amazonaws.com",
    source_arn=user_pool.arn,
)
domain_suffix = random.RandomString(f"{prefix}-login-suffix", length=6, special=False, upper=False)
user_pool_domain = aws.cognito.UserPoolDomain(
    f"{prefix}-login",
    domain=domain_suffix.result.apply(lambda s: f"{prefix}-{s}"),
    user_pool_id=user_pool.id,
)

# "Sign in with Microsoft" — TKMiND's Microsoft 365 (Entra ID) accounts,
# once the app registration's tenant/client ID and secret are configured.
identity_providers = ["COGNITO"]
client_dependencies = []
if entra_tenant_id and entra_client_id and entra_client_secret is not None:
    microsoft_idp = aws.cognito.IdentityProvider(
        f"{prefix}-microsoft",
        user_pool_id=user_pool.id,
        provider_name="Microsoft",
        provider_type="OIDC",
        provider_details={
            "client_id": entra_client_id,
            "client_secret": entra_client_secret,
            "oidc_issuer": f"https://login.microsoftonline.com/{entra_tenant_id}/v2.0",
            "authorize_scopes": "openid email profile",
            "attributes_request_method": "GET",
        },
        attribute_mapping={"email": "email", "name": "name", "username": "sub"},
    )
    identity_providers.append("Microsoft")
    client_dependencies.append(microsoft_idp)

callback_urls = [alb.dns_name.apply(lambda dns: f"https://{dns}/oauth2/idpresponse")]
if domain:
    callback_urls.append(f"https://{domain}/oauth2/idpresponse")

user_pool_client = aws.cognito.UserPoolClient(
    f"{prefix}-alb-client",
    name=f"{prefix}-alb",
    user_pool_id=user_pool.id,
    generate_secret=True,  # required by the ALB's authenticate-cognito action
    allowed_oauth_flows_user_pool_client=True,
    allowed_oauth_flows=["code"],
    allowed_oauth_scopes=["openid", "email"],
    supported_identity_providers=identity_providers,
    callback_urls=callback_urls,
    opts=pulumi.ResourceOptions(depends_on=client_dependencies),
)

# Custom domain certificate (ACM, DNS-validated through records added at OVH).
domain_cert = None
serving_cert_arn = certificate.arn
if domain:
    domain_cert = aws.acm.Certificate(
        f"{prefix}-domain-cert", domain_name=domain, validation_method="DNS", tags=_name("domain")
    )
    if domain_cert_validated:
        serving_cert_arn = aws.acm.CertificateValidation(
            f"{prefix}-domain-cert-validation", certificate_arn=domain_cert.arn
        ).certificate_arn

fargate_tg = aws.lb.TargetGroup(
    f"{prefix}-fargate-tg",
    port=8080,
    protocol="HTTP",
    target_type="ip",
    vpc_id=vpc.id,
    deregistration_delay=30,
    health_check=aws.lb.TargetGroupHealthCheckArgs(
        path="/api/health", matcher="200", interval=30, timeout=10, healthy_threshold=2, unhealthy_threshold=3
    ),
    tags=_name("fargate-tg"),
)

# ── Legacy EC2 app server (only while migrating) ─────────────────────────────
ec2 = None
if ec2_app_enabled or keep_legacy_data_volume:
    from legacy_ec2 import build_legacy_ec2

    ec2 = build_legacy_ec2(
        prefix=prefix,
        stack=stack,
        region=region,
        param_prefix=param_prefix,
        tags=tags,
        name=_name,
        assume_role=_assume_role,
        vpc=vpc,
        subnet=subnets[0],
        alb_sg=alb_sg,
        efs_sg=efs_sg,
        env_params=list(env_params.values()),
        bedrock_statement=BEDROCK_EMBED_STATEMENT,
        instance_enabled=ec2_app_enabled,
        github_repo=github_repo,
        git_branch=git_branch,
        instance_type=app_instance_type,
        data_volume_gb=data_volume_gb,
        snapshot_retain_count=snapshot_retain_count,
    )

serving_tg = fargate_tg if serve_from == "fargate" else ec2.target_group

https_listener = aws.lb.Listener(
    f"{prefix}-https",
    load_balancer_arn=alb.arn,
    port=443,
    protocol="HTTPS",
    ssl_policy="ELBSecurityPolicy-TLS13-1-2-2021-06",
    certificate_arn=serving_cert_arn,
    default_actions=[
        aws.lb.ListenerDefaultActionArgs(
            type="authenticate-cognito",
            order=1,
            authenticate_cognito=aws.lb.ListenerDefaultActionAuthenticateCognitoArgs(
                user_pool_arn=user_pool.arn,
                user_pool_client_id=user_pool_client.id,
                user_pool_domain=user_pool_domain.domain,
                scope="openid email",
                on_unauthenticated_request="authenticate",
                session_timeout=login_session_hours * 3600,
            ),
        ),
        aws.lb.ListenerDefaultActionArgs(type="forward", order=2, target_group_arn=serving_tg.arn),
    ],
)
if domain and domain_cert_validated:
    # The ALB's own hostname keeps working (with its self-signed warning):
    # the listener picks the certificate by SNI.
    aws.lb.ListenerCertificate(
        f"{prefix}-https-alb-hostname-cert", listener_arn=https_listener.arn, certificate_arn=certificate.arn
    )

aws.lb.Listener(
    f"{prefix}-http",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[
        aws.lb.ListenerDefaultActionArgs(
            type="redirect",
            redirect=aws.lb.ListenerDefaultActionRedirectArgs(protocol="HTTPS", port="443", status_code="HTTP_301"),
        )
    ],
)

# ── ECS task + service ───────────────────────────────────────────────────────
service = None


def _container_definitions(args) -> str:
    param_arns, image_uri, log_group_name = args
    container = {
        "name": "app",
        "image": image_uri,
        "essential": True,
        "portMappings": [{"containerPort": 8080, "protocol": "tcp"}],
        "secrets": [{"name": key, "valueFrom": arn} for key, arn in sorted(param_arns.items())],
        "mountPoints": [{"sourceVolume": "data", "containerPath": "/app/data", "readOnly": False}],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {"awslogs-group": log_group_name, "awslogs-region": region, "awslogs-stream-prefix": "app"},
        },
        "linuxParameters": {"initProcessEnabled": True},  # needed by ECS Exec
        "stopTimeout": 30,
    }
    return json.dumps([container])

task_definition = aws.ecs.TaskDefinition(
    f"{prefix}-app",
    family=f"{prefix}-app",
    cpu=task_cpu,
    memory=task_memory,
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    runtime_platform=aws.ecs.TaskDefinitionRuntimePlatformArgs(
        operating_system_family="LINUX", cpu_architecture="X86_64"
    ),
    execution_role_arn=execution_role.arn,
    task_role_arn=task_role.arn,
    volumes=[
        aws.ecs.TaskDefinitionVolumeArgs(
            name="data",
            efs_volume_configuration=aws.ecs.TaskDefinitionVolumeEfsVolumeConfigurationArgs(
                file_system_id=data_fs.id,
                transit_encryption="ENABLED",
                authorization_config=aws.ecs.TaskDefinitionVolumeEfsVolumeConfigurationAuthorizationConfigArgs(
                    access_point_id=data_access_point.id, iam="ENABLED"
                ),
            ),
        )
    ],
    container_definitions=pulumi.Output.all(
        pulumi.Output.all(**{key: p.arn for key, p in env_params.items()}),
        image,
        log_group.name,
    ).apply(_container_definitions),
    tags=tags,
)

if serve_from == "fargate":
    service = aws.ecs.Service(
        f"{prefix}-app",
        name=f"{prefix}-app",
        cluster=cluster.arn,
        task_definition=task_definition.arn,
        desired_count=1,
        launch_type="FARGATE",
        platform_version="LATEST",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=[s.id for s in subnets], security_groups=[task_sg.id], assign_public_ip=True
        ),
        load_balancers=[
            aws.ecs.ServiceLoadBalancerArgs(target_group_arn=fargate_tg.arn, container_name="app", container_port=8080)
        ],
        # Single-writer SQLite on EFS: never run two tasks at once — a
        # deploy stops the old task before starting the new one.
        deployment_minimum_healthy_percent=0,
        deployment_maximum_percent=100,
        deployment_circuit_breaker=aws.ecs.ServiceDeploymentCircuitBreakerArgs(enable=True, rollback=True),
        health_check_grace_period_seconds=180,  # migrations + first start
        enable_execute_command=True,
        propagate_tags="SERVICE",
        wait_for_steady_state=False,
        tags=tags,
        opts=pulumi.ResourceOptions(
            depends_on=[https_listener, *mount_targets],
            # With the work-hours schedule, Application Auto Scaling owns
            # the task count; Pulumi must not reset it on every `up`.
            ignore_changes=["desiredCount"] if app_schedule_enabled else None,
        ),
    )

    if app_schedule_enabled:
        scalable = aws.appautoscaling.Target(
            f"{prefix}-app-scaling",
            service_namespace="ecs",
            scalable_dimension="ecs:service:DesiredCount",
            resource_id=pulumi.Output.all(cluster.name, service.name).apply(
                lambda names: f"service/{names[0]}/{names[1]}"
            ),
            min_capacity=0,
            max_capacity=1,
        )
        for action, cron, count in (("start", app_start_cron, 1), ("stop", app_stop_cron, 0)):
            aws.appautoscaling.ScheduledAction(
                f"{prefix}-app-{action}",
                name=f"{prefix}-app-{action}",
                service_namespace=scalable.service_namespace,
                scalable_dimension=scalable.scalable_dimension,
                resource_id=scalable.resource_id,
                schedule=cron,
                timezone=schedule_timezone,
                scalable_target_action=aws.appautoscaling.ScheduledActionScalableTargetActionArgs(
                    min_capacity=count, max_capacity=count
                ),
            )

# ── Outputs ──────────────────────────────────────────────────────────────────
profile = pulumi.Config("aws").get("profile") or "adlc"
pulumi.export(
    "url", f"https://{domain}" if domain and domain_cert_validated else alb.dns_name.apply(lambda dns: f"https://{dns}")
)
pulumi.export("albUrl", alb.dns_name.apply(lambda dns: f"https://{dns}"))
pulumi.export("loginDomain", user_pool_domain.domain.apply(lambda d: f"{d}.auth.{region}.amazoncognito.com"))
pulumi.export(
    "microsoftRedirectUri",  # the Redirect URI for the Entra ID app registration
    user_pool_domain.domain.apply(lambda d: f"https://{d}.auth.{region}.amazoncognito.com/oauth2/idpresponse"),
)
if domain_cert is not None:

    def _field(option, snake: str):
        """Typed output object in a real run, plain camelCase dict under mocks."""
        if isinstance(option, dict):
            camel = snake.split("_")[0] + "".join(w.title() for w in snake.split("_")[1:])
            return option.get(snake, option.get(camel))
        return getattr(option, snake)

    # The two CNAME records to add at the DNS host (OVH) for adlc:domain.
    pulumi.export(
        "dnsRecords",
        pulumi.Output.all(domain_cert.domain_validation_options, alb.dns_name).apply(
            lambda args: [
                {
                    "purpose": "certificate validation (keep it — ACM renews with it)",
                    "type": _field(args[0][0], "resource_record_type"),
                    "name": _field(args[0][0], "resource_record_name"),
                    "value": _field(args[0][0], "resource_record_value"),
                },
                {"purpose": "site address", "type": "CNAME", "name": f"{domain}.", "value": f"{args[1]}."},
            ]
        ),
    )
    pulumi.export("domainCertArn", domain_cert.arn)
pulumi.export("serveFrom", serve_from)
pulumi.export("cognitoUserPoolId", user_pool.id)
pulumi.export(
    "addUserCommand",
    user_pool.id.apply(
        lambda pool: f"aws cognito-idp admin-create-user --user-pool-id {pool} --username NAME@tkmind.net "
        f"--user-attributes Name=email,Value=NAME@tkmind.net Name=email_verified,Value=true --profile {profile}"
    ),
)
pulumi.export("efsId", data_fs.id)
pulumi.export("ecrRepositoryUrl", ecr_repo.repository_url)
pulumi.export("image", image)
pulumi.export("githubActionsRoleArn", github_role.arn)  # GitHub repo variable AWS_ROLE_ARN
pulumi.export("clusterName", cluster.name)
pulumi.export("logsCommand", log_group.name.apply(lambda g: f"aws logs tail {g} --follow --profile {profile}"))
if service is not None:
    pulumi.export("serviceName", service.name)
    pulumi.export(
        "deployCommand",
        pulumi.Output.all(cluster.name, service.name).apply(
            lambda n: f"aws ecs update-service --cluster {n[0]} --service {n[1]} --force-new-deployment "
            f"--query service.deployments[0].rolloutState --output text --profile {profile}"
        ),
    )
    pulumi.export(
        "shellCommand",
        cluster.name.apply(
            lambda c: f"aws ecs execute-command --cluster {c} --container app --interactive --command /bin/sh "
            f"--task (aws ecs list-tasks --cluster {c} --query taskArns[0] --output text --profile {profile}) "
            f"--profile {profile}"
        ),
    )
if ec2 is not None:
    ec2.export_outputs(profile)
