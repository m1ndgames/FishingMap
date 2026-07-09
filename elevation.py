import re
import logging
from pathlib import Path
import rasterio
from rasterio.crs import CRS

from terrain_download import ensure_dtm_dsm, ensure_rhine_dem

logger = logging.getLogger(__name__)

_DTM_DIR      = Path(__file__).parent / "data" / "dtm"
_DSM_DIR      = Path(__file__).parent / "data" / "dsm"
_RHINE_DEM_DIR = Path(__file__).parent / "data" / "rhine_dem"

# Tile name pattern: dgm1_32_{x_km}_{y_km}_1_nw_{year}.tif
_PATTERN = re.compile(r"(?:dgm|dom)1_32_(\d+)_(\d+)_1_nw_\d+\.tif")

_utm32 = CRS.from_epsg(25832)


def _build_index(directory: Path) -> dict:
    index = {}
    for f in directory.glob("*.tif"):
        m = _PATTERN.match(f.name)
        if m:
            index[(int(m.group(1)), int(m.group(2)))] = f
    return index


def _build_rhine_index(directory: Path) -> list[tuple]:
    """Return list of (BoundingBox_in_UTM32N, path) for large Rhine DEM tiles."""
    from rasterio.warp import transform_bounds
    entries = []
    if not directory.exists():
        return entries
    for f in sorted(directory.glob("*.tif")):
        try:
            with rasterio.open(f) as src:
                # Normalise to a 2D horizontal CRS for bounds comparison
                h_crs = CRS.from_epsg(src.crs.to_epsg() or 25832)
                if h_crs.to_epsg() == 25832:
                    bounds = src.bounds
                else:
                    left, bottom, right, top = transform_bounds(h_crs, _utm32, *src.bounds)
                    bounds = rasterio.coords.BoundingBox(left, bottom, right, top)
            entries.append((bounds, f))
        except Exception as exc:
            logger.warning("[rhine_dem] skipping %s: %s", f.name, exc)
    return entries


ensure_dtm_dsm(_DTM_DIR, _DSM_DIR)
ensure_rhine_dem(_RHINE_DEM_DIR)

logger.info("Building tile index…")
_dtm_index = _build_index(_DTM_DIR)
_dsm_index = _build_index(_DSM_DIR)
_rhine_dem_index = _build_rhine_index(_RHINE_DEM_DIR)
logger.info("DTM: %d tiles | DSM: %d tiles | Rhine DEM: %d tiles",
            len(_dtm_index), len(_dsm_index), len(_rhine_dem_index))
