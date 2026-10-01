"""pumpscan web server: serves the frontend and the /api/lookup endpoint.

Local:      python app.py                     -> http://localhost:8000
Production: gunicorn --chdir pumpscan app:app (see render.yaml)

If the frontend is hosted elsewhere (e.g. a v0 / Vercel page), set
PUMPSCAN_CORS_ORIGINS to that site's origin (comma-separated, or * for any).
"""

import os

from flask import Flask, jsonify, request, send_from_directory

from lookup import AddressError, search

app = Flask(__name__, static_folder="static", static_url_path="")
CORS_ORIGINS = {o.strip() for o in os.environ.get("PUMPSCAN_CORS_ORIGINS", "*").split(",") if o.strip()}


@app.after_request
def cors(resp):
    origin = request.headers.get("Origin")
    if request.path.startswith("/api/") and origin:
        if "*" in CORS_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in CORS_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
    return resp


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/lookup")
def api_lookup():
    query = request.args.get("q") or request.args.get("address", "")
    chain = request.args.get("chain", "auto")
    if chain not in ("auto", "solana", "ethereum", "bnb"):
        return jsonify(error="Unknown chain."), 400
    try:
        return jsonify(search(query, chain))
    except AddressError as exc:
        return jsonify(error=str(exc)), 400


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 8000)),
        debug=False,
    )
