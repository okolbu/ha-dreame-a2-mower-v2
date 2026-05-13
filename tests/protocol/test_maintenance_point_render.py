"""render_base_map paints a maintenance-point glyph for each point."""
from __future__ import annotations
import dataclasses
import json
from pathlib import Path


def test_maintenance_point_glyph_drawn():
    from custom_components.dreame_a2_mower.map_render import render_base_map
    from custom_components.dreame_a2_mower.map_decoder import (
        parse_cloud_maps, MaintenancePoint,
    )
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "multi_map_response.json")
        .read_text()
    )
    by_id = {int(k): v for k, v in fixture["by_id"].items()}
    parsed = parse_cloud_maps(by_id)
    m0 = parsed[0]
    # Inject a maintenance point at the cloud origin (in-bounds for the fixture)
    m0 = dataclasses.replace(
        m0,
        maintenance_points=(
            MaintenancePoint(point_id=99, x_mm=0.0, y_mm=0.0),
        ),
    )
    png_no_mp = render_base_map(dataclasses.replace(m0, maintenance_points=()))
    png_with_mp = render_base_map(m0)
    assert png_no_mp != png_with_mp
    assert png_with_mp and len(png_with_mp) > 100
