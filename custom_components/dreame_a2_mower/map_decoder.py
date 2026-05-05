"""Cloud-JSON map decoder for Dreame g2408 mower.

Parses the cloud's ``MAP.0`` … ``MAP.27`` batch response (joined and
JSON-decoded) into a typed :class:`MapData` dataclass.  The decoder
extracts only the geometry fields needed for the base map render
(F2.8.2) and future overlays; it does **not** produce a pixel array —
that's :mod:`map_render`.

Cloud-frame geometry reference:
  docs/research/cloud-map-geometry.md

Coordinate conventions
----------------------
- Cloud units: millimetres.
- Cloud origin ``(0, 0)`` = mower nose at dock entry.
- ``+X`` = toward the house (docking direction).
- The pixel mask applies ``px = (bx2 - x) / grid``, ``py = (by2 - y) / grid``
  (both axes flipped relative to cloud frame).
- For renderer overlay points (charger, exclusion corners) the midline
  reflection ``(bx1+bx2 - x, by1+by2 - y)`` aligns raw cloud coords
  to the flipped pixel frame.  See §3.3 of the geometry doc.

Lifted from: legacy dreame/device.py::_build_map_from_cloud_data
             (~lines 2317–2914 of the A2-mower v1 repo).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .protocol.cloud_map_geom import _rotate_path_around_centroid

_LOGGER = logging.getLogger(__name__)

# Millimetres from mower-nose-at-dock to physical charger centre.
# Empirically tuned against the app rendering (2026-04-19).
CHARGER_OFFSET_MM: int = 800

# Cloud MAP grid resolution.
GRID_SIZE_MM: int = 50


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExclusionZone:
    """A single exclusion / forbidden area polygon in *renderer* coords.

    ``points`` contains the polygon corners after:
      1. Rotating around the polygon centroid by ``-angle`` (angle negated
         to match app rendering handedness).
      2. Reflecting through the bbox midlines so the renderer's
         ``Point.to_img`` places each corner over the same pixel the mask
         formula uses.

    ``subtype`` is one of:

    - ``None`` — classic no-go / forbidden (red in app)
    - ``"ignore"`` — Designated Ignore Obstacle zone (green in app)

    Spots used to live here too (subtype="spot") but are now their own
    dataclass (`SpotZone`) so the user can target individual spots by
    cloud-provided id+name from the UI.
    """

    points: tuple[tuple[float, float], ...]
    subtype: str | None = None


@dataclass(frozen=True, slots=True)
class MowingZone:
    """Mowing area (lawn zone) as described by the cloud MAP.* JSON.

    ``path`` is the raw polygon in cloud-frame mm (not yet reflected).
    Pixel-mask painting applies the ``(bx2-x)/grid, (by2-y)/grid``
    formula; the renderer uses the reflected midline coords.

    ``area_m2`` is the cloud-supplied ``area`` value (already in
    square metres). May be 0.0 when the cloud omits it.
    """

    zone_id: int
    name: str
    path: tuple[tuple[float, float], ...]  # cloud-frame mm
    area_m2: float = 0.0


@dataclass(frozen=True, slots=True)
class SpotZone:
    """A single spot-mowing area with cloud id+name.

    ``points`` is in *renderer* coords (post-rotation, post-reflection)
    so the renderer can paint it identically to ExclusionZone. The
    ``spot_id`` is the integer key from the cloud's ``spotAreas[entry][0]``
    and is what the s2.50 op=103 spot-mow task expects in
    ``d.area: [spot_id, ...]``.
    """

    spot_id: int
    name: str
    points: tuple[tuple[float, float], ...]
    area_m2: float = 0.0


@dataclass(frozen=True, slots=True)
class MaintenancePoint:
    """Maintenance / clean-point marker in raw cloud-frame mm.

    Coordinates are kept in the cloud frame so go-to services can pass
    them straight to ``device.go_to(x_mm, y_mm)`` without re-reflecting.
    """

    point_id: int
    x_mm: float
    y_mm: float


@dataclass(frozen=True, slots=True)
class MapData:
    """Decoded base-map geometry from the Dreame cloud ``MAP.*`` keys.

    This dataclass is the single output of :func:`parse_cloud_map`.  It
    carries all geometric fields required by the F2.8.2 renderer and
    future overlay work.  It does **not** contain a pixel array —
    computing the pixel mask is renderer work.

    Field notes
    -----------
    ``md5`` — stable content hash (not the cloud's ``md5sum`` field,
    which is volatile).  Used for deduplication: if ``md5`` matches the
    previously decoded map the coordinator can skip a re-render.

    ``dock_xy`` — charger position in *renderer* coordinates (midline-
    reflected, with ``CHARGER_OFFSET_MM`` applied along the +X axis).
    ``None`` when the boundary is zero-sized (empty/error response).

    ``boundary_polygon`` — axis-aligned bounding box of the lawn
    expressed as four ``(x, y)`` corners in cloud-frame mm:
    ``(bx1,by1), (bx2,by1), (bx2,by2), (bx1,by2)``.  Primarily
    informational; the renderer sizes its canvas from ``width_px`` /
    ``height_px``.

    ``exclusion_zones`` — polygons in renderer coords (post-rotation,
    post-reflection); ready for ``Area``-style overlay painting.

    ``mowing_zones`` — raw cloud-frame polygons; the renderer's pixel
    mask logic applies its own ``(bx2-x)/grid`` flip when painting.

    ``contour_paths`` — closed contour polylines in cloud-frame mm.
    Rendered as ``WALL`` outlines on the pixel mask.

    ``maintenance_points`` — user-placed go-to markers; raw cloud-frame
    mm so go-to services need no extra transform.

    ``cloud_x_reflect``, ``cloud_y_reflect`` — midline values
    ``bx1+bx2`` and ``by1+by2`` (mm).  Trail / overlay consumers use
    these to convert raw cloud coords to renderer coords without knowing
    the bbox.

    ``total_area_m2`` — lawn area reported by the cloud (may be 0.0 if
    absent from the payload).
    """

    # --- deduplication ---
    md5: str

    # --- canvas dimensions ---
    width_px: int
    height_px: int
    pixel_size_mm: float  # always GRID_SIZE_MM (50) for g2408

    # --- bounding box (cloud-frame mm) ---
    bx1: float
    by1: float
    bx2: float
    by2: float

    # --- midline reflections (bx1+bx2, by1+by2) ---
    cloud_x_reflect: float
    cloud_y_reflect: float

    # --- map rotation (always 0 for g2408 cloud maps) ---
    rotation_deg: float

    # --- geometry ---
    boundary_polygon: tuple[tuple[float, float], ...]
    mowing_zones: tuple[MowingZone, ...]
    exclusion_zones: tuple[ExclusionZone, ...]
    spot_zones: tuple[SpotZone, ...]
    contour_paths: tuple[tuple[tuple[float, float], ...], ...]
    # Contour IDs in cloud-key order, parallel to ``contour_paths``.
    # Each entry is the 2-int composite identifier from the cloud's
    # ``contours.value`` map keying — e.g. ``(1, 0)`` for "the outer
    # perimeter of zone-region 1", ``(1, 1)`` for an inner-seam contour,
    # ``(2, 0)`` for "outer perimeter of region 2" on multi-zone lawns.
    # Used by the edge-mow action dispatcher to default to "all outer
    # perimeters" (entries with second-int = 0) when no explicit
    # contour selection is given. See docs/research/g2408-protocol.md
    # §4.6 for the wire-format finding (2026-05-05 live runs).
    available_contour_ids: tuple[tuple[int, int], ...]
    maintenance_points: tuple[MaintenancePoint, ...]

    # --- charger (renderer coords, post-reflection + offset) ---
    dock_xy: tuple[float, float] | None

    # --- metadata ---
    total_area_m2: float = 0.0


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def parse_cloud_map(cloud_response: dict[str, Any]) -> MapData | None:
    """Parse the cloud's ``MAP.*`` batch response into a :class:`MapData`.

    ``cloud_response`` should be the already-joined-and-JSON-decoded
    top-level map dict (the dict that contains ``"boundary"``,
    ``"mowingAreas"``, etc. — see §1 of cloud-map-geometry.md).

    Returns ``None`` when the input is empty, malformed, or carries an
    unusable boundary (e.g. all-zero after a failed cloud fetch).  The
    caller should log and skip re-render in that case.
    """
    if not isinstance(cloud_response, dict):
        _LOGGER.debug("parse_cloud_map: not a dict (%r)", type(cloud_response))
        return None

    boundary = cloud_response.get("boundary")
    if not isinstance(boundary, dict):
        _LOGGER.debug("parse_cloud_map: missing 'boundary' key")
        return None

    # Cloud sometimes returns float boundary coords.
    try:
        bx1 = float(boundary.get("x1", 0))
        by1 = float(boundary.get("y1", 0))
        bx2 = float(boundary.get("x2", 0))
        by2 = float(boundary.get("y2", 0))
    except (TypeError, ValueError) as exc:
        _LOGGER.debug("parse_cloud_map: bad boundary values: %s", exc)
        return None

    # An all-zero boundary almost always means an empty/error response.
    if bx1 == 0 and by1 == 0 and bx2 == 0 and by2 == 0:
        _LOGGER.debug("parse_cloud_map: zero boundary — skipping")
        return None

    # -----------------------------------------------------------------------
    # Forbidden/exclusion zones — pre-rotate so bbox expansion is correct.
    # The cloud's angle convention is mirror-flipped vs the app's rendering;
    # we negate the angle before rotating (see §4.1 of geometry doc).
    # -----------------------------------------------------------------------
    forbidden_raw = cloud_response.get("forbiddenAreas", {})
    ignore_raw = cloud_response.get("notObsAreas", {})
    spot_raw = cloud_response.get("spotAreas", {})

    rotated_exclusions: list[tuple[list[dict], str | None]] = []
    rotated_spots: list[tuple[int, str, list[dict], float]] = []

    def _accumulate(entries_wrapper: Any, subtype: str | None) -> None:
        entries = entries_wrapper.get("value", []) if isinstance(entries_wrapper, dict) else []
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                zdata = entry[1]
            elif isinstance(entry, dict):
                zdata = entry
            else:
                continue
            path = zdata.get("path", [])
            if not path:
                continue
            raw_angle = zdata.get("angle")
            rot_angle = -raw_angle if raw_angle is not None else None
            rotated = _rotate_path_around_centroid(path, rot_angle)
            rotated_exclusions.append((rotated, subtype))

    def _accumulate_spots(entries_wrapper: Any) -> None:
        entries = entries_wrapper.get("value", []) if isinstance(entries_wrapper, dict) else []
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                spot_id_raw = entry[0]
                zdata = entry[1]
            elif isinstance(entry, dict):
                spot_id_raw = entry.get("id", 0)
                zdata = entry
            else:
                continue
            path = zdata.get("path", [])
            if not path:
                continue
            try:
                spot_id = int(spot_id_raw)
            except (TypeError, ValueError):
                continue
            name = str(zdata.get("name", "") or f"Spot {spot_id}")
            try:
                area_m2 = float(zdata.get("area", 0.0) or 0.0)
            except (TypeError, ValueError):
                area_m2 = 0.0
            raw_angle = zdata.get("angle")
            rot_angle = -raw_angle if raw_angle is not None else None
            rotated = _rotate_path_around_centroid(path, rot_angle)
            rotated_spots.append((spot_id, name, rotated, area_m2))

    _accumulate(forbidden_raw, None)     # red
    _accumulate(ignore_raw, "ignore")    # green
    _accumulate_spots(spot_raw)          # grey, with id+name preserved

    # -----------------------------------------------------------------------
    # Expand bbox to cover every rotated exclusion / spot corner.
    # -----------------------------------------------------------------------
    bx1_exp = bx1
    by1_exp = by1
    bx2_exp = bx2
    by2_exp = by2
    for (rp, _sub) in rotated_exclusions:
        for pt in rp:
            x, y = float(pt["x"]), float(pt["y"])
            bx1_exp = min(bx1_exp, x)
            by1_exp = min(by1_exp, y)
            bx2_exp = max(bx2_exp, x)
            by2_exp = max(by2_exp, y)
    for (_sid, _nm, rp, _area) in rotated_spots:
        for pt in rp:
            x, y = float(pt["x"]), float(pt["y"])
            bx1_exp = min(bx1_exp, x)
            by1_exp = min(by1_exp, y)
            bx2_exp = max(bx2_exp, x)
            by2_exp = max(by2_exp, y)

    width_px = max(1, int((bx2_exp - bx1_exp) / GRID_SIZE_MM) + 1)
    height_px = max(1, int((by2_exp - by1_exp) / GRID_SIZE_MM) + 1)

    # Midline reflections used to align renderer overlay coords to the
    # flipped pixel-mask frame (see §3.3 of geometry doc).
    x_reflect = bx1_exp + bx2_exp
    y_reflect = by1_exp + by2_exp

    # -----------------------------------------------------------------------
    # Exclusion zones — apply midline reflection for renderer coords.
    # -----------------------------------------------------------------------
    excl_out: list[ExclusionZone] = []
    for (rp, subtype) in rotated_exclusions:
        pts = tuple(
            (float(x_reflect - pt["x"]), float(y_reflect - pt["y"]))
            for pt in rp
        )
        if pts:
            excl_out.append(ExclusionZone(points=pts, subtype=subtype))

    spot_out: list[SpotZone] = []
    for (spot_id, name, rp, area_m2) in rotated_spots:
        pts = tuple(
            (float(x_reflect - pt["x"]), float(y_reflect - pt["y"]))
            for pt in rp
        )
        if pts:
            spot_out.append(
                SpotZone(spot_id=spot_id, name=name, points=pts, area_m2=area_m2)
            )

    # -----------------------------------------------------------------------
    # Mowing zones — keep in cloud-frame mm (renderer applies its own flip).
    # -----------------------------------------------------------------------
    mowing_out: list[MowingZone] = []
    mowing_areas = cloud_response.get("mowingAreas", {})
    entries = mowing_areas.get("value", []) if isinstance(mowing_areas, dict) else []
    for entry in entries:
        if isinstance(entry, list) and len(entry) >= 2:
            zone_id = entry[0]
            zdata = entry[1]
        elif isinstance(entry, dict):
            zone_id = entry.get("id", 1)
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        name = zdata.get("name", f"Zone {zone_id}")
        if not path:
            continue
        try:
            zone_id_int = int(zone_id)
        except (TypeError, ValueError):
            continue
        if zone_id_int < 1 or zone_id_int > 62:
            continue
        try:
            area_m2 = float(zdata.get("area", 0.0) or 0.0)
        except (TypeError, ValueError):
            area_m2 = 0.0
        pts = tuple((float(pt["x"]), float(pt["y"])) for pt in path if "x" in pt and "y" in pt)
        if len(pts) >= 3:
            mowing_out.append(
                MowingZone(zone_id=zone_id_int, name=name, path=pts, area_m2=area_m2)
            )

    # -----------------------------------------------------------------------
    # Contour paths — closed outlines, cloud-frame mm.
    # Each cloud entry is keyed by a 2-int composite ID (e.g. [1, 0],
    # [1, 1], [2, 0]) which the edge-mow wire format passes directly
    # in ``d.edge: [[m, c], ...]``. We preserve those keys parallel
    # to the path tuples for the dispatcher's default-selection logic.
    # -----------------------------------------------------------------------
    contour_out: list[tuple[tuple[float, float], ...]] = []
    contour_ids_out: list[tuple[int, int]] = []
    contours_raw = cloud_response.get("contours", {})
    c_entries = contours_raw.get("value", []) if isinstance(contours_raw, dict) else []
    for entry in c_entries:
        cid: tuple[int, int] | None = None
        if isinstance(entry, list) and len(entry) >= 2:
            raw_key = entry[0]
            zdata = entry[1]
            # Cloud key is typically a 2-element list/tuple [m, c]; some
            # firmware variants emit it as a "m,c" string. Both forms
            # collapse to a (m, c) int tuple here.
            if isinstance(raw_key, (list, tuple)) and len(raw_key) == 2:
                try:
                    cid = (int(raw_key[0]), int(raw_key[1]))
                except (TypeError, ValueError):
                    cid = None
            elif isinstance(raw_key, str):
                parts = [p.strip() for p in raw_key.split(",")]
                if len(parts) == 2:
                    try:
                        cid = (int(parts[0]), int(parts[1]))
                    except ValueError:
                        cid = None
        elif isinstance(entry, dict):
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        pts = tuple((float(pt["x"]), float(pt["y"])) for pt in path if "x" in pt and "y" in pt)
        if len(pts) >= 2:
            contour_out.append(pts)
            # If the cloud entry didn't carry a parseable composite key
            # (e.g. dict-shaped entries from older firmware), synthesise
            # one from the entry's positional index — keeps the parallel
            # arrays aligned and lets dispatcher logic fall back to
            # "everything" rather than crashing.
            contour_ids_out.append(cid if cid is not None else (1, len(contour_ids_out)))

    # -----------------------------------------------------------------------
    # Maintenance / clean points — raw cloud-frame mm.
    # -----------------------------------------------------------------------
    mp_out: list[MaintenancePoint] = []
    clean_raw = cloud_response.get("cleanPoints", {})
    cp_entries = clean_raw.get("value", []) if isinstance(clean_raw, dict) else []
    for entry in cp_entries:
        if isinstance(entry, list) and len(entry) >= 2:
            point_id = entry[0]
            pdata = entry[1]
        elif isinstance(entry, dict):
            point_id = entry.get("id", 1)
            pdata = entry
        else:
            continue
        point_path = pdata.get("path") or []
        if not point_path:
            continue
        try:
            pt = point_path[0]
            pid = int(point_id) if isinstance(point_id, (int, float)) else int(pdata.get("id", len(mp_out) + 1))
            mp_out.append(MaintenancePoint(point_id=pid, x_mm=float(pt["x"]), y_mm=float(pt["y"])))
        except (KeyError, TypeError, ValueError):
            continue

    # -----------------------------------------------------------------------
    # Charger position — cloud (0, 0) + CHARGER_OFFSET_MM along +X,
    # then reflected through midlines for renderer coords.
    # See §5 of cloud-map-geometry.md.
    # -----------------------------------------------------------------------
    dock_xy: tuple[float, float] | None
    if bx2_exp != bx1_exp or by2_exp != by1_exp:
        dock_xy = (
            float(x_reflect - CHARGER_OFFSET_MM),
            float(y_reflect),
        )
    else:
        dock_xy = None

    # -----------------------------------------------------------------------
    # Boundary polygon (axis-aligned box, cloud-frame mm).
    # -----------------------------------------------------------------------
    boundary_polygon = (
        (bx1_exp, by1_exp),
        (bx2_exp, by1_exp),
        (bx2_exp, by2_exp),
        (bx1_exp, by2_exp),
    )

    # -----------------------------------------------------------------------
    # Stable content hash (NOT the cloud's md5sum which is volatile).
    # -----------------------------------------------------------------------
    stable = json.dumps(
        {
            "zones": sorted(
                (z.zone_id, round(z.path[0][0], 3), round(z.path[0][1], 3))
                for z in mowing_out
            ),
            "excl": [
                (round(p[0], 2), round(p[1], 2))
                for ez in excl_out
                for p in ez.points[:4]
            ],
            "dims": (width_px, height_px),
            "charger": dock_xy,
        },
        sort_keys=True,
    ).encode()
    md5 = hashlib.md5(stable).hexdigest()

    total_area_m2 = float(cloud_response.get("totalArea", 0.0) or 0.0)

    return MapData(
        md5=md5,
        width_px=width_px,
        height_px=height_px,
        pixel_size_mm=float(GRID_SIZE_MM),
        bx1=bx1_exp,
        by1=by1_exp,
        bx2=bx2_exp,
        by2=by2_exp,
        cloud_x_reflect=float(x_reflect),
        cloud_y_reflect=float(y_reflect),
        rotation_deg=0.0,
        boundary_polygon=boundary_polygon,
        mowing_zones=tuple(mowing_out),
        exclusion_zones=tuple(excl_out),
        spot_zones=tuple(spot_out),
        contour_paths=tuple(contour_out),
        available_contour_ids=tuple(contour_ids_out),
        maintenance_points=tuple(mp_out),
        dock_xy=dock_xy,
        total_area_m2=total_area_m2,
    )


# ---------------------------------------------------------------------------
# Batch-join helper
# ---------------------------------------------------------------------------


def join_map_parts(batch_response: dict[str, Any], *, prefix: str = "MAP") -> dict[str, Any] | None:
    """Join the 28 cloud batch keys (``MAP.0`` … ``MAP.27``) and JSON-decode.

    Handles the wrapped-list form ``[json_string, ...]`` that some firmware
    versions emit.  Returns ``None`` when no valid map dict can be extracted.

    This is the outer shell around :func:`parse_cloud_map`; the coordinator
    calls ``parse_cloud_map(join_map_parts(batch))`` to obtain a
    :class:`MapData`.
    """
    if not batch_response:
        return None

    parts = [batch_response.get(f"{prefix}.{i}", "") or "" for i in range(28)]
    raw = "".join(parts)
    if not raw:
        return None

    try:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        _LOGGER.debug("join_map_parts: JSON decode failed: %s", exc)
        return None

    if isinstance(parsed, list):
        # Wrapped form: try each element.
        for item in parsed:
            if isinstance(item, str):
                try:
                    candidate = json.loads(item)
                    if isinstance(candidate, dict) and (
                        "boundary" in candidate or "mowingAreas" in candidate
                    ):
                        return candidate
                except (json.JSONDecodeError, ValueError):
                    continue
            elif isinstance(item, dict) and (
                "boundary" in item or "mowingAreas" in item
            ):
                return item
        _LOGGER.debug("join_map_parts: list form but no usable map entry")
        return None

    if isinstance(parsed, dict):
        return parsed

    return None
