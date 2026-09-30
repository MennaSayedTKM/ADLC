"""
Runs the whole Pulumi program under mocks — no AWS account or credentials
needed. Catches wrong resource arguments (pulumi-aws raises TypeError) and
checks the security-relevant wiring: who can reach what, where secrets go,
and how the Fargate service is set up.

This module imports the program once, in the "cutover" configuration:
Fargate serving traffic, the legacy EC2 server still present, work-hours
schedule on, image from the stack's ECR repository. Other configurations
are checked in test_stages.py (separate processes).

Run from infra/:  venv\\Scripts\\python -m pytest tests
"""

import json
import sys
from pathlib import Path

import pulumi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mocks  # noqa: E402

IMAGE = "111111111111.dkr.ecr.eu-central-1.amazonaws.com/adlc:latest"
mocks.install(
    {
        **mocks.BASE_CONFIG,
        "adlc:serveFrom": "fargate",
        "adlc:ec2AppEnabled": "true",
        "adlc:appScheduleEnabled": "true",
        "adlc:githubOwnerId": "295564551",
        "adlc:githubRepoId": "1385264226",
        "adlc:domain": "adlc.tkmind.net",
        "adlc:domainCertValidated": "true",
        "adlc:entraTenantId": "11111111-2222-3333-4444-555555555555",
        "adlc:entraClientId": "66666666-7777-8888-9999-000000000000",
        "adlc:entraClientSecret": "entra-secret-not-real",
    },
    mocks.SECRET_KEYS + ["adlc:entraClientSecret"],
)

import adlc_stack  # noqa: E402  (must import after mocks are set)


def _by_type(typ: str) -> list[tuple[str, dict]]:
    return [(name, inputs) for t, name, inputs in mocks.resources if t == typ]


def _one(typ: str, name: str) -> dict:
    matches = [inputs for n, inputs in _by_type(typ) if n == name]
    assert len(matches) == 1, f"expected one {typ} named {name}, found {len(matches)}"
    return matches[0]


@pulumi.runtime.test
def test_program_builds():
    return adlc_stack.alb.arn.apply(lambda arn: arn is not None)


def test_descriptions_use_only_characters_aws_accepts():
    # IAM and EC2 reject descriptions outside Latin-1 (e.g. an em dash) at
    # create time — which the mocks otherwise wouldn't catch.
    for typ, name, inputs in mocks.resources:
        text = inputs.get("description")
        if isinstance(text, str):
            assert all(ch in "\t\n\r" or 0x20 <= ord(ch) <= 0x7E or 0xA1 <= ord(ch) <= 0xFF for ch in text), (
                f"{typ} {name}: {text!r}"
            )


def test_container_definition():
    task = _one("aws:ecs/taskDefinition:TaskDefinition", "adlc-prod-app")
    assert task["requiresCompatibilities"] == ["FARGATE"]
    assert (task["cpu"], task["memory"]) == ("1024", "4096")
    (container,) = json.loads(task["containerDefinitions"])
    assert container["image"] == IMAGE
    assert container["portMappings"] == [{"containerPort": 8080, "protocol": "tcp"}]
    assert container["mountPoints"][0]["containerPath"] == "/app/data"
    assert "repositoryCredentials" not in container  # ECR: pulled with the execution role, no stored token
    # every secret comes from this stack's SSM parameters, never inline
    secrets = {s["name"]: s["valueFrom"] for s in container["secrets"]}
    assert set(secrets) == {"OPENAI_API_KEY", "CONFLUENCE_BASE_URL"}
    assert "environment" not in container
    assert "sk-test-not-real" not in task["containerDefinitions"]

    (volume,) = task["volumes"]
    efs = volume["efsVolumeConfiguration"]
    assert efs["transitEncryption"] == "ENABLED"
    assert efs["authorizationConfig"]["iam"] == "ENABLED"


def test_service_runs_exactly_one_task_behind_the_alb():
    service = _one("aws:ecs/service:Service", "adlc-prod-app")
    assert service["launchType"] == "FARGATE"
    assert service["desiredCount"] == 1
    # single-writer SQLite on EFS: the old task stops before the new one starts
    assert service["deploymentMinimumHealthyPercent"] == 0
    assert service["deploymentMaximumPercent"] == 100
    assert service["deploymentCircuitBreaker"] == {"enable": True, "rollback": True}
    assert service["networkConfiguration"]["assignPublicIp"] is True
    assert service["loadBalancers"][0]["containerPort"] == 8080


