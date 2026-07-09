import io
import threading
from collections import OrderedDict
import numpy as np
from pathlib import Path
from PIL import Image
import mercantile
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from pyproj import Transformer

from elevation import _dtm_index, _rhine_dem_index

TILE_SIZE = 256
CACHE_DIR = Path(__file__).parent / "data" / "cache"

_web_crs = CRS.from_epsg(3857)
_to_utm  = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)

# Concurrent tile requests often reproject from the same source raster (e.g.
# adjacent map tiles sharing one NRW km-tile). Opening+closing a fresh dataset
# per request discards GDAL's block cache each time, so concurrent cold reads
# of the same file contend badly instead of sharing decoded blocks. Keeping a
# small LRU of open datasets (one lock each, since GDAL datasets aren't
# safe for concurrent access from multiple threads) fixes both.
_DATASET_CACHE_SIZE = 256
_dataset_cache: "OrderedDict[Path, tuple]" = OrderedDict()
_dataset_cache_lock = threading.Lock()


def _get_dataset(path: Path):
    with _dataset_cache_lock:
        entry = _dataset_cache.get(path)
        if entry is not None:
            _dataset_cache.move_to_end(path)
            return entry
        entry = (rasterio.open(path), threading.Lock())
        _dataset_cache[path] = entry
        if len(_dataset_cache) > _DATASET_CACHE_SIZE:
            _, (old_ds, _) = _dataset_cache.popitem(last=False)
            old_ds.close()
        return entry

# Depth colour gradient stops: (depth_m, (R, G, B))
_DEPTH_STOPS = [
    (0.0,  (224, 242, 254)),   # barely wet  – #e0f2fe
    (0.5,  (125, 211, 252)),   # shallow     – #7dd3fc
    (1.5,  ( 59, 130, 246)),   # medium      – #3b82f6
    (3.0,  ( 29,  78, 216)),   # deep        – #1d4ed8
    (6.0,  ( 30,  58, 138)),   # very deep   – #1e3a8a
    (12.0, ( 15,  23,  42)),   # channel bed – #0f172a
]


def _profile_key(profile: list) -> str:
    """Compact string key for a water-surface profile, used in cache paths."""
    return "_".join(str(round(ws * 20)) for _, ws in profile)


def _water_surface_grid(wgs_bounds, profile: list) -> np.ndarray:
    """Return a (TILE_SIZE, 1) float32 array of water-surface elevations.

    Interpolates linearly from the gauge profile at each pixel row's latitude.
    Row 0 = northern edge of tile, row TILE_SIZE-1 = southern edge.
    """
    lats_ctrl = np.array([p[0] for p in profile], dtype=np.float64)
    ws_ctrl   = np.array([p[1] for p in profile], dtype=np.float64)
    lats_pix  = np.linspace(wgs_bounds.north, wgs_bounds.south, TILE_SIZE)
    ws_row    = np.interp(lats_pix, lats_ctrl, ws_ctrl)
    return ws_row.reshape(TILE_SIZE, 1).astype(np.float32)


def _reproject_into(path, dst_transform, dst_nodata=np.nan) -> np.ndarray:
    """Reproject a single raster file into a 256×256 float32 grid aligned to dst_transform."""
    tmp = np.full((TILE_SIZE, TILE_SIZE), dst_nodata, dtype=np.float32)
    src, lock = _get_dataset(path)
    with lock:
        reproject(
            source=rasterio.band(src, 1),
            destination=tmp,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=_web_crs,
            resampling=Resampling.bilinear,
            src_nodata=src.nodata,
            dst_nodata=dst_nodata,
        )
    return tmp


