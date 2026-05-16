# Dashboard minor sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every tab a single-line, full-width title delimiter modelled on the existing "Picked session ---" card, and replace the stale 🚧 Plan-3 placeholders on More Settings with real `entities` cards bound to the live integration entities.

**Architecture:** Single-file YAML edit on `dashboards/mower/dashboard.yaml`. YAML anchors at the top of the file define one per-tab delimiter anchor; each tab's `cards:` list aliases its anchor as the first card. More Settings becomes a stack of ~12 `entities` cards, app-page ordered. No new integration entities, no new tooling.

**Tech Stack:** Home Assistant Lovelace YAML; `marked`-rendered markdown cards with inline HTML; YAML anchors; `mcp__home-assistant__ha_eval_template` for Jinja iteration; `sshpass+scp` for deploy.

---

## Reference: deploy + lint commands

These appear in every task that ends with deploy or lint. Quote verbatim — don't paraphrase.

**Why SCP, not `ha_config_set_dashboard` MCP:** the live dashboard is listed by the MCP as `mode: yaml` (`url_path: lovelace-mower`, file: `dashboards/mower/dashboard.yaml`) and `ha_config_get_dashboard` can read it, but `ha_config_set_dashboard` parses YAML → Python → re-serializes, which flattens YAML anchors. This file relies on anchors (`*tab_header_*`), so an MCP write would silently expand them and the diff would become unreviewable. The workspace repo (`/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml`) stays canonical; SCP keeps it that way.

**Lint (YAML parses):**
```bash
python3 -c "import yaml, sys; yaml.safe_load(open('/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml')); print('OK')"
```
Expected: `OK`.

**Anchor-resolution check (every `*tab_header_*` alias resolves):**
```bash
python3 -c "
import yaml
with open('/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml') as f:
    d = yaml.safe_load(f)
print('views:', len(d['views']))
for v in d['views']:
    first = v.get('cards', [{}])[0]
    # panel-type tabs nest under vertical-stack
    if v.get('type') == 'panel':
        first = first.get('cards', [{}])[0]
    kind = first.get('type')
    content_preview = (first.get('content') or '')[:80].replace(chr(10), ' ')
    print(f\"  {v['title']:<20} first_card={kind:<10} {content_preview}\")
"
```
Expected: every view's first card is `markdown` and the preview shows `<hr` + `## <emoji>` for its tab.

**Deploy to live HA:**
```bash
HOST=$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt)
USER=$(awk 'NR==2' /data/claude/homeassistant/ha-credentials.txt)
PASS=$(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PASS" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
  "$USER@$HOST:/config/dashboards/mower/dashboard.yaml"
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "md5sum /config/dashboards/mower/dashboard.yaml"
```
Expected: scp succeeds, md5 prints.

**Browser-side reload after deploy:** open the dashboard in a browser, three-dot menu → "Reload resources" → hard refresh (Ctrl-Shift-R). The dashboard is YAML-mode, so changes apply on reload without an HA restart. `ha_reload_core` has no `lovelace` target, so a programmatic reload is not available — the browser refresh is the only way.

**Post-deploy HA-side verification (MCP):** after every deploy, call:
- `mcp__home-assistant__ha_check_config` — expected: `{"is_valid": true, "errors": []}`. Catches schema errors HA's loader would silently downgrade.
- `mcp__home-assistant__ha_get_logs(source="system", search="lovelace", limit=5)` — expected: `entries: []`. Catches the `createErrorCardElement` family of render errors (see [[feedback_dashboard_lovelace_cards]]).
- `mcp__home-assistant__ha_get_logs(source="system", search="dreame", limit=10)` — expected: no new ERROR/WARNING entries timestamped after the deploy.

---

### Task 1: Baseline lint + backup

**Files:**
- Read: `/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml`
- Create: `/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.pre-minor.yaml.bak`

- [ ] **Step 1: Lint the current file**

Run the **Lint** command from the Reference section. Confirm `OK`. If it fails, stop — the baseline is broken and that's a different bug.

- [ ] **Step 2: Snapshot the current line count and tab order**

```bash
wc -l /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
grep -n "^  - title:" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
```
Expected: ~1470 lines, 11 tab titles (`Mower`, `Map Selector`, `Settings & Zones`, `Schedule`, `LiDAR`, `WiFi Coverage`, `Sessions`, `More Settings`, `Diagnostics`, `Tools`, `Photo Privacy`). Record both numbers — Task 10 verifies the new file is roughly the same shape.

