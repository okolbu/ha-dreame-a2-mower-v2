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
2. **RESOLVED 2026-05-26 — `device-messages/v2` is the empirical-mapping
   endpoint.** `GET /dreame-messaging/user/device-messages/v2?did=…&pageNum=…&pageSize=…`
   returns a Spring Pageable envelope; each record carries
   `source: {siid, piid, value, eiid, aiid}` (value as **string**) and
   `localizationContents` (en/de/fr/ru/fi/… — auto-localised to the
   account language, which sidesteps having to ship texts in the
   integration). 7 distinct `s2p2` → text mappings recovered from the
   user's recent history; full table in
   `app-notification-history-2026-05-16.md § Empirical s2p2 mapping`.
   The cloud's retention is short (~10 records, ~6-7 days), so any code
   that fires while we aren't listening can be lost — argues for an
   "MQTT-triggered fetch latest" pattern rather than periodic catch-up.
   `message-record/list` with `categories ∈ {1..5}` returned `code=0
   records=0` — that endpoint is not where mower notifications live;
   System / Sharing / Service / Activity tabs in the app are user-account
   scoped, not per-device.
3. Whether writes/actions have an 80001-resilient path (`setDeviceData` /
   `sendCommand` variants) — separate, side-effecting test.

## Appendix: full endpoint catalog (233)

233 relative paths extracted by `strings` on `libapp.so`, split by structural classification:

