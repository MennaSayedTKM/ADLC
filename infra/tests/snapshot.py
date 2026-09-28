"""
Runs adlc_stack.py under mocks with the config given as JSON on argv[1] and
prints the created resources as JSON — used by test_stages.py to check
configurations other than the one test_stack.py imports in-process.
Exit code 3 + the message on stderr if the program raises.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pulumi  # noqa: E402

import mocks  # noqa: E402

mocks.install(json.loads(sys.argv[1]), mocks.SECRET_KEYS)


@pulumi.runtime.test
def run():
    import adlc_stack  # noqa: F401

    return adlc_stack.alb.arn.apply(lambda _: None)


try:
    run()
except Exception as e:  # noqa: BLE001 — report config errors to the caller
    print(str(e), file=sys.stderr)
    sys.exit(3)

print(json.dumps([{"type": t, "name": n, "inputs": i} for t, n, i in mocks.resources], default=str))
