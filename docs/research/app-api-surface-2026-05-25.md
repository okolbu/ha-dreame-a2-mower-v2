# Dreame app — API surface vs our integration (2026-05-25)

Goal: mine the shipped Android apps to **corroborate and extend** our MQTT +
cloud-API understanding, and look for device-data paths less prone to the
g2408 `80001` ("device unreachable via cloud relay") error.

## Method / provenance

- **Reliable — static APK** (`apks/`, extracted with `unzip` only; no
  jadx/apktool needed):
  - `com.dreame.smartlife 2.5.6.4` is a **Flutter** app. `.apkm`/`.xapk` are
    zip-of-apks → `unzip -p X.apkm base.apk`, then unzip that. Protocol JSON
    lives in `assets/flutter_assets/...`; Dart code (with API path strings)
    is in the arm64 split's `lib/arm64-v8a/libapp.so` (`strings` it).
  - Older `Dreamehome 1.5.41` / `2.1.0.14` are **not** React-Native and
    `uptodown 1.4` is **pre-mower** (no MIoT/fault vocabulary). So the RN-era
    `index.android.bundle` (source of the ioBroker `apk.md` FaultIndex) is in
    **none** of the local apks.
- **Tentative — proxyman/** (`proxyman/*.txt`): a *work-in-progress* TLS
  capture; endpoints "kept moving around" during SSL-decrypt, so what's there
  is one partial slice, not a representative trace. Treat as a lead only.

## Three distinct cloud backends

| # | Backend | Who uses it | Auth | Notes |
|---|---|---|---|---|
| A | `{cc}.iot.dreame.tech` (Xiaomi-miio style) | **our integration** | `DREAME_STRINGS` obfuscated table, host `-10000` | matches MQTT `bindDomain` `10000.mt.eu.iot.dreame.tech`. Batch device-data + OSS reliable; `action`/props → **80001**. |
| B | `app.dreame.tech/dreame-*` microservices | the app | Dreame OAuth (`/dreame-auth/oauth/token`) | account, notifications, smarthome, device-bind. |
| C | `{region}.api-iot.aliyuncs.com` (Aliyun Link IoT) | the app | Aliyun API-GW signing (`x-ca-*`, HmacSHA1, `x-ca-key 33954864`) + `iotToken` from `/account/createSessionByAuthCode` | **tentative (proxyman WIP).** Classic Aliyun device identity seen: `productKey a5RAm2U4V72`, per-device `deviceSecret`. Living Link SDK (`user-agent: ALIYUN-ANDROID-DEMO`). |

Key takeaway: the app does **not** use our backend (A). It rides Dreame OAuth
(B) + an Aliyun Link IoT platform (C). Both B and C maintain a server-side
**device shadow / last-known state**, which is the structural reason they would
return status **without** an `80001` when the mower is asleep.

## App endpoint catalog (static, from `libapp.so`)

233 relative endpoints total; the device/notification-relevant ones:

**`app.dreame.tech/dreame-user-iot/…` (device-IoT ops):**
`iotstatus/props`, `iotstatus/devOTCInfo`, `iotuserdata/setDeviceData`,
`iotmqttdomain/v2/list`, `iotuserbind/device/{info,listV2,getDeviceListByHomeV2,rename,pair,…}`,
`smarthome/{home,room,scene}/…`

**`/device/…`:** `sendCommand`, `device_machine_setting`, `device_message`,
`device_notification_setting`, `device_server_info`, `device_share`.

**`/dreame-message-push/v2/…` (push history):** `message-record/list`,
`message-record/homestat`, `message-record/mark-messages-read`,
`message-record/remove-*`, `message-set`.

**`/dreame-messaging/user/…`:** `device-messages/v2`, `message-settings/v2`,
`switch-settings/{query,saveOrUpdate}`, `share-messages/v2`.

## What this corroborates in our existing findings

- **STATE enum (s2p1)** — `common_mower_protocol.json` `keyDefine "2.1"`
  matches our `value_catalog`; also gives the authoritative `4 = "Paused"`
  (we previously inherited a vacuum `4=ERROR`). See `inventory.yaml § s2p1`.
- **MIoT RPC layer** — `callMethod`, `get_properties`, `set_properties`,
  `properties_changed`, `action` all present in the Dart binary. Our
  `cloud_client` RPC model is correct.
- **IoT/MQTT host** — backend A's `{cc}.iot.dreame.tech` + host `-10000`
  lines up with the live MQTT `bindDomain`.
- **Fault→notification text is cloud-composed** — there is **no** fault (2.2)
  table in any flutter asset and **no** FaultIndex enum names / push texts in
  `libapp.so` or the 1473-key `en.json` (only other device classes). The wire
  carries only the numeric `s2p2`; the words come from the server, surfaced to
  the app via `dreame-message-push/v2/message-record/list`. This is why
  `s2p2` has resisted a month of probe logs. (`server_data_alert` is **not**
  it — that OSS file is a one-off legal "Data Transfer Notice" banner.)

## The `80001` angle — RESOLVED for reads (shadow read beats the relay)

**Reproduced head-to-head, mower docked+asleep, 2026-05-25** (same instant,
same property):

| call | result |
|---|---|
| `get_properties (6,3)` via `dreame-iot-com/device/sendCommand` (relay) | **80001** ("device may be offline, send timed out") |
| `iotstatus/props keys="6.3"` (shadow) | **OK** `[{"key":"6.3","value":"[true,-128]","updateDate":…}]` |

`(6,3)` = `[cloud_connected, rssi]` is exactly what the hourly
`_poll_slow_properties` fetches via the relay — the source of the 113 logged
80001s at `:01`. The relay times out reaching the asleep device; the shadow
returns the last-known value.

**Mechanism: 80001 is property-specific, not timing.** Core slots (`2.1` state,
`3.1` battery, `2.2`) answered OK from the relay in every test (idle, active,
post-60-min-gap); only niche slow-poll slots (`6.3`; `1.5` "mostly") time out
when asleep. Four attempts to trigger 80001 by *timing* (active mow, frequent
sampler, 60-min relay gap) all stayed clean — it was the *property* all along.

**Near drop-in, not a different backend.** `iotstatus/props` lives on
`{cc}.iot.dreame.tech:13267/dreame-user-iot/…` — the **same host + same
Dreame-Auth token our `cloud_client` already uses** (proven: the probe uses the
identical login; mova's `DREAME_STRINGS` lists `iotstatus` under
`dreame-user-iot`). No app-OAuth/Aliyun flow needed for reads. *(Supersedes the
earlier "needs backend-B/C auth" note — wrong for reads.)*

**Caveat — freshness.** Shadow values are last-known and carry `updateDate`. In
this test `6.3` was ~21.6 h stale (`rssi=-128` = sentinel) while `2.1` was
current. Fine for slow diagnostics (cloud_connected/rssi); fast state still
comes from MQTT (the integration's primary). `1.5` (serial) is NOT in the
shadow — but DEV already provides the serial, so moot.

**Recommendation:** switch `_poll_slow_properties`' `s6.3` read from the relay
to `iotstatus/props` (comma-string `keys`, parse `data[].value`), keeping the
relay as fallback — removes the hourly 80001. Writes/actions (also 80001-prone)
are a separate test; a shadow *read* can't substitute for them.

## Open questions / next steps

1. Adopt `iotstatus/props` for the `s6.3` slow-poll (above) behind a fallback;
   measure the 80001-rate drop.
2. `message-record/list` needs a non-empty `categories` list (values unknown) +
   `device-messages/v2` needs GET — pin via one clean capture if we want the
   notification-history → s2p2 mapping.
3. Whether writes/actions have an 80001-resilient path (`setDeviceData` /
   `sendCommand` variants) — separate, side-effecting test.
