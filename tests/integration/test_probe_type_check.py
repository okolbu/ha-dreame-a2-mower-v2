"""Type-check probe values against MowerState annotations.
Run via pytest so HA stubs are available.
"""
import json, glob, typing
from pathlib import Path
from enum import IntEnum, Enum

from custom_components.dreame_a2_mower.coordinator import apply_property_to_state, _BLOB_SLOTS, _SUPPRESSED_SLOTS
from custom_components.dreame_a2_mower.mower.property_mapping import PROPERTY_MAPPING
from custom_components.dreame_a2_mower.mower.state import MowerState

def test_probe_values_produce_correct_types(capsys):
    hints = typing.get_type_hints(MowerState)
    slot_to_fields = {}
    for key, entry in PROPERTY_MAPPING.items():
        if entry.field_name:
            slot_to_fields[key] = [entry.field_name]
        if entry.multi_field:
            slot_to_fields[key] = [n for n, _ in entry.multi_field]

    slot_values = {}
    for path in sorted(glob.glob('/data/claude/homeassistant/probe_log_*.jsonl')):
        for line in Path(path).read_text(errors='replace').splitlines():
            try: e = json.loads(line)
            except: continue
            if e.get('type') != 'mqtt_message' or e.get('method') != 'properties_changed': continue
            for p in (e.get('params') or []):
                try:
                    k = (int(p['siid']), int(p['piid']))
                    slot_values.setdefault(k, []).append(p.get('value'))
                except: continue

    issues = []
    for slot, fields in slot_to_fields.items():
        values = slot_values.get(slot, [])
        if not values: continue
        seen = set(); sample = []
        for v in values:
            r = repr(v)[:200]
            if r not in seen:
                seen.add(r); sample.append(v)
            if len(sample) >= 5: break
        for v in sample:
            try:
                ns = apply_property_to_state(MowerState(), slot[0], slot[1], v)
            except Exception as ex:
                issues.append((slot, v, f"CRASH: {ex}"))
                continue
            for fld in fields:
                applied = getattr(ns, fld, None)
                if applied is None: continue
                exp = hints.get(fld)
                args = typing.get_args(exp) if exp is not None else ()
                allowed = []
                if args:
                    for a in args:
                        if a is type(None): continue
                        origin = typing.get_origin(a)
                        if origin is None and isinstance(a, type): allowed.append(a)
                        elif origin in (list, tuple, dict): allowed.append(origin)
                elif exp and isinstance(exp, type):
                    allowed.append(exp)
                if not allowed: continue
                if isinstance(applied, (IntEnum, Enum)) and int in allowed: continue
                if not any(isinstance(applied, t) for t in allowed):
                    issues.append((slot, v, f"field={fld} expected={[t.__name__ for t in allowed]} got={type(applied).__name__}({applied!r})"))

    if issues:
        with capsys.disabled():
            print(f"\n{len(issues)} type-mismatch(es):")
            for slot, value, msg in issues:
                print(f"  s{slot[0]}p{slot[1]} value={value!r} → {msg}")
    assert not issues, f"{len(issues)} probe values produced wrong types"
