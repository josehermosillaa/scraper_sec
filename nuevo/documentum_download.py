import argparse
import json
import os
import sys
import tempfile
import time

from curl_cffi import requests as curl_requests
from patchright.sync_api import sync_playwright

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
SERVICE_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperServicePP/WrapperService.svc"
IMPERSONATE = "chrome146"
USER_DATA_DIR = os.path.join(tempfile.gettempdir(), "patchright_dobnow_down")

HEADERS_CHROME = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://a810-dobnow.nyc.gov",
    "Referer": "https://a810-dobnow.nyc.gov/Publish/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Google Chrome";v="146", "Chromium";v="146", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}

BOROUGH_MAP = {
    "MANHATTAN": "MANHATTAN",
    "BRONX": "BRONX",
    "BROOKLYN": "BROOKLYN",
    "QUEENS": "QUEENS",
    "STATEN ISLAND": "STATEN ISLAND",
    "Manhattan": "MANHATTAN",
    "Bronx": "BRONX",
    "Brooklyn": "BROOKLYN",
    "Queens": "QUEENS",
    "Staten Island": "STATEN ISLAND",
}

_PLATFORM_SPOOF = "Win32" if sys.platform == "win32" else "Linux x86_64"
_WEBGL_VENDOR = "Google Inc. (NVIDIA)" if sys.platform == "win32" else "Intel Inc."
_WEBGL_RENDERER = (
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)"
    if sys.platform == "win32"
    else "Intel Iris OpenGL Engine"
)

ANTI_FINGERPRINT_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch(e) {}
try { delete navigator.__proto__.webdriver; } catch(e) {}
window.chrome = { runtime: {} };

try { Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'deviceMemory', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'platform', {get: () => '__PLATFORM__'}); } catch(e) {}

const TzDate = Date;
const origToString = TzDate.prototype.toString;
TzDate.prototype.toString = function() {
    return origToString.call(this).replace(
        /GMT[+-]\\d{4} \\(([^)]+)\\)/,
        'GMT-0400 (Eastern Daylight Time)'
    );
};

try { Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']}); } catch(e) {}
try { Object.defineProperty(navigator, 'language', {get: () => 'en-US'}); } catch(e) {}

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

(function() {
    const handler = {
        apply(target, self, args) {
            if (args[0] === 37445) return '__WEBGL_VENDOR__';
            if (args[0] === 37446) return '__WEBGL_RENDERER__';
            return target.apply(self, args);
        }
    };
    try { WebGLRenderingContext.prototype.getParameter = new Proxy(WebGLRenderingContext.prototype.getParameter, handler); } catch(e) {}
    if (typeof WebGL2RenderingContext !== 'undefined') {
        try { WebGL2RenderingContext.prototype.getParameter = new Proxy(WebGL2RenderingContext.prototype.getParameter, handler); } catch(e) {}
    }
})();

(function() {
    if (typeof AudioBuffer === 'undefined') return;
    const _gcd = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(c) {
        const d = _gcd.call(this, c);
        for (let i=0; i<Math.min(5,d.length); i++) d[i] += Math.random()*1e-12 - 5e-13;
        return d;
    };
})();

try { Object.defineProperty(screen, 'colorDepth', {get: () => 24}); } catch(e) {}
try { Object.defineProperty(screen, 'pixelDepth', {get: () => 24}); } catch(e) {}

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
"""

ANTI_FINGERPRINT_JS = ANTI_FINGERPRINT_JS.replace("__PLATFORM__", _PLATFORM_SPOOF)
ANTI_FINGERPRINT_JS = ANTI_FINGERPRINT_JS.replace("__WEBGL_VENDOR__", _WEBGL_VENDOR)
ANTI_FINGERPRINT_JS = ANTI_FINGERPRINT_JS.replace("__WEBGL_RENDERER__", _WEBGL_RENDERER)


def launch_browser():
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,
        no_viewport=True,
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.add_init_script(ANTI_FINGERPRINT_JS)
    page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    return pw, context, page


def close_browser(pw, context):
    try:
        context.close()
    except Exception:
        pass
    time.sleep(2)
    try:
        pw.stop()
    except Exception:
        pass


def wait_angular(page, timeout_s=120):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            ok = page.evaluate("""
                typeof angular !== 'undefined' &&
                angular.element(document.body).injector() !== undefined
            """, isolated_context=False)
            if ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def extract_auth(page, context):
    headers = None
    last_err = ""
    for attempt in range(60):
        try:
            headers = page.evaluate("""
                var i = angular.element(document.body).injector();
                var ai = i.get("AuthTokenInterceptor");
                var r = {method:"POST", url:"/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", headers:{}};
                r = ai.request(r);
                r.headers
            """, isolated_context=False)
            if headers:
                break
        except Exception as e:
            last_err = str(e)[:120]
        time.sleep(1)
    if not headers:
        print(f"[!] AuthTokenInterceptor no disponible tras 60s. Last error: {last_err}")
        return {}, []
    cookies = context.cookies()
    return headers, cookies


def build_http_session(interceptor_headers, cookies):
    s = curl_requests.Session(impersonate=IMPERSONATE)
    s.headers.update(HEADERS_CHROME)
    s.headers.update(interceptor_headers)
    for c in cookies:
        s.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", "").lstrip(".") or "",
            path=c.get("path") or "/",
        )
    return s


def http_post(session, url, body, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.post(url, json=body, timeout=30)
            if resp.status_code == 403 and "Access Denied" in resp.text:
                return None, "AKAMAI_BLOCKED"
            if "Access Denied" in resp.text and "edgesuite" in resp.text:
                return None, "AKAMAI_BLOCKED"
            if resp.status_code != 200:
                return resp.status_code, f"HTTP {resp.status_code}: {resp.text[:200]}"
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None, str(last_err)


def get_download_url(session, doc_url, borough):
    bk = BOROUGH_MAP.get(borough, borough.upper())
    dp = f"\\\\PortalDownloadedDocuments\\{bk}\\TEST\\"
    st, data = http_post(
        session,
        f"{SERVICE_BASE}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": dp},
    )
    if st is None or isinstance(data, str):
        print(f"[!] downloadFromDocumentum FAILED: st={st} err={str(data)[:200]}")
        return None
    return data.get("downloadPath", "")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Obtiene URL de descarga de un PDF desde Documentum via DOB Now"
    )
    parser.add_argument("url", help="URL DCTM REST del objeto (ej: http://bscan-broker.../objects/0900303985c75fc6)")
    parser.add_argument("--borough", default="MANHATTAN",
                        help="Borough para el downloadPath (default: MANHATTAN)")
    parser.add_argument("--timeout", type=int, default=90,
                        help="Timeout para esperar Angular en DOB Now (default: 90s)")
    return parser.parse_args()


def main():
    args = parse_args()
    url = args.url.strip()
    borough = args.borough.strip()

    if not url:
        print("[!] Debes proporcionar una URL DCTM REST.")
        sys.exit(1)

    print("-" * 50)
    print("Lanzando Chrome...")
    pw, context, page = launch_browser()

    print(f"Navegando a {DOBNOW_URL}")
    print(f"Esperando Angular (timeout={args.timeout}s)...")

    if not wait_angular(page, timeout_s=args.timeout):
        print("[!] Angular no detectado en DOB Now.")
        print("    Asegurate de que la sesion en el perfil Chrome este activa.")
        close_browser(pw, context)
        sys.exit(2)

    print("Extrayendo auth...")
    headers, cookies = extract_auth(page, context)
    if not headers:
        print("[!] No se pudo extraer auth.")
        close_browser(pw, context)
        sys.exit(3)

    print(f"Auth OK: {len(cookies)} cookies")
    http_s = build_http_session(headers, cookies)

    print(f"\nLlamando downloadFromDocumentum...")
    print(f"  URL:       {url[:80]}...")
    print(f"  Borough:   {borough}")
    download_url = get_download_url(http_s, url, borough)

    close_browser(pw, context)

    if download_url:
        print(f"\nURL de descarga:")
        print(download_url)
    else:
        print("\n[!] No se obtuvo URL de descarga.")
        sys.exit(4)


if __name__ == "__main__":
    main()