def _read_dtm_grid(z, x, y) -> np.ndarray | None:
    """Return a 256×256 float32 elevation grid (NaN = no data).

    Merges NRW DTM 1 km tiles (land surface) with the BfG Rhine DEM
    (includes echo-sounded channel bathymetry). Where both overlap the
    Rhine DEM wins via np.minimum so the deeper channel floor is used.
    """
    xy  = mercantile.xy_bounds(x, y, z)
    dst_transform = from_bounds(xy.left, xy.bottom, xy.right, xy.top, TILE_SIZE, TILE_SIZE)

    wgs = mercantile.bounds(x, y, z)
    w, s = _to_utm.transform(wgs.west, wgs.south)
    e, n = _to_utm.transform(wgs.east, wgs.north)

    nrw_paths = [
        _dtm_index[(tx, ty)]
        for tx in range(int(w // 1000), int(e // 1000) + 1)
        for ty in range(int(s // 1000), int(n // 1000) + 1)
        if (tx, ty) in _dtm_index
    ]
    rhine_paths = [
        path for (bounds, path) in _rhine_dem_index
        if bounds.left < e and bounds.right > w and bounds.bottom < n and bounds.top > s
    ]

    if not nrw_paths and not rhine_paths:
        return None

    dst = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype=np.float32)

    # Layer 1 — NRW DTM (land surface, fills most of NRW)
    for path in nrw_paths:
        tmp = _reproject_into(path, dst_transform)
        valid = ~np.isnan(tmp)
        dst[valid] = tmp[valid]

    # Layer 2 — Rhine DEM (floodplain + echo-sounded channel bed).
    # Use np.minimum so the lower channel-bed values win over the NRW DTM
    # water-surface values that were stored for river pixels.
    for path in rhine_paths:
        tmp = _reproject_into(path, dst_transform)
        valid = ~np.isnan(tmp)
        both       = valid & ~np.isnan(dst)
        only_rhine = valid & np.isnan(dst)
        dst[both]       = np.minimum(dst[both], tmp[both])
        dst[only_rhine] = tmp[only_rhine]

    return dst if not np.all(np.isnan(dst)) else None


def get_water_tile(z: int, x: int, y: int, profile: list) -> bytes | None:
    """Return an RGBA PNG tile with water-covered pixels filled in solid blue.

    profile: [(lat, water_surface_m), ...] sorted south→north, from pegelonline.
    """
    pkey  = _profile_key(profile)
    cache = CACHE_DIR / "water" / pkey / str(z) / str(x) / f"{y}.png"
    if cache.exists():
        data = cache.read_bytes()
        return data or None   # empty file = cached "no data" sentinel

    grid = _read_dtm_grid(z, x, y)
    if grid is None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.touch()
        return None

    wgs = mercantile.bounds(x, y, z)
    ws_grid = _water_surface_grid(wgs, profile)   # (256, 1), broadcasts to (256, 256)

    wet = ~np.isnan(grid) & (grid <= ws_grid)
    if not wet.any():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.touch()
        return None

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    rgba[wet] = (14, 165, 233, 180)   # sky-400, ~70 % opacity

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=False)
    data = buf.getvalue()

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return data


def get_depth_tile(z: int, x: int, y: int, profile: list) -> bytes | None:
    """Return an RGBA PNG tile coloured by water depth.

    profile: [(lat, water_surface_m), ...] sorted south→north, from pegelonline.
    """
    pkey  = _profile_key(profile)
    cache = CACHE_DIR / "depth" / pkey / str(z) / str(x) / f"{y}.png"
    if cache.exists():
        data = cache.read_bytes()
        return data or None   # empty file = cached "no data" sentinel

    grid = _read_dtm_grid(z, x, y)
    if grid is None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.touch()
        return None

    wgs   = mercantile.bounds(x, y, z)
    ws    = _water_surface_grid(wgs, profile)   # (256, 1)
    depth = ws - grid                            # positive = underwater
    rgba  = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)

    underwater = depth > 0
    if underwater.any():
        t = np.clip(depth, 0, _DEPTH_STOPS[-1][0])
        for i in range(len(_DEPTH_STOPS) - 1):
            d0, c0 = _DEPTH_STOPS[i]
            d1, c1 = _DEPTH_STOPS[i + 1]
            mask = underwater & (t > d0) & (t <= d1)
            if mask.any():
                f = (t[mask] - d0) / (d1 - d0)
                rgba[mask, 0] = (c0[0] + f * (c1[0] - c0[0])).astype(np.uint8)
                rgba[mask, 1] = (c0[1] + f * (c1[1] - c0[1])).astype(np.uint8)
                rgba[mask, 2] = (c0[2] + f * (c1[2] - c0[2])).astype(np.uint8)
                rgba[mask, 3] = 200
        deep = underwater & (t >= _DEPTH_STOPS[-1][0])
        if deep.any():
            rgba[deep] = (*_DEPTH_STOPS[-1][1], 200)

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=False)
    data = buf.getvalue()

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return data
