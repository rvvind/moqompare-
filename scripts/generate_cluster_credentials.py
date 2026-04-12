#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sys


AUTH_KEY_PATH = "cluster_auth.jwk"
TOKEN_PATH = "cluster_token"


def b64url(data):
    raw = data if isinstance(data, bytes) else data.encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main():
    bad_paths = []
    for path in (AUTH_KEY_PATH, TOKEN_PATH):
        if os.path.isdir(path):
            bad_paths.append(path)
            os.rmdir(path)

    if bad_paths:
        print("Removed invalid directories: " + ", ".join(bad_paths))

    if os.path.isfile(AUTH_KEY_PATH) and os.path.isfile(TOKEN_PATH):
        print("cluster_auth.jwk + cluster_token already exist, skipping")
        return 0

    secret = os.urandom(32)
    jwk = {
        "kty": "oct",
        "k": b64url(secret),
        "alg": "HS256",
        "key_ops": ["sign", "verify"],
    }
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")))
    payload = b64url(
        json.dumps(
            {"cluster": True, "put": [""], "get": [""], "exp": 4102444800},
            separators=(",", ":"),
        )
    )
    sig = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    token = f"{header}.{payload}.{b64url(sig)}"

    with open(AUTH_KEY_PATH, "w") as f:
        json.dump(jwk, f, separators=(",", ":"))
    with open(TOKEN_PATH, "w") as f:
        f.write(token)

    print("Generated cluster_auth.jwk and cluster_token")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
