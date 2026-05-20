"""Guard: the cloud_client package re-exports the public client with its full
method surface. Catches an accidental drop during the B1d mixin split."""
from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def test_public_client_importable_and_complete():
    # One+ representative public member per mixin + the shell, so a dropped
    # mixin (missing base class) fails loudly.
    expected = [
        "login",                              # _auth
        "get_device_info", "get_info",         # _discovery
        "send", "request", "routed_action",    # _rpc
        "fetch_wifi_map", "get_file",          # _oss
        "get_batch_device_datas", "write_chunked_key",  # _batch
        "fetch_full_cloud_state", "set_cfg", "fetch_map",  # _fetchers
        "mqtt_host_port", "disconnect",        # shell
    ]
    missing = [name for name in expected if not hasattr(DreameA2CloudClient, name)]
    assert not missing, f"missing methods after split: {missing}"
