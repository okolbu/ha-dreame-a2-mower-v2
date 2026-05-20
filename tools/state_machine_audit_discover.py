"""AST-based entity-description discovery.

Walks the platform Python files under custom_components/dreame_a2_mower/
and extracts every *EntityDescription instance — capturing key, name,
platform, and the literal source text of each `value_fn` so the checks
module can both invoke it and classify its holder.

Source-text extraction is preferred over symbolic eval because value_fns
are often lambdas that close over module-scope helpers; AST gives us
faithful source without import-time side effects.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

CCDIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "dreame_a2_mower"
)

PLATFORMS: tuple[str, ...] = (
    "binary_sensor",
    "sensor",
    "switch",
    "select",
    "number",
    "time",
)

# Sibling helper modules that carry entity classes / description tables for a
# platform but are NOT named after the HA platform domain (so HA won't try to
# load them directly).  Keyed by platform name; values are module filenames
# relative to CCDIR.  Populated incrementally as B3a refactors split each
# platform file.
PLATFORM_SIBLINGS: dict[str, tuple[str, ...]] = {
    "switch": ("switch_global.py", "switch_map.py", "_switch_base.py"),
    "select": ("select_global.py", "select_map_settings.py", "_select_base.py"),
}


# Improvement C (F10 2026-05-14): broaden the entity-description suffix
# check so we also catch description subclasses whose name doesn't end in
# "EntityDescription" — currently just `DreameA2SettingsSelectDescription`
# (a SelectEntityDescription subclass used for the bulk of CFG-bound
# settings in select.py). Explicit suffix list keeps the matcher narrow:
# we don't want to accidentally pick up unrelated `*Description` classes.
_DESCRIPTION_SUFFIXES: tuple[str, ...] = (
    "EntityDescription",
    "SelectDescription",
)


@dataclass(frozen=True)
class EntityDescriptor:
    """One discovered entity description."""

    platform: str
    key: str
    name: str | None
    value_fn_src: str
    source_file: str
    line: int


def _kwarg_str(call: ast.Call, name: str) -> str | None:
    """Pull a string-literal kwarg out of a Call node, or None."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            v = kw.value.value
            if isinstance(v, str):
                return v
    return None


def _kwarg_source(call: ast.Call, name: str, source: str) -> str | None:
    """Pull a kwarg's source text out of a Call node, or None."""
    for kw in call.keywords:
        if kw.arg == name:
            return ast.get_source_segment(source, kw.value)
    return None


def _scan_module_for_description_entities(
    platform: str, path: Path
) -> list[EntityDescriptor]:
    """Scan a single source file for *EntityDescription call instances."""
    source = path.read_text()
    tree = ast.parse(source)
    path_str = str(path.relative_to(CCDIR.parent.parent))
    out: list[EntityDescriptor] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match calls like DreameA2BinarySensorEntityDescription(...) or
        # any *EntityDescription suffix.
        name_id = ""
        if isinstance(func, ast.Name):
            name_id = func.id
        elif isinstance(func, ast.Attribute):
            name_id = func.attr
        if not name_id.endswith(_DESCRIPTION_SUFFIXES):
            continue
        key = _kwarg_str(node, "key")
        if not key:
            continue
        name = _kwarg_str(node, "name")
        # Prefer `value_fn` (most platforms) but fall back to
        # `minutes_fn` for the Time platform, which uses a different
        # kwarg name to read an integer-minutes field off the snapshot.
        value_fn_src = (
            _kwarg_source(node, "value_fn", source)
            or _kwarg_source(node, "minutes_fn", source)
            or ""
        )
        # Skip entities without any value reader (e.g. the action_mode
        # SelectEntityDescription, which reads state via a property on
        # the entity class itself rather than a closure). The audit
        # only verifies read paths driven by a kwarg-supplied callable.
        if not value_fn_src:
            continue
        out.append(
            EntityDescriptor(
                platform=platform,
                key=key,
                name=name,
                value_fn_src=value_fn_src,
                source_file=path_str,
                line=node.lineno,
            )
        )
    # Also discover class-attribute-driven entities (snapshot-attr bases
    # + standalone registry). These don't go through *EntityDescription
    # tuples — they live on the entity class itself as `_attr_*` class
    # attrs + a `native_value`/`current_option`/`is_on` property.
    out.extend(_discover_class_attribute_entities(platform, tree, source, path_str))
    return out


