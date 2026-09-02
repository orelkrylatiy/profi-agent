#!/usr/bin/env python3
"""Read-side API for profi.ru backoffice. Cookies from server browser, headers required.
Usage: uv run python scripts/api_reader.py [count|feed]
Antibot: max 1 request per 90-120s; on 403/401 pause 30-60 min."""
import json, sys, urllib.request
from playwright.sync_api import sync_playwright

TD = "/root/.openclaw/agents/profi/skills/profi-worker/templates"
op = sys.argv[1] if len(sys.argv) > 1 else "count"
name = "BoSearchBoardItemsCount" if op == "count" else "BoSearchBoardItems"
query = open(f"{TD}/{name}.graphql").read()
variables = json.load(open(f"{TD}/{name}.variables.json"))
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9223").contexts[0]
    ck = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies(["https://profi.ru"]))
    req = urllib.request.Request("https://profi.ru/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
            "Cookie": ck, "Origin": "https://profi.ru", "Referer": "https://profi.ru/backoffice/n.php",
            "X-Requested-With": "XMLHttpRequest", "x-app-id": "BO", "x-warp-ui-app": "MOBWEBBO",
            "x-warp-ui-type": "WEB", "x-warp-ui-ver": "1.0", "x-new-auth-compatible": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.status, json.dumps(json.loads(r.read()), ensure_ascii=False)[:2000])
