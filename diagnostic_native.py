#!/usr/bin/env python3
"""
diagnostic_native.py — Test minimo de sesion Akamai SIN anti-fingerprinting

Objetivo: descartar si nuestro ANTI_FINGERPRINT_JS es lo que triggerea el ~-1
o si el proxy de Webshare ya viene quemado de fabrica.

Solo usa Patchright nativo (su stealth integrado: oculta webdriver, etc).
NO inyecta canvas/WebGL/AudioContext spoofing.

Uso:
  python3 diagnostic_native.py --proxy "http://user:pass@p.webshare.io:80"
  python3 diagnostic_native.py  # sin proxy
"""

import argparse
import os
import sys
import time
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"


def parse_proxy(proxy_str):
    p = urlparse(proxy_str)
    return {
        "server": f"{p.scheme}://{p.hostname}:{p.port or 80}",
        "username": p.username or "",
        "password": p.password or "",
    }


def detect_ip(page):
    for _ in range(3):
        try:
            r = page.evaluate("async () => { const r = await fetch('https://httpbin.org/ip'); const d = await r.json(); return d.origin; }")
            if r: return r
        except Exception:
            pass
        time.sleep(2)
    return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Diagnostico Akamai — solo Patchright nativo")
    parser.add_argument("--proxy", help="Proxy. Ej: http://user:pass@res.webshare.io:80")
    args = parser.parse_args()

    proxy_config = parse_proxy(args.proxy) if args.proxy else None

    print("=" * 60)
    print("  diagnostic_native.py — Patchright nativo, sin JS nuestro")
    print("=" * 60)
    print(f"  Proxy: {'SI' if proxy_config else 'NO'}")
    print()

    # ── Launch ──
    print("[1/4] Lanzando navegador...")
    user_dir = os.path.join("/tmp", f"diag_native_{int(time.time())}")
    os.makedirs(user_dir, exist_ok=True)

    pw = sync_playwright().start()
    kw = {
        "user_data_dir": user_dir,
        "channel": "chrome",
        "headless": False,
        "no_viewport": True,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    if proxy_config:
        kw["proxy"] = proxy_config

    context = pw.chromium.launch_persistent_context(**kw)
    page = context.pages[0] if context.pages else context.new_page()
    # NOTA: NO llamamos a page.add_init_script() — solo stealth nativo
    print("    Navegador lanzado (sin anti-fingerprinting inyectado)")

    # ── Navigate ──
    print("[2/4] Navegando a DOB Now...")
    page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)

    title = page.title() or ""
    print(f"    Titulo: {title}")

    try:
        body = page.evaluate("document.body && document.body.innerText || ''", isolated_context=False) or ""
    except Exception:
        body = ""

    if "Access Denied" in title or ("Access Denied" in body and "edgesuite" in body):
        print("\n" + "=" * 60)
        print("  RESULTADO: ACCESS DENIED")
        print("  Akamai bloqueo la IP directamente. Ni siquiera")
        print("  llego a evaluar cookies — la IP esta quemada.")
        print("=" * 60)
        context.close()
        pw.stop()
        return

    # ── Wait 30s ──
    print("[3/4] Esperando 30s para que Akamai evalue la sesion...")
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            page.evaluate(f"window.scrollBy(0, {50 + int(time.time() % 300)})", isolated_context=False)
        except Exception:
            pass
        time.sleep(2)
    print("    Hecho.")

    # ── Analyze _abck ──
    print("[4/4] Analizando cookies...")
    cookies = context.cookies()

    ip = detect_ip(page)
    print(f"\n    IP visible: {ip}")

    abck_val = ""
    for c in cookies:
        if c.get("name") == "_abck":
            abck_val = c.get("value", "")
            break

    print()
    print("=" * 60)
    if not abck_val:
        print("  RESULTADO: SIN _abck")
        print("  Akamai aun no ha asignado cookie. La IP paso el")
        print("  primer filtro. Posiblemente este limpia.")
    elif "~-1" in abck_val:
        print("  RESULTADO: ENVENENADO (~-1)")
        print(f"  _abck: {abck_val[:120]}")
        print(f"  ...(total {len(abck_val)} chars)")
        if args.proxy:
            print("\n  CONCLUSION: El proxy de Webshare esta quemado.")
            print("  Sin nuestro JS anti-fingerprinting, solo con")
            print("  Patchright nativo, Akamai ya marca ~-1.")
            print("  Tu codigo NO es el problema. Es la IP del proxy.")
        else:
            print("\n  CONCLUSION: Tu IP local esta marcada por Akamai.")
    else:
        segments = abck_val.count("~")
        score_part = abck_val.split("~")[1] if "~" in abck_val else "?"
        print(f"  RESULTADO: LIMPIO (score={score_part}, segments={segments})")
        print(f"  _abck: {abck_val[:120]}")
        print(f"  ...(total {len(abck_val)} chars)")
        if args.proxy:
            print(f"\n  EXITO: El proxy {ip} paso limpio con solo")
            print("  Patchright nativo. Nuestro ANTI_FINGERPRINT_JS")
            print("  es lo que estaba triggereando el ~-1.")
    print("=" * 60)

    print("\nPresiona Enter para cerrar...")
    try:
        input()
    except Exception:
        pass
    context.close()
    pw.stop()


if __name__ == "__main__":
    main()
