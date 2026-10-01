"""pumpscan web server: serves the frontend and the /api/lookup endpoint."""

import os

from flask import Flask, jsonify, request, send_from_directory

from lookup import AddressError, search

app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


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
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)), debug=False)
