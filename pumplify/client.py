import json
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlparse

import base58
import requests
from nacl import signing

from .config import (
    API_BASE,
    DEFAULT_HEADERS,
    IPFS_UPLOAD_URL,
    LOGIN_URL,
    PROFILE_UPDATE_URL,
    Settings,
)


def get_auth_token(session: requests.Session):
    for cookie in session.cookies:
        if cookie.name == "auth_token":
            return cookie.value
    return None


def auth_headers(auth_token: str, *, json_content=False, referer=None):
    headers = dict(DEFAULT_HEADERS)

    if json_content:
        headers["Content-Type"] = "application/json"

    if referer:
        headers["Referer"] = referer

    headers["Cookie"] = f"auth_token={auth_token}"
    return headers


def login(session: requests.Session, signing_key: signing.SigningKey, address: str):
    timestamp = int(time.time() * 1000)
    message = f"Sign in to pump.fun: {timestamp}".encode("utf-8")

    signature = signing_key.sign(message).signature
    signature_b58 = base58.b58encode(signature).decode("utf-8")

    payload = {
        "address": address,
        "signature": signature_b58,
        "timestamp": timestamp,
    }

    return session.post(
        LOGIN_URL,
        headers={**DEFAULT_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )


def set_name_and_bio(
    session: requests.Session,
    auth_token: str,
    username: str,
    bio: str,
):
    payload = {
        "username": username,
        "bio": bio,
    }

    return session.post(
        PROFILE_UPDATE_URL,
        headers=auth_headers(auth_token, json_content=True),
        json=payload,
        timeout=20,
    )


def upload_profile_image(
    session: requests.Session,
    auth_token: str,
    image_path: Path,
    settings: Settings,
):
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    with image_path.open("rb") as f:
        files = {
            "file": (image_path.name, f, mime_type),
        }

        headers = {
            **DEFAULT_HEADERS,
            "Cookie": f"auth_token={auth_token}",
            "Referer": f"https://pump.fun/profile/{settings.target_wallet}",
        }

        return session.post(
            IPFS_UPLOAD_URL,
            headers=headers,
            files=files,
            timeout=60,
        )


def extract_ipfs_url(response: requests.Response) -> str:
    """
    Pump.fun's exact upload response schema may change.
    This tries several common response shapes and also accepts raw URL/CID text.
    """
    text = response.text.strip()

    try:
        data = response.json()
    except ValueError:
        data = None

    if isinstance(data, str):
        text = data.strip()

    if isinstance(data, dict):
        candidate_keys = (
            "url",
            "uri",
            "fileUri",
            "fileURL",
            "fileUrl",
            "image",
            "imageUrl",
            "imageUri",
            "profileImage",
            "ipfsUrl",
            "ipfsUri",
            "cid",
            "hash",
            "ipfsHash",
        )

        for key in candidate_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break

        if not text.startswith(("http://", "https://", "ipfs://", "baf")):
            nested = data.get("data")
            if isinstance(nested, dict):
                for key in candidate_keys:
                    value = nested.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break

    if not text:
        raise ValueError("Upload response was empty.")

    if text.startswith("ipfs://"):
        return "https://ipfs.io/ipfs/" + text[len("ipfs://"):]

    if text.startswith("baf"):
        return f"https://ipfs.io/ipfs/{text}"

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc:
            return text

    for token in (
        text.replace('"', " ")
        .replace("'", " ")
        .replace(",", " ")
        .replace("}", " ")
        .replace("{", " ")
        .split()
    ):
        if token.startswith("baf") and len(token) > 20:
            return f"https://ipfs.io/ipfs/{token}"

    raise ValueError(
        "Could not identify the IPFS URL/CID in the upload response.\n"
        f"Response preview: {text[:1000]}"
    )


def set_profile_image(
    session: requests.Session,
    auth_token: str,
    image_url: str,
    bio: str,
):
    payload = {
        "profileImage": image_url,
        "bio": bio,
    }

    return session.post(
        PROFILE_UPDATE_URL,
        headers=auth_headers(auth_token, json_content=True),
        json=payload,
        timeout=20,
    )


def follow_wallet(
    session: requests.Session,
    auth_token: str,
    wallet_address: str,
):
    url = f"{API_BASE}/following/v2/{wallet_address}"

    return session.post(
        url,
        headers=auth_headers(
            auth_token,
            json_content=True,
            referer=f"https://pump.fun/profile/{wallet_address}",
        ),
        timeout=20,
    )




def read_profile(session: requests.Session, auth_token: str, wallet: str):
    return session.get(
        f"{API_BASE}/users/{wallet}",
        headers=auth_headers(auth_token),
        timeout=20,
    )


def check_follow(
    session: requests.Session,
    auth_token: str,
    follower_wallet: str,
    settings: Settings,
):
    url = (
        f"{API_BASE}/following/single/{settings.target_wallet}"
        f"?userId={follower_wallet}"
    )

    return session.get(
        url,
        headers=auth_headers(
            auth_token,
            json_content=True,
            referer=f"https://pump.fun/profile/{settings.target_wallet}",
        ),
        timeout=20,
    )


def is_blocked_response(response: requests.Response) -> bool:
    text = response.text.lower()
    location = response.headers.get("Location", "").lower()

    return (
        response.status_code in {403, 429}
        and (
            "static.pump.fun/blocked" in text
            or "static.pump.fun/blocked" in location
            or "challenge-platform" in text
            or "__cf$cv$params" in text
        )
    )


def response_preview(response: requests.Response, limit=1500):
    try:
        return json.dumps(response.json(), indent=2)[:limit]
    except ValueError:
        return response.text[:limit]
