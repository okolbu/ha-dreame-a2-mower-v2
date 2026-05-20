"""Schedule wire format — re-export shim (B2a split into decode/encode).

Decode lives in schedule_decode.py, encode in schedule_encode.py. This shim
preserves the `protocol.schedule` import path for existing callers
(coordinator/_writes.py, cloud_client/_fetchers.py, tests).
"""
from __future__ import annotations

from .schedule_decode import (
    _decode_blob,
    _decode_one_record,
    parse_schedule_batch,
)
from .schedule_encode import (
    build_schedule_set_value,
    encode_schedule_blob,
)

__all__ = [
    "_decode_blob",
    "_decode_one_record",
    "parse_schedule_batch",
    "build_schedule_set_value",
    "encode_schedule_blob",
]
