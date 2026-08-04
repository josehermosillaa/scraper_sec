#!/usr/bin/env python3
"""
undetectable_scraper.py — Scraper anti-Akamai por capas

Estrategia contra Akamai Bot Manager (5 capas de deteccion):

  1. CAPA IP (40%): Proxy residencial rotativo (Webshare).
     Los proxies residenciales salen de IPs de ISP reales (hogares, 4G).
     Akamai NO las clasifica como "datacenter/hosting" → score base bajo.

  2. CAPA FINGERPRINT (25%): Spoofing completo del navegador.
     Akamai recolecta ~40 propiedades (canvas, WebGL, AudioContext, fonts,
     hardwareConcurrency, deviceMemory, timezone, languages, platform...).
     Cada una se modifica para que el hash coincida con un Chrome real.

  3. CAPA RED (20%): Sin mismatch browser/HTTP.
     Todas las requests se hacen con fetch() desde dentro del navegador.
     Mismo TLS handshake, mismos headers, misma sesion → Akamai ve UN solo
     dispositivo. No hay dos fingerprints correlacionables.

  4. CAPA COMPORTAMIENTO (10%): Movimiento de mouse Bezier,
     navegacion de investigacion (visitar paginas del portal entre BINs),
     session aging (5 min de warm-up pasivo), pausas largas aleatorias.

  5. CAPA SESION (5%): Monitoreo de _abck, deteccion de spinner intermedio
     de Akamai, rotacion automatica de proxy al detectar envenenamiento.

Uso:
  python3 undetectable_scraper.py --proxy "http://user:pass@p.webshare.io:80"
  python3 undetectable_scraper.py --proxy "http://user:pass@p.webshare.io:80" --rotate-every 5
  python3 undetectable_scraper.py  # sin proxy (IP local)
"""

import argparse
import csv
import json
import logging
import math
import os
import random
import sys
import time
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright

# ── Rutas ────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(HERE, "input.csv")
OUTPUT_CSV = os.path.join(HERE, "resultado_undetectable.csv")
CHECKPOINT_FILE = os.path.join(HERE, "checkpoint_undetectable.json")

