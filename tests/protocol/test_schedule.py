"""Tests for SCHEDULE decoder (header + blob) + encoder."""
from __future__ import annotations

from custom_components.dreame_a2_mower.cloud_state import (
    ScheduleSlot,
    SchedulePlan,
)
from custom_components.dreame_a2_mower.protocol.schedule import (
    build_schedule_set_value,
    encode_schedule_blob,
    parse_schedule_batch,
)


# Weekday-bit helpers — keep tests readable.
MON = 1 << 0
TUE = 1 << 1
WED = 1 << 2
THU = 1 << 3
FRI = 1 << 4
SAT = 1 << 5
SUN = 1 << 6


def test_parse_real_shape():
    """Verified shape (2026-05-08, g2408 fw 4.3.6_0550):
        {"d": [[id, mode, name, blob_b64], ...], "v": version}

    Live cloud emits mode=1 for the active/primary slot and mode=0 for
    empty/secondary; the parser must round-trip both so writes don't
    flip an active slot off.
    """
    raw = {
        "d": [
            [0, 1, "Spr & Sum Schedule", "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="],
            [1, 0, "", "qgcQHAIA7aoHQBwCAO0="],
        ],
        "v": 657,
    }
    result = parse_schedule_batch(raw)
    assert result.version == 657
    assert len(result.slots) == 2
    assert result.slots[0].slot_id == 0
    assert result.slots[0].name == "Spr & Sum Schedule"
    assert result.slots[0].raw_blob_b64 == "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="
    assert result.slots[0].mode == 1
    assert result.slots[1].slot_id == 1
    assert result.slots[1].name == ""
    assert result.slots[1].mode == 0


def test_parse_empty_returns_empty_slots():
    result = parse_schedule_batch({"d": [], "v": 0})
    assert result.version == 0
    assert result.slots == ()


def test_parse_html_escape_in_name_decoded():
    """Cloud emits `&amp;`; decoder unescapes to `&`."""
    raw = {"d": [[0, 0, "A &amp; B", ""]], "v": 1}
    result = parse_schedule_batch(raw)
    assert result.slots[0].name == "A & B"


def test_parse_invalid_input_returns_empty():
    """Defensive: non-dict input → empty result, not crash."""
    assert parse_schedule_batch(None).slots == ()
    assert parse_schedule_batch([]).slots == ()
    assert parse_schedule_batch({}).slots == ()


def test_parse_skips_malformed_slot_entries():
    raw = {"d": [[0, 0, "Good", ""], "not-a-list", [1]], "v": 1}
    result = parse_schedule_batch(raw)
    assert len(result.slots) == 1  # only the well-formed entry
    assert result.slots[0].slot_id == 0


# ---------------------------------------------------------------------------
# Blob-decode tests against the user's verified ground truth (2026-05-08).
# ---------------------------------------------------------------------------


def test_decode_real_slot0_with_zone_and_edge():
    """Live slot 0 from 2026-05-08 — 6 records, 5 plans (Mon+Wed coalesce)."""
    raw = {
        "d": [[0, 0, "Spr & Sum Schedule",
               "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqggxwBMAAe2qB1DgAQDtqglidCQAAQDt"]],
        "v": 1,
    }
    plans = parse_schedule_batch(raw).slots[0].plans
    assert plans == (
        SchedulePlan(time_min=7*60+58, weekday_mask=MON|WED, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=17*60+30, weekday_mask=MON, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=16*60, weekday_mask=WED, action_type=1,
                     zone_id=1, extra_bytes=b""),
        SchedulePlan(time_min=8*60, weekday_mask=FRI, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=19*60, weekday_mask=SAT, action_type=2,
                     zone_id=1, extra_bytes=b"\x00"),
    )


