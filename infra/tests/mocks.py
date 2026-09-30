"""
Pulumi mocks shared by the infra tests. A Pulumi program can only be
imported once per process, so test_stack.py runs the main configuration
in-process and snapshot.py runs other configurations in a subprocess.
"""

import pulumi

resources: list[tuple[str, str, dict]] = []  # (type, name, inputs)


class AdlcMocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        state = dict(args.inputs)
        rid = f"{args.name}-id"
        if args.typ == "aws:ebs/volume:Volume":
            rid = "vol-0123456789abcdef0"
        if args.typ == "aws:ec2/instance:Instance":
            state["privateIp"] = "10.40.0.25"
        if args.typ == "aws:lb/loadBalancer:LoadBalancer":
            state["dnsName"] = "adlc-prod-alb-123.eu-central-1.elb.amazonaws.com"
        if args.typ == "tls:index/privateKey:PrivateKey":
            state.update(privateKeyPem="PEM", privateKeyOpenssh="OPENSSH", publicKeyOpenssh="ssh-ed25519 AAAA")
        if args.typ == "tls:index/selfSignedCert:SelfSignedCert":
            state["certPem"] = "CERT"
        if args.typ == "random:index/randomString:RandomString":
            state["result"] = "abc123"
        if args.typ == "aws:cloudwatch/logGroup:LogGroup":
            state.setdefault("name", args.name)
        if args.typ in ("aws:ecs/cluster:Cluster", "aws:ecs/service:Service"):
            state.setdefault("name", args.name)
        if args.typ == "aws:acm/certificate:Certificate" and args.inputs.get("domainName"):
            state["domainValidationOptions"] = [
                {
                    "domainName": args.inputs["domainName"],
                    "resourceRecordName": f"_abc123.{args.inputs['domainName']}.",
                    "resourceRecordType": "CNAME",
                    "resourceRecordValue": "_def456.xyz.acm-validations.aws.",
                }
            ]
        if args.typ == "aws:acm/certificateValidation:CertificateValidation":
            state["certificateArn"] = args.inputs["certificateArn"]
        if args.typ == "aws:cognito/userPoolDomain:UserPoolDomain":
            state.setdefault("domain", args.inputs.get("domain"))
        if args.typ == "aws:ecr/repository:Repository":
            state["repositoryUrl"] = f"111111111111.dkr.ecr.eu-central-1.amazonaws.com/{args.inputs['name']}"
        state.setdefault("arn", f"arn:aws:mock:::{args.name}")
        resources.append((args.typ, args.name, dict(args.inputs)))
        return rid, state

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "aws:index/getAvailabilityZones:getAvailabilityZones":
            return {"names": ["eu-central-1a", "eu-central-1b", "eu-central-1c"], "zoneIds": ["a", "b", "c"]}
        if args.token == "aws:ssm/getParameter:getParameter":
            return {"name": args.args["name"], "value": "ami-0123456789", "type": "String"}
        return {}


def install(config: dict, secret_keys: list[str]) -> None:
    pulumi.runtime.set_mocks(AdlcMocks(), project="adlc", stack="prod", preview=False)
    pulumi.runtime.set_all_config(config, secret_keys=secret_keys)


BASE_CONFIG = {
    "aws:region": "eu-central-1",
    "adlc:openaiApiKey": "sk-test-not-real",
    "adlc:confluenceBaseUrl": "https://example.atlassian.net/wiki",
}
SECRET_KEYS = ["adlc:openaiApiKey"]