- [ ] **Step 3: Take a local backup**

```bash
cp /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
   /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.pre-minor.yaml.bak
```
No commit yet — the backup is a working-tree-only safety net, gitignored along with the existing `.bak` siblings.

---

### Task 2: Replace the tab-header anchor block

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` (lines 29–74 — the four `_tab_header_*` anchors and their preceding comment block, ending with the blank line before `title: Dreame A2 Mower`)

- [ ] **Step 1: Read the current anchor block to confirm line range**

Read `dashboards/mower/dashboard.yaml` lines 29–74 and verify it ends with the `_tab_header_lidar` anchor's `_Pick any archived scan…_` italic subtitle line followed by a blank line before `title: Dreame A2 Mower`. If the file has drifted, adjust the line numbers in the Edit below.

- [ ] **Step 2: Replace the block with the 11-tab anchor set**

Edit `dashboards/mower/dashboard.yaml`. Replace the entire block from the comment `# Per-map view header anchor — defined here, aliased from each per-map view` through the end of `_tab_header_lidar`'s subtitle (i.e. the four existing anchors plus their preamble comment) with this new content:

```yaml
# Per-tab title delimiter — defined here as YAML anchors, aliased from
# each tab's first card. Shape mirrors the "## 📊 Picked session — X"
# delimiter the Sessions tab uses for per-session sub-views: a 3px
# horizontal rule, then a single `##` line carrying emoji + tab name,
# optional em-dash + live value (per-map active map, archive count),
# and an inline small-grey-text helper note describing what the tab
# *is*. See docs/superpowers/specs/2026-05-16-dashboard-minor-design.md
# for the per-tab table.
#
# Small grey note uses an inline <span>; HA's markdown card passes
# inline HTML through `marked`. If a future HA version sanitizes the
# style attribute, fall back to <sub>…</sub> (always supported).

_tab_header_mower: &tab_header_mower
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 🤖 Mower — Active map: {{ states('select.dreame_a2_mower_active_map') }} &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">switch on Map Selector</span>

_tab_header_map_selector: &tab_header_map_selector
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 🗺️ Map Selector &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">drives the active map for every per-map tab</span>

_tab_header_settings_zones: &tab_header_settings_zones
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## ⚙️ Settings & Zones — Active map: {{ states('select.dreame_a2_mower_active_map') }} &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">switch on Map Selector</span>

_tab_header_schedule: &tab_header_schedule
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 📅 Schedule — Active map: {{ states('select.dreame_a2_mower_active_map') }} &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">read-only on cloud; switch on Map Selector</span>

_tab_header_lidar: &tab_header_lidar
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 📡 LiDAR &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">archived 3-D point clouds</span>

_tab_header_wifi: &tab_header_wifi
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 📶 WiFi Coverage &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">signal strength as measured during mowing</span>

_tab_header_sessions: &tab_header_sessions
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 📊 Sessions — {{ states('sensor.dreame_a2_mower_archived_session_count') }} archived &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">calendar plus per-session breakdown</span>

_tab_header_more_settings: &tab_header_more_settings
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## ⚙️ More Settings &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">device-wide settings (per-map ones live on Settings & Zones)</span>

_tab_header_diagnostics: &tab_header_diagnostics
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 🩺 Diagnostics &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">health checks and raw state</span>

_tab_header_tools: &tab_header_tools
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 🔧 Tools &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">helpers, services, manual ops</span>

_tab_header_photo_privacy: &tab_header_photo_privacy
  type: markdown
  content: |
    <hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

    ## 🔒 Photo Privacy &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">review and delete AI-obstacle photos</span>
```

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Render-check one anchor's Jinja via MCP**

Call `mcp__home-assistant__ha_eval_template` with template:
```
## 🤖 Mower — Active map: {{ states('select.dreame_a2_mower_active_map') }} &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">switch on Map Selector</span>
```
Expected: `result` contains `Active map: Map 1` (or whichever active map is live).

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: define 11-tab delimiter anchors (Picked-Session shape)"
```

---

### Task 3: Mower / Settings & Zones / Schedule tabs — confirm alias still wired

These three tabs already alias `*tab_header_mower`, `*tab_header_settings_zones`, `*tab_header_schedule` as their first card. With Task 2's anchor rewrite the visible content changes but the YAML structure does not.

