#!/usr/bin/env python3
"""
check_abck.py — Diagnostico rapido de sesion Akamai

Abre el navegador con anti-fingerprinting, navega a DOB Now,
espera que Angular cargue y analiza la cookie _abck para
determinar si la IP/sesion esta limpia o envenenada.

Uso:
  python3 check_abck.py                              # sin proxy (IP local)
  python3 check_abck.py --proxy "http://user:pass@host:port"

No depende de ningun otro archivo del proyecto.
"""

import argparse
import os
import time
import sys
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
USER_DATA_DIR = os.path.join("/tmp", "check_abck_profile")

ANTI_FINGERPRINT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
delete navigator.__proto__.webdriver;
window.chrome = { runtime: {} };

Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [1, 2, 3, 4, 5];
        arr.item = (i) => arr[i];
        arr.namedItem = () => null;
        arr.refresh = () => {};
        return arr;
    }
});

(function() {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try { const d = ctx.getImageData(0,0,1,1); d.data[0]^=1; ctx.putImageData(d,0,0); } catch(e) {}
        }
        return origToDataURL.apply(this, arguments);
    };
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x,y,w,h) {
        const d = origGetImageData.call(this,x,y,w,h);
        d.data[0] ^= 1; return d;
    };
})();

(function() {
    const gp = WebGLRenderingContext.prototype.getParameter;
    const h = { apply(t, self, a) {
        if (a[0]===37445) return 'Intel Inc.';
        if (a[0]===37446) return 'Intel Iris OpenGL Engine';
        return t.apply(self, a);
    }};
    WebGLRenderingContext.prototype.getParameter = new Proxy(gp, h);
    if (typeof WebGL2RenderingContext !== 'undefined')
        WebGL2RenderingContext.prototype.getParameter = new Proxy(WebGL2RenderingContext.prototype.getParameter, h);
})();

(function() {
    if (typeof AudioBuffer === 'undefined') return;
    const og = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(c) {
        const d = og.call(this, c);
        for (let i=0; i<Math.min(5,d.length); i++) d[i]+=Math.random()*1e-12-5e-13;
        return d;
    };
})();