def discover_entities() -> list[EntityDescriptor]:
    """Discover all EntityDescription instances across platform modules.

    Also scans sibling helper modules listed in PLATFORM_SIBLINGS (e.g.
    switch_global.py, switch_map.py) that carry entity classes / description
    tables but are not named after the HA platform domain.
    """
    out: list[EntityDescriptor] = []
    for platform in PLATFORMS:
        # Primary platform file
        path = CCDIR / f"{platform}.py"
        out.extend(_scan_module_for_description_entities(platform, path))
        # Sibling helper modules (B3a splits)
        for sibling_name in PLATFORM_SIBLINGS.get(platform, ()):
            sibling_path = CCDIR / sibling_name
            if sibling_path.exists():
                out.extend(_scan_module_for_description_entities(platform, sibling_path))
    return out


# Bases whose subclasses derive an entity value from a _SNAPSHOT_FIELD class attr.
_SNAPSHOT_FIELD_BASES: frozenset[str] = frozenset({
    "_SnapshotEnumSensorBase",
})


# Hand-curated registry of standalone class-attribute entities that don't share
# a common base. Each entry: (platform, key, synthetic_value_fn_src).
# The synthetic value_fn must be invocable in the audit harness (eval'd against
# the fake coord). Use coord.X attribute paths that the fake coord supports.
_STANDALONE_CLASS_REGISTRY: dict[str, tuple[str, str, str]] = {
    # sensor.py standalone classes
    "DreameA2OtaStatusSensor": (
        "sensor", "ota_status",
        "lambda coord: coord.cloud_state.ota_status[0] if coord.cloud_state.ota_status else None",
    ),
    "DreameA2ScheduleCountSensor": (
        "sensor", "schedule_count",
        "lambda coord: len(coord.cloud_state.schedule.slots)",
    ),
    "DreameA2WifiRefreshStatusSensor": (
        "sensor", "wifi_refresh_status",
        "lambda coord: coord._wifi_archive_last_refresh.get('last_attempt_unix') if coord._wifi_archive_last_refresh else None",
    ),
    "DreameA2WifiHeatmapAgeSensor": (
        "sensor", "wifi_heatmap_age",
        "lambda coord: (max((int(e.unix_ts) for e in coord._wifi_archive_index if int(e.unix_ts) > 0), default=None) if coord._wifi_archive_index else None)",
    ),
    "DreameA2LastNotificationSensor": (
        "sensor", "last_notification",
        "lambda coord: coord._last_notification.get('text') if coord._last_notification else None",
    ),
    "DreameA2CloudDeviceIdSensor": (
        "sensor", "cloud_device_id",
        "lambda coord: coord._cloud.device_id if coord._cloud else None",
    ),
    "DreameA2ApiEndpointSensor": (
        "sensor", "api_endpoint",
        "lambda coord: f'{coord._cloud.host}:19973' if coord._cloud else None",
    ),
    "DreameA2IntegrationVersionSensor": (
        "sensor", "integration_version",
        "lambda coord: '1.0.0'",  # static manifest read; just a non-None placeholder
    ),
    # select.py standalone classes
    "DreameA2ActionModeSelect": (
        "select", "action_mode",
        "lambda coord: coord.data.action_mode.value if coord.data.action_mode else None",
    ),
    "DreameA2LidarArchiveSelect": (
        "select", "lidar_archive",
        "lambda coord: coord._lidar_render_entry",
    ),
    "DreameA2ActiveMapSelect": (
        "select", "active_map",
        "lambda coord: coord._active_map_id",
    ),
    # NOTE: settings_mowing_direction, mowing_pattern, settings_edge_mowing_walk_mode
    # were migrated to per-map sub-devices in v1.0.10a7 — like the other per-map
    # SETTINGS switches, the per-map select classes intentionally slip past
    # the audit discovery walker (they're parameterized by map_id and aren't
    # mower-scoped singletons).
    "DreameA2WifiArchiveSelect": (
        "select", "wifi_archive",
        "lambda coord: coord._wifi_render_entry",
    ),
    # number.py standalone classes
    # NOTE: the 7 SETTINGS-driven number entities (mowing_height,
    # cutter_position, cutter_position_height, edge_mowing_num,
    # obstacle_avoidance_height/distance/sensitivity) were migrated to per-map
    # sub-devices in v1.0.10a7. Like the per-map SETTINGS switches, the
    # per-map number classes intentionally slip past the audit discovery
    # walker — they're parameterized by map_id and aren't mower-scoped
    # singletons.
    "DreameA2StationBearingNumber": (
        "number", "station_bearing_deg",
        "lambda coord: coord.station_bearing_deg if coord.station_bearing_deg is not None else 0",
    ),
    # switch.py standalone classes
    "DreameA2AiHumanDetectionSwitch": (
        "switch", "cloud_state_ai_human_enabled",
        "lambda coord: coord.cloud_state.ai_human_enabled",
    ),
}


