"""Placeholder — tests removed in Task 8 (session-replay rewrite).

The three tests that previously lived here (test_mowing_and_traversal_legs_keys_present,
test_legs_back_compat_key_still_present, test_points_are_lists_of_lists_not_tuples)
guarded the `mowing_legs`, `traversal_legs`, and `legs` keys on
build_picked_session_summary output.  Those keys were emitted by the old
`_summary_trail_legs` which derived legs from `_local_legs` + `summary.track_segments`
via a trail-diff classifier.

Task 8 replaced that path with a single track-derived pipeline: `_summary_trail_legs`
now reads `raw_dict["track"]`, calls `derive_render_legs`, and emits only
`legs_timeline` / `track_first_ts` / `track_last_ts`.  The `legs`, `mowing_legs`,
and `traversal_legs` keys no longer exist on the output — their intent is superseded
by `legs_timeline` which carries role + timestamps per segment.
"""
