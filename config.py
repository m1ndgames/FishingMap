STATION_UUID   = "8f7e5f92-1153-4f93-acba-ca48670c8ca9"
STATION_LABEL  = "Rhein – Düsseldorf"
PNP_M          = 24.529   # Pegelnullpunkt in metres above NHN
FALLBACK_CM    = 300      # fallback gauge reading when API is unreachable

# Rhine gauges used to build a longitudinal water-surface profile.
# Sorted south → north (ascending latitude).  PNP values from PEGELONLINE
# (stations/<uuid>/W.json -> gaugeZero.value).
RHINE_GAUGES = [
    {"uuid": "593647aa-9fea-43ec-a7d6-6476a76ae868", "pnp_m": 42.713, "lat": 50.736, "label": "Bonn"},
    {"uuid": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c", "pnp_m": 35.038, "lat": 50.937, "label": "Köln"},
    {"uuid": "8f7e5f92-1153-4f93-acba-ca48670c8ca9", "pnp_m": 24.529, "lat": 51.226, "label": "Düsseldorf"},
    {"uuid": "c0f51e35-d0e8-4318-afaf-c5fcbc29f4c1", "pnp_m": 16.106, "lat": 51.455, "label": "Duisburg-Ruhrort"},
    {"uuid": "f33c3cc9-dc4b-4b77-baa9-5a5f10704398", "pnp_m": 11.206, "lat": 51.646, "label": "Wesel"},
]

# UTM32N (EPSG:25832) km-tile bounding box for the Rhine Bonn->Wesel corridor
# the app actually renders (index.html bounds [6.39, 50.72, 7.12, 51.77]),
# padded ~30 km so edge tiles at the app's minzoom (15) are never missing.
# Used to fetch only the NRW DTM/DSM tiles this app needs, not all of NRW.
DTM_TILE_BOUNDS = (294, 390, 5601, 5765)   # (x0_km, x1_km, y0_km, y1_km)

# Elevation encoding range for raster tiles.
# Pixel 0   = ELEV_ORIGIN_M NHN   (≈ riverbed)
# Pixel 100 = PNP_M NHN           (= gauge zero)
# Pixel 254 = ELEV_ORIGIN_M+25.4  (well above any flood level)
# Pixel 255 = no-data sentinel
ELEV_ORIGIN_M  = PNP_M - 10        # 14.529 m NHN
ELEV_SCALE     = 10                 # 0.1 m per grey level
MAX_DEPTH_M    = 12                 # colour scale upper bound