**Files:**
- Verify only: `dashboards/mower/dashboard.yaml` near `^  - title: Mower$`, `^  - title: Settings & Zones$`, `^  - title: Schedule$`

- [ ] **Step 1: Confirm each tab's first card is still the alias**

```bash
grep -A2 "^  - title: Mower$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml | head -6
grep -A2 "^  - title: Settings & Zones$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml | head -6
grep -A2 "^  - title: Schedule$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml | head -6
```
Expected: each shows `cards:` followed by `- *tab_header_mower` / `_settings_zones` / `_schedule` within the next few lines.

- [ ] **Step 2: Run the anchor-resolution check**

Run the **Anchor-resolution check** command. Expected: rows for Mower, Settings & Zones, Schedule show `first_card=markdown` with previews starting `<hr` and containing `🤖` / `⚙️` / `📅`.

No edit, no commit — verification only.

---

### Task 4: Map Selector tab — add delimiter, remove "# Pick the active map" intro

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` lines 420–427 (the existing `type: markdown` intro card on Map Selector)

- [ ] **Step 1: Read the tab's current top**

Read lines 416–432. Confirm the first card is the `# Pick the active map` markdown block.

- [ ] **Step 2: Replace the intro card with the alias**

Use Edit on `dashboards/mower/dashboard.yaml`. Replace:
```yaml
    cards:
      - type: markdown
        content: |
          # Pick the active map

          Tap a map to zoom in. Press **Select** to make that map the
          active map for the rest of the dashboard (mowing target,
          schedule, settings). Switching is blocked during an active
          mow — you'll see a notification if the API refuses.
```
with:
```yaml
    cards:
      - *tab_header_map_selector
```

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: Map Selector tab uses unified delimiter"
```

---

### Task 5: LiDAR tab — already aliased; move "Re-tag" reference card to bottom

LiDAR already aliases `*tab_header_lidar`. The only change is that the existing tab-content order has the `### Re-tag a mis-categorized scan` reference card embedded mid-tab. Move it to the bottom so the new header → archive picker → 3D viewer flow reads cleanly.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` lines 742–747 (the `### Re-tag` markdown card)

- [ ] **Step 1: Read the LiDAR tab**

Read lines 724–748. Confirm card order is: header → Archive entities → custom lidar card → Re-tag markdown.

- [ ] **Step 2: Delete the Re-tag card from its current position**

Use Edit to remove:
```yaml
      - type: markdown
        content: |
          ### Re-tag a mis-categorized scan
          Use **Developer Tools → Services** with
          `dreame_a2_mower.move_lidar_scan` — provide `from_map_id`,
          `filename` (from picker option text), `to_map_id`.
```

- [ ] **Step 3: Re-add the same card immediately before the next `^  - title: WiFi Coverage$` block**

Use Edit to insert (just before the `  - title: WiFi Coverage` line):
```yaml
      - type: markdown
        content: |
          ### Re-tag a mis-categorized scan
          Use **Developer Tools → Services** with
          `dreame_a2_mower.move_lidar_scan` — provide `from_map_id`,
          `filename` (from picker option text), `to_map_id`.

```
Card order is now: header → Archive entities → custom lidar card → Re-tag markdown (unchanged position because it was already at the bottom of LiDAR; this task is a no-op if Step 1 confirmed Re-tag is already last). If Re-tag was the last card in Step 1, skip Steps 2–3 and just lint + commit nothing.

- [ ] **Step 4: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 5: Commit (only if reorder happened)**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git diff --quiet dashboards/mower/dashboard.yaml || {
  git add dashboards/mower/dashboard.yaml
  git commit -m "dashboard: LiDAR tab — Re-tag reference moved to bottom"
}
```

---

### Task 6: WiFi Coverage tab — add delimiter alias, remove "# WiFi heatmap" intro

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` lines 753–758 (the existing intro markdown card on WiFi Coverage)

- [ ] **Step 1: Read the tab's current top**

Read lines 749–763. Confirm the first card is the `# WiFi heatmap` markdown block.

- [ ] **Step 2: Replace the intro card with the alias**

