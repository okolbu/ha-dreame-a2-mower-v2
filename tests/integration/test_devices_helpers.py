"""Helpers in _devices.py for SN-keyed identifiers and DeviceInfo."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower._devices import (
    map_device_info,
    map_identifiers,
    map_unique_id,
    mower_device_info,
    mower_identifiers,
    mower_unique_id,
)
from custom_components.dreame_a2_mower.const import DOMAIN


def _coord(sn="G2408053AEE0006232", mac="ef:ce:cc:aa:fe:fd",
           model="dreame.mower.g2408", entry_id="abc123"):
    coord = MagicMock()
    coord.sn = sn
    coord.entry.entry_id = entry_id
    client = MagicMock()
    client.serial_number = sn
    client.mac_address = mac
    client.model = model
    coord._cloud = client
    return coord


def test_mower_identifiers_uses_sn():
    assert mower_identifiers(_coord()) == {(DOMAIN, "G2408053AEE0006232")}


def test_mower_identifiers_falls_back_to_mac_when_sn_missing():
    c = _coord(sn=None)
    assert mower_identifiers(c) == {(DOMAIN, "mac:ef:ce:cc:aa:fe:fd")}


def test_mower_identifiers_falls_back_to_entry_id_when_both_missing():
    c = _coord(sn=None, mac=None)
    assert mower_identifiers(c) == {(DOMAIN, "entry:abc123")}


def test_map_identifiers():
    assert map_identifiers(_coord(), 0) == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_mower_unique_id():
    assert mower_unique_id(_coord(), "battery") == "G2408053AEE0006232_battery"


def test_map_unique_id():
    assert (
        map_unique_id(_coord(), 1, "lidar_top_down")
        == "G2408053AEE0006232_map_1_lidar_top_down"
    )


def test_mower_device_info_shape():
    info = mower_device_info(_coord())
    assert info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}
    assert info["manufacturer"] == "Dreame"
    assert info["model"] == "dreame.mower.g2408"
    assert info["serial_number"] == "G2408053AEE0006232"


def test_map_device_info_shape():
    info = map_device_info(_coord(), 0, name="Front Lawn")
    assert info["identifiers"] == {(DOMAIN, "G2408053AEE0006232_map_0")}
    assert info["via_device"] == (DOMAIN, "G2408053AEE0006232")
    # Per-map device names are always prefixed with the integration's
    # display name so per-map entity_ids land in the
    # ``dreame_a2_mower_map_N_*`` namespace.
    assert info["name"] == "Dreame A2 Mower Front Lawn"


def test_map_device_info_default_name_when_none():
    info = map_device_info(_coord(), 1, name=None)
    # When MapData has no user name, fall back to "Map N+1" — and still
    # prefix with the integration's display name.
    assert info["name"] == "Dreame A2 Mower Map 2"
