"""
The migration stages other than the cutover configuration in test_stack.py.
Each runs the program in its own process (tests/snapshot.py), because a
Pulumi program can only be imported once per process.
"""

import json
import subprocess
import sys
from pathlib import Path

from mocks import BASE_CONFIG

_SNAPSHOT = Path(__file__).resolve().parent / "snapshot.py"


def _run(config: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SNAPSHOT), json.dumps({**BASE_CONFIG, **config})],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _resources(config: dict) -> list[dict]:
    result = _run(config)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _names(resources: list[dict], typ: str) -> set[str]:
    return {r["name"] for r in resources if r["type"] == typ}


def test_stage_1_ec2_still_serving_while_efs_is_prepared():
    res = _resources({"adlc:serveFrom": "ec2", "adlc:ec2AppEnabled": "true"})
    assert _names(res, "aws:ec2/instance:Instance") == {"adlc-prod-app"}
    assert _names(res, "aws:efs/fileSystem:FileSystem") == {"adlc-prod-data-fs"}
    assert "adlc-prod-efs-in-app" in _names(res, "aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule")
    assert not _names(res, "aws:ecs/service:Service")  # nothing on Fargate yet
    https = next(r for r in res if r["name"] == "adlc-prod-https")
    forward = next(a for a in https["inputs"]["defaultActions"] if a["type"] == "forward")
    assert forward["targetGroupArn"] == "arn:aws:mock:::adlc-prod-app-tg"


def test_final_stage_no_ec2_only_the_protected_old_volume_remains():
    res = _resources({"adlc:serveFrom": "fargate", "adlc:ec2AppEnabled": "false"})
    assert not _names(res, "aws:ec2/instance:Instance")
    assert not _names(res, "aws:lb/targetGroup:TargetGroup") - {"adlc-prod-fargate-tg"}
    assert _names(res, "aws:ebs/volume:Volume") == {"adlc-prod-data"}
    assert _names(res, "aws:ecs/service:Service") == {"adlc-prod-app"}
    assert "adlc-prod-efs-in-app" not in _names(res, "aws:vpc/securityGroupIngressRule:SecurityGroupIngressRule")


def test_after_old_volume_is_released_nothing_legacy_remains():
    res = _resources({"adlc:serveFrom": "fargate", "adlc:ec2AppEnabled": "false", "adlc:keepLegacyDataVolume": "false"})
    assert not _names(res, "aws:ebs/volume:Volume")
    assert not _names(res, "aws:dlm/lifecyclePolicy:LifecyclePolicy")


def test_image_can_be_pinned_to_a_specific_build():
    res = _resources({"adlc:serveFrom": "fargate", "adlc:imageTag": "3f2a1bc"})
    task = next(r for r in res if r["type"] == "aws:ecs/taskDefinition:TaskDefinition")
    image = json.loads(task["inputs"]["containerDefinitions"])[0]["image"]
    assert image == "111111111111.dkr.ecr.eu-central-1.amazonaws.com/adlc:3f2a1bc"


def test_misconfigurations_are_refused():
    no_server = _run({"adlc:serveFrom": "ec2", "adlc:ec2AppEnabled": "false"})
    assert no_server.returncode == 3 and "nothing would serve traffic" in no_server.stderr
    typo = _run({"adlc:serveFrom": "lambda"})
    assert typo.returncode == 3 and "must be 'ec2' or 'fargate'" in typo.stderr
