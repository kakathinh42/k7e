#!/usr/bin/env python
"""Mint an HS256 dev JWT for local smoke tests (JWT_DEV_SECRET mode, ENV=dev).

Usage:
    python scripts/mint_dev_jwt.py --sub alice --ttl 3600
    TOK=$(JWT_DEV_SECRET=local-secret python scripts/mint_dev_jwt.py --sub alice)
    curl -H "Authorization: Bearer $TOK" http://localhost:8001/items

Defaults for --secret/--iss/--aud come from JWT_DEV_SECRET / JWT_ISSUER /
JWT_AUDIENCE in the environment, matching the API's settings.
"""

from __future__ import annotations

import argparse
import os
import time

import jwt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sub", required=True, help="JWT subject (user id)")
    parser.add_argument("--email", default="", help="optional email claim")
    parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds")
    parser.add_argument("--secret", default=os.environ.get("JWT_DEV_SECRET", ""))
    parser.add_argument("--iss", default=os.environ.get("JWT_ISSUER", "devportal"))
    parser.add_argument("--aud", default=os.environ.get("JWT_AUDIENCE", ""))
    args = parser.parse_args()
    if not args.secret:
        parser.error("--secret or JWT_DEV_SECRET is required")

    now = int(time.time())
    claims: dict = {"sub": args.sub, "iss": args.iss, "iat": now, "exp": now + args.ttl}
    if args.aud:
        claims["aud"] = args.aud
    if args.email:
        claims["email"] = args.email
    print(jwt.encode(claims, args.secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
