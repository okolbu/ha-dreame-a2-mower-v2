"""Guard: the _cached_maps_by_id shadow stays removed.

cloud_state.maps_by_id is the single source of truth for map data. If this
test fails, the shadow was reintroduced -- route the reader/writer to
cloud_state.maps_by_id instead.
"""
import pathlib


def test_no_cached_maps_shadow_in_source():
    src = pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower"
    assert src.is_dir(), f"source tree not found at {src}"
    hits = []
    for path in src.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if "_cached_maps_by_id" in line:
                hits.append(f"{path}:{lineno}: {line.strip()}")
    assert not hits, "shadow reintroduced:\n" + "\n".join(hits)
