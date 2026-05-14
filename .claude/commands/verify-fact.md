---
description: Record a wire-verified fact about a protocol surface, updating inventory.yaml's status + verifications list.
argument-hint: <surface-key> [claim=...] [evidence=...] [status=verified|retracted]
---

You are recording an authoritative verification about a protocol surface. The
project's source of truth is
`custom_components/dreame_a2_mower/inventory.yaml`; the goal of this command is
to make updating it the path of least resistance after a wire test or a
protocol-RE finding.

## Arguments

The arguments after `/verify-fact` follow this loose form (parse heuristically,
ask for any missing required field):

- **surface-key** (REQUIRED, positional) — entry id in inventory.yaml, e.g.
  `s6p2`, `s2p56`, `e4.1` (event), or `cfg.PRE`.
- **claim=** (REQUIRED, quoted if it contains spaces) — one-line statement of
  what's been verified. Example: `claim="byte[2] cleanly toggles with EdgeMaster on both maps"`.
- **evidence=** (REQUIRED) — pointer to where the verification was observed.
  Format: `<log_file>@<HH:MM:SS>` OR `app-screenshot:<filename>` OR
  `apk:<reference>`. Example: `evidence=probe_log_20260510_190812.jsonl@20:10:48`.
- **status=** (OPTIONAL, default `verified`) — one of `verified`, `partial`
  (decoded with gaps), `presumed` (hypothesis only), `retracted` (this entry's
  prior claim is being withdrawn).
- **retracts=** (OPTIONAL, only when status=retracted) — quoted text of the
  prior claim being withdrawn.

If any REQUIRED argument is missing, list what's missing and stop — do not
guess values.

## What the command does

1. **Pick the inventory file** based on the surface-key prefix:
   - `entity:<id>` → `custom_components/dreame_a2_mower/entity-inventory.yaml`
     (strip the `entity:` prefix when matching `id:`)
   - everything else → `custom_components/dreame_a2_mower/inventory.yaml`

   **Locate the entry** matching `id: "<surface-key>"`. If the entry does
   not exist, print:
   ```
   No inventory entry for <key>. Create one before verifying? (y/n)
   ```
   and wait. If yes, scaffold a minimal entry (id, siid, piid, name, category,
   payload_shape — these can be derived from probe data the user supplies) and
   then proceed.

2. **Update `status.last_seen`** to today's ISO date (read from the runtime,
   not from the user's wording — current date is in the system context).

3. **Append a record under a `verifications:` list** on the entry. If the list
   does not exist yet, create it. The record shape:

   ```yaml
   verifications:
     - date: "<YYYY-MM-DD>"
       claim: "<one-line claim>"
       evidence: "<log_file>@<ts>" or "app-screenshot:..." or "apk:..."
       status: verified | partial | presumed | retracted
       retracts: "<prior-claim>"   # only when status=retracted
   ```

4. **If status=retracted**, ALSO scan the entry's `semantic: |` prose for any
   text that asserts the retracted claim. Flag (do not auto-edit) those lines
   so the user can update the narrative consistent with the retraction. Print
   the line numbers and quoted matches.

5. **Show the diff** (using Read + Edit or by displaying the changed lines)
   and write the changes. Do NOT commit — leave the working tree dirty so the
   user reviews before staging.

6. **Print a confirmation**:

   ```
   verify-fact: <surface-key> ← <status> on <date>
     evidence: <evidence>
     claim: <claim>
     diff: M custom_components/dreame_a2_mower/inventory.yaml
   ```

## Schema details (so you edit the right shape)

- The entry id is the key after `id: "..."` under the `properties:` /
  `events:` / `actions:` lists at the top of `inventory.yaml`. Use `grep -n
  'id: "<surface-key>"' custom_components/dreame_a2_mower/inventory.yaml` to
  locate.
- Indentation: the entry itself is `  - id: ...` (two spaces). Nested fields
  on the entry are four spaces deep. The new `verifications:` list goes at
  four spaces deep, alongside `status`, `references`, etc. Its records are at
  six spaces deep.
- Keep `verifications:` immediately after `status:` for readability.
- `last_seen` lives under `status:` and is a quoted ISO date string.

## What this command does NOT do

- Does not commit. Leaves the working tree dirty so the user reviews.
- Does not regenerate `docs/research/inventory/generated/g2408-canonical.md` —
  that's `tools/inventory_gen.py`, run separately if the user wants the
  rendered doc refreshed.
- Does not run the audit. If a CI check on `inventory.yaml` needs to pass
  before commit, run `python tools/inventory_audit.py --consistency`
  manually.

## Examples

Wire-truth:
```
/verify-fact s6p2 claim="byte[2] toggles cleanly Off→On→Off on map1, then map2 after switch" evidence=probe_log_20260510_190812.jsonl@20:10:48
/verify-fact s6p2 status=partial claim="byte[3] usually 2 but observed 198 during mid-mow efficiency change" evidence=probe_log_20260419_130434.jsonl@2026-05-10T17:04:16
```

Integration-entity:
```
/verify-fact entity:switch.map_N_edgemaster claim="reads per-map shadow correctly; tracks app saves on both maps" evidence=probe_log_20260510_190812.jsonl@20:10:48–20:12:34
```

For retractions, prefer the `/retract` shortcut, but `status=retracted`
also works here:
```
/verify-fact s6p2 status=retracted retracts="byte[3] is constant 2" claim="byte[3] not strictly constant" evidence=probe_log_20260419_130434.jsonl@2026-05-10T17:04:16
```

## Failure modes to surface

If you find yourself about to invent argument values, STOP and ask the user.
Verifications must trace to real evidence. A fabricated entry is worse than
no entry.
