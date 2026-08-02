"""Re-export shared fail-soft raw tracer from ElaTool."""

from elatec_uid_tool.readonly_capture.raw_trace import (  # noqa: F401
    RawSerialTracer,
    decode_command,
)

__all__ = ["RawSerialTracer", "decode_command"]
