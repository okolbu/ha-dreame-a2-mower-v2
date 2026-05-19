# Block 1 — Discovery Findings

**Date:** 2026-05-19
**Status:** in progress — populated task-by-task per plan
**Plan:** `docs/superpowers/plans/2026-05-19-block1-discovery.md`
**Design:** `docs/superpowers/specs/2026-05-19-block1-discovery-design.md`
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Ground truth (meta):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

This document is read-only output of the Block 1 discovery pass. It captures
phase-ready inventories for the four remediation phases (B1a/b/c/d), a
broader sweep of B1 surface findings, and deferred-split sketches for the
four coordinator files >800 LOC.

Every finding uses the format:
`- **[bucket]** \`file.py:LL\` — short description. Evidence: <line>. Disposition: <phase | defer>.`

Buckets: `dead` (remove), `dup` (consolidate), `refactor` (split/simplify), `bug` (fix), `better` (cleaner option).

## 1. B1a — Cleanup inventory

### 1.1 Dead-code candidates
(populated by Task 2)

### 1.2 Silent-swallow log additions
(populated by Task 2)

### 1.3 Uncancelled handles / timers
(populated by Task 2)

### 1.4 Coordinator-mixin import consolidation
(populated by Task 2)

## 2. B1b — Retry helper inventory

### 2.1 Helper contract
(populated by Task 3)

### 2.2 Call sites
(populated by Task 3)

### 2.3 Stacked-loop elimination
(populated by Task 3)

## 3. B1c — `_cached_*` shadow inventory

### 3.1 Every `_cached_*` attribute on the coordinator
(populated by Task 4)

### 3.2 Readers per attribute
(populated by Task 4)

### 3.3 Removal sequence
(populated by Task 4)

## 4. B1d — `cloud_client.py` split plan

### 4.1 Function-by-function placement table
(populated by Task 5)

### 4.2 Module-level state placement
(populated by Task 5)

### 4.3 Test import impact
(populated by Task 5)

## 5. Broader sweep

### 5.1 Refreshers inventory (`_refreshers.py`)
(populated by Task 6)

### 5.2 Settings-write fan-out
(populated by Task 6)

### 5.3 MQTT subscription lifecycle
(populated by Task 6)

### 5.4 Out-of-scope notes (catch-all)
(populated by Task 6)

## 6. Deferred coordinator-split sketches

### 6.1 `coordinator/_core.py`
(populated by Task 7)

### 6.2 `coordinator/_refreshers.py`
(populated by Task 7)

### 6.3 `coordinator/_session.py`
(populated by Task 7)

### 6.4 `coordinator/_mqtt_handlers.py`
(populated by Task 7)
