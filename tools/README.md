# tools/

Standalone scripts that read or write integration state without
needing a running Home Assistant. Run from the repo root:

```
python3 tools/<script>.py [args]
```

## `recover_sessions.py`

Reconstructs historical session JSONs from the probe-log
(`probe_log_*.jsonl`) corpus.

Each output session lands in `tools/recovered_sessions/` as a
file the integration's replay can render — same schema the live
finalize path writes, including `_local_legs` so the mowed path
draws on replay. The script is idempotent; re-running over the
same probe corpus produces the same filenames (md5 derived from
`start_ts`).

Usage:

```
python3 tools/recover_sessions.py \
    --probe-dir /data/claude/homeassistant/ \
    --out-dir tools/recovered_sessions/
```

### Quirks worth knowing

- **Session boundaries depend on `s2p56` transitions in the probe.**
  Sessions whose end-transition was missed (probe restarted, was
  off, or the firmware silently dropped the push) stay "open" until
  the next start-event; expect inflated `duration_min` for those.
  Inspect the print summary and filter manually if the time looks
  wrong.
- **The synthetic md5 is `rec_<28-hex>`** so it never collides with
  a real cloud md5 and the integration's `(md5, start_ts)` dedup
  always lets recovered entries through.
- **The probe doesn't capture `event_occured`-style cloud-summary
  payloads,** so `areas`, `map_area`, `mode`, `result` come from
  the last-seen s1p4 telemetry frame inside the session window.

### Installing recovered sessions on a live HA

1. Copy the produced `.json` files into
   `/config/dreame_a2_mower/sessions/`.
2. Merge the entries from `index_recovered.json` into the live
   `index.json` (keep the existing entries, just add the recovered
   ones).
3. Reload the integration via Settings → Devices → ⋮ →
   Reload, or via:

```
curl -sX POST -H "Authorization: Bearer $TOKEN" \
    "$HA_HOST/api/config/config_entries/entry/$ENTRY_ID/reload"
```

The replay picker rebuilds its dropdown from the index on next
state push.
