"""Probe-log replay iterator.

Consumes a `.jsonl` probe-log file and yields one ProbeLogEvent per
MQTT `properties_changed` message, with the message's siid/piid/value
extracted for downstream decoding.

The probe tool (probe_a2_mqtt.py) writes one JSON object per line. Lines whose
"type" is not "mqtt_message" are skipped (session_start, pretty annotations,
api_probe records, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class ProbeLogEvent:
    timestamp: str
    method: str
    siid: int
    piid: int
    value: Any


def iter_probe_log(path: str | Path) -> Iterator[ProbeLogEvent]:
    """Yield ProbeLogEvent for each properties_changed message in a probe log."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "mqtt_message":
                continue
            parsed_data = obj.get("parsed_data", {})
            if parsed_data.get("method") != "properties_changed":
                continue
            for param in parsed_data.get("params") or []:
                siid = param.get("siid")
                piid = param.get("piid")
                if siid is None or piid is None:
                    continue
                yield ProbeLogEvent(
                    timestamp=obj.get("timestamp", ""),
                    method=parsed_data["method"],
                    siid=int(siid),
                    piid=int(piid),
                    value=param.get("value"),
                )
