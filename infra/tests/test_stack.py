"""
Runs the whole Pulumi program under mocks — no AWS account or credentials
needed. Catches wrong resource arguments (pulumi-aws raises TypeError) and
checks the security-relevant wiring: who can reach what, where secrets go,
and that the bootstrap scripts are fully rendered.

Run from infra/:  venv\\Scripts\\python -m pytest tests
"""

import json
import sys
from pathlib import Path

import pulumi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_resources: list[tuple[str, str, dict]] = []  # (type, name, inputs)


class Mocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        state = dict(args.inputs)
        rid = f"{args.name}-id"
        if args.typ == "aws:ebs/volume:Volume":
            rid = "vol-0123456789abcdef0"
        if args.typ == "aws:ec2/instance:Instance":
            state["privateIp"] = "10.40.0.25"
            state["arn"] = f"arn:aws:ec2:eu-central-1:111111111111:instance/{rid}"
        if args.typ == "aws:lb/loadBalancer:LoadBalancer":
            state["dnsName"] = "adlc-prod-alb-123.eu-central-1.elb.amazonaws.com"
            state["arn"] = "arn:aws:elasticloadbalancing:eu-central-1:111111111111:loadbalancer/app/x/1"
        if args.typ == "tls:index/privateKey:PrivateKey":
            state.update(privateKeyPem="PEM", privateKeyOpenssh="OPENSSH", publicKeyOpenssh="ssh-ed25519 AAAA")
        if args.typ == "tls:index/selfSignedCert:SelfSignedCert":
            state["certPem"] = "CERT"
        if args.typ == "random:index/randomString:RandomString":
            state["result"] = "abc123"
        state.setdefault("arn", f"arn:aws:mock:::{args.name}")
        _resources.append((args.typ, args.name, dict(args.inputs)))
        return rid, state

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "aws:index/getAvailabilityZones:getAvailabilityZones":
            return {"names": ["eu-central-1a", "eu-central-1b", "eu-central-1c"], "zoneIds": ["a", "b", "c"]}
        if args.token == "aws:ssm/getParameter:getParameter":
            return {"name": args.args["name"], "value": "ami-0123456789", "type": "String"}
        return {}


pulumi.runtime.set_mocks(Mocks(), project="adlc", stack="prod", preview=False)
pulumi.runtime.set_all_config(
    {"aws:region": "eu-central-1", "adlc:openaiApiKey": "sk-test-not-real"},
    secret_keys=["adlc:openaiApiKey"],
)

import adlc_stack  # noqa: E402  (must import after mocks are set)


def _by_type(typ: str) -> list[tuple[str, dict]]:
    return [(name, inputs) for t, name, inputs in _resources if t == typ]


def _plain(value):
    """pulumi-aws marks some inputs (e.g. ssm.Parameter.value) secret; mocks
    then see Pulumi's secret wrapper {<sig>: <secret sig>, "value": ...}."""
    return value["value"] if isinstance(value, dict) and "value" in value else value


def _one(typ: str, name: str) -> dict:
    matches = [inputs for n, inputs in _by_type(typ) if n == name]
    assert len(matches) == 1, f"expected one {typ} named {name}, found {len(matches)}"
    return matches[0]


@pulumi.runtime.test
def test_program_builds_and_app_user_data_is_fully_rendered():
    def check(user_data):
        assert "__" not in user_data.replace("__pycache__", ""), "unrendered placeholder in app user-data"
        assert "\r" not in user_data
        assert 'DATA_VOLUME_ID="vol-0123456789abcdef0"' in user_data
        assert 'PARAM_PREFIX="/adlc/prod"' in user_data
        assert 'REPO="MennaSayedTKM/ADLC"' in user_data
        assert "sk-test-not-real" not in user_data  # secrets go via SSM, never user-data
        assert "--workers 1" in user_data  # single-writer SQLite + in-process FAISS

    return adlc_stack.app_instance.user_data.apply(check)


