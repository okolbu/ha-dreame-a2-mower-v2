# Data policy — persistent / volatile / computed

Per spec §8, every `MowerState` field has a documented unknowns
policy. This doc is the index, kept in sync with the source-of-truth
docstrings in `custom_components/dreame_a2_mower/mower/state.py`.

## Persistent fields (RestoreEntity, last-known across HA boot)

(populated in F1.2.1 onward as fields are added)

## Volatile fields (unavailable when source is None)

(populated in F1.2.1 onward)

## Computed fields (inherits source's policy)

(populated in F1.2.1 onward)
