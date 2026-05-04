# Cutover runbook — legacy → greenfield

This document describes how to swap the legacy
`okolbu/ha-dreame-a2-mower-legacy` integration for the greenfield
`okolbu/ha-dreame-a2-mower`. Run the spec §6 parity checklist
first; cut over only after every item passes.

## Pre-flight

1. **Capture session and LiDAR archives.** The legacy integration
   stores archives at `/config/dreame_a2_mower/{sessions,lidar}/`. Back
   them up to a tarball or another path. The greenfield integration
   uses the SAME paths so archives are picked up automatically — the
   backup is insurance against a botched swap.

2. **Snapshot the legacy config-entry options** from
   Settings → Devices & Services → Dreame A2 Mower → Configure. Note
   retention caps and MQTT-archive enable flag.

3. **Confirm the parity checklist passes.** Spec §6 lists 48 items.
   Each should demonstrably work in greenfield before cutover.

## Cutover steps

1. Stop HA, or at minimum disable the legacy integration in
   Settings → Devices & Services.

2. Remove the legacy custom component:

   ```
   rm -rf /config/custom_components/dreame_a2_mower
   ```

3. Install the greenfield component (HACS or manual git clone). The
   custom-component path stays the same: `dreame_a2_mower`.

4. Restart HA.

5. Re-add the integration via Settings → Devices & Services → ADD
   INTEGRATION → Dreame A2 Mower. Re-enter username/password — these
   are NOT migrated (credential storage is HA-encrypted under the
   config entry, not on disk in a portable form).

6. Set the same options as the legacy snapshot via Configure → Options:
   archive retention caps. (Station bearing is not yet exposed in
   greenfield's options flow; it will be added in a future release.)

7. Verify on the dashboard:
   - Live map renders with the archived dock pin and exclusion zones.
   - Mower state shows correctly (battery, charging, mode).
   - Session archive list is preserved; replay works against existing
     md5s.
   - LiDAR thumbnail will populate after the next `s99p20` push; to
     force one, tap "Download LiDAR map" in the Dreame app.

8. Re-add the bundled Lovelace card resource if you used it before:

   - URL `/dreame_a2_mower/dreame-a2-lidar-card.js`
   - Type `JavaScript Module`

## Rollback

If something is broken:

1. Remove `/config/custom_components/dreame_a2_mower` again.
2. Restore the legacy integration from git or HACS.
3. Restart HA.
4. The archives at `/config/dreame_a2_mower/` are unchanged and will
   pick up under the legacy integration.

The greenfield integration does NOT delete or rewrite archive entries
written by the legacy version.

## Repo cleanup post-cutover

The repo rename has already happened: the legacy integration now
lives at `okolbu/ha-dreame-a2-mower-legacy`, and the greenfield repo
took over the `okolbu/ha-dreame-a2-mower` name. Update any HACS
custom-repository pin accordingly.

## Known greenfield/legacy differences

- Greenfield does not yet implement every settings entity from legacy.
  The dashboard YAML notes which sections are deferred. The
  integration self-reports gaps via `sensor.novel_observations` (F6) —
  attach the diagnostics dump (Settings → Devices & Services → Dreame
  A2 Mower → Download Diagnostics) to a bug report if a feature is
  missing that you depended on.
- Greenfield's session-finalize gate is bounded (30 min max-age, 10
  max-attempts) — a stuck session won't loop forever like legacy did.
  If you need the legacy "hang forever waiting" behavior for
  diagnostics, file an issue.
