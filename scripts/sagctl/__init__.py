"""sagctl — engine that supplies the write operations SAG MCP (read-only) lacks.

Stdlib-only, Python 3.11+. No external package dependencies, so it can be
vendored easily into a container/agent host without a pip install. See
docs/SPEC.md (LOCKED SPEC v1) as the contract — every module here references
that spec's section numbers S1..S12.
"""

__version__ = "0.1.0"

# schema_version for assessment/manifest — bump when the data contract changes (S5, S1).
CONTRACT_VERSION = "1"