Object.defineProperty(screen, 'colorDepth', {get: () => 24});
Object.defineProperty(screen, 'pixelDepth', {get: () => 24});
"""


def parse_proxy(proxy_str):
    """Parse proxy URL -> {server, username, password} for Playwright."""
    p = urlparse(proxy_str)
    host = p.hostname
    port = p.port or 80
    username = p.username or ""
    password = p.password or ""
    server = f"{p.scheme}://{host}:{port}"
    return {"server": server, "username": username, "password": password}


def detect_ip(page):
    """Get the public IP visible through the current proxy/connection."""
    try:
        result = page.evaluate(
            """
            async () => {
                try {
                    const r = await fetch("https://httpbin.org/ip", {timeout: 8000});
                    const data = await r.json();
                    return data.origin;
                } catch(e) {
                    return "ERROR: " + e.message;
                }
            }
        """
        )
        return result
    except Exception as e:
        return f"ERROR: {e}"


def analyze_abck(abck_value):
    result = {"value": abck_value, "healthy": True, "flags": []}

    if not abck_value:
        result["healthy"] = True
        result["flags"].append("NOT_SET (sesion nueva, aun sin cookie)")
        return result

    if "~-1" in abck_value:
        result["healthy"] = False
        result["flags"].append("~-1 DETECTADO (sesion envenenada)")
    else:
        result["flags"].append("sin flag ~-1")

    segments = abck_value.count("~")
    if segments > 5:
        result["healthy"] = False
        result["flags"].append(f"SEGMENTOS_ALTOS ({segments})")
    else:
        result["flags"].append(f"segmentos normales ({segments})")

    try:
        hash_part = abck_value.split("~")[0]
        result["flags"].append(f"hash={hash_part[:16]}...")
    except Exception:
        pass

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostico de sesion Akamai (_abck health check)"
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        default=None,
        help="Proxy residencial rotativo. Ej: http://user:pass@res.webshare.io:80",
    )
    args = parser.parse_args()

    proxy_config = None
    if args.proxy:
        try:
            proxy_config = parse_proxy(args.proxy)
        except Exception as e:
            print(f"[!] Error parseando proxy: {e}")
            sys.exit(1)

    print("=" * 60)
    print("  check_abck.py — Diagnostico de sesion Akamai")
    print("=" * 60)
    print()
    if proxy_config:
        print(f"Proxy: {proxy_config['server']}  (user={proxy_config['username']})")
    else:
        print("Proxy: NINGUNO (IP local)")
    print("Objetivo: detectar si la cookie _abck esta limpia o envenenada")
    print()

    # ── 1: Launch browser ──
    print("[1/6] Lanzando navegador con anti-fingerprinting...")
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    pw = sync_playwright().start()

    launch_kwargs = {
        "user_data_dir": USER_DATA_DIR,
        "channel": "chrome",
        "headless": False,
        "no_viewport": True,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    if proxy_config:
        launch_kwargs["proxy"] = proxy_config

    context = pw.chromium.launch_persistent_context(**launch_kwargs)
    page = context.pages[0] if context.pages else context.new_page()
    page.add_init_script(ANTI_FINGERPRINT_JS)
    print("    Navegador lanzado.")

    # ── 2: Detect public IP ──
    print("[2/6] Detectando IP publica...")
    ip = detect_ip(page)
    print(f"    IP visible: {ip}")

    # ── 3: Navigate to DOB Now ──
    print("[3/6] Navegando a DOB Now...")
    page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)

    title = page.title()
    print(f"    Titulo: {title}")

    # ── 4: Check for Akamai block ──
    print("[4/6] Verificando bloqueo Akamai...")
    try:
        body = (
            page.evaluate(
                "document.body && document.body.innerText || ''",
                isolated_context=False,
            )
            or ""
        )
    except Exception:
        body = ""
    if "Access Denied" in title or ("Access Denied" in body and "edgesuite" in body):
        print()
        print("=" * 60)
        print("  RESULTADO: BLOQUEADO")
        print("  Akamai esta sirviendo Access Denied.")
        print(f"  IP: {ip}")
        print("  Esta IP esta quemada. Prueba con otra o rota el proxy.")
        print("=" * 60)
        page.screenshot(path="/tmp/check_abck_blocked.png")
        print("  Screenshot: /tmp/check_abck_blocked.png")
        context.close()
        pw.stop()
        return

    print("    No bloqueado. Buscando Angular...")

    # ── 5: Wait for Angular ──
    print("[5/6] Esperando Angular...")
    angular_ok = False
    for i in range(60):
        try:
            ok = page.evaluate(
                """
                typeof angular !== 'undefined' &&
                angular.element(document.body).injector() !== undefined
                """,
                isolated_context=False,
            )
            if ok:
                angular_ok = True
                break
        except Exception:
            pass
        time.sleep(1)
    print(f"    Angular: {'DETECTADO' if angular_ok else 'NO DETECTADO'}")
    if not angular_ok:
        print("    (Si no has hecho login, hazlo ahora y presiona Ctrl+C)")

    # ── 6: Analyze _abck ──
    print("[6/6] Analizando cookie _abck...")
    time.sleep(2)
    cookies = context.cookies()

    print()
    print("=" * 60)
    print("  COOKIES RELEVANTES")
    print("=" * 60)

    relevant = ["_abck", "bm_mi", "bm_sv", "bm_sz", "bm_so", "ak_bmsc"]
    for c in cookies:
        name = c.get("name", "")
        if name in relevant or name.startswith("bm_"):
            val = c.get("value", "")
            print(f"  {name}: {val[:100]}{'...' if len(val)>100 else ''}")

    abck_cookie = None
    for c in cookies:
        if c.get("name") == "_abck":
            abck_cookie = c.get("value", "")
            break

    print()
    print("=" * 60)
    print("  ANALISIS _abck")
    print("=" * 60)

    analysis = analyze_abck(abck_cookie)
    for flag in analysis["flags"]:
        print(f"  - {flag}")

    print()
    print("=" * 60)
    if analysis["healthy"]:
        print("  RESULTADO: LIMPIO")
        print(f"  IP: {ip}")
        print("  La sesion y la IP parecen estar OK para scrapear.")
    else:
        print("  RESULTADO: ENVENENADO")
        print(f"  IP: {ip}")
        print("  Akamai ha marcado esta sesion como bot.")
        print("  Recomendacion: rotar IP (nueva IP de proxy) y limpiar cookies.")
    print("=" * 60)

    # ── Bonus: test API call ──
    if angular_ok:
        print()
        print("[*] Probando una llamada API real (getPublicPortalBuildDisplay)...")
        try:
            result = page.evaluate(
                """
                async () => {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method: "POST", url: "/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", headers: {}};
                    req = interceptor.request(req);
                    try {
                        const resp = await fetch("https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", {
                            method: "POST",
                            headers: {"Content-Type":"application/json", "X-Requested-With":"XMLHttpRequest", ...req.headers},
                            body: JSON.stringify({"BIN":"4624658","SearchBy":"2","StreetName":""})
                        });
                        const text = await resp.text();
                        return {status: resp.status, len: text.length};
                    } catch(e) {
                        return {status: 0, len: 0, error: e.message};
                    }
                }
                """,
                isolated_context=False,
            )
            if result.get("status") == 200:
                print(f"    OK: status={result['status']} | response={result['len']} bytes")
                print("    La API responde correctamente. Sesion valida.")
            else:
                print(f"    FAIL: status={result.get('status')} | error={result.get('error','')}")
        except Exception as e:
            print(f"    ERROR: {e}")

    print()
    print("Presiona Enter para cerrar el navegador...")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    context.close()
    pw.stop()
    print("Navegador cerrado.")


if __name__ == "__main__":
    main()