Use Edit on `dashboards/mower/dashboard.yaml`. Replace:
```yaml
    cards:
      - type: markdown
        content: |
          # WiFi heatmap
          Pick any heatmap from the archive. The viewer overlays it on
          the corresponding map's base snapshot. Adjust opacity, flip,
          or hide the base map with the controls below.
```
with:
```yaml
    cards:
      - *tab_header_wifi
```

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: WiFi Coverage tab uses unified delimiter"
```

---

### Task 7: Sessions tab — add delimiter inside outer vertical-stack

Sessions is `type: panel`, so the only top-level card is one `vertical-stack`. The new delimiter goes as the **first** child of that outer stack, above the existing top-row `horizontal-stack`.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` near lines 794–810 (the `- title: Sessions` view and its outer stack)

- [ ] **Step 1: Read the Sessions tab top**

Read lines 794–812. Confirm structure is `title: Sessions` → `path: sessions` → `type: panel` → `cards:` → `- type: vertical-stack` → `cards:` → comment → `- type: horizontal-stack` …

- [ ] **Step 2: Insert the alias as the first child of the outer vertical-stack**

Use Edit on `dashboards/mower/dashboard.yaml`. Replace:
```yaml
      - type: vertical-stack
        cards:
          # ───── Top row: cross-session widgets (left) + big replay map (right) ─────
```
with:
```yaml
      - type: vertical-stack
        cards:
          - *tab_header_sessions
          # ───── Top row: cross-session widgets (left) + big replay map (right) ─────
```

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Render-check the archived-count Jinja via MCP**

Call `mcp__home-assistant__ha_eval_template` with:
```
{{ states('sensor.dreame_a2_mower_archived_session_count') }} archived
```
Expected: `result` is `<integer> archived` (e.g. `44 archived`), not `unknown archived`.

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: Sessions tab gets top-of-page delimiter (archived count)"
```

---

### Task 8: Diagnostics / Tools / Photo Privacy — add delimiter aliases

These three tabs do not currently have a unified header card. Add the alias as the first item of each tab's `cards:` list, leaving the rest of the content unchanged.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` near `^  - title: Diagnostics$`, `^  - title: Tools$`, `^  - title: Photo Privacy$`

- [ ] **Step 1: Read each tab's current top**

```bash
grep -A4 "^  - title: Diagnostics$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
grep -A4 "^  - title: Tools$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
grep -A4 "^  - title: Photo Privacy$" /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
```
Note for each whether the first existing card is an intro `markdown` (which would be replaced) or content-card (which stays; alias goes above it).

- [ ] **Step 2: For each tab, insert the alias as the first card**

For each of the three tabs:

- If the first existing card after `cards:` is a tab-intro markdown block (one that just describes what the tab is), replace it with the matching alias (`- *tab_header_diagnostics` / `_tools` / `_photo_privacy`).
- If the first card is a content card (entities / picture-entity / button / etc.), insert the alias on its own line directly under `cards:` and leave the rest in place.

Use Edit per tab. Concrete example for Diagnostics if it starts with content:
```yaml
    cards:
      - *tab_header_diagnostics
      <existing first card unchanged>
```

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Run the anchor-resolution check**

Run the **Anchor-resolution check**. Expected: rows for Diagnostics, Tools, Photo Privacy all show `first_card=markdown` with `<hr` and the right emoji (`🩺` / `🔧` / `🔒`).

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: Diagnostics/Tools/Photo Privacy tabs use unified delimiter"
```

---

### Task 9: More Settings tab — replace placeholders with real entity cards

This is the largest task. The current More Settings tab (lines 1158–1230) has: a `# More Settings` intro, an existing `Work Management` entities card, several 🚧 Plan-3 placeholder markdown cards, an existing single-entity `Security` card, and a `General — Language & Voice` entities card. Replace the intro + every 🚧 placeholder + the Security single-entity card with the new layout. Delete the `Time Zone / Switch Unit / Notifications` placeholder entirely (app-only settings; see [[project_g2408_app_only_settings]]).

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` lines 1158–1230 (entire body of the More Settings view, from the `# More Settings` markdown card through the final `🚧 Time Zone …` placeholder)

- [ ] **Step 1: Read the current More Settings body**

Read lines 1158–1232. Verify the existing content matches the spec's "before" picture (intro + Work Management + 🚧 placeholders + Security + Language & Voice + 🚧 Time Zone).

- [ ] **Step 2: Replace the entire body**

