"""g2408 capability flags — frozen constants.

The Dreame A2 mower (g2408) is a single-model integration. Capability
flags are not runtime-resolved against a per-model registry (that
machinery was deleted in legacy P1.4 — the upstream blob had no g2408
entry, so the lookup was provably inert).

The values here come from the offline snapshot derived from 3 weeks of
MQTT probe logs + decompression of the legacy DREAME_MODEL_CAPABILITIES
blob. See ``docs/research/g2408-protocol.md`` §2.1 for the property
mapping that drives each flag.

If a future firmware introduces a property never observed in the
snapshot scan (e.g., the integration sees ``s4.22 AI_DETECTION`` push
for the first time), the flag is added here AND covered by a regression
test.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capabilities:
    """g2408 capability snapshot — every flag is a constant."""

    # Confirmed True on g2408 — MAP_SAVING (s13.1) never observed.
    lidar_navigation: bool = True

    # All confirmed False per the snapshot — these properties never
    # arrive on MQTT in 3 weeks of probe logs.
    ai_detection: bool = False
    auto_charging: bool = False
    auto_rename_segment: bool = False
    auto_switch_settings: bool = False
    backup_map: bool = False
    camera_streaming: bool = False
    cleangenius: bool = False
    cleangenius_auto: bool = False
    cleaning_route: bool = False
    customized_cleaning: bool = False
    dnd: bool = False
    dnd_task: bool = False
    extended_furnitures: bool = False
    fill_light: bool = False
    floor_direction_cleaning: bool = False
    floor_material: bool = False
    fluid_detection: bool = False
    gen5: bool = False
    large_particles_boost: bool = False
    lensbrush: bool = False
    map_object_offset: bool = False
    max_suction_power: bool = False
    multi_floor_map: bool = False
    new_furnitures: bool = False
    new_state: bool = False
    obstacle_image_crop: bool = False
    obstacles: bool = False
    off_peak_charging: bool = False
    pet_detective: bool = False
    pet_furniture: bool = False
    pet_furnitures: bool = False
    saved_furnitures: bool = False
    segment_slow_clean_route: bool = False
    segment_visibility: bool = False
    shortcuts: bool = False
    task_type: bool = False
    voice_assistant: bool = False
    wifi_map: bool = False


CAPABILITIES: Capabilities = Capabilities()
"""The single global Capabilities instance for g2408. Import this rather
than instantiating Capabilities() directly."""
