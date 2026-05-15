# Dreame app — A2 mower notification history

Extracted from screenshots `IMG_4519.PNG` through `IMG_4524.PNG`
(captured 2026-05-16 ~01:09 local). Times are local CEST (UTC+2).
Dates are as the app shows them; entries appear newest-first in the
app and are reversed here so the file reads chronologically.

The right-hand column is the most likely `s2p2` code based on the
existing `S2P2_NOTIFICATION_MAP` and protocol-doc table. Codes
marked "UNMAPPED" are notification texts the integration doesn't
yet recognise — leads for new s2p2 codes to identify in the
probe-log corpus.

## Distinct notification texts seen

| App text | Best-fit s2p2 code | Notes |
|---|---|---|
| Mowing task started. | 50 (mowing_started) | manual-start |
| Scheduled mowing task started. | 53 (scheduled_mowing_started) | schedule-trigger |
| Mowing task complete. View work log in the app. | 48 (mowing_complete) | session-end |
| Robot will continue the unfinished task. | 70 (continue_unfinished_task) | post-recharge resume |
| Low battery. Returning to station. | 54 (low_battery_return) | battery threshold |
| Water is detected on the lidar. Rain Protection is activated. Returning to the station. | 56 (rain_protection) | LiDAR sees rain |
| Blades are severely worn. Replace them soon. | 28 (blades_worn) | added 2026-05-15 (a474f83) |
| Robot is working. Scheduled task cancelled. | 63 (schedule_cancelled_busy) | schedule conflict |
| Arrived at maintenance point. | 75 (arrived_at_maintenance_point) | post-cruise dock |
| The robot is on standby outside the station for too long. Automatically returning to the station. | **UNMAPPED** | likely a new code — first observation 2026-05-12 21:00; capture s2p2 around that time to identify |
| Emergency stop is activated. Tap to view the solution. | **UNMAPPED** (likely 23) | apk lists 23=EMERGENCY_STOP; not yet observed/correlated. 4 fires 2026-05-09 21:56-22:18 |

## Chronological log

### 2026-05-09

- 14:31  Mowing task started.
- 15:19  Mowing task complete. View work log in the app.
- 15:38  Mowing task started.
- 15:38  Mowing task complete. View work log in the app.
- 15:40  Mowing task started.
- 16:11  Mowing task complete. View work log in the app.
- 19:00  Scheduled mowing task started.
- 19:13  Mowing task complete. View work log in the app.
- 21:56  Emergency stop is activated. Tap to view the solution.   ← UNMAPPED
- 22:01  Emergency stop is activated. Tap to view the solution.   ← UNMAPPED
- 22:07  Emergency stop is activated. Tap to view the solution.   ← UNMAPPED
- 22:18  Emergency stop is activated. Tap to view the solution.   ← UNMAPPED

### 2026-05-10

- 14:11  Mowing task started.
- 15:11  Low battery. Returning to station.
- 15:20  Mowing task complete. View work log in the app.
- 16:38  Mowing task started.
- 17:23  Mowing task complete. View work log in the app.
- 17:46  Mowing task started.
- 18:31  Low battery. Returning to station.
- 19:03  Mowing task complete. View work log in the app.
- 21:57  Mowing task started.
- 22:59  Low battery. Returning to station.
- 23:49  Robot will continue the unfinished task.

### 2026-05-11

- 00:51  Low battery. Returning to station.
- 01:47  Robot will continue the unfinished task.
- 02:59  Low battery. Returning to station.
- 03:49  Robot will continue the unfinished task.
- 04:54  Low battery. Returning to station.
- 05:45  Robot will continue the unfinished task.
- 06:12  Mowing task complete. View work log in the app.
- 07:58  Scheduled mowing task started.
- 08:58  Low battery. Returning to station.
- 09:52  Robot will continue the unfinished task.
- 10:36  Low battery. Returning to station.
- 11:33  Robot will continue the unfinished task.
- 12:30  Low battery. Returning to station.
- 13:24  Robot will continue the unfinished task.
- 13:33  Water is detected on the lidar. Rain Protection is activated. Returning to the station.
- 17:30  Robot is working. Scheduled task cancelled.
- 17:33  Robot will continue the unfinished task.
- 17:42  Mowing task complete. View work log in the app.

### 2026-05-12

- 17:16  Mowing task started.
- 18:03  Low battery. Returning to station.
- 19:02  Robot will continue the unfinished task.
- 19:49  Mowing task complete. View work log in the app.
- 19:52  Arrived at maintenance point.
- 20:00  Arrived at maintenance point.
- 21:00  The robot is on standby outside the station for too long. Automatically returning to the station.   ← UNMAPPED

### 2026-05-13

- 07:58  Scheduled mowing task started.
- 08:59  Low battery. Returning to station.
- 09:50  Robot will continue the unfinished task.
- 10:26  Mowing task complete. View work log in the app.
- 16:55  Low battery. Returning to station.
- 17:52  Robot will continue the unfinished task.
- 18:56  Low battery. Returning to station.
- 19:50  Robot will continue the unfinished task.
- 20:38  Mowing task complete. View work log in the app.

### 2026-05-14

- 08:00  Scheduled mowing task started.
- 08:41  Low battery. Returning to station.
- 09:31  Robot will continue the unfinished task.
- 10:27  Low battery. Returning to station.
- 11:19  Robot will continue the unfinished task.

### 2026-05-15

- 12:18  Water is detected on the lidar. Rain Protection is activated. Returning to the station.
- 16:18  Robot will continue the unfinished task.
- 16:18  Blades are severely worn. Replace them soon.
- 16:34  Water is detected on the lidar. Rain Protection is activated. Returning to the station.
- 20:34  Robot will continue the unfinished task.
- 20:34  Blades are severely worn. Replace them soon.
- 20:35  Water is detected on the lidar. Rain Protection is activated. Returning to the station.

### 2026-05-16

- 00:35  Robot will continue the unfinished task.
- 00:35  Blades are severely worn. Replace them soon.
- 00:55  Blades are severely worn. Replace them soon.

## How to use this file

When investigating an app notification:
1. Find the timestamp in the chronological log above.
2. Grep the corresponding `probe_log_*.jsonl` for `mqtt_message`
   entries within the same minute.
3. Look at the `siid/piid/value` of any s2p2 push (and surrounding
   properties for context — s1p1, s1p4, s2p1, s2p55, etc.).
4. If the text matches an existing entry in
   `S2P2_NOTIFICATION_MAP`, confirm the code-to-text mapping
   stands.
5. If UNMAPPED in the table above, correlate the timestamp with
   the s2p2 value and add a verification record to
   `inventory.yaml § s2p2`.

## Top investigative leads

1. **Emergency stop notifications** (4 in a 22-min window 2026-05-09
   evening): apk lists code 23=EMERGENCY_STOP; correlate with probe
   log. Note that the integration *constants* don't currently include
   `emergency_stop` in `ALERT_EVENT_TYPES`.
2. **"Standby outside station too long"** (single observation
   2026-05-12 21:00): unique notification, suggests a watchdog
   timer in the firmware. Likely a previously-unobserved s2p2 code.
3. **App-side repeats**: notifications like "Blades are severely
   worn. Replace them soon." appear multiple times the same day
   (2026-05-15: 16:18, 20:34; 2026-05-16: 00:35, 00:55) but only
   one of those (16:18) had a corresponding s2p2=28 in probe — the
   later three are app-side reminders. Confirms the per-repeat
   trigger is NOT a wire event for at least the blade-worn case.
