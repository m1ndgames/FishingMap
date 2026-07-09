import re
import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

from config import DTM_TILE_BOUNDS

logger = logging.getLogger(__name__)

_DTM_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/hm/dgm1_tiff/dgm1_tiff"
_DSM_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/hm/dom1_tiff/dom1_tiff"
_TILE_RE = re.compile(r"_(\d+)_(\d+)_1_nw_\d+\.tif$")

# BfG Rhine floodplain DEM (Weber 2020, PANGAEA.919308, CC-BY-4.0), Iffezheim->
# Kleve, split into 40 tiles. PANGAEA has no index.json like OpenGeoData NRW,
# so this table (name, direct URL, UTM32N bounds in metres) is hardcoded from
# https://doi.pangaea.de/10.1594/PANGAEA.919308?format=textfile
_RHINE_DEM_BASE = "https://hs.pangaea.de/Maps/DEM_Rhine/Weber_2020"
_RHINE_DEM_TILES = [
    # (name, east_min, east_max, north_min, north_max)
    ("r001_IFFEZHEIM_DEM", 434030, 437804, 5408998, 5415820),
    ("r002_PLITTERSDORF1_DEM", 436045, 442431, 5414133, 5425346),
    ("r003_PLITTERSDORF2_DEM", 440847, 447333, 5422000, 5426699),
    ("r004_PLITTERSDORF3_DEM", 446070, 452037, 5425604, 5432679),
    ("r005_MAXAU1_DEM", 448511, 455018, 5431599, 5439676),
    ("r006_MAXAU2_DEM", 452548, 457235, 5438503, 5449097),
    ("r007_MAXAU3_DEM", 452704, 459065, 5447955, 5456683),
    ("r008_PHILIPPSBURG_DEM", 457614, 463292, 5454819, 5464269),
    ("r009_SPEYER_DEM", 458947, 465652, 5463049, 5483107),
    ("r010_MANNHEIM_DEM", 454615, 461891, 5480937, 5498567),
    ("r011_WORMS1_DEM", 453272, 458061, 5497302, 5506800),
    ("r012_WORMS2_DEM", 454839, 463128, 5503902, 5517448),
    ("r013_WORMS3_DEM", 453115, 462803, 5514861, 5525157),
    ("r014_NIERSTEIN_OPPENHEIM_DEM", 447741, 454626, 5523336, 5540086),
    ("r015_MAINZ_DEM", 429936, 448905, 5538377, 5543713),
    ("r016_OESTRICH_DEM", 420511, 431415, 5535340, 5539754),
    ("r017_BINGEN_DEM", 411031, 421561, 5535730, 5549298),
    ("r018_KAUB_DEM", 407519, 411933, 5548302, 5557028),
    ("r019_SANKT_GOAR_DEM", 399034, 408566, 5556083, 5565820),
    ("r020_BOPPARD_DEM", 398482, 404095, 5565323, 5580450),
    ("r021_KOBLENZ1_DEM", 393932, 401932, 5578845, 5586928),
    ("r022_KOBLENZ2_DEM", 385366, 395053, 5585270, 5589872),
    ("r023_ANDERNACH1_DEM", 379440, 386369, 5588799, 5597012),
    ("r024_ANDERNACH2_DEM", 373139, 380581, 5595774, 5607623),
    ("r025_OBERWINTER_DEM", 366349, 374364, 5606513, 5622863),
    ("r026_BONN1_DEM", 359928, 367284, 5621744, 5632252),
    ("r027_BONN2_DEM", 356688, 363144, 5631240, 5645433),
    ("r028_KOELN1_DEM", 356744, 359706, 5644359, 5654954),
    ("r029_KOELN2_DEM", 349335, 358072, 5653897, 5663312),
    ("r030_KOELN3_DEM", 345383, 352876, 5661822, 5671500),
    ("r031_KOELN4_DEM", 338674, 346604, 5670294, 5677985),
    ("r032_DUESSELDORF1_DEM", 339313, 344478, 5676720, 5689989),
    ("r033_DUESSELDORF2_DEM", 336434, 344028, 5688622, 5703692),
    ("r034_DUISBURG_RUHRORT1_DEM", 338332, 344020, 5701504, 5714843),
    ("r035_DUISBURG_RUHRORT2_DEM", 331933, 340039, 5713624, 5725046),
    ("r036_WESEL1_DEM", 324753, 336306, 5722836, 5728133),
    ("r037_WESEL2_DEM", 319638, 326329, 5726667, 5737717),
    ("r038_REES1_DEM", 312737, 320756, 5735824, 5744459),
    ("r039_REES2_DEM", 305048, 314202, 5742593, 5747372),
    ("r040_REES3_DEM", 297493, 307036, 5744883, 5752262),
]


