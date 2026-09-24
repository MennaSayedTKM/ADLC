"""Pulumi entry point — all resources are declared in adlc_stack.py so the
tests in tests/ can import the same program under Pulumi mocks."""

import adlc_stack  # noqa: F401
