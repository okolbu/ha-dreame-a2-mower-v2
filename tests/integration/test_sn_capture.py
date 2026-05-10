"""SN capture in DreameA2CloudClient._handle_device_info."""
from custom_components.dreame_a2_mower.cloud_client import (
    DreameA2CloudClient,
)


def test_sn_captured_from_device_info():
    proto = DreameA2CloudClient.__new__(DreameA2CloudClient)
    proto._strings = None
    info = {
        "did": "BM169439",
        "model": "dreame.mower.g2408",
        "uid": "-112293549",
        "host": "10000.mt.eu.iot.dreame.tech",
        "mac": "EF:CE:CC:AA:FE:FD",
        "sn": "G2408053AEE0006232",
        "property": "",
    }
    # Patch _ensure_strings so the index lookups resolve.
    proto._ensure_strings = lambda: {
        8: "uid", 9: "host", 10: "property", 11: "stream_key", 35: "model",
    }
    proto._handle_device_info(info)
    assert proto.serial_number == "G2408053AEE0006232"


def test_sn_missing_logs_warning_and_sets_none(caplog):
    proto = DreameA2CloudClient.__new__(DreameA2CloudClient)
    info = {
        "did": "BM169439", "model": "dreame.mower.g2408",
        "uid": "u", "host": "h", "mac": None, "property": "",
    }
    proto._ensure_strings = lambda: {
        8: "uid", 9: "host", 10: "property", 11: "stream_key", 35: "model",
    }
    proto._handle_device_info(info)
    assert proto.serial_number is None
    assert "sn missing" in caplog.text.lower()
