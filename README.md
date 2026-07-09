# FishingMap

A local web app exploring the Rhine between Bonn and Wesel, combining OpenStreetMap with a real bathymetric depth overlay and live gauge data.

## Features

- **OSM / Satellite toggle** — switch between OpenStreetMap and ESRI World Imagery
- **Depth gradient overlay** — colour-coded channel depth from pale blue (shallow) to near-black (>12 m), driven by real echo-sounded bathymetry; single "Overlay" button to show/hide it (visible zoom 15–18 only)
- **Live gauge data** — polls PEGELONLINE every 5 min for five Rhine stations (Bonn, Köln, Düsseldorf, Duisburg-Ruhrort, Wesel); water surface is interpolated per pixel row so depth is accurate across the full ~160 km Bonn→Wesel stretch

## Data sources

| Data | Source | Coverage |
|------|--------|----------|
| Base map | OpenStreetMap | Worldwide |
| Satellite imagery | ESRI World Imagery | Worldwide |
| Land-surface elevation (DTM/DSM) | NRW DGM1 / DOM1 LiDAR (IT.NRW) | NRW, 1 m res |
| Channel bathymetry | BfG Rhine DEM — PANGAEA [10.1594/PANGAEA.919308](https://doi.org/10.1594/PANGAEA.919308), CC BY 4.0 | Rhine Bonn→Rees (17 of 40 tiles, auto-fetched), 1 m res |
| Live water levels | [PEGELONLINE](https://www.pegelonline.wsv.de) REST API | Bonn · Köln · Düsseldorf · Duisburg-Ruhrort · Wesel |

### Rhine DEM tiles in `data/rhine_dem/`

17 of the 40 tiles in the PANGAEA.919308 series overlap the app's corridor bounding box (`config.DTM_TILE_BOUNDS`, padded ~30 km around Bonn→Wesel), from Andernach down to Rees:

r024_ANDERNACH2, r025_OBERWINTER, r026_BONN1, r027_BONN2, r028_KOELN1, r029_KOELN2, r030_KOELN3, r031_KOELN4, r032_DUESSELDORF1, r033_DUESSELDORF2, r034_DUISBURG_RUHRORT1, r035_DUISBURG_RUHRORT2, r036_WESEL1, r037_WESEL2, r038_REES1, r039_REES2, r040_REES3

## Setup

```bash
uv sync
uv run python app.py
# → http://127.0.0.1:5000
```

On first run, all terrain data (`data/dtm/`, `data/dsm/` from OpenGeoData NRW, and `data/rhine_dem/` from PANGAEA — see [Data sources](#data-sources)) is downloaded automatically for the Rhine corridor by `terrain_download.py` (~65 GB total; only takes a while the first time, then it's a no-op). Tile cache is written to `data/cache/` and is safe to delete.

### Docker

```bash
docker compose up
# → http://127.0.0.1:5000
```

The image (`ghcr.io/m1ndgames/fishingmap:latest`) is built and pushed by GitHub Actions (`.github/workflows/docker.yml`) on every push to `main` — `compose.yaml` pulls it rather than building locally. If the package is private, run `docker login ghcr.io` once first. For a local build off your own working tree instead (e.g. while iterating on the Dockerfile), run `docker compose build` or `docker build -t fishingmap .`.

`compose.yaml` mounts `./data` into the container so the downloaded terrain data (and tile cache) persists across restarts instead of re-downloading ~65 GB every time. Logs go to stdout/stderr only (no log files are written), so `docker compose logs -f` shows everything.

## Architecture

```
app.py             Flask routes (gauge API, tile endpoints)
pegelonline.py     PEGELONLINE proxy — fetches 5 gauges, builds lat-indexed water-surface profile
tiles.py           Raster tile renderer — merges NRW DTM + Rhine DEM, interpolates water surface per row
elevation.py       Builds NRW DTM/DSM/Rhine-DEM tile indexes used by tiles.py
terrain_download.py  Auto-downloads missing corridor tiles (NRW DTM/DSM + PANGAEA Rhine DEM)
config.py          PNP values, gauge UUIDs, constants
templates/
  index.html       MapLibre GL JS single-page app
data/
  dtm/             NRW DGM1 tiles (1 km × 1 km .tif, EPSG:25832)
  dsm/             NRW DOM1 tiles (same layout)
  rhine_dem/       BfG Rhine DEM tiles (large .tif, EPSG:25832/DHHN92)
  cache/           Server-side PNG tile cache (auto-created)
```

## How the depth overlay works

1. For each tile request the server merges the NRW DTM (land surface) with the Rhine DEM (actual echo-sounded channel bathymetry) using `np.minimum()` so the lower channel-bed value always wins.
2. A longitudinal water-surface profile is built from five live PEGELONLINE gauge readings (Bonn, Köln, Düsseldorf, Duisburg-Ruhrort, Wesel), each anchored by its Pegelnullpunkt (NHN elevation). The water surface is interpolated linearly by latitude across every pixel row of the tile.
3. `depth = water_surface(lat) − terrain_elevation`. Positive pixels are coloured; negative pixels are transparent.
4. Tiles are cached by a profile key derived from all five rounded gauge readings.