def test_decode_skips_record_with_bad_length_byte():
    """A record with len < 7 or len > 16 is rejected (whole slot drops)."""
    import base64
    bad = base64.b64encode(b"\xaa\x05\x10\xde\x01\xed").decode()  # len=5 too short
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_decode_skips_zone_with_bad_terminator():
    """Zone record (len=8) with non-ED at byte 7 is rejected."""
    import base64
    bad = base64.b64encode(b"\xaa\x08\x31\xc0\x13\x00\x01\xff").decode()
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_parse_real_blob_slot1_one_plan_two_weekdays():
    """Aut & Win slot has 1 plan: 09:00 All-area, Mon Thu — emitted as
    two records (Mon record, Thu record) which the decoder coalesces."""
    raw = {"d": [[1, 0, "", "qgcQHAIA7aoHQBwCAO0="]], "v": 1}
    plans = parse_schedule_batch(raw).slots[0].plans
    assert plans == (
        SchedulePlan(time_min=9 * 60, weekday_mask=MON | THU, action_type=0),
    )


def test_parse_blob_empty_string_yields_no_plans():
    """A slot with an empty blob (no plans yet) returns ()."""
    raw = {"d": [[0, 0, "Empty", ""]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_parse_blob_invalid_base64_yields_no_plans():
    """Bad base64 → log + empty plans, not a crash."""
    raw = {"d": [[0, 0, "Bad", "@@not_base64@@"]], "v": 1}
    slot = parse_schedule_batch(raw).slots[0]
    assert slot.plans == ()
    # raw_blob_b64 is still preserved for round-trip / debugging
    assert slot.raw_blob_b64 == "@@not_base64@@"


def test_parse_blob_wrong_length_yields_no_plans():
    """A record with a bad length byte (6 is not in 7/8/9) → reject."""
    import base64
    short = base64.b64encode(b"\xaa\x06\x10\xde\x01\x00").decode()  # len=6 not valid
    raw = {"d": [[0, 0, "Short", short]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_parse_blob_bad_sentinel_yields_no_plans():
    """A record without the AA/ED sentinels → reject the whole slot."""
    import base64
    bad = base64.b64encode(b"\xff\x07\x10\xde\x01\x00\xed").decode()  # wrong start
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_parse_blob_bad_weekday_yields_no_plans():
    """Weekday byte outside 1..7 → reject the slot."""
    import base64
    # weekday = 0 (high nibble 0x00) — out of range
    bad = base64.b64encode(b"\xaa\x07\x00\xde\x01\x00\xed").decode()
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_parse_blob_bad_time_yields_no_plans():
    """time_min outside 0..1439 → reject the slot."""
    import base64
    # time = 0xFFFF = 65535, way out of range
    bad = base64.b64encode(b"\xaa\x07\x10\xff\xff\x00\xed").decode()
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


# ---------------------------------------------------------------------------
# Encoder + round-trip tests.
# ---------------------------------------------------------------------------


def test_encode_empty_plans_returns_empty_string():
    assert encode_schedule_blob(()) == ""


def test_roundtrip_real_slot0_blob():
    """Encode the user's slot-0 plans → decode → identical plans."""
    plans = (
        SchedulePlan(time_min=7 * 60 + 58, weekday_mask=MON | WED, action_type=0),
        SchedulePlan(time_min=17 * 60 + 30, weekday_mask=MON, action_type=0),
        SchedulePlan(time_min=8 * 60, weekday_mask=FRI, action_type=0),
    )
    blob = encode_schedule_blob(plans)
    raw = {"d": [[0, 0, "Spr & Sum Schedule", blob]], "v": 1}
    decoded = parse_schedule_batch(raw).slots[0].plans
    assert decoded == plans


def test_encode_real_slot0_byte_identical():
    """Encoder must produce the exact same base64 the cloud emits, for the
    full slot 0 with All-area + Zone + Edge plans (live 2026-05-08)."""
    plans = (
        SchedulePlan(time_min=7*60+58, weekday_mask=MON|WED, action_type=0),
        SchedulePlan(time_min=17*60+30, weekday_mask=MON, action_type=0),
        SchedulePlan(time_min=16*60, weekday_mask=WED, action_type=1, zone_id=1),
        SchedulePlan(time_min=8*60, weekday_mask=FRI, action_type=0),
        SchedulePlan(time_min=19*60, weekday_mask=SAT, action_type=2,
                     zone_id=1, extra_bytes=b"\x00"),
    )
    expected = "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqggxwBMAAe2qB1DgAQDtqglidCQAAQDt"
    assert encode_schedule_blob(plans) == expected


def test_encode_zone_requires_zone_id():
    """Encoding a Zone (action=1) plan without zone_id raises."""
    plans = (SchedulePlan(time_min=600, weekday_mask=MON, action_type=1, zone_id=None),)
    try:
        encode_schedule_blob(plans)
    except ValueError:
        return
    raise AssertionError("expected ValueError for Zone plan without zone_id")


def test_roundtrip_real_slot1_blob_byte_identical():
    """Slot 1 is a single Mon+Thu plan."""
    plans = (
        SchedulePlan(time_min=9 * 60, weekday_mask=MON | THU, action_type=0),
    )
    expected = "qgcQHAIA7aoHQBwCAO0="
    assert encode_schedule_blob(plans) == expected


def test_encode_rejects_invalid_time():
    plans = (SchedulePlan(time_min=1500, weekday_mask=MON, action_type=0),)
    try:
        encode_schedule_blob(plans)
    except ValueError:
        return
    raise AssertionError("expected ValueError for time_min=1500")


def test_encode_rejects_empty_weekday_mask():
    plans = (SchedulePlan(time_min=600, weekday_mask=0, action_type=0),)
    try:
        encode_schedule_blob(plans)
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty weekday_mask")


def test_build_schedule_set_value_amp_html_escaped():
    """The wire format escapes `&` to `&amp;` (matches the read shape).

    Default ScheduleSlot.mode=0; this slot has no plans so it's encoded
    as a placeholder/empty slot.
    """
    slots = (
        ScheduleSlot(
            slot_id=0,
            name="Spr & Sum Schedule",
            raw_blob_b64="",
            plans=(),
        ),
    )
    json_str = build_schedule_set_value(slots, version=1000)
    assert "Spr &amp; Sum Schedule" in json_str
    assert '"v":1000' in json_str
    # Round-trip via the read decoder for parity.
    import json
    parsed = json.loads(json_str)
    assert parsed == {"d": [[0, 0, "Spr &amp; Sum Schedule", ""]], "v": 1000}


def test_build_schedule_set_value_preserves_mode():
    """Mode round-trips: a slot parsed with mode=1 must re-encode with
    mode=1, NOT 0. Hardcoding 0 here used to flip the active slot off
    on every save.
    """
    slots = (
        ScheduleSlot(slot_id=0, name="Active", raw_blob_b64="", plans=(), mode=1),
        ScheduleSlot(slot_id=1, name="Empty", raw_blob_b64="", plans=(), mode=0),
    )
    json_str = build_schedule_set_value(slots, version=42)
    import json
    parsed = json.loads(json_str)
    assert parsed["d"][0][1] == 1
    assert parsed["d"][1][1] == 0


def test_build_schedule_set_value_full_roundtrip():
    """A built JSON value parses back to the same plans via parse_schedule_batch."""
    import json
    slots = (
        ScheduleSlot(
            slot_id=0,
            name="A",
            raw_blob_b64="",
            plans=(SchedulePlan(time_min=478, weekday_mask=MON | WED, action_type=0),),
        ),
        ScheduleSlot(
            slot_id=1,
            name="",
            raw_blob_b64="",
            plans=(SchedulePlan(time_min=540, weekday_mask=MON | THU, action_type=0),),
        ),
    )
    json_str = build_schedule_set_value(slots, version=2)
    parsed = json.loads(json_str)
    decoded = parse_schedule_batch(parsed)
    assert decoded.version == 2
    assert decoded.slots[0].plans == slots[0].plans
    assert decoded.slots[1].plans == slots[1].plans