Use Edit on `dashboards/mower/dashboard.yaml`. Replace everything from the line `      - type: markdown` that starts the `# More Settings` intro card down through the final `### 🚧 Time Zone / Switch Unit / Notifications (Plan 3)` markdown block (i.e. all cards on the tab) with this new content:

```yaml
      - *tab_header_more_settings

      # ───── Consumables & Maintenance (read-only sensors) ─────
      - type: entities
        title: Consumables & Maintenance
        entities:
          - entity: sensor.dreame_a2_mower_blades_life
            name: Blades
          - entity: sensor.dreame_a2_mower_cleaning_brush_life
            name: Cleaning brush
          - entity: sensor.dreame_a2_mower_robot_maintenance_life
            name: Robot maintenance
        footer:
          type: graph
          entity: sensor.dreame_a2_mower_blades_life
          hours_to_show: 168
      - type: markdown
        content: |
          _Reset buttons not yet exposed — see iobroker write-path tier reference for candidates._

      # ───── Work Management (existing card; kept in place after Consumables) ─────
      - type: entities
        title: Work Management
        entities:
          - entity: switch.dreame_a2_mower_ai_obstacle_photos
            name: Capture photos of AI obstacles

      # ───── Rain Protection ─────
      - type: entities
        title: Rain Protection
        entities:
          - entity: switch.dreame_a2_mower_rain_protection
            name: Enabled
          - entity: select.dreame_a2_mower_rain_protection_resume_hours
            name: Resume after
          - entity: binary_sensor.dreame_a2_mower_rain_protection_active
            name: Currently delayed
      - type: markdown
        content: |
          _Ambient temperature not exposed; rain trigger source TBD._

      # ───── Frost Protection ─────
      - type: entities
        title: Frost Protection
        entities:
          - entity: switch.dreame_a2_mower_frost_protection
            name: Enabled
      - type: markdown
        content: |
          _Stops below 6 °C. Ambient temperature not exposed (possible candidate in unknown mqtt corpus)._

      # ───── Do Not Disturb / Nighttime ─────
      - type: entities
        title: Do Not Disturb / Nighttime
        entities:
          - entity: switch.dreame_a2_mower_do_not_disturb
            name: Do not disturb
          - entity: switch.dreame_a2_mower_low_speed_at_night
            name: Low speed at night
      - type: markdown
        content: |
          _Time windows live on the Schedule tab._

      # ───── Navigation Path ─────
      - type: entities
        title: Navigation Path
        entities:
          - entity: select.dreame_a2_mower_navigation_path
            name: Path mode

      # ───── Charging ─────
      - type: entities
        title: Charging
        entities:
          - entity: switch.dreame_a2_mower_auto_recharge_after_extended_standby
            name: Auto-recharge after standby
          - entity: number.dreame_a2_mower_auto_recharge_battery_threshold
            name: Auto-recharge threshold (%)
          - entity: number.dreame_a2_mower_resume_after_charge_battery_threshold
            name: Resume-after-charge threshold (%)
          - entity: switch.dreame_a2_mower_custom_charging_period
            name: Custom charging period

      # ───── LED Light ─────
      - type: entities
        title: LED Light
        entities:
          - entity: switch.dreame_a2_mower_led_in_standby
            name: In standby
          - entity: switch.dreame_a2_mower_led_on_error
            name: On error
          - entity: switch.dreame_a2_mower_led_while_charging
            name: While charging
          - entity: switch.dreame_a2_mower_led_while_working
            name: While working
          - entity: switch.dreame_a2_mower_led_period
            name: Period (timed)

      # ───── Anti-theft ─────
      - type: entities
        title: Anti-theft
        entities:
          - entity: switch.dreame_a2_mower_anti_theft_lift_alarm
            name: Lift alarm
          - entity: switch.dreame_a2_mower_anti_theft_off_map_alarm
            name: Off-map alarm
          - entity: switch.dreame_a2_mower_anti_theft_realtime_location
            name: Realtime location

      # ───── Human Presence ─────
      - type: entities
        title: Human Presence
        entities:
          - entity: switch.dreame_a2_mower_human_presence_alert
            name: Alert enabled
          - entity: number.dreame_a2_mower_human_presence_alert_sensitivity
            name: Sensitivity (1–10)
      - type: markdown
        content: |
          _1 = nearest detection, 10 = farthest (or vice versa — verify against app)._

      # ───── Child Lock ─────
      - type: entities
        title: Child Lock
        entities:
          - entity: switch.dreame_a2_mower_child_lock
            name: Enabled

      # ───── General — Language & Voice (existing card; kept) ─────
      - type: entities
        title: General — Language & Voice
        entities:
          - entity: select.dreame_a2_mower_voice_language
            name: Voice
          - entity: select.dreame_a2_mower_mower_lcd_language
            name: LCD language
          - entity: number.dreame_a2_mower_voice_volume
            name: Volume
```

