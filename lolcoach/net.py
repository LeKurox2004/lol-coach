"""Tiny HTTP helper (stdlib only)."""
import base64
import json
import ssl
import urllib.request

# The League client and the Live Client API use a self-signed certificate on 127.0.0.1.
_LOCAL_CTX = ssl.create_default_context()
_LOCAL_CTX.check_hostname = False
_LOCAL_CTX.verify_mode = ssl.CERT_NONE


def get_json(url, auth=None, timeout=5.0, local=False):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "lol-coach/1.0"})
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    if local and not url.startswith("https://127.0.0.1"):
        raise ValueError("local=True only allowed for 127.0.0.1")
    with urllib.request.urlopen(req, timeout=timeout, context=_LOCAL_CTX if local else None) as resp:
        return json.loads(resp.read().decode("utf-8"))