def _discover_class_attribute_entities(
    platform: str, tree: ast.Module, source: str, path_str: str | None = None
) -> list[EntityDescriptor]:
    """Find class-attribute-driven entities (snapshot-attr bases + standalone registry).

    Two flavors:

    Part A — subclasses of ``_SnapshotEnumSensorBase`` (and any other base in
    ``_SNAPSHOT_FIELD_BASES``) define ``_SNAPSHOT_FIELD = "<name>"`` plus
    ``_attr_translation_key``. The base's ``native_value`` reads
    ``state_machine.snapshot().<_SNAPSHOT_FIELD>``, so we synthesize that
    lambda from the AST-extracted field name.

    Part B — standalone classes hand-curated in ``_STANDALONE_CLASS_REGISTRY``.
    The walker matches class names; the registry supplies the synthetic
    value_fn. Keeps the audit free of brittle property-body parsing.
    """
    out: list[EntityDescriptor] = []
    if path_str is None:
        path_str = f"custom_components/dreame_a2_mower/{platform}.py"

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Part A: classes that subclass a snapshot-attribute base
        base_names = set()
        for b in node.bases:
            if isinstance(b, ast.Name):
                base_names.add(b.id)
            elif isinstance(b, ast.Attribute):
                base_names.add(b.attr)
        if base_names & _SNAPSHOT_FIELD_BASES:
            snapshot_field: str | None = None
            translation_key: str | None = None
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                    continue
                target = stmt.targets[0].id
                if not isinstance(stmt.value, ast.Constant):
                    continue
                if not isinstance(stmt.value.value, str):
                    continue
                if target == "_SNAPSHOT_FIELD":
                    snapshot_field = stmt.value.value
                elif target == "_attr_translation_key":
                    translation_key = stmt.value.value
            if snapshot_field and translation_key:
                synthetic = (
                    f"lambda coord: coord.state_machine.snapshot().{snapshot_field}"
                )
                out.append(EntityDescriptor(
                    platform=platform,
                    key=translation_key,
                    name=None,
                    value_fn_src=synthetic,
                    source_file=path_str,
                    line=node.lineno,
                ))
            continue

        # Part B: standalone registry classes
        if node.name in _STANDALONE_CLASS_REGISTRY:
            reg_platform, reg_key, reg_src = _STANDALONE_CLASS_REGISTRY[node.name]
            if reg_platform != platform:
                continue  # skip if cross-file
            out.append(EntityDescriptor(
                platform=platform,
                key=reg_key,
                name=None,
                value_fn_src=reg_src,
                source_file=path_str,
                line=node.lineno,
            ))
    return out


def classify_holder(value_fn_src: str) -> str:
    """Classify which state holder this value_fn reads from.

    Returns one of: "snapshot", "mower_state", "cloud_state", "multi", "other".

    Pure-text heuristic over the source — keeps the tool deterministic and
    avoids any need to import the integration just to classify.
    """
    src = value_fn_src or ""
    hits: set[str] = set()
    if "state_machine.snapshot" in src or ".snapshot()." in src:
        hits.add("snapshot")
    if (
        # `coord.data.X` reads MowerState
        ".data." in src
        # `lambda s: s.X` — MowerState shorthand used in sensor.py
        or src.lstrip().startswith("lambda s:")
        or src.lstrip().startswith("lambda s :")
    ):
        hits.add("mower_state")
    if "cloud_state" in src:
        hits.add("cloud_state")
    if not hits:
        return "other"
    if len(hits) == 1:
        return next(iter(hits))
    return "multi"
