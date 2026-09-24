"""
adlc_stack.py
ADLC on AWS, in one Control Tower member account:

  Internet ──HTTPS──> ALB (Cognito login, self-signed cert for now)
                        │ HTTP :80, from the ALB only
                        ▼
                      EC2 "app" — nginx + FastAPI (1 worker) + built frontend
                        │  data/ on a separate, protected EBS volume
                        │  (daily snapshots) so the instance is replaceable
                        │ HTTP :8000, from the app only
                        ▼
                      EC2 "embed" — g4dn GPU, Qwen3-VL embedding server,
                                    started/stopped on a work-hours schedule

No NAT gateway: both instances sit in public subnets with public IPs for
outbound traffic (OpenAI, GitHub, pip/npm, Hugging Face), but their security
groups accept nothing from the internet. Admin access is SSM Session
Manager — no SSH port. Secrets live in SSM Parameter Store (SecureString),
set from encrypted Pulumi config; the app server turns them into .env.
"""

import base64
import json
from pathlib import Path

import pulumi
import pulumi_aws as aws
import pulumi_random as random
import pulumi_tls as tls

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent

cfg = pulumi.Config("adlc")
stack = pulumi.get_stack()
region = aws.config.region
prefix = f"adlc-{stack}"
param_prefix = f"/adlc/{stack}"

github_repo = cfg.get("githubRepo") or "MennaSayedTKM/ADLC"
git_branch = cfg.get("gitBranch") or "main"
app_instance_type = cfg.get("appInstanceType") or "t3.large"
data_volume_gb = cfg.get_int("dataVolumeGb") or 50
snapshot_retain_count = cfg.get_int("snapshotRetainCount") or 14
vpc_cidr = cfg.get("vpcCidr") or "10.40.0.0/16"
embed_enabled = cfg.get_bool("embedEnabled")
embed_enabled = True if embed_enabled is None else embed_enabled
embed_instance_type = cfg.get("embedInstanceType") or "g4dn.xlarge"
embed_ami_parameter = (
    cfg.get("embedAmiParameter")
    or "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"
)
embed_schedule_enabled = cfg.get_bool("embedScheduleEnabled")
embed_schedule_enabled = True if embed_schedule_enabled is None else embed_schedule_enabled
embed_start_cron = cfg.get("embedStartCron") or "cron(0 8 ? * MON-FRI *)"
embed_stop_cron = cfg.get("embedStopCron") or "cron(0 19 ? * MON-FRI *)"
schedule_timezone = cfg.get("scheduleTimezone") or "Asia/Dubai"
login_session_hours = cfg.get_int("loginSessionHours") or 12

tags = {"Project": "ADLC", "Stack": stack, "ManagedBy": "pulumi"}


def _name(suffix: str) -> dict:
    return {**tags, "Name": f"{prefix}-{suffix}"}


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
app_sg = aws.ec2.SecurityGroup(f"{prefix}-app-sg", vpc_id=vpc.id, description="ADLC app server", tags=_name("app-sg"))
embed_sg = aws.ec2.SecurityGroup(
    f"{prefix}-embed-sg", vpc_id=vpc.id, description="ADLC embedding server", tags=_name("embed-sg")
)

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
    f"{prefix}-app-in-alb",
    security_group_id=app_sg.id,
    referenced_security_group_id=alb_sg.id,
    ip_protocol="tcp",
    from_port=80,
    to_port=80,
    description="nginx, from the ALB only",
)
aws.vpc.SecurityGroupIngressRule(
    f"{prefix}-embed-in-app",
    security_group_id=embed_sg.id,
    referenced_security_group_id=app_sg.id,
    ip_protocol="tcp",
    from_port=8000,
    to_port=8000,
    description="Embedding API, from the app server only",
)
# Outbound: the ALB reaches Cognito's token endpoint; instances reach OpenAI,
# GitHub, package mirrors, Hugging Face and AWS APIs.
for sg_name, sg in (("alb", alb_sg), ("app", app_sg), ("embed", embed_sg)):
    aws.vpc.SecurityGroupEgressRule(
        f"{prefix}-{sg_name}-out", security_group_id=sg.id, cidr_ipv4="0.0.0.0/0", ip_protocol="-1"
    )