Note: the `footer: type: graph` on the Consumables card requires no extra resource. If it fails to render after deploy (e.g. graph type unsupported), remove the entire `footer:` block in a follow-up — it's a nice-to-have, not load-bearing.

- [ ] **Step 3: Lint**

Run the **Lint** command. Expected: `OK`.

- [ ] **Step 4: Spot-check every referenced entity exists**

Save the list of entity_ids referenced in the new block to a temp file and verify each one exists by querying via MCP, or use a one-liner:
```bash
python3 -c "
import re, yaml
with open('/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml') as f:
    text = f.read()
# Extract entity_ids in the More Settings tab only
start = text.index('- title: More Settings')
end = text.index('- title: Diagnostics', start)
ids = sorted(set(re.findall(r'entity:\s+([a-z_]+\.[a-z0-9_]+)', text[start:end])))
print('\n'.join(ids))
"
```
Then call `mcp__home-assistant__ha_search_entities` with each id (or batch with one search per domain). Expected: every entity returns a non-empty match. If any miss, the entity_id slug drifted — fix the YAML to match the live id before continuing.

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: More Settings tab — wire 11 cards to live integration entities"
```

---

### Task 10: Deploy + browser verification + cleanup commit

**Files:**
- Deploy: `dashboards/mower/dashboard.yaml` to live HA host

- [ ] **Step 1: Final lint + anchor-resolution check**

Run **Lint** and **Anchor-resolution check** commands. Expected: `OK` and every view's first card is `markdown` with the right emoji.

- [ ] **Step 2: Deploy to live HA**

Run the **Deploy** command from the Reference section. Confirm the scp finishes and the remote md5 prints.

- [ ] **Step 2b: HA-side validation via MCP**

Run the three MCP calls from the **Post-deploy HA-side verification** section in Reference (`ha_check_config`, two `ha_get_logs` calls). Expected: config valid, no `lovelace` entries, no fresh `dreame` ERROR/WARNING entries. If any of these fail, the YAML is structurally broken or references a card/entity HA can't resolve — fix locally and redeploy before continuing to Step 3.

- [ ] **Step 3: Reload in browser**

Open the Mower dashboard in a browser. Hard-reload (Ctrl-Shift-R). For each of the 11 tabs, verify:

- Header card is the first thing visible on the tab.
- Header is one line (`<hr/>` rule + `## …` heading on the next line, no italic subtitle wrapping below).
- Per-map tabs (Mower, Settings & Zones, Schedule) show the live active-map name after the em-dash.
- Sessions tab shows the live archived-session count.
- The small grey helper note is visibly smaller than the heading text. If it renders at full size, the inline `<span style>` was stripped — fall back: replace each `<span style="...">…</span>` with `<sub>…</sub>` in the anchor block, redeploy, re-verify. Commit the fallback as `dashboard: fall back to <sub> for header helper text`.
- More Settings tab cards (Consumables → Language & Voice) render in order. Toggling a switch updates its UI state (the integration may or may not push to the device; that's not a dashboard concern).

If any tab fails to render, open Developer Tools → Logs in HA, search for `createErrorCardElement` (see [[feedback_dashboard_lovelace_cards]]), and identify the offending card. Fix and redeploy.

- [ ] **Step 4: Delete the local working-tree backup**

```bash
rm /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.pre-minor.yaml.bak
```

- [ ] **Step 5: Push**

Per [[feedback_cleanup_push_cadence]] — dashboard-only, no version bump, no release.

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git push origin HEAD
```

Expected: push succeeds; commits from Tasks 2, 4, (5), 6, 7, 8, 9 land on `main`.

---

## Post-implementation update

If Step 3 of Task 10 forced the `<sub>` fallback, update the spec's "Risks & open questions" entry on `<span style>` to record that this HA version requires `<sub>`, and add a one-line entry to [[reference_ha_integration_gotchas]] so the next dashboard plan starts from the known-working form.