def _needed_tile_names(base_url: str) -> list[str]:
    """Names of tiles within DTM_TILE_BOUNDS, per the source's index.json."""
    x0, x1, y0, y1 = DTM_TILE_BOUNDS
    index = requests.get(f"{base_url}/index.json", timeout=30).json()
    names = []
    for f in index["datasets"][0]["files"]:
        name = f["name"]
        m = _TILE_RE.search(name)
        if not m:
            continue
        tx, ty = int(m.group(1)), int(m.group(2))
        if x0 <= tx <= x1 and y0 <= ty <= y1:
            names.append(name)
    return names


def _download_one(base_url: str, dest_dir: Path, name: str, retries: int = 6) -> None:
    resp = requests.get(f"{base_url}/{name}", timeout=60)
    for attempt in range(retries - 1):
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(2 ** attempt)
        resp = requests.get(f"{base_url}/{name}", timeout=60)
    resp.raise_for_status()
    (dest_dir / name).write_bytes(resp.content)


def ensure_tiles(base_url: str, dest_dir: Path, label: str) -> None:
    """Download any corridor tiles missing from dest_dir. No-op if all present."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        names = _needed_tile_names(base_url)
    except Exception as exc:
        logger.warning("[%s] could not reach tile index (%s); using tiles already on disk.", label, exc)
        return

    missing = [n for n in names if not (dest_dir / n).exists()]
    if not missing:
        logger.info("[%s] %d corridor tiles present, none missing.", label, len(names))
        return

    logger.info("[%s] downloading %d of %d needed tiles…", label, len(missing), len(names))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_download_one, base_url, dest_dir, n) for n in missing]
        for i, fut in enumerate(futures, 1):
            fut.result()
            if i % 50 == 0 or i == len(missing):
                logger.info("[%s] %d/%d", label, i, len(missing))
    logger.info("[%s] done.", label)


def ensure_dtm_dsm(dtm_dir: Path, dsm_dir: Path) -> None:
    ensure_tiles(_DTM_URL, dtm_dir, "DTM")
    ensure_tiles(_DSM_URL, dsm_dir, "DSM")


def ensure_rhine_dem(dest_dir: Path) -> None:
    """Download any BfG Rhine DEM tiles overlapping DTM_TILE_BOUNDS that are missing."""
    x0, x1, y0, y1 = (v * 1000 for v in DTM_TILE_BOUNDS)
    needed = [
        name for name, e0, e1, n0, n1 in _RHINE_DEM_TILES
        if e0 < x1 and e1 > x0 and n0 < y1 and n1 > y0
    ]

    dest_dir.mkdir(parents=True, exist_ok=True)
    missing = [n for n in needed if not (dest_dir / f"{n}.tif").exists()]
    if not missing:
        logger.info("[Rhine DEM] %d corridor tiles present, none missing.", len(needed))
        return

    logger.info("[Rhine DEM] downloading %d of %d needed tiles…", len(missing), len(needed))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = [
                pool.submit(_download_one, _RHINE_DEM_BASE, dest_dir, f"{n}.tif")
                for n in missing
            ]
            for i, fut in enumerate(futures, 1):
                fut.result()
                logger.info("[Rhine DEM] %d/%d", i, len(missing))
    except Exception as exc:
        logger.warning("[Rhine DEM] download failed (%s); continuing with tiles already on disk.", exc)
        return
    logger.info("[Rhine DEM] done.")
