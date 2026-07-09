"""
Proxy + cache for the PEGELONLINE REST API.
Fetches three Rhine gauges (Köln, Düsseldorf, Duisburg-Ruhrort) and builds a
longitudinal water-surface profile used by the tile renderer.
"""
import time
import threading
import logging
import requests
from config import STATION_UUID, PNP_M, FALLBACK_CM, RHINE_GAUGES

logger = logging.getLogger(__name__)

_BASE = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"
_TTL  = 300   # seconds between live fetches

def _fallback_profile():
    return [(g["lat"], round(g["pnp_m"] + FALLBACK_CM / 100, 3)) for g in RHINE_GAUGES]

def _profile_key(profile):
    return "_".join(str(round(ws * 20)) for _, ws in profile)

_state: dict = {
    "profile":         _fallback_profile(),   # [(lat, water_surface_m)] S→N
    "profile_key":     _profile_key(_fallback_profile()),
    "gauges":          [{"label": g["label"], "value_cm": FALLBACK_CM,
                         "water_surface_m": round(g["pnp_m"] + FALLBACK_CM / 100, 3)}
                        for g in RHINE_GAUGES],
    # Düsseldorf values kept for backwards-compat display
    "value_cm":        FALLBACK_CM,
    "water_surface_m": round(PNP_M + FALLBACK_CM / 100, 3),
    "timestamp":       None,
    "source":          "fallback",
    "fetched_at":      0.0,
}
_lock = threading.Lock()


def get_water_level() -> dict:
    """Return current water level info.  Fetches all three gauges from PEGELONLINE when stale."""
    with _lock:
        age = time.time() - _state["fetched_at"]
        if age < _TTL and _state["source"] == "live":
            return dict(_state)

    try:
        gauges_out = []
        profile    = []
        dus_cm = dus_ws = None
        latest_ts  = None
        for g in RHINE_GAUGES:
            url = f"{_BASE}/stations/{g['uuid']}/W/currentmeasurement.json"
            r   = requests.get(url, timeout=5)
            r.raise_for_status()
            data     = r.json()
            value_cm = int(data["value"])
            ws_m     = round(g["pnp_m"] + value_cm / 100, 3)
            gauges_out.append({"label": g["label"], "value_cm": value_cm, "water_surface_m": ws_m})
            profile.append((g["lat"], ws_m))
            if g["uuid"] == STATION_UUID:
                dus_cm = value_cm
                dus_ws = ws_m
                latest_ts = data.get("timestamp")

        with _lock:
            _state.update({
                "profile":         profile,
                "profile_key":     _profile_key(profile),
                "gauges":          gauges_out,
                "value_cm":        dus_cm,
                "water_surface_m": dus_ws,
                "timestamp":       latest_ts,
                "source":          "live",
                "fetched_at":      time.time(),
            })
    except Exception as exc:
        logger.warning("fetch failed – using cached value. Reason: %s", exc)
        with _lock:
            _state["source"] = "fallback" if _state["fetched_at"] == 0 else "cached"

    with _lock:
        return dict(_state)