def test_https_listener_logs_in_then_forwards_to_fargate():
    listener = _one("aws:lb/listener:Listener", "adlc-prod-https")
    actions = sorted(listener["defaultActions"], key=lambda a: a["order"])
    assert [a["type"] for a in actions] == ["authenticate-cognito", "forward"]
    assert actions[1]["targetGroupArn"] == "arn:aws:mock:::adlc-prod-fargate-tg"
    assert _one("aws:lb/listener:Listener", "adlc-prod-http")["defaultActions"][0]["type"] == "redirect"


def test_custom_domain_serves_the_validated_acm_certificate():
    cert = _one("aws:acm/certificate:Certificate", "adlc-prod-domain-cert")
    assert (cert["domainName"], cert["validationMethod"]) == ("adlc.tkmind.net", "DNS")
    listener = _one("aws:lb/listener:Listener", "adlc-prod-https")
    assert listener["certificateArn"] == "arn:aws:mock:::adlc-prod-domain-cert"
    # the ALB's own hostname still gets its (self-signed) certificate via SNI
    extra = _one("aws:lb/listenerCertificate:ListenerCertificate", "adlc-prod-https-alb-hostname-cert")
    assert extra["certificateArn"] == "arn:aws:mock:::adlc-prod-cert"
    client = _one("aws:cognito/userPoolClient:UserPoolClient", "adlc-prod-alb-client")
    assert client["callbackUrls"] == [
        "https://adlc-prod-alb-123.eu-central-1.elb.amazonaws.com/oauth2/idpresponse",
        "https://adlc.tkmind.net/oauth2/idpresponse",
    ]


def test_self_sign_up_is_on_but_gated_to_company_email():
    pool = _one("aws:cognito/userPool:UserPool", "adlc-prod-users")
    assert pool["adminCreateUserConfig"]["allowAdminCreateUserOnly"] is False
    assert pool["autoVerifiedAttributes"] == ["email"]  # sign-up confirms by emailed code
    assert pool["lambdaConfig"]["preSignUp"] == "arn:aws:mock:::adlc-prod-pre-signup"
    fn = _one("aws:lambda/function:Function", "adlc-prod-pre-signup")
    assert fn["environment"]["variables"] == {"ALLOWED_EMAIL_DOMAINS": "tkmind.net"}
    assert fn["handler"] == "pre_signup.handler"
    permission = _one("aws:lambda/permission:Permission", "adlc-prod-pre-signup-invoke")
    assert permission["principal"] == "cognito-idp.amazonaws.com"
    assert permission["sourceArn"] == "arn:aws:mock:::adlc-prod-users"  # only this user pool may invoke it


def test_sign_in_with_microsoft_uses_the_tkmind_tenant():
    idp = _one("aws:cognito/identityProvider:IdentityProvider", "adlc-prod-microsoft")
    assert (idp["providerName"], idp["providerType"]) == ("Microsoft", "OIDC")
    details = idp["providerDetails"]
    # the map holds the client secret, so Pulumi marks the whole map secret
    details = details.get("value", details)
    assert details["client_secret"] == "entra-secret-not-real"
    assert details["oidc_issuer"] == "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
    assert idp["attributeMapping"]["email"] == "email"
    client = _one("aws:cognito/userPoolClient:UserPoolClient", "adlc-prod-alb-client")
    assert client["supportedIdentityProviders"] == ["COGNITO", "Microsoft"]


def test_nothing_but_the_alb_is_reachable_from_the_internet():
    ingress = dict(_by_type("aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule"))
    open_to_world = sorted(n for n, i in ingress.items() if i.get("cidrIpv4") == "0.0.0.0/0")
    assert open_to_world == ["adlc-prod-alb-in-443", "adlc-prod-alb-in-80"]
    assert ingress["adlc-prod-task-in-alb"]["fromPort"] == 8080
    assert ingress["adlc-prod-efs-in-task"]["fromPort"] == 2049
    assert not any(i.get("fromPort") == 22 for i in ingress.values())  # no SSH anywhere


def test_efs_is_encrypted_backed_up_and_owned_by_the_container_user():
    fs = _one("aws:efs/fileSystem:FileSystem", "adlc-prod-data-fs")
    assert fs["encrypted"] is True
    assert _one("aws:efs/backupPolicy:BackupPolicy", "adlc-prod-data-fs-backup")["backupPolicy"]["status"] == "ENABLED"
    ap = _one("aws:efs/accessPoint:AccessPoint", "adlc-prod-data-ap")
    assert ap["posixUser"] == {"uid": 1000, "gid": 1000}  # matches the Dockerfile's user
    assert len(_by_type("aws:efs/mountTarget:MountTarget")) == 2


