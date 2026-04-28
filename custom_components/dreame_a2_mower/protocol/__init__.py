"""Pure-Python MQTT protocol decoders for the Dreame A2 (g2408) mower."""

from __future__ import annotations

from .config_s2p51 import (
    S2P51DecodeError,
    S2P51Event,
    Setting,
    decode_s2p51,
    encode_s2p51,
)
from .heartbeat import Heartbeat, InvalidS1P1Frame, decode_s1p1
from .properties_g2408 import (
    PROPERTY_MAP,
    ChargingStatus,
    Property,
    StateCode,
    charging_label,
    property_for,
    siid_piid,
    state_label,
)
from .replay import ProbeLogEvent, iter_probe_log
from .telemetry import (
    InvalidS1P4Frame,
    MowingTelemetry,
    Phase,
    decode_s1p4,
)

__all__ = [
    "PROPERTY_MAP",
    "ChargingStatus",
    "Heartbeat",
    "InvalidS1P1Frame",
    "InvalidS1P4Frame",
    "MowingTelemetry",
    "Phase",
    "ProbeLogEvent",
    "Property",
    "S2P51DecodeError",
    "S2P51Event",
    "Setting",
    "StateCode",
    "charging_label",
    "decode_s1p1",
    "decode_s1p4",
    "decode_s2p51",
    "encode_s2p51",
    "iter_probe_log",
    "property_for",
    "siid_piid",
    "state_label",
]
