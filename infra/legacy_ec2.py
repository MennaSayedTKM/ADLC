"""
legacy_ec2.py
The original EC2 deployment of the app (nginx + FastAPI on Ubuntu, data/ on a
protected EBS volume), kept only while moving to ECS Fargate:

  adlc:ec2AppEnabled=true         the server keeps running (and may serve
                                  traffic with adlc:serveFrom=ec2); it can
                                  also reach EFS for the one-time data copy
  adlc:ec2AppEnabled=false        server, role, deploy key and target group
                                  are removed
  adlc:keepLegacyDataVolume=true  the EBS data volume stays (protected) until
                                  it is deliberately deleted

Resource names are unchanged from the original single-file stack so Pulumi
keeps managing the existing resources instead of recreating them.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pulumi
import pulumi_aws as aws
import pulumi_tls as tls

_ROOT = Path(__file__).resolve().parent


@dataclass
class LegacyEc2:
    data_volume: aws.ebs.Volume
    instance: Optional[aws.ec2.Instance] = None
    target_group: Optional[aws.lb.TargetGroup] = None
    deploy_key: Optional[tls.PrivateKey] = None

    def export_outputs(self, profile: str) -> None:
        pulumi.export("legacyDataVolumeId", self.data_volume.id)
        if self.instance is None:
            return
        pulumi.export("ec2InstanceId", self.instance.id)
        pulumi.export("githubDeployPublicKey", self.deploy_key.public_key_openssh)
        pulumi.export(
            "ec2DeployCommand",
            self.instance.id.apply(
                lambda iid: f"aws ssm send-command --instance-ids {iid} --document-name AWS-RunShellScript "
                f"--parameters commands=/usr/local/bin/adlc-deploy --comment \"ADLC deploy\" --profile {profile}"
            ),
        )
        pulumi.export(
            "ec2ShellCommand", self.instance.id.apply(lambda iid: f"aws ssm start-session --target {iid} --profile {profile}")
        )


def build_legacy_ec2(
    *,
    prefix: str,
    stack: str,
    region: str,
    param_prefix: str,
    tags: dict,
    name: Callable[[str], dict],
    assume_role: Callable[[str], str],
    vpc: aws.ec2.Vpc,
    subnet: aws.ec2.Subnet,
    alb_sg: aws.ec2.SecurityGroup,
    efs_sg: aws.ec2.SecurityGroup,
    env_params: list,
    bedrock_statement: dict,
    instance_enabled: bool,
    github_repo: str,
    git_branch: str,
    instance_type: str,
    data_volume_gb: int,
    snapshot_retain_count: int,
) -> LegacyEc2:
    data_volume = aws.ebs.Volume(
        f"{prefix}-data",
        availability_zone=subnet.availability_zone,
        size=data_volume_gb,
        type="gp3",
        encrypted=True,
        tags={**name("data"), "Backup": f"{prefix}-daily"},
        # Held the DB, FAISS index and client uploads before the move to EFS:
        # `pulumi destroy` must never delete it by accident.
        opts=pulumi.ResourceOptions(protect=True),
    )
    legacy = LegacyEc2(data_volume=data_volume)
    if not instance_enabled:
        return legacy

    app_sg = aws.ec2.SecurityGroup(f"{prefix}-app-sg", vpc_id=vpc.id, description="ADLC app server", tags=name("app-sg"))
    aws.vpc.SecurityGroupIngressRule(
        f"{prefix}-app-in-alb",
        security_group_id=app_sg.id,
        referenced_security_group_id=alb_sg.id,
        ip_protocol="tcp",
        from_port=80,
        to_port=80,
        description="nginx, from the ALB only",
    )
    aws.vpc.SecurityGroupEgressRule(f"{prefix}-app-out", security_group_id=app_sg.id, cidr_ipv4="0.0.0.0/0", ip_protocol="-1")
    aws.vpc.SecurityGroupIngressRule(  # one-time copy of data/ from EBS to EFS
        f"{prefix}-efs-in-app",
        security_group_id=efs_sg.id,
        referenced_security_group_id=app_sg.id,
        ip_protocol="tcp",
        from_port=2049,
        to_port=2049,
        description="NFS, from the legacy EC2 app server (data migration)",
    )

    deploy_key = tls.PrivateKey(f"{prefix}-github-deploy-key", algorithm="ED25519")
    aws.ssm.Parameter(
        f"{prefix}-github-deploy-key",
        name=f"{param_prefix}/github_deploy_key",
        type="SecureString",
        value=deploy_key.private_key_openssh,
        description="Read-only GitHub deploy key the app server clones the repo with",
        tags=tags,
    )

    role = aws.iam.Role(f"{prefix}-app-role", assume_role_policy=assume_role("ec2.amazonaws.com"), tags=tags)
    aws.iam.RolePolicyAttachment(
        f"{prefix}-app-ssm-core",
        role=role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",  # Session Manager access
    )
    aws.iam.RolePolicy(
        f"{prefix}-app-policy",
        role=role.id,
        policy=json.dumps(
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
                    },
                    bedrock_statement,
                ],
            }
        ),
    )
    profile = aws.iam.InstanceProfile(f"{prefix}-app-profile", role=role.name, tags=tags)

    user_data = data_volume.id.apply(
        lambda volume_id: (_ROOT / "userdata" / "app.sh")
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("__REGION__", region)
        .replace("__PARAM_PREFIX__", param_prefix)
        .replace("__REPO__", github_repo)
        .replace("__BRANCH__", git_branch)
        .replace("__DATA_VOLUME_ID__", volume_id)
    )
    instance = aws.ec2.Instance(
        f"{prefix}-app",
        ami=aws.ssm.get_parameter(
            name="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
        ).value,
        instance_type=instance_type,
        subnet_id=subnet.id,
        vpc_security_group_ids=[app_sg.id],
        iam_instance_profile=profile.name,
        user_data=user_data,
        root_block_device=aws.ec2.InstanceRootBlockDeviceArgs(volume_size=30, volume_type="gp3", encrypted=True),
        metadata_options=aws.ec2.InstanceMetadataOptionsArgs(http_tokens="required"),
        tags=name("app"),
        opts=pulumi.ResourceOptions(ignore_changes=["ami"], depends_on=env_params),
    )
    aws.ec2.VolumeAttachment(
        f"{prefix}-data-attachment",
        device_name="/dev/sdf",
        volume_id=data_volume.id,
        instance_id=instance.id,
        stop_instance_before_detaching=True,
    )

    dlm_role = aws.iam.Role(f"{prefix}-dlm-role", assume_role_policy=assume_role("dlm.amazonaws.com"), tags=tags)
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
        tags=name("app-tg"),
    )
    aws.lb.TargetGroupAttachment(
        f"{prefix}-app-tg-attachment", target_group_arn=target_group.arn, target_id=instance.id, port=80
    )

    legacy.instance = instance
    legacy.target_group = target_group
    legacy.deploy_key = deploy_key
    return legacy
