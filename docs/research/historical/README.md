# Historical raw source preservation

These files are **the pre-axis-2 raw source** for two layered-findings docs that
got restructured into the slim+journal+canonical triad. The axis-2 migration was
deliberately editorial — the destinations RESHAPE the prose (distilling
cross-cutting summaries into the slim doc, lifting dated saga entries into
journal topics, lifting per-slot semantic into inventory rows for canonical).

Because the destinations are editorial restructures rather than verbatim
extracts, a strict substring-match completeness audit between source and
destinations is a poor proxy for "was content preserved" — most paragraphs are
preserved as content but not as exact substrings. The audit is documented in
`tools/journal_completeness_check.py` and remains useful for catching genuine
omissions of distinctive prose; it is NOT acceptance-gating for axis 2 because
the migration's editorial nature makes 100% substring match unattainable.

These files are kept here so that:

1. Future contributors can re-read the original layered-findings prose if
   needed.
2. Any specific finding the migration may have under-preserved is recoverable
   directly.
3. The audit-tool development effort isn't wasted — the tool stays available
   for tasks where strict substring preservation IS the right gate (e.g.,
   migrating a config file).

Do not edit these files. They are immutable historical record. Updates go to
the live destinations:

- `docs/research/g2408-protocol.md` — slim hybrid overview
- `docs/research/g2408-research-journal.md` — topic-clustered investigation history
- `docs/TODO.md` — open work
- `docs/research/inventory/inventory.yaml` (rendered to `inventory/generated/g2408-canonical.md`) — per-slot reference

## Files in this directory

| File | Original location | Lines | Replaced by |
|------|-------------------|-------|-------------|
| `g2408-protocol-PRESERVED-RAW-2026-05-06.md` | `docs/research/g2408-protocol.md` | 1821 | slim protocol + journal + canonical |
| `TODO-PRESERVED-RAW-2026-05-06.md` | `docs/TODO.md` | 1082 | slim TODO + journal |