- **API endpoints** (191): live under a `/dreame-*` microservice or `/device/<verb>` — real cloud calls on `{cc}.iot.dreame.tech:13267` (confirmed via mova's decoded `DREAME_STRINGS` and our own `cloud_client`).
- **Flutter routes** (42): Navigator targets baked into the Dart binary — single-segment `snake_case` paths and non-`dreame-*` prefixes (`/device_*`, `/connect-*`, `/account`, etc.). Do NOT hit a server.

### API endpoints (191 paths, 13 service prefixes)

```
# /dreame-user  (58)
/dreame-user/alldata/download/enable
/dreame-user/alldata/download/submit
/dreame-user/dialog/alertRemind
/dreame-user/dialog/submit
/dreame-user/home/app
/dreame-user/overseas/shopping/mall/user/shopify
/dreame-user/public/user/bind/switch
/dreame-user/v1/avatarGreen
/dreame-user/v1/contacts
/dreame-user/v1/contacts/
/dreame-user/v1/email/unbind
/dreame-user/v1/feedback
/dreame-user/v1/feedback/gen-upload-url?filename=
/dreame-user/v1/forgotpass/email/code
/dreame-user/v1/forgotpass/email/code/verification
/dreame-user/v1/forgotpass/sms/code/verification
/dreame-user/v1/genShareLink
/dreame-user/v1/info
/dreame-user/v1/logoff
/dreame-user/v1/phone/unbind
/dreame-user/v1/phone/unbind/sms/code/verification
/dreame-user/v1/privacy/agree
/dreame-user/v1/query
/dreame-user/v1/register/email
/dreame-user/v1/register/sms/verification
/dreame-user/v1/secure-info-new
/dreame-user/v1/secure-info/email/code/verification
/dreame-user/v1/secure-info/sms/code/verification
/dreame-user/v1/set-birthday
/dreame-user/v1/set-country
/dreame-user/v1/set-sex
/dreame-user/v1/social/bind
/dreame-user/v1/social/binds
/dreame-user/v1/social/unbind
/dreame-user/v1/userext/info
/dreame-user/v1/userext/oauth/list
/dreame-user/v1/userext/oauth/save
/dreame-user/v1/userext/subscribe
/dreame-user/v2/change-password
/dreame-user/v2/forgotpass/reset-by-email
/dreame-user/v2/forgotpass/reset-by-sms
/dreame-user/v2/forgotpass/sms/code4
/dreame-user/v2/phone/unbind/sms/code
/dreame-user/v2/register/email/bind/code
/dreame-user/v2/register/email/bind/verification
/dreame-user/v2/register/email/check/code
/dreame-user/v2/register/email/check/verification
/dreame-user/v2/register/email/code
/dreame-user/v2/register/email/verification
/dreame-user/v2/register/phone
/dreame-user/v2/register/sms
/dreame-user/v2/registerConfig/noSmsReg
/dreame-user/v2/secure-info/email/code-new
/dreame-user/v2/secure-info/sms/code
/dreame-user/v2/secure-info/sms/code-new
/dreame-user/v2/set-password
/dreame-user/v3/aftersale
/dreame-user/v3/register/email

# /dreame-user-iot  (58)
/dreame-user-iot/iotmqttdomain/v2/list
/dreame-user-iot/iotstatus/devOTCInfo
/dreame-user-iot/iotstatus/props
/dreame-user-iot/iotuserbind/checkDeviceBind
/dreame-user-iot/iotuserbind/device/del
/dreame-user-iot/iotuserbind/device/delShared
/dreame-user-iot/iotuserbind/device/getDeviceListByHomeV2
/dreame-user-iot/iotuserbind/device/info
/dreame-user-iot/iotuserbind/device/listV2
/dreame-user-iot/iotuserbind/device/rename
/dreame-user-iot/iotuserbind/device/shareCheck
/dreame-user-iot/iotuserbind/device/shareWithPermissions
/dreame-user-iot/iotuserbind/device/sharedUserList
/dreame-user-iot/iotuserbind/deviceLogPackage
/dreame-user-iot/iotuserbind/devicePermit
/dreame-user-iot/iotuserbind/pair
/dreame-user-iot/iotuserbind/pair4ble
/dreame-user-iot/iotuserbind/pairByNonce
/dreame-user-iot/iotuserbind/pairQRKey
/dreame-user-iot/iotuserbind/queryDevicePermit
/dreame-user-iot/iotuserdata/setDeviceData
/dreame-user-iot/smarthome/home
/dreame-user-iot/smarthome/home/addOrUpdate
/dreame-user-iot/smarthome/home/checkRoomUpdate
/dreame-user-iot/smarthome/home/deleteHome
/dreame-user-iot/smarthome/home/selectHome
/dreame-user-iot/smarthome/home/syncRoomFromVacuum
/dreame-user-iot/smarthome/home/updateHomeIndex
/dreame-user-iot/smarthome/room
/dreame-user-iot/smarthome/room/addOrUpdate
/dreame-user-iot/smarthome/room/deleteRoom
/dreame-user-iot/smarthome/room/getRoomTemplate
/dreame-user-iot/smarthome/room/selectDevice
/dreame-user-iot/smarthome/room/updateRoomIndex
/dreame-user-iot/smarthome/scene
/dreame-user-iot/smarthome/scene-log/getLog
/dreame-user-iot/smarthome/scene/action/getDeviceCommand
/dreame-user-iot/smarthome/scene/createSceneTemplate
/dreame-user-iot/smarthome/scene/deleteCommandAction
/dreame-user-iot/smarthome/scene/deleteSceneV2
/dreame-user-iot/smarthome/scene/getCustomTemplateList
/dreame-user-iot/smarthome/scene/getCustomTemplateMoreList
/dreame-user-iot/smarthome/scene/getDeviceCommand
/dreame-user-iot/smarthome/scene/getDeviceList
/dreame-user-iot/smarthome/scene/getMallUrl
/dreame-user-iot/smarthome/scene/getMarketingList
/dreame-user-iot/smarthome/scene/getSceneByHomeV2
/dreame-user-iot/smarthome/scene/getSceneDetailV2
/dreame-user-iot/smarthome/scene/openAuto
/dreame-user-iot/smarthome/scene/saveCommandAction
/dreame-user-iot/smarthome/scene/saveDate
/dreame-user-iot/smarthome/scene/saveOrUpdate
/dreame-user-iot/smarthome/scene/saveTime
/dreame-user-iot/smarthome/scene/startSceneAction
/dreame-user-iot/smarthome/scene/trigger/getDeviceCommand
/dreame-user-iot/smarthome/scene/updateSceneActionIndex
/dreame-user-iot/userEvaluate/queryNeedDialog
/dreame-user-iot/userEvaluate/submit

# /dreame-product  (22)
/dreame-product/aduserswitch
/dreame-product/aduserswitch/get
/dreame-product/preRelease/callback
/dreame-product/public/advertisement/v1/list-by-position
/dreame-product/public/advisetag/bycategory
/dreame-product/public/apps/latestByCountry
/dreame-product/public/common-plugin
/dreame-product/public/common-plugin/getCommonPlugins
/dreame-product/public/faqs/pdf
/dreame-product/public/faqs/product
/dreame-product/public/privacy/by-country
/dreame-product/public/privacy/lastVersionListByCountry
/dreame-product/public/privacy/v2
/dreame-product/public/products/
/dreame-product/public/smarthomeManual/list
/dreame-product/public/v1/productCategory
/dreame-product/public/v1/productCategory/by-models
/dreame-product/public/v1/productCategory/by-pids
/dreame-product/public/v1/productCategory/by-pids-with-model
/dreame-product/public/v1/productCategory/checkModel
/dreame-product/upgrades/appplugin
/dreame-product/upgrades/sdk

# /dreame-message-push  (15)
/dreame-message-push/v1/message-record
/dreame-message-push/v1/message-record/homestat
/dreame-message-push/v1/message-record/list
/dreame-message-push/v1/message-record/mark-allmessages-read
/dreame-message-push/v1/message-record/mark-messages-read
/dreame-message-push/v1/message-record/remove-all-messages
/dreame-message-push/v1/message-record/remove-messages
/dreame-message-push/v1/message-set
/dreame-message-push/v2/message-record
/dreame-message-push/v2/message-record/homestat
/dreame-message-push/v2/message-record/list
/dreame-message-push/v2/message-record/mark-messages-read
/dreame-message-push/v2/message-record/remove-all-messages
/dreame-message-push/v2/message-record/remove-messages
/dreame-message-push/v2/message-set

# /dreame-messaging  (15)
/dreame-messaging/user/device-messages
/dreame-messaging/user/device-messages/mark-read-by-deviceid
/dreame-messaging/user/device-messages/v2
/dreame-messaging/user/device-messages/v2/mark-read-by-deviceid
/dreame-messaging/user/message-settings
/dreame-messaging/user/message-settings/v2
/dreame-messaging/user/push/devices/evictKey
/dreame-messaging/user/push/devices/manusave
/dreame-messaging/user/share-messages
/dreame-messaging/user/share-messages/
/dreame-messaging/user/share-messages/device/ack
/dreame-messaging/user/share-messages/v2
/dreame-messaging/user/share-messages/v2/
/dreame-messaging/user/switch-settings/query
/dreame-messaging/user/switch-settings/saveOrUpdate

# /dreame-auth  (8)
/dreame-auth/countryCode
/dreame-auth/oauth/authCode
/dreame-auth/oauth/logout
/dreame-auth/oauth/token
/dreame-auth/v2/oauth/sms
/dreame-auth/v2/oauth/social/register/sms
/dreame-auth/v2/oauth/social/sms
/dreame-auth/v3/oauth/social/autoregisterbind/sms

# /dreame-third-video  (7)
/dreame-third-video/tx/dev/getP2PInfo
/dreame-third-video/tx/dev/isDevUser
/dreame-third-video/tx/dev/pair
/dreame-third-video/tx/dev/setShare
/dreame-third-video/tx/mgr/dev/getIdentity
/dreame-third-video/tx/mgr/family/getFamilyId
/dreame-third-video/tx/user/accesstoken

# /dreame-system  (2)
/dreame-system/appCommonUrl/queryUrlByCountryBatch
/dreame-system/dreame-app/setting/query

# /dreame-third-proxy  (2)
/dreame-third-proxy/thirdProxy/queryDeviceMaintenanceRecords
/dreame-third-proxy/thirdProxy/queryThirdProxyUrl

# /device  (1)
/device/sendCommand

# /dreame-iot-com-  (1)
/dreame-iot-com-

# /dreame-log  (1)
/dreame-log/common/log/report

# /dreame-mqtt-log  (1)
/dreame-mqtt-log/appLog

```

### Flutter routes (in-app navigation, NOT API) (42 paths, 38 service prefixes)

```
# /app  (2)
/app/voiceControlAlexa?link=
/app/voiceControlSiri?name=

# /device_share  (2)
/device_share
/device_share/add_contacts

# /device_sharing  (2)
/device_sharing/contacts_detail
/device_sharing/search_list

# /product_main  (2)
/product_main
/product_main/trigger_page

# /account_setting  (1)
/account_setting

# /connect  (1)
/connect/device/productQR

# /connect-instructions  (1)
/connect-instructions

# /connect-instructions-new  (1)
/connect-instructions-new

# /device_accepted  (1)
/device_accepted/device_detail

# /device_machine_setting  (1)
/device_machine_setting

# /device_message  (1)
/device_message

# /device_notification_setting  (1)
/device_notification_setting

# /device_offline_tips_page  (1)
/device_offline_tips_page

# /device_server_info  (1)
/device_server_info

# /product_air_quality_trigger  (1)
/product_air_quality_trigger&

# /product_device_condition_settings  (1)
/product_device_condition_settings

# /product_device_selection  (1)
/product_device_selection

# /product_device_trigger  (1)
/product_device_trigger

# /product_environment_trigger  (1)
/product_environment_trigger

# /product_explore  (1)
/product_explore

# /product_humidity_trigger  (1)
/product_humidity_trigger

# /product_list  (1)
/product_listD

# /product_manual_page  (1)
/product_manual_page

# /product_manual_viewer_page  (1)
/product_manual_viewer_page

# /product_scene_creation  (1)
/product_scene_creation

# /product_scene_template_empty  (1)
/product_scene_template_empty

# /product_scene_template_list  (1)
/product_scene_template_list

# /product_setting_main  (1)
/product_setting_main

# /product_specific_time_trigger  (1)
/product_specific_time_trigger

# /product_suggest_page  (1)
/product_suggest_page

# /product_temperature_trigger  (1)
/product_temperature_trigger

# /user_change_password  (1)
/user_change_password

# /user_delete_account  (1)
/user_delete_account

# /user_mail_seting  (1)
/user_mail_seting

# /user_name_seting  (1)
/user_name_seting

# /user_phone_seting  (1)
/user_phone_seting

# /user_setting_password  (1)
/user_setting_password

# /user_third_account_seting  (1)
/user_third_account_seting

```

