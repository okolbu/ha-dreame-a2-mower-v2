---
description: Record a retraction of a prior claim about a protocol surface or HA entity, updating the corresponding inventory with the retraction record + reason.
argument-hint: <surface-key> retracts="<prior claim>" reason="<why>"
---

You are recording a retraction. A prior claim about a protocol surface
or HA entity is being withdrawn. The retraction itself is the event —
no new evidence is required, but the prior claim text must be quoted
verbatim (or close enough that a grep against the entry's prose finds
it) so the agent can flag related text for review.

## Arguments

- **surface-key** (REQUIRED, positional) — entry id. For wire-truth
  retractions, use the inventory.yaml entry id directly: `s6p2`, `s2p56`.
  For entity-handling retractions, prefix with `entity:` —
  `entity:switch.edgemaster`, `entity:select.map_N_edge_walk_mode`.
- **retracts=** (REQUIRED, quoted) — the prior claim text being
  withdrawn. Should be specific enough that grep finds it in the entry's
  `semantic:` prose or in a prior `verifications:` record.
- **reason=** (REQUIRED, quoted) — why the prior claim is wrong.
  Reference an event, log line, or observation when possible.

## What the command does

1. **Pick the inventory file** based on the surface-key prefix:
   - `entity:<id>` → `custom_components/dreame_a2_mower/entity-inventory.yaml`
   - everything else → `custom_components/dreame_a2_mower/inventory.yaml`

2. **Locate the entry** by `id:` match.

3. **Update `status.last_seen`** to today's ISO date.

4. **Append a retraction record under `verifications:`**:
   ```yaml
   verifications:
     - date: "<YYYY-MM-DD>"
       status: retracted
       claim: "<short replacement, or 'see reason below' if no new claim>"
       retracts: "<exact prior-claim text>"
       reason: "<why retracted>"
   ```

5. **Scan the entry's `semantic:` block** for any prose matching the
   `retracts:` text. For each match, print the line number and quoted
   line — do NOT auto-edit. The user reviews and rewords.

6. **Also scan `references.docs:`** and any linked doc files for the
   same prose. Print matches the same way. Common drift spots:
   `docs/research/g2408-protocol.md`, `docs/research/g2408-research-journal.md`,
   `docs/research/entity-validation-matrix.md`.

7. **Show the diff** for the inventory file and write it. Do NOT
   commit. Leave the working tree dirty.

8. **Print a summary**:
   ```
   retract: <surface-key> — prior claim withdrawn
     retracts: "<...>"
     reason: "<...>"
     diff: M <inventory-file>
     review needed in:
       <doc>:line <prose>
       <doc>:line <prose>
   ```

## Examples

```
/retract s6p2 retracts="byte[3] is constant 2" reason="198 outlier 2026-05-10 17:04:16 during mid-mow efficiency change"
/retract s6p2 retracts="properties_changed is value-deduped" reason="3 noop saves at 21:08 emitted identical s6p2 frames"
/retract entity:switch.edgemaster retracts="surfaces the EdgeMaster state" reason="actually shows only the active-map value; per-map switch is the correct surface"
```

## Honesty constraint

The `retracts:` text must be quotable from the prior state — paraphrasing
is fine but the retraction record should match what the agent / user
would have read before this retraction. If the retraction is so vague
that no specific prior claim can be quoted, ask the user to clarify.

## Companion

The reverse operation — recording a positive verification — is
`/verify-fact`. See `.claude/commands/verify-fact.md` for that shape.
The fact-discipline rule that makes both commands mandatory in
practice is in `CLAUDE.md`.