# ── Secrets → SSM Parameter Store ────────────────────────────────────────────
# Every parameter under {param_prefix}/env/ becomes a line in the app's .env.
deploy_key = tls.PrivateKey(f"{prefix}-github-deploy-key", algorithm="ED25519")
aws.ssm.Parameter(
    f"{prefix}-github-deploy-key",
    name=f"{param_prefix}/github_deploy_key",
    type="SecureString",
    value=deploy_key.private_key_openssh,
    description="Read-only GitHub deploy key the app server clones the repo with",
    tags=tags,
)

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
env_params = []
for key, value in _env_secrets.items():
    if value is not None:
        env_params.append(
            aws.ssm.Parameter(
                f"{prefix}-env-{key.lower()}",
                name=f"{param_prefix}/env/{key}",
                type="SecureString",
                value=value,
                tags=tags,
            )
        )
for key, value in _env_plain.items():
    if value:
        env_params.append(
            aws.ssm.Parameter(
                f"{prefix}-env-{key.lower()}", name=f"{param_prefix}/env/{key}", type="String", value=value, tags=tags
            )
        )

# ── IAM ──────────────────────────────────────────────────────────────────────
def _assume_role(service: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}],
        }
    )


def _instance_profile(role_name: str, extra_policy: pulumi.Input[str] | None = None) -> aws.iam.InstanceProfile:
    role = aws.iam.Role(f"{prefix}-{role_name}-role", assume_role_policy=_assume_role("ec2.amazonaws.com"), tags=tags)
    aws.iam.RolePolicyAttachment(
        f"{prefix}-{role_name}-ssm-core",
        role=role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",  # Session Manager access
    )
    if extra_policy is not None:
        aws.iam.RolePolicy(f"{prefix}-{role_name}-policy", role=role.id, policy=extra_policy)
    return aws.iam.InstanceProfile(f"{prefix}-{role_name}-profile", role=role.name, tags=tags)


app_profile = _instance_profile(
    "app",
    json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                    "Resource": [
                        f"arn:aws:ssm:*:*:parameter{param_prefix}/*",
                        f"arn:aws:ssm:*:*:parameter{param_prefix}",
                    ],
                }
            ],
        }
    ),
)

# ── Embedding server (GPU) ───────────────────────────────────────────────────
embed_instance = None
embed_url = None
if embed_enabled:
    server_py = (_REPO / "embed_server" / "server.py").read_bytes()
    embed_requirements = (_REPO / "embed_server" / "requirements.txt").read_bytes()
    embed_user_data = (
        (_ROOT / "userdata" / "embed.sh")
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("__SERVER_PY_B64__", base64.encodebytes(server_py).decode())
        .replace("__REQUIREMENTS_B64__", base64.encodebytes(embed_requirements).decode())
    )
    embed_instance = aws.ec2.Instance(
        f"{prefix}-embed",
        ami=aws.ssm.get_parameter(name=embed_ami_parameter).value,
        instance_type=embed_instance_type,
        subnet_id=subnets[0].id,
        vpc_security_group_ids=[embed_sg.id],
        iam_instance_profile=_instance_profile("embed").name,
        user_data=embed_user_data,
        user_data_replace_on_change=True,  # stateless: a new server.py means a fresh box
        root_block_device=aws.ec2.InstanceRootBlockDeviceArgs(volume_size=100, volume_type="gp3", encrypted=True),
        metadata_options=aws.ec2.InstanceMetadataOptionsArgs(http_tokens="required"),
        tags=_name("embed"),
        # A newer AMI must not silently replace the instance on a later `pulumi up`.
        opts=pulumi.ResourceOptions(ignore_changes=["ami"]),
    )
    embed_url = embed_instance.private_ip.apply(lambda ip: f"http://{ip}:8000")
    env_params.append(
        aws.ssm.Parameter(
            f"{prefix}-env-embed_api_url",
            name=f"{param_prefix}/env/EMBED_API_URL",
            type="String",
            value=embed_url,
            tags=tags,
        )
    )

    if embed_schedule_enabled:
        scheduler_role = aws.iam.Role(
            f"{prefix}-embed-scheduler-role", assume_role_policy=_assume_role("scheduler.amazonaws.com"), tags=tags
        )
        aws.iam.RolePolicy(
            f"{prefix}-embed-scheduler-policy",
            role=scheduler_role.id,
            policy=embed_instance.arn.apply(
                lambda arn: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {"Effect": "Allow", "Action": ["ec2:StartInstances", "ec2:StopInstances"], "Resource": arn}
                        ],
                    }
                )
            ),
        )
        for action, cron in (("start", embed_start_cron), ("stop", embed_stop_cron)):
            aws.scheduler.Schedule(
                f"{prefix}-embed-{action}",
                description=f"{action.title()} the ADLC embedding GPU ({cron}, {schedule_timezone})",
                schedule_expression=cron,
                schedule_expression_timezone=schedule_timezone,
                flexible_time_window=aws.scheduler.ScheduleFlexibleTimeWindowArgs(mode="OFF"),
                target=aws.scheduler.ScheduleTargetArgs(
                    arn=f"arn:aws:scheduler:::aws-sdk:ec2:{action}Instances",
                    role_arn=scheduler_role.arn,
                    input=embed_instance.id.apply(lambda iid: json.dumps({"InstanceIds": [iid]})),
                ),
            )