def test_task_role_only_gets_cohere_embeddings_its_efs_and_ecs_exec():
    policy = json.loads(_one("aws:iam/rolePolicy:RolePolicy", "adlc-prod-task-policy")["policy"])
    bedrock, efs, exec_ = policy["Statement"]
    assert bedrock["Action"] == "bedrock:InvokeModel"
    assert all("cohere.embed-v4" in r for r in bedrock["Resource"])
    assert efs["Resource"] == "arn:aws:mock:::adlc-prod-data-fs"
    assert "elasticfilesystem:AccessPointArn" in efs["Condition"]["StringEquals"]
    assert all(a.startswith("ssmmessages:") for a in exec_["Action"])


def test_execution_role_reads_only_this_stacks_secrets():
    policy = json.loads(_one("aws:iam/rolePolicy:RolePolicy", "adlc-prod-task-exec-policy")["policy"])
    (ssm,) = policy["Statement"]
    assert ssm["Resource"] == ["arn:aws:ssm:*:*:parameter/adlc/prod/env/*"]
    assert not _by_type("aws:secretsmanager/secret:Secret")  # no registry token to store


def test_ecr_repository_scans_images_and_expires_old_ones():
    repo = _one("aws:ecr/repository:Repository", "adlc-prod-ecr")
    assert repo["name"] == "adlc"
    assert repo["imageScanningConfiguration"] == {"scanOnPush": True}
    rules = json.loads(_one("aws:ecr/lifecyclePolicy:LifecyclePolicy", "adlc-prod-ecr-lifecycle")["policy"])["rules"]
    assert {r["selection"]["tagStatus"] for r in rules} == {"untagged", "any"}
    # the registry-level config overrides scanOnPush — it must actually scan this repo
    (rule,) = _one("aws:ecr/registryScanningConfiguration:RegistryScanningConfiguration", "adlc-prod-ecr-scanning")["rules"]
    assert rule["scanFrequency"] == "SCAN_ON_PUSH"
    assert rule["repositoryFilters"] == [{"filter": "adlc", "filterType": "WILDCARD"}]


def test_github_actions_role_trusts_only_this_repos_main_branch():
    oidc = _one("aws:iam/openIdConnectProvider:OpenIdConnectProvider", "adlc-prod-github-oidc")
    assert oidc["url"] == "https://token.actions.githubusercontent.com"
    trust = json.loads(_one("aws:iam/role:Role", "adlc-prod-github-actions-role")["assumeRolePolicy"])
    conditions = trust["Statement"][0]["Condition"]["StringEquals"]
    # exact matches only (StringEquals, no wildcards), including GitHub's
    # immutable-ID form of the subject
    assert conditions["token.actions.githubusercontent.com:sub"] == [
        "repo:MennaSayedTKM/ADLC:ref:refs/heads/main",
        "repo:MennaSayedTKM@295564551/ADLC@1385264226:ref:refs/heads/main",
    ]
    assert conditions["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"


def test_github_actions_role_can_only_push_this_image_and_redeploy_this_cluster():
    policy = json.loads(_one("aws:iam/rolePolicy:RolePolicy", "adlc-prod-github-actions-policy")["policy"])
    token, push, deploy = policy["Statement"]
    assert token["Action"] == "ecr:GetAuthorizationToken"  # account-wide by design; grants no repo access
    assert push["Resource"] == "arn:aws:mock:::adlc-prod-ecr"
    assert "ecr:DeleteRepository" not in push["Action"] and "ecr:BatchDeleteImage" not in push["Action"]
    assert deploy["Action"] == ["ecs:UpdateService", "ecs:DescribeServices"]
    assert deploy["Resource"] == "arn:aws:ecs:eu-central-1:*:service/adlc-prod/*"


def test_work_hours_schedule_scales_between_zero_and_one_task():
    target = _one("aws:appautoscaling/target:Target", "adlc-prod-app-scaling")
    assert (target["minCapacity"], target["maxCapacity"]) == (0, 1)
    actions = dict(_by_type("aws:appautoscaling/scheduledAction:ScheduledAction"))
    assert actions["adlc-prod-app-start"]["scalableTargetAction"] == {"minCapacity": 1, "maxCapacity": 1}
    assert actions["adlc-prod-app-stop"]["scalableTargetAction"] == {"minCapacity": 0, "maxCapacity": 0}
    assert all(a["timezone"] == "Asia/Dubai" for a in actions.values())


def test_legacy_ec2_can_reach_efs_for_the_data_copy_and_keeps_its_protected_volume():
    ingress = dict(_by_type("aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule"))
    assert ingress["adlc-prod-efs-in-app"]["fromPort"] == 2049
    assert _one("aws:ebs/volume:Volume", "adlc-prod-data")["encrypted"] is True
    assert len(_by_type("aws:ec2/instance:Instance")) == 1
    # the GPU embedding server is gone for good (Bedrock replaced it)
    assert not any("embed" in n for t, n, _ in mocks.resources if t == "aws:ec2/instance:Instance")