LOG_FILE = os.path.join(HERE, "undetectable.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("undetectable")

# ── URLs ─────────────────────────────────────────────────────────────────────
DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
PUBLIC_PATH = "/Publish/WrapperPP/PublicPortal.svc"
SERVICE_PATH = "/Publish/WrapperServicePP/WrapperService.svc"

# Secciones del portal para "research navigation" (simular que un humano explora)
RESEARCH_PATHS = [
    "/Publish/",
    "/Publish/#!/search",
    "/Publish/#!/dashboard",
    "/Publish/#!/propertySearch",
]

# ── Constantes ───────────────────────────────────────────────────────────────
KEYS = {"ZD1", "ZD2", "ZD1A", "ZRD"}
KEYS_LOWER = {k.lower() for k in KEYS}
BOROUGH_MAP = {
    "Manhattan": "MANHATTAN", "Bronx": "BRONX",
    "Brooklyn": "BROOKLYN", "Queens": "QUEENS",
    "Staten Island": "STATEN ISLAND",
}
COLS = [
    "Job Filing Number", "Filing Status", "Filing Date",
    "House No", "Street Name", "Borough", "Block", "LOT", "Bin",
    "Job Description", "Filing Review Type",
    "guid", "filing_status", "doc_description", "doc_name",
    "doc_url_original", "download_url", "result_status", "error_body",
    "zoning_status", "doc_create_on", "doc_category",
    "doc_type_name", "doc_status_label",
]

DEFAULT_MAX_ROWS = 10
DEFAULT_ROTATE_EVERY = 10
DEFAULT_SESSION_AGE_S = 120
WARM_UP_S = 20
AKAMAI_RELOAD_TRIES = 3
PROXY_COOLDOWN_S = 30
MAX_PROXY_FAILS = 4

# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 2: ANTI-FINGERPRINTING EXTENDIDO
# ═══════════════════════════════════════════════════════════════════════════════
#
# Cada propiedad que Akamai mide se modifica aqui.
# El objetivo: que el hash de fingerprint del browser sea indistinguible
# de un Chrome 130+ real en Windows/Linux con hardware comun.

ANTI_FINGERPRINT_JS = """
// ── webdriver (Patchright ya lo oculta) ──
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch(e) {}
try { delete navigator.__proto__.webdriver; } catch(e) {}
window.chrome = { runtime: {} };

// ── Hardware: simular laptop tipica (8 cores, 8GB) ──
//    Chrome 130+ sella varias de estas propiedades. Si falla defineProperty,
//    es porque ya vienen con valores reales de hardware → no hay nada que ocultar.
try { Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'deviceMemory', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'platform', {get: () => 'Linux x86_64'}); } catch(e) {}

// ── Timezone NYC ──
const TzDate = Date;
const origToString = TzDate.prototype.toString;
TzDate.prototype.toString = function() {
    return origToString.call(this).replace(
        /GMT[+-]\\d{4} \\(([^)]+)\\)/,
        'GMT-0400 (Eastern Daylight Time)'
    );
};

// ── Languages ──
try { Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']}); } catch(e) {}
try { Object.defineProperty(navigator, 'language', {get: () => 'en-US'}); } catch(e) {}

// ── Plugins ──
try {
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = [
                {name:'Chrome PDF Plugin', filename:'internal-pdf-viewer', description:'Portable Document Format'},
                {name:'Chrome PDF Viewer', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:''},
                {name:'Native Client', filename:'internal-nacl-plugin', description:''},
            ];
            arr.item = (i) => arr[i] || null;
            arr.namedItem = (n) => arr.find(p => p.name === n) || null;
            arr.refresh = () => {};
            try { Object.setPrototypeOf(arr, PluginArray.prototype); } catch(e) {}
            return arr;
        }
    });
} catch(e) {}

// ── Canvas fingerprint: modificar 1 bit del primer pixel ──
(function() {
    const noise = function(ctx) {
        try {
            const d = ctx.getImageData(0, 0, 1, 1);
            d.data[0] = d.data[0] ^ 1;
            ctx.putImageData(d, 0, 0);
        } catch(e) {}
    };
    const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d'); if(ctx) noise(ctx);
        return _toDataURL.apply(this, arguments);
    };
    const _toBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function() {
        const ctx = this.getContext('2d'); if(ctx) noise(ctx);
        return _toBlob.apply(this, arguments);
    };
    const _getImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x,y,w,h) {
        const d = _getImageData.call(this,x,y,w,h);
        d.data[0] = d.data[0] ^ 1;
        return d;
    };
})();

// ── WebGL vendor/renderer (Intel Iris, comun en laptops) ──
(function() {
    const handler = {
        apply(target, self, args) {
            if (args[0] === 37445) return 'Intel Inc.';
            if (args[0] === 37446) return 'Intel Iris OpenGL Engine';
            return target.apply(self, args);
        }
    };
    try {
        WebGLRenderingContext.prototype.getParameter = new Proxy(
            WebGLRenderingContext.prototype.getParameter, handler
        );
    } catch(e) {}
    if (typeof WebGL2RenderingContext !== 'undefined') {
        try {
            WebGL2RenderingContext.prototype.getParameter = new Proxy(
                WebGL2RenderingContext.prototype.getParameter, handler
            );
        } catch(e) {}
    }
})();

// ── AudioContext: ruido minusculo en el primer sample ──
(function() {
    if (typeof AudioBuffer === 'undefined') return;
    const _gcd = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(c) {
        const d = _gcd.call(this, c);
        for (let i=0; i<Math.min(5,d.length); i++) d[i] += Math.random()*1e-12 - 5e-13;
        return d;
    };
})();

// ── Screen: colorDepth y pixelDepth ──
try { Object.defineProperty(screen, 'colorDepth', {get: () => 24}); } catch(e) {}
try { Object.defineProperty(screen, 'pixelDepth', {get: () => 24}); } catch(e) {}

// ── Font enumeration noise ──
try {
    const _origQueryLocalFonts = window.queryLocalFonts;
    if (_origQueryLocalFonts) {
        window.queryLocalFonts = async function() {
            const fonts = await _origQueryLocalFonts.call(this);
            fonts.push({family:'ArialUnicodeMS', fullName:'Arial Unicode MS', postscriptName:'ArialUnicodeMS', style:'Regular'});
            fonts.push({family:'CalibriLight', fullName:'Calibri Light', postscriptName:'CalibriLight', style:'Regular'});
            return fonts;
        };
    }
} catch(e) {}

// ── Permissions ──
try {
    if (navigator.permissions && navigator.permissions.query) {
        const _q = navigator.permissions.query;
        navigator.permissions.query = function(args) {
            if (args.name === 'notifications')
                return Promise.resolve({state:'prompt', onchange:null});
            return _q.apply(this, arguments);
        };
    }
} catch(e) {}

// ── Media devices ──
try {
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        const _ed = navigator.mediaDevices.enumerateDevices;
        navigator.mediaDevices.enumerateDevices = async function() {
            const devices = await _ed.call(this);
            if (!devices.some(d => d.kind === 'videoinput')) {
                devices.push({deviceId:'fake-cam', kind:'videoinput', label:'Integrated Camera', groupId:'fake-grp'});
            }
            return devices;
        };
    }
} catch(e) {}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 4: MOUSE BEZIER
# ═══════════════════════════════════════════════════════════════════════════════
#
# El mouse humano no se teletransporta. Sigue curvas Bezier.
# Akamai mide la trayectoria del puntero via eventos mousemove.
# Una linea recta (o peor, ausencia de movimiento) delata el bot.
# Generamos puntos intermedios entre inicio y destino con
# una curva cuadratica de Bezier + control point aleatorio.


def _bezier_point(p0, p1, p2, t):
    """Punto en curva Bezier cuadratica en t (0..1)."""
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
    return (int(x), int(y))


def _bezier_curve(start, end, steps=30):
    """Genera [steps] puntos entre start y end siguiendo curva Bezier."""
    mid_x = (start[0] + end[0]) / 2 + random.randint(-150, 150)
    mid_y = (start[1] + end[1]) / 2 + random.randint(-100, 100)
    mid_x = max(0, min(mid_x, 1920))
    mid_y = max(0, min(mid_y, 1080))
    control = (mid_x, mid_y)
    return [_bezier_point(start, control, end, t / steps) for t in range(steps + 1)]


def human_mouse_move(page, to_x, to_y, from_x=None, from_y=None):
    """
    Mueve el mouse del punto actual (o from) al destino usando curva Bezier.
    Cada punto intermedio se despacha como evento CDP Input.dispatchMouseEvent.
    """
    if from_x is None or from_y is None:
        try:
            w = page.evaluate("window.innerWidth", isolated_context=False)
            h = page.evaluate("window.innerHeight", isolated_context=False)
            from_x, from_y = random.randint(100, w - 100), random.randint(100, h - 100)
        except Exception:
            from_x, from_y = 500, 400

    curve = _bezier_curve((from_x, from_y), (to_x, to_y), steps=random.randint(20, 40))

    cdp = None
    try:
        cdp = page.context.new_cdp_session(page)
    except Exception:
        pass

    for i, (x, y) in enumerate(curve):
        delay = random.uniform(0.002, 0.008)  # 2-8ms entre puntos (rapido pero natural)
        time.sleep(delay)
        if cdp:
            try:
                cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved",
                    "x": x, "y": y,
                    "button": "none",
                    "modifiers": 0,
                    "timestamp": int(time.time() * 1000),
                })
            except Exception:
                pass

    if cdp:
        try:
            cdp.detach()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 4: RESEARCH NAVIGATION (warm-up como un humano investigando)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Un humano real no llega y scrapea. Primero navega, explora, hace scroll,
# quizas clickea en algun link, vuelve atras, etc.
# Esto se hace DURANTE el session aging para "envejecer" la sesion
# con comportamiento organico antes de mandar requests.


def research_warmup(page, duration_s=WARM_UP_S):
    """
    Simula navegacion humana durante duration_s segundos:
    - Scrolls aleatorios
    - Movimientos de mouse con Bezier
    - Clicks en areas no-interactivas (simular exploracion visual)
    - Visitas a otras secciones del portal (search, dashboard)
    """
    print(f"  [research] Warm-up humano ({duration_s}s)...")
    log.info(f"Research warmup started ({duration_s}s)")
    t0 = time.time()

    w = page.evaluate("window.innerWidth", isolated_context=False) or 1920
    h = page.evaluate("window.innerHeight", isolated_context=False) or 1080

    visit_sections = random.sample(RESEARCH_PATHS, min(2, len(RESEARCH_PATHS)))

    while time.time() - t0 < duration_s:
        action = random.random()

        if action < 0.35:
            # Scroll natural
            delta = random.randint(80, 400)
            page.evaluate(f"window.scrollBy(0, {delta})", isolated_context=False)
            time.sleep(random.uniform(1.0, 3.5))

        elif action < 0.55:
            # Mouse move + hover
            target_x = random.randint(100, w - 100)
            target_y = random.randint(100, h - 100)
            human_mouse_move(page, target_x, target_y)
            time.sleep(random.uniform(0.8, 2.5))

        elif action < 0.65:
            # Scroll up (como re-leyendo)
            delta = random.randint(-300, -50)
            page.evaluate(f"window.scrollBy(0, {delta})", isolated_context=False)
            time.sleep(random.uniform(0.5, 2.0))

        elif action < 0.72 and visit_sections:
            # Visitar otra seccion del portal y volver
            section = visit_sections.pop()
            full_url = f"https://a810-dobnow.nyc.gov{section}"
            try:
                page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(random.uniform(3, 8))
                page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=15000)
                time.sleep(random.uniform(2, 4))
            except Exception:
                pass

        else:
            time.sleep(random.uniform(2, 6))

    print("  [research] Warm-up completado.")
    log.info("Research warmup done")


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 5: DETECCION DE SPINNER INTERMEDIO DE AKAMAI
# ═══════════════════════════════════════════════════════════════════════════════
#
# Antes del Access Denied, Akamai a veces muestra una pagina intermedia
# con spinner ("Checking your browser..."). Si la detectamos, esperamos
# a que se resuelva en vez de asumir bloqueo inmediato.


def wait_for_akamai_spinner(page, timeout_s=30):
    """
    Detecta la pagina de desafio intermedio de Akamai (spinner)
    y espera a que se resuelva (sea redirigiendo al sitio real
    o mostrando Access Denied).
    Retorna True si el desafio se resolvio exitosamente.
    """
    t0 = time.time()
    checked_once = False
    while time.time() - t0 < timeout_s:
        try:
            title = page.title() or ""
            body_snippet = page.evaluate(
                "document.body ? document.body.innerText.slice(0,200) : ''",
                isolated_context=False,
            ) or ""
        except Exception:
            time.sleep(1)
            continue

        combined = (title + body_snippet).lower()

        # Indicadores de desafio Akamai en curso
        spinner_keywords = [
            "checking your browser",
            "redirecting",
            "please wait",
            "verifying",
            "ddos protection",
        ]
        is_challenge = any(kw in combined for kw in spinner_keywords)

        if is_challenge:
            if not checked_once:
                print("  [akamai] Desafio intermedio detectado. Esperando...")
                log.info("Akamai spinner detected, waiting...")
                checked_once = True
            time.sleep(2)
            continue

        # Ya paso el desafio (o nunca hubo)
        if checked_once:
            print("  [akamai] Desafio resuelto.")
            log.info("Akamai spinner resolved")
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# PROXY PARSING
# ═══════════════════════════════════════════════════════════════════════════════


def parse_proxy(proxy_str):
    p = urlparse(proxy_str)
    return {
        "server": f"{p.scheme}://{p.hostname}:{p.port or 80}",
        "username": p.username or "",
        "password": p.password or "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BROWSER LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════


def launch_browser(proxy_config=None):
    """Lanza Chrome via Patchright con perfil persistente y anti-fingerprinting."""
    if proxy_config is None:
        user_data_dir = os.path.join("/tmp", "undetectable_profile")
    else:
        # Perfil UNICO por sesion: evita que cookies _abck envenenadas persistan
        user_data_dir = os.path.join("/tmp", f"undetectable_{int(time.time())}")

    os.makedirs(user_data_dir, exist_ok=True)
    log.debug(f"User data dir: {user_data_dir}")
    pw = sync_playwright().start()

    kwargs = {
        "user_data_dir": user_data_dir,
        "channel": "chrome",
        "headless": False,
        "no_viewport": True,
        "args": [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if proxy_config:
        kwargs["proxy"] = proxy_config
        log.info(f"Browser launching with proxy: {proxy_config['server']}")

    context = pw.chromium.launch_persistent_context(**kwargs)
    page = context.pages[0] if context.pages else context.new_page()
    page.add_init_script(ANTI_FINGERPRINT_JS)
    return pw, context, page


def close_browser(pw, context):
    try:
        context.close()
    except Exception:
        pass
    time.sleep(1)
    try:
        pw.stop()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# AKAMAI DETECTION & HEALTH
# ═══════════════════════════════════════════════════════════════════════════════


def page_is_blocked(page):
    try:
        if "Access Denied" in (page.title() or ""):
            return True
        body = (
            page.evaluate("document.body && document.body.innerText || ''", isolated_context=False) or ""
        )
        return "Access Denied" in body and "edgesuite" in body
    except Exception:
        return False


def wait_angular(page, timeout_s=120):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            ok = page.evaluate(
                "typeof angular !== 'undefined' && angular.element(document.body).injector() !== undefined",
                isolated_context=False,
            )
            if ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def check_abck_health(context):
    """
    Analiza la cookie _abck de Akamai.
    Estructura: HASH~SCORE~SENSOR_DATA

    Scores de Akamai:
      ~-1~ = BOT confirmado (envenenado)
      ~0~  = humano/normal (limpio)
      >5 segmentos ~ = posible telemetria anormal

    Retorna (healthy: bool, full_value: str)
    """
    cookies = context.cookies()
    for c in cookies:
        if c.get("name") == "_abck":
            val = c.get("value", "")
            if not val:
                return True, val

            # ── Check 1: flag ~-1 (bot confirmado) ──
            if "~-1" in val:
                print(f"  [_abck] ENVENENADO (~-1 detectado)")
                print(f"  [_abck] valor completo: {val}")
                log.warning(f"_abck POISONED: ~-1 found | full={val}")
                return False, val

            # ── Check 2: segmentos anormales (>5 ~) ──
            segments = val.count("~")
            if segments > 5:
                print(f"  [_abck] SOSPECHOSO ({segments} segmentos ~)")
                print(f"  [_abck] valor completo: {val}")
                log.warning(f"_abck SUSPICIOUS segments={segments} | full={val}")
                return False, val

            return True, val

    return True, ""


def detect_ip(page):
    """Detecta IP publica via httpbin.org/ip, con retry."""
    for attempt in range(3):
        try:
            result = page.evaluate(
                "async () => { const r = await fetch('https://httpbin.org/ip'); const d = await r.json(); return d.origin; }"
            )
            if result and result != "unknown":
                return result
        except Exception:
            pass
        if attempt < 2:
            time.sleep(2)
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 3: IN-BROWSER API (sin curl_cffi, todo via fetch del navegador)
# ═══════════════════════════════════════════════════════════════════════════════


def browser_post(page, url_path, body, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            result = page.evaluate(
                """
                async ({url, body}) => {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method:"POST", url:url, headers:{}};
                    req = interceptor.request(req);
                    try {
                        const resp = await fetch("https://a810-dobnow.nyc.gov"+url, {
                            method:"POST",
                            headers:{"Content-Type":"application/json","X-Requested-With":"XMLHttpRequest",...req.headers},
                            body:JSON.stringify(body)
                        });
                        const text = await resp.text();
                        return {status:resp.status, body:text};
                    } catch(e) { return {status:0, body:e.message}; }
                }
            """,
                {"url": url_path, "body": body},
                isolated_context=False,
            )
            status = result.get("status", 0)
            body_text = result.get("body", "")
            if status == 403 and "Access Denied" in body_text:
                return None, "AKAMAI_BLOCKED"
            if status == 0:
                last_err = body_text
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                continue
            try:
                return status, json.loads(body_text)
            except json.JSONDecodeError:
                return status, body_text
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None, str(last_err)


def browser_get(page, url_path, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            result = page.evaluate(
                """
                async ({url}) => {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method:"GET", url:url, headers:{}};
                    req = interceptor.request(req);
                    try {
                        const resp = await fetch("https://a810-dobnow.nyc.gov"+url, {
                            method:"GET",
                            headers:{"X-Requested-With":"XMLHttpRequest",...req.headers}
                        });
                        const text = await resp.text();
                        return {status:resp.status, body:text};
                    } catch(e) { return {status:0, body:e.message}; }
                }
            """,
                {"url": url_path},
                isolated_context=False,
            )
            status = result.get("status", 0)
            body_text = result.get("body", "")
            if status == 403 and "Access Denied" in body_text:
                return None, "AKAMAI_BLOCKED"
            if status == 0:
                last_err = body_text
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                continue
            try:
                return status, json.loads(body_text)
            except json.JSONDecodeError:
                return status, body_text
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None, str(last_err)


def human_delay():
    """Delay humano entre requests: 60% rapido, 30% medio, 10% largo."""
    r = random.random()
    if r < 0.6:
        time.sleep(random.uniform(2, 5))
    elif r < 0.9:
        time.sleep(random.uniform(5, 12))
    else:
        time.sleep(random.uniform(15, 30))


def human_scroll(page):
    for _ in range(random.randint(1, 3)):
        delta = random.randint(100, 500)
        try:
            page.evaluate(f"window.scrollBy(0, {delta})", isolated_context=False)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 1.0))


# ═══════════════════════════════════════════════════════════════════════════════
# API WRAPPERS
# ═══════════════════════════════════════════════════════════════════════════════


def api_search_bin(page, bin_num, street=""):
    human_delay()
    human_scroll(page)
    log.debug(f"api_search_bin BIN={bin_num}")
    st, data = browser_post(
        page, f"{PUBLIC_PATH}/getPublicPortalBuildDisplay",
        {"BIN": bin_num, "SearchBy": "2", "StreetName": street},
    )
    if st is None or isinstance(data, str):
        log.warning(f"api_search_bin BIN={bin_num} FAIL: {data}")
        return None, data or "KO"
    if not data.get("IsSuccess") or st != 200:
        log.warning(f"api_search_bin BIN={bin_num} API_ERROR")
        return None, "API_ERROR"
    jobs = data.get("ListBuildDetails", [])
    return (jobs[0] if jobs else None), None


def api_get_pw1(page, guid):
    human_delay()
    human_scroll(page)
    st, data = browser_get(page, f"{SERVICE_PATH}/GetJobFilingPW1/{guid}")
    if st is None or isinstance(data, str):
        return None, None, None
    return (data.get("FilingIncludes", ""), data.get("CurrentFilingStatusValue", ""), data.get("IsPlanApproved", False))


def api_get_zd1wd(page, guid):
    human_delay()
    human_scroll(page)
    st, data = browser_post(
        page, f"{SERVICE_PATH}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid},
    )
    if st is None or isinstance(data, str) or st != 200:
        return []
    return data.get("RequiredDocumentList") or []


def api_get_portal_docs(page, guid, fi, cstatus, isplan):
    human_delay()
    human_scroll(page)
    st, data = browser_post(
        page, f"{PUBLIC_PATH}/GetPublicPortalPartialJobFiling",
        {"Applicant": None, "RelatedEntityLogicalName": "dobnyc_documentlist",
         "JobFilingGUID": guid, "FilingIncludes": fi or "",
         "CurrentFilingStatusValue": cstatus or "", "IsPlanApproved": isplan or False},
    )
    if st is None or isinstance(data, str) or st != 200:
        return []
    return data.get("RequiredDocumentList") or []


def api_get_download_url(page, doc_url, borough):
    human_delay()
    human_scroll(page)
    bk = BOROUGH_MAP.get(borough, borough.upper())
    dp = f"\\\\PortalDownloadedDocuments\\{bk}\\TEST\\"
    st, data = browser_post(
        page, f"{SERVICE_PATH}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": dp},
    )
    if st is None or isinstance(data, str) or st != 200:
        return ""
    return data.get("downloadPath", "")


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 1 + 5: RECOVERY CON PROXY ROTATION
# ═══════════════════════════════════════════════════════════════════════════════
#
# Cuando Akamai bloquea o envenena _abck:
#   1. Cerramos el navegador actual
#   2. Abrimos uno nuevo (el proxy residencial dara nueva IP al reconnect)
#   3. Session aging + research warmup
#   4. Verificamos que Angular y _abck esten OK
#   5. Continuamos


def rotation_recovery(proxy_config, fail_count, pw=None, context=None, prev_ip=None):
    """
    Rotacion completa: cerrar browser, forzar nueva conexion TCP
    (el proxy residencial asigna IP nueva), abrir browser nuevo,
    session aging, verificar salud.
    Retorna (pw, context, page) o (None, None, None)
    """
    if pw and context:
        close_browser(pw, context)

    fail_count[0] += 1
    if fail_count[0] >= MAX_PROXY_FAILS:
        cooldown = PROXY_COOLDOWN_S * 3
        print(f"  [recovery] {fail_count[0]} fallos. Cooldown {cooldown}s...")
        log.warning(f"Max proxy fails ({fail_count[0]}), cooldown {cooldown}s")
        time.sleep(cooldown)
        fail_count[0] = 0
    else:
        time.sleep(PROXY_COOLDOWN_S)
        log.info(f"Rotation recovery attempt {fail_count[0]}")

    new_pw, new_context, new_page = launch_browser(proxy_config)
    ip = detect_ip(new_page)
    if prev_ip:
        if ip == prev_ip:
            print(f"  [recovery] IP NO cambio: {ip} (misma que antes)")
            log.warning(f"Recovery: same IP returned ({ip})")
        else:
            print(f"  [recovery] IP cambio: {prev_ip} -> {ip}")
    else:
        print(f"  [recovery] Nueva IP: {ip}")
    log.info(f"Recovery new IP: {ip} (prev={prev_ip})")

    try:
        new_page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        close_browser(new_pw, new_context)
        return None, None, None
    time.sleep(4)

    # Esperar por posible spinner de Akamai
    wait_for_akamai_spinner(new_page, timeout_s=30)

    if page_is_blocked(new_page):
        print("  [recovery] Nueva IP tambien bloqueada.")
        log.warning("Recovery: new IP blocked")
        close_browser(new_pw, new_context)
        return None, None, None

    # Session aging: dejar que la sesion "madure" unos minutos
    print("  [recovery] Session aging + research warmup...")
    research_warmup(new_page, duration_s=min(60, WARM_UP_S))

    if not wait_angular(new_page, timeout_s=60):
        print("  [recovery] Angular no disponible en nueva sesion.")
        log.warning("Recovery: Angular not ready")
        close_browser(new_pw, new_context)
        return None, None, None

    healthy, val = check_abck_health(new_context)
    if healthy:
        print(f"  [recovery] _abck OK. Sesion limpia.")
        log.info("Recovery: _abck healthy")
        fail_count[0] = 0
        return new_pw, new_context, new_page
    else:
        print(f"  [recovery] _abck envenenado en nueva IP: {val[:60]}...")
        log.warning(f"Recovery: _abck still poisoned on new IP")
        close_browser(new_pw, new_context)
        return None, None, None


# ═══════════════════════════════════════════════════════════════════════════════
# CSV
# ═══════════════════════════════════════════════════════════════════════════════


def empty_row():
    return {k: "" for k in COLS}


def row_from_job(job):
    r = empty_row()
    r["Bin"] = job.get("Bin", "")
    r["Borough"] = job.get("Borough", "")
    r["Street Name"] = job.get("StreetName", "")
    r["House No"] = job.get("HouseNo", "")
    r["Block"] = job.get("Block", "")
    r["LOT"] = job.get("LOT", "")
    r["Job Description"] = job.get("JobDescription", "")
    r["Job Filing Number"] = job.get("JobNumber_FilingNumber", "")
    r["Filing Date"] = job.get("FilingDate", "")
    r["Filing Status"] = job.get("FilingStatusDescription", "")
    r["Filing Review Type"] = job.get("FilingReviewType", "")
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Scraper anti-Akamai para DOB Now")
    parser.add_argument(
        "--proxy", metavar="URL", default=None,
        help="Proxy residencial. Ej: http://user:pass@res.webshare.io:80",
    )
    parser.add_argument(
        "--rotate-every", type=int, default=DEFAULT_ROTATE_EVERY,
        help=f"Rotar proxy cada N BINs procesados (default: {DEFAULT_ROTATE_EVERY})",
    )
    parser.add_argument(
        "--max-rows", type=int, default=DEFAULT_MAX_ROWS,
        help=f"Max BINs a procesar (default: {DEFAULT_MAX_ROWS})",
    )
    parser.add_argument(
        "--session-age", type=int, default=DEFAULT_SESSION_AGE_S,
        help=f"Segundos de warm-up inicial (default: {DEFAULT_SESSION_AGE_S})",
    )
    args = parser.parse_args()

    proxy_config = None
    if args.proxy:
        proxy_config = parse_proxy(args.proxy)

    print("=" * 60)
    print("  undetectable_scraper.py")
    print("  Anti-Akamai: 5 capas de proteccion")
    print("=" * 60)
    print(f"  Proxy:      {'SI' if proxy_config else 'NO (IP local)'}")
    print(f"  Rotar cada: {args.rotate_every} BINs")
    print(f"  Max rows:   {args.max_rows}")
    print(f"  Session age:{args.session_age}s")
    print("=" * 60)
    log.info(f"START | proxy={bool(proxy_config)} rotate_every={args.rotate_every} max_rows={args.max_rows}")

    if not os.path.exists(INPUT_CSV):
        print(f"[!] {INPUT_CSV} no existe.")
        sys.exit(1)

    # ── 1. Launch browser ──
    print("\n[*] Lanzando navegador con anti-fingerprinting extendido...")
    pw, context, page = launch_browser(proxy_config)

    ip = detect_ip(page)
    print(f"    IP: {ip}")
    log.info(f"Initial IP: {ip}")

    print("[*] Navegando a DOB Now...")
    page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)

    # Esperar spinner de Akamai si aparece
    wait_for_akamai_spinner(page, timeout_s=30)

    if page_is_blocked(page):
        print("[!] Bloqueado en primera carga. Intentando recovery...")
        new = rotation_recovery(proxy_config, [0], pw, context)
        if new[0]:
            pw, context, page = new
        else:
            print("[!] No se pudo establecer sesion. Abortando.")
            sys.exit(1)

    # ── 2. Session aging ──
    print(f"\n[*] Session aging ({args.session_age}s) + research navigation...")
    research_warmup(page, duration_s=args.session_age)

    # ── 3. Wait for Angular ──
    print("[*] Esperando Angular (logueate si es necesario)...")
    if not wait_angular(page, 120):
        print("[!] Angular no detectado. Reintentando...")
        page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        if not wait_angular(page, 60):
            print("[!] Sin Angular. Abortando.")
            close_browser(pw, context)
            sys.exit(1)

    healthy, abck_val = check_abck_health(context)
    print(f"    _abck: {'OK' if healthy else 'ENVENENADO'}")
    log.info(f"Initial _abck: {'OK' if healthy else 'POISONED'} (full={abck_val})")

    # ── Strategic rotation: si _abck envenenado desde el inicio, rotar ANTES de scrapear ──
    if not healthy and proxy_config:
        print("  [_abck] Envenenado al inicio. Rotando proxy antes de scrapear...")
        log.warning("_abck poisoned at startup, pre-emptive rotation")
        new = rotation_recovery(proxy_config, [0], pw, context, prev_ip=ip)
        if new[0]:
            pw, context, page = new
            ip = detect_ip(page)
            healthy, abck_val = check_abck_health(context)
            print(f"    IP tras rotacion: {ip}")
            print(f"    _abck tras rotacion: {'OK' if healthy else 'SIGUE ENVENENADO'}")
            log.info(f"Post start-rotation _abck: {'OK' if healthy else 'POISONED'} | IP={ip}")
        else:
            print("  [_abck] Rotacion inicial fallida. Sin sesion limpia. Abortando.")
            log.error("Pre-emptive rotation failed, exiting")
            sys.exit(1)

    # ── 4. Read input ──
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    end_at = min(args.max_rows, total)
    print(f"\n[*] {total} filas en CSV, procesando {end_at}")

    # ── 5. Main loop ──
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=COLS)
        writer.writeheader()

        processed = 0
        fail_count = [0]
        total_zd = 0

        for idx, row in enumerate(rows):
            if idx >= end_at:
                break

            # ── Proxy rotation ──
            if processed > 0 and proxy_config and processed % args.rotate_every == 0:
                print(f"\n  [rotate] Rotando proxy (cada {args.rotate_every} BINs)...")
                log.info(f"Rotating proxy at BIN {processed}")
                new = rotation_recovery(proxy_config, [0], pw, context, prev_ip=ip)
                if new[0]:
                    pw, context, page = new
                    ip = detect_ip(page)
                else:
                    print("  [rotate] Fallo al rotar. Sin navegador usable. Abortando.")
                    log.error("Rotation failed, no usable browser left")
                    break

            # ── Periodic _abck check ──
            if processed > 0 and processed % 5 == 0:
                healthy, val = check_abck_health(context)
                if not healthy and proxy_config:
                    print("  [_abck] Envenenado. Forzando rotacion de proxy...")
                    log.warning("_abck poisoned mid-run, forcing rotation")
                    new = rotation_recovery(proxy_config, [0], pw, context, prev_ip=ip)
                    if new[0]:
                        pw, context, page = new
                        ip = detect_ip(page)
                    else:
                        print("  [_abck] Recovery fallido. Sin navegador. Abortando.")
                        log.error("_abck recovery failed, no usable browser")
                        break

            # ── Parse row ──
            bin_num = row.get("Bin", "").strip()
            job_filing = row.get("Job Filing Number", "").strip()
            borough = row.get("Borough", "").strip()
            street = row.get("Street Name", "").strip()

            if not bin_num or not job_filing:
                writer.writerow({**empty_row(), "Bin": bin_num, "result_status": "MISSING DATA"})
                processed = idx + 1
                continue

            t0 = time.time()
            print(f"\n[{idx + 1}/{end_at}] BIN {bin_num} | {job_filing}")
            log.info(f"Processing BIN={bin_num} job={job_filing}")

            # ── API calls ──
            job, err = api_search_bin(page, bin_num, street)
            if err == "AKAMAI_BLOCKED":
                new = rotation_recovery(proxy_config, fail_count, pw, context, prev_ip=ip)
                if new[0]:
                    pw, context, page = new
                    ip = detect_ip(page)
                    job, err = api_search_bin(page, bin_num, street)
                else:
                    writer.writerow({**empty_row(), "Bin": bin_num, "result_status": "BLOCKED_UNRECOVERABLE"})
                    print(f"  [FATAL] No se pudo recuperar del bloqueo. Abortando.")
                    log.error("AKAMAI_BLOCKED unrecoverable, aborting")
                    processed = idx + 1
                    break

            if err or job is None:
                writer.writerow({**empty_row(), "Bin": bin_num, "result_status": err or "JOB_NOT_FOUND"})
                processed = idx + 1
                continue

            guid = job.get("BuildID", "")
            base = row_from_job(job)
            base["guid"] = guid

            fi, cstatus, isplan = api_get_pw1(page, guid)
            base["filing_status"] = cstatus or ""

            zd1wd = api_get_zd1wd(page, guid)
            zone = "HAS ZONING DOCUMENTS" if zd1wd else "NO ZONING DOCUMENTS"

            portal = api_get_portal_docs(page, guid, fi, cstatus, isplan)

            seen = {d.get("DocumentURL", "") for d in portal if d.get("DocumentURL")}
            for z in zd1wd:
                u = z.get("DocumentURL", "")
                if u and u not in seen:
                    portal.append(z)
                    seen.add(u)

            if not portal:
                writer.writerow({**base, "zoning_status": zone, "result_status": "NO DOCUMENTS"})
                processed = idx + 1
                continue

            zcount = 0
            for doc in portal:
                doc_url = doc.get("DocumentURL", "")
                doc_name = doc.get("Name", "")
                matched = any(k in doc_name.lower() for k in KEYS_LOWER)

                if not matched:
                    writer.writerow({
                        **base, "doc_description": doc_name, "doc_name": doc_name,
                        "doc_url_original": doc_url, "result_status": "FILTERED",
                        "zoning_status": zone,
                        "doc_create_on": doc.get("CreateOn", "") or "",
                        "doc_category": doc.get("DocumentCategory", "") or "",
                        "doc_type_name": doc.get("DocumentTypeName", "") or "",
                        "doc_status_label": doc.get("RequiredItemStatusLabel", "") or "",
                    })
                    continue

                total_zd += 1
                dload = ""
                if doc_url:
                    dload = api_get_download_url(page, doc_url, borough)
                    if dload == "AKAMAI_BLOCKED":
                        new = rotation_recovery(proxy_config, fail_count, pw, context, prev_ip=ip)
                        if new[0]:
                            pw, context, page = new
                            ip = detect_ip(page)
                            dload = api_get_download_url(page, doc_url, borough)
                        else:
                            dload = ""

                writer.writerow({
                    **base, "doc_description": doc_name, "doc_name": doc_name,
                    "doc_url_original": doc_url, "download_url": dload or "",
                    "result_status": "OK", "zoning_status": zone,
                    "doc_create_on": doc.get("CreateOn", "") or "",
                    "doc_category": doc.get("DocumentCategory", "") or "",
                    "doc_type_name": doc.get("DocumentTypeName", "") or "",
                    "doc_status_label": doc.get("RequiredItemStatusLabel", "") or "",
                })
                zcount += 1

            elapsed = time.time() - t0
            print(f"  {zcount} docs ZD | {len(portal)} total | {elapsed:.2f}s")
            log.info(f"BIN={bin_num} done: {zcount} ZD docs in {elapsed:.1f}s")
            processed = idx + 1
            f_out.flush()

            if processed % 50 == 0:
                with open(CHECKPOINT_FILE, "w") as cp:
                    json.dump({"processed": processed, "total": total}, cp)

    # ── Done ──
    print(f"\n{'=' * 60}")
    print(f"  OK: {total_zd} docs ZD en {processed} BINs")
    print(f"  CSV: {OUTPUT_CSV}")
    print(f"  Log: {LOG_FILE}")
    print("=" * 60)
    log.info(f"DONE: {total_zd} ZD docs | {processed} BINs | output={OUTPUT_CSV}")
    close_browser(pw, context)
    print("Hecho.")


if __name__ == "__main__":
    main()
