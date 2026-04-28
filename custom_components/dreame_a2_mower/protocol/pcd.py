"""Minimal PCD v0.7 parser — just enough for the g2408 LiDAR blob.

PCD (Point Cloud Data) is the PCL reference format and what the mower
uploads. We only need the single shape the firmware emits:

    VERSION 0.7
    FIELDS x y z rgb   (or subset — rgb is optional)
    SIZE 4 4 4 4
    TYPE F F F U       (floats + packed u32 rgb)
    COUNT 1 1 1 1
    WIDTH <N>
    HEIGHT 1           (unorganised cloud)
    VIEWPOINT 0 0 0 1 0 0 0
    POINTS <N>
    DATA binary

ASCII-PCD and organised (height > 1) clouds are not supported — the
firmware never emits them, and supporting them here would only add
untested paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

import numpy as np


class PCDHeaderError(ValueError):
    """Raised when a PCD stream has a missing/malformed header."""


REQUIRED_KEYS = ("VERSION", "FIELDS", "SIZE", "TYPE", "COUNT", "WIDTH", "HEIGHT", "POINTS", "DATA")


@dataclass
class PCDHeader:
    version: str
    fields: list[str]
    sizes: list[int]
    types: list[str]
    counts: list[int]
    width: int
    height: int
    points: int
    data: str
    viewpoint: list[float] = field(default_factory=list)


@dataclass
class PointCloud:
    xyz: np.ndarray         # shape (N, 3) float32
    rgb: np.ndarray         # shape (N, 3) uint8 — zeros when file had no rgb
    header: PCDHeader
    bytes_per_point: int


def parse_pcd_header(data: bytes) -> Tuple[PCDHeader, int]:
    """Parse the ASCII header and return ``(header, body_offset)``.

    ``body_offset`` is the byte index of the first point after the final
    ``DATA <format>\n`` line — ready for ``numpy.frombuffer``.
    """
    # Find the end of the header (the byte after the newline following "DATA …").
    data_idx = data.find(b"DATA ")
    if data_idx < 0:
        raise PCDHeaderError("PCD stream has no DATA line")
    nl = data.find(b"\n", data_idx)
    if nl < 0:
        raise PCDHeaderError("PCD DATA line not newline-terminated")
    header_bytes = data[: nl + 1]

    parsed: dict[str, str] = {}
    for raw_line in header_bytes.split(b"\n"):
        line = raw_line.decode("ascii", errors="replace").strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        parsed[key.upper()] = rest.strip()

    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        raise PCDHeaderError(f"PCD header missing keys: {missing}")

    fields = parsed["FIELDS"].split()
    sizes = [int(s) for s in parsed["SIZE"].split()]
    types = parsed["TYPE"].split()
    counts = [int(c) for c in parsed["COUNT"].split()]
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PCDHeaderError("FIELDS/SIZE/TYPE/COUNT arity mismatch")
    for xyz in ("x", "y", "z"):
        if xyz not in fields:
            raise PCDHeaderError(f"required field {xyz!r} missing")

    header = PCDHeader(
        version=parsed["VERSION"],
        fields=fields,
        sizes=sizes,
        types=types,
        counts=counts,
        width=int(parsed["WIDTH"]),
        height=int(parsed["HEIGHT"]),
        points=int(parsed["POINTS"]),
        data=parsed["DATA"].lower(),
        viewpoint=[float(v) for v in parsed.get("VIEWPOINT", "").split()],
    )
    return header, nl + 1


def parse_pcd(data: bytes) -> PointCloud:
    """Full parse — header plus body. Raises ``PCDHeaderError`` on any
    format this helper does not support."""
    header, body_offset = parse_pcd_header(data)
    if header.data != "binary":
        raise PCDHeaderError(f"only DATA=binary is supported, got {header.data!r}")

    bytes_per_point = sum(s * c for s, c in zip(header.sizes, header.counts))
    body = data[body_offset : body_offset + bytes_per_point * header.points]

    dtype_parts = []
    for name, sz, tp, cnt in zip(header.fields, header.sizes, header.types, header.counts):
        if cnt != 1:
            raise PCDHeaderError(f"COUNT>1 not supported (field {name!r})")
        if tp == "F" and sz == 4:
            np_dtype = "<f4"
        elif tp == "U" and sz == 4:
            np_dtype = "<u4"
        elif tp == "I" and sz == 4:
            np_dtype = "<i4"
        else:
            raise PCDHeaderError(f"unsupported TYPE/SIZE combo: {tp}/{sz} for {name!r}")
        dtype_parts.append((name, np_dtype))

    structured = np.frombuffer(body, dtype=dtype_parts)
    xyz = np.column_stack([structured["x"], structured["y"], structured["z"]]).astype(np.float32)

    if "rgb" in header.fields:
        packed = structured["rgb"]
        r = ((packed >> 16) & 0xFF).astype(np.uint8)
        g = ((packed >> 8) & 0xFF).astype(np.uint8)
        b = (packed & 0xFF).astype(np.uint8)
        rgb = np.column_stack([r, g, b])
    else:
        rgb = np.zeros((len(xyz), 3), dtype=np.uint8)

    return PointCloud(xyz=xyz, rgb=rgb, header=header, bytes_per_point=bytes_per_point)
