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

## The `80001` angle (candidate alternatives — untested)

Reads in our integration already dodge `80001` via batch device-data + OSS
(the CloudState path). What still `80001`s is the realtime `action`/props RPC.
Alternatives on the *other* backends, worth evaluating later:

- **Read:** `dreame-user-iot/iotstatus/props` (B) or an Aliyun device-shadow
  read (C) — both likely serve last-known props with no `80001`.
- **Write/command:** `/device/sendCommand` or `dreame-user-iot/iotuserdata/setDeviceData` (B).
- **Notifications:** `dreame-message-push/v2/message-record/list` (B) — the
  user's own stored push history; may carry the originating code alongside the
  text (would map `s2p2` codes ↔ notification texts empirically).

**Gating issue:** all of these need backend-B/C auth (Dreame OAuth + Aliyun
session), which is a different flow than our miio-style login. Not a drop-in.

## Open questions / next steps

1. Firm up the proxyman TLS-decrypt, then capture **one** clean round-trip
   each for `iotstatus/props`, `setDeviceData`/`sendCommand`, and
   `message-record/list` to pin request/response shapes (go gently — avoid
   rate-limit/lockout).
2. Confirm whether an Aliyun shadow read returns mower props while the device
   sleeps (the `80001` case).
3. Confirm whether `message-record/list` items include the source fault code.
