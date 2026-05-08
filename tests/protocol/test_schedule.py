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
        {"d": [[id, ?, name, blob_b64], ...], "v": version}
    """
    raw = {
        "d": [
            [0, 0, "Spr & Sum Schedule", "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="],
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
    assert result.slots[1].slot_id == 1
    assert result.slots[1].name == ""


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


def test_parse_real_blob_slot0_three_plans():
    """Spr & Sum slot has 3 plans:
       07:58 All-area, Mon+Wed
       17:30 All-area, Mon
       08:00 All-area, Fri
    The Mon+Wed plan emits 2 records (one per weekday) and gets coalesced
    on decode.
    """
    raw = {
        "d": [[0, 0, "Spr & Sum Schedule", "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="]],
        "v": 1,
    }
    plans = parse_schedule_batch(raw).slots[0].plans
    assert plans == (
        SchedulePlan(time_min=7 * 60 + 58, weekday_mask=MON | WED, action_type=0),
        SchedulePlan(time_min=17 * 60 + 30, weekday_mask=MON, action_type=0),
        SchedulePlan(time_min=8 * 60, weekday_mask=FRI, action_type=0),
    )


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
    """A blob whose byte-length isn't a multiple of 7 → reject."""
    import base64
    short = base64.b64encode(b"\xaa\x07\x10\xde\x01\x00").decode()  # only 6 bytes
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


def test_roundtrip_real_slot0_blob_byte_identical():
    """Encoding the user's slot-0 plans should produce the EXACT same
    base64 bytes as the cloud sent — no order drift, no padding diff."""
    plans = (
        SchedulePlan(time_min=7 * 60 + 58, weekday_mask=MON | WED, action_type=0),
        SchedulePlan(time_min=17 * 60 + 30, weekday_mask=MON, action_type=0),
        SchedulePlan(time_min=8 * 60, weekday_mask=FRI, action_type=0),
    )
    expected = "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="
    assert encode_schedule_blob(plans) == expected


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
    """The wire format escapes `&` to `&amp;` (matches the read shape)."""
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
