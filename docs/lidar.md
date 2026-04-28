# LiDAR — user guide

This integration archives every LiDAR scan the mower uploads (announced
on MQTT slot s99p20) and renders it three ways: a top-down PNG
thumbnail, a full-resolution PNG popout, and a 3D interactive WebGL
view via the bundled Lovelace card.

## Entities

| Entity | What |
|---|---|
| `camera.dreame_a2_mower_lidar_top_down` | 512×512 thumbnail (45° tilt). Default-enabled. |
| `camera.dreame_a2_mower_lidar_top_down_full` | 1024×1024 popout. Default-enabled. |
| `sensor.dreame_a2_mower_lidar_archive_count` | Count of archived `.pcd` files on disk. |

## Triggering an upload

The mower only uploads a new PCD when you tap **Download LiDAR map** in
the Dreamehome app. The integration listens for the MQTT announcement
(`s99p20`), fetches the binary blob from Aliyun OSS, dedups by md5, and
writes it to `<config>/dreame_a2_mower/lidar/`.

## 3D viewer setup

1. The integration ships a Lovelace card at
   `/dreame_a2_mower/dreame-a2-lidar-card.js`. Add it as a Lovelace
   resource (Settings → Dashboards → Resources → ADD RESOURCE):

   - URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`
   - Type: `JavaScript Module`

2. Add a card to your dashboard:

   ```yaml
   - type: custom:dreame-a2-lidar-card
     url: /api/dreame_a2_mower/lidar/latest.pcd
     show_map: true
     map_entity: camera.dreame_a2_mower_map
     point_size: 3
   ```

3. Drag to orbit, wheel to zoom; bottom slider adjusts splat size;
   toggle the map underlay if the lawn outline isn't visible.

## Archive retention

Configure under Settings → Devices & Services → Dreame A2 Mower →
Configure → Options:

| Option | Default | Range |
|---|---|---|
| LiDAR archive count cap | 20 | 1..50 |
| LiDAR archive size cap (MB) | 200 | 50..2000 |
| Session archive count cap | 50 | 1..200 |

When either LiDAR cap is reached, oldest scans are evicted oldest-first.
PCDs run 2–3 MB each on this hardware, so the size cap typically bites
before the count cap. Cap changes apply at runtime — no integration
reload needed.

## Manual download

The most recent `.pcd` blob is served (auth required) at:

```
GET /api/dreame_a2_mower/lidar/latest.pcd
```

Save it locally and open in Open3D, CloudCompare, or MeshLab for the
full interactive 3D view.

## Service

`dreame_a2_mower.show_lidar_fullscreen` fires a
`dreame_a2_mower_lidar_fullscreen` event on the HA bus. Lovelace cards
can listen for this event to pop up a full-screen LiDAR view.