def test_embed_user_data_inlines_server_code():
    inputs = _one("aws:ec2/instance:Instance", "adlc-prod-embed")
    user_data = inputs["userData"]
    assert "__SERVER_PY_B64__" not in user_data and "__REQUIREMENTS_B64__" not in user_data
    assert inputs["userDataReplaceOnChange"] is True
    assert inputs["instanceType"] == "g4dn.xlarge"


def test_nothing_but_the_alb_is_reachable_from_the_internet():
    ingress = _by_type("aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule")
    open_to_world = sorted(name for name, i in ingress if i.get("cidrIpv4") == "0.0.0.0/0")
    assert open_to_world == ["adlc-prod-alb-in-443", "adlc-prod-alb-in-80"]
    app_in = _one("aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule", "adlc-prod-app-in-alb")
    embed_in = _one("aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule", "adlc-prod-embed-in-app")
    assert "referencedSecurityGroupId" in app_in and app_in["fromPort"] == 80
    assert "referencedSecurityGroupId" in embed_in and embed_in["fromPort"] == 8000
    assert not any(i.get("fromPort") == 22 for _, i in ingress)  # no SSH: Session Manager only


def test_https_listener_requires_cognito_login_before_forwarding():
    listener = _one("aws:lb/listener:Listener", "adlc-prod-https")
    actions = sorted(listener["defaultActions"], key=lambda a: a["order"])
    assert [a["type"] for a in actions] == ["authenticate-cognito", "forward"]
    http = _one("aws:lb/listener:Listener", "adlc-prod-http")
    assert http["defaultActions"][0]["type"] == "redirect"


def test_user_pool_is_invite_only_and_callback_matches_alb():
    pool = _one("aws:cognito/userPool:UserPool", "adlc-prod-users")
    assert pool["adminCreateUserConfig"]["allowAdminCreateUserOnly"] is True
    client = _one("aws:cognito/userPoolClient:UserPoolClient", "adlc-prod-alb-client")
    assert client["callbackUrls"] == ["https://adlc-prod-alb-123.eu-central-1.elb.amazonaws.com/oauth2/idpresponse"]
    assert client["generateSecret"] is True


def test_secrets_are_secure_strings_and_env_includes_embed_url():
    params = {i["name"]: i for _, i in _by_type("aws:ssm/parameter:Parameter")}
    assert params["/adlc/prod/env/OPENAI_API_KEY"]["type"] == "SecureString"
    assert params["/adlc/prod/github_deploy_key"]["type"] == "SecureString"
    assert _plain(params["/adlc/prod/env/EMBED_API_URL"]["value"]) == "http://10.40.0.25:8000"
    # optional secrets that weren't configured create no parameter
    assert "/adlc/prod/env/ANTHROPIC_API_KEY" not in params


def test_app_role_reads_only_this_stacks_parameters():
    policy = json.loads(_one("aws:iam/rolePolicy:RolePolicy", "adlc-prod-app-policy")["policy"])
    resources = policy["Statement"][0]["Resource"]
    assert all(r.startswith("arn:aws:ssm:*:*:parameter/adlc/prod") for r in resources)


def test_data_volume_is_encrypted_tagged_for_backup_and_snapshotted():
    volume = _one("aws:ebs/volume:Volume", "adlc-prod-data")
    assert volume["encrypted"] is True
    assert volume["tags"]["Backup"] == "adlc-prod-daily"
    dlm = _one("aws:dlm/lifecyclePolicy:LifecyclePolicy", "adlc-prod-data-snapshots")
    assert dlm["policyDetails"]["targetTags"] == {"Backup": "adlc-prod-daily"}


def test_gpu_schedule_starts_and_stops_in_dubai_time():
    schedules = dict(_by_type("aws:scheduler/schedule:Schedule"))
    assert set(schedules) == {"adlc-prod-embed-start", "adlc-prod-embed-stop"}
    for action, s in (("start", schedules["adlc-prod-embed-start"]), ("stop", schedules["adlc-prod-embed-stop"])):
        assert s["scheduleExpressionTimezone"] == "Asia/Dubai"
        assert s["target"]["arn"] == f"arn:aws:scheduler:::aws-sdk:ec2:{action}Instances"