# ── App server + persistent data volume ──────────────────────────────────────
data_volume = aws.ebs.Volume(
    f"{prefix}-data",
    availability_zone=subnets[0].availability_zone,
    size=data_volume_gb,
    type="gp3",
    encrypted=True,
    tags={**_name("data"), "Backup": f"{prefix}-daily"},
    # Holds the DB, FAISS index and client uploads: `pulumi destroy` must
    # never delete it. Unprotect deliberately if it really has to go.
    opts=pulumi.ResourceOptions(protect=True),
)

app_user_data = data_volume.id.apply(
    lambda volume_id: (_ROOT / "userdata" / "app.sh")
    .read_text(encoding="utf-8")
    .replace("\r\n", "\n")
    .replace("__REGION__", region)
    .replace("__PARAM_PREFIX__", param_prefix)
    .replace("__REPO__", github_repo)
    .replace("__BRANCH__", git_branch)
    .replace("__DATA_VOLUME_ID__", volume_id)
)

app_instance = aws.ec2.Instance(
    f"{prefix}-app",
    ami=aws.ssm.get_parameter(
        name="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    ).value,
    instance_type=app_instance_type,
    subnet_id=subnets[0].id,
    vpc_security_group_ids=[app_sg.id],
    iam_instance_profile=app_profile.name,
    user_data=app_user_data,
    root_block_device=aws.ec2.InstanceRootBlockDeviceArgs(volume_size=30, volume_type="gp3", encrypted=True),
    metadata_options=aws.ec2.InstanceMetadataOptionsArgs(http_tokens="required"),
    tags=_name("app"),
    opts=pulumi.ResourceOptions(ignore_changes=["ami"], depends_on=env_params),
)
aws.ec2.VolumeAttachment(
    f"{prefix}-data-attachment",
    device_name="/dev/sdf",
    volume_id=data_volume.id,
    instance_id=app_instance.id,
    stop_instance_before_detaching=True,
)

# Daily snapshots of the data volume.
dlm_role = aws.iam.Role(f"{prefix}-dlm-role", assume_role_policy=_assume_role("dlm.amazonaws.com"), tags=tags)
aws.iam.RolePolicyAttachment(
    f"{prefix}-dlm-policy",
    role=dlm_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole",
)
aws.dlm.LifecyclePolicy(
    f"{prefix}-data-snapshots",
    description=f"Daily snapshots of the ADLC {stack} data volume",
    execution_role_arn=dlm_role.arn,
    state="ENABLED",
    policy_details=aws.dlm.LifecyclePolicyPolicyDetailsArgs(
        resource_types=["VOLUME"],
        target_tags={"Backup": f"{prefix}-daily"},
        schedules=[
            aws.dlm.LifecyclePolicyPolicyDetailsScheduleArgs(
                name="daily",
                create_rule=aws.dlm.LifecyclePolicyPolicyDetailsScheduleCreateRuleArgs(
                    interval=24, interval_unit="HOURS", times="22:00"  # UTC = 02:00 Dubai
                ),
                retain_rule=aws.dlm.LifecyclePolicyPolicyDetailsScheduleRetainRuleArgs(count=snapshot_retain_count),
                copy_tags=True,
            )
        ],
    ),
    tags=tags,
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

user_pool = aws.cognito.UserPool(
    f"{prefix}-users",
    name=f"{prefix}-users",
    username_attributes=["email"],
    auto_verified_attributes=["email"],
    # Only an admin can add people — no public sign-up.
    admin_create_user_config=aws.cognito.UserPoolAdminCreateUserConfigArgs(allow_admin_create_user_only=True),
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
domain_suffix = random.RandomString(f"{prefix}-login-suffix", length=6, special=False, upper=False)
user_pool_domain = aws.cognito.UserPoolDomain(
    f"{prefix}-login",
    domain=domain_suffix.result.apply(lambda s: f"{prefix}-{s}"),
    user_pool_id=user_pool.id,
)
user_pool_client = aws.cognito.UserPoolClient(
    f"{prefix}-alb-client",
    name=f"{prefix}-alb",
    user_pool_id=user_pool.id,
    generate_secret=True,  # required by the ALB's authenticate-cognito action
    allowed_oauth_flows_user_pool_client=True,
    allowed_oauth_flows=["code"],
    allowed_oauth_scopes=["openid", "email"],
    supported_identity_providers=["COGNITO"],
    callback_urls=[alb.dns_name.apply(lambda dns: f"https://{dns}/oauth2/idpresponse")],
)

target_group = aws.lb.TargetGroup(
    f"{prefix}-app-tg",
    port=80,
    protocol="HTTP",
    target_type="instance",
    vpc_id=vpc.id,
    deregistration_delay=30,
    health_check=aws.lb.TargetGroupHealthCheckArgs(
        path="/api/health", matcher="200", interval=30, timeout=10, healthy_threshold=2, unhealthy_threshold=3
    ),
    tags=_name("app-tg"),
)
aws.lb.TargetGroupAttachment(f"{prefix}-app-tg-attachment", target_group_arn=target_group.arn, target_id=app_instance.id, port=80)

aws.lb.Listener(
    f"{prefix}-https",
    load_balancer_arn=alb.arn,
    port=443,
    protocol="HTTPS",
    ssl_policy="ELBSecurityPolicy-TLS13-1-2-2021-06",
    certificate_arn=certificate.arn,
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
        aws.lb.ListenerDefaultActionArgs(type="forward", order=2, target_group_arn=target_group.arn),
    ],
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

# ── Outputs ──────────────────────────────────────────────────────────────────
profile = pulumi.Config("aws").get("profile") or "adlc"
pulumi.export("url", alb.dns_name.apply(lambda dns: f"https://{dns}"))
pulumi.export("githubDeployPublicKey", deploy_key.public_key_openssh)
pulumi.export("cognitoUserPoolId", user_pool.id)
pulumi.export(
    "addUserCommand",
    user_pool.id.apply(
        lambda pool: f"aws cognito-idp admin-create-user --user-pool-id {pool} --username NAME@tkmind.net "
        f"--user-attributes Name=email,Value=NAME@tkmind.net Name=email_verified,Value=true --profile {profile}"
    ),
)
pulumi.export("appInstanceId", app_instance.id)
pulumi.export(
    "deployCommand",
    app_instance.id.apply(
        lambda iid: f"aws ssm send-command --instance-ids {iid} --document-name AWS-RunShellScript "
        f"--parameters commands=/usr/local/bin/adlc-deploy --comment \"ADLC deploy\" --profile {profile}"
    ),
)
pulumi.export(
    "shellCommand", app_instance.id.apply(lambda iid: f"aws ssm start-session --target {iid} --profile {profile}")
)
pulumi.export("dataVolumeId", data_volume.id)
if embed_instance is not None:
    pulumi.export("embedInstanceId", embed_instance.id)
    pulumi.export("embedApiUrl", embed_url)
