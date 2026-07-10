import os
import sys
import logging

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

from flask import Flask, jsonify, render_template, abort, Response, request
import tiles
import pegelonline

app = Flask(__name__)
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"


@app.get("/")
def index():
    return render_template("index.html")


# ── Water level ───────────────────────────────────────────────────────────────

@app.get("/api/waterlevel")
def api_waterlevel():
    return jsonify(pegelonline.get_water_level())


@app.get("/api/depth")
def api_depth():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        abort(400)

    wl = pegelonline.get_water_level()
    depth = tiles.get_depth_at_point(lat, lon, wl["profile"])
    if depth is None:
        return jsonify({"depth_m": None, "underwater": False})
    return jsonify({"depth_m": round(depth, 2), "underwater": depth > 0})


# ── Depth raster tiles ────────────────────────────────────────────────────────

@app.get("/tiles/water/<int:z>/<int:x>/<int:y>.png")
def water_tile(z, x, y):
    if z < 15 or z > 18:
        abort(404)
    wl = pegelonline.get_water_level()
    data = tiles.get_water_tile(z, x, y, wl["profile"])
    if data is None:
        return Response(status=404, headers={"Cache-Control": "public, max-age=300"})
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/tiles/depth/<int:z>/<int:x>/<int:y>.png")
def depth_tile(z, x, y):
    if z < 15 or z > 18:
        abort(404)
    wl = pegelonline.get_water_level()
    data = tiles.get_depth_tile(z, x, y, wl["profile"])
    if data is None:
        return Response(status=404, headers={"Cache-Control": "public, max-age=300"})
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


if __name__ == "__main__":
    app.run(debug=DEBUG, host="0.0.0.0", port=5000, threaded=True)
