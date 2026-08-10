import argparse
import csv
import json
import os
import random
import sys
import time

from curl_cffi import requests as curl_requests
from patchright.sync_api import sync_playwright

try:
    from vpn import ProtonVPN
    VPN_AVAILABLE = True
except (ImportError, FileNotFoundError):
    ProtonVPN = None
    VPN_AVAILABLE = False

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"
SERVICE_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperServicePP/WrapperService.svc"
IMPERSONATE = "chrome146"

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(HERE, "input.csv")
OUTPUT_CSV = os.path.join(HERE, "resultado_hibrido.csv")
CHECKPOINT_FILE = os.path.join(HERE, "checkpoint_hybrid.json")
CACHE_FILE = os.path.join(HERE, "cache_hibrido.json")
USER_DATA_DIR = os.path.join("/tmp", "patchright_dobnow_profile")

KEYS = {"ZD1", "ZD2", "ZD1A", "ZRD"}
KEYS_LOWER = {k.lower() for k in KEYS}

BOROUGH_MAP = {
    "Manhattan": "MANHATTAN",
    "Bronx": "BRONX",
    "Brooklyn": "BROOKLYN",
    "Queens": "QUEENS",
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

ANTI_FINGERPRINT_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch(e) {}
try { delete navigator.__proto__.webdriver; } catch(e) {}
window.chrome = { runtime: {} };

try { Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'deviceMemory', {get: () => 8}); } catch(e) {}
try { Object.defineProperty(navigator, 'platform', {get: () => 'Linux x86_64'}); } catch(e) {}

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
            if (args[0] === 37445) return 'Intel Inc.';
            if (args[0] === 37446) return 'Intel Iris OpenGL Engine';
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


class StopForBlock(RuntimeError):
    pass


class ResponseCache:
    def __init__(self, path):
        self.path = path
        self.hits = 0
        self.misses = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def get(self, key):
        if key in self.data:
            self.hits += 1
            return self.data[key]
        self.misses += 1
        return None

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp_path, self.path)
        except PermissionError:
            try:
                os.remove(self.path)
                os.rename(tmp_path, self.path)
            except Exception:
                pass


def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return {"next_index": 0, "retry_count": 0}
    with open(CHECKPOINT_FILE, encoding="utf-8") as f:
        cp = json.load(f)
    cp.setdefault("retry_count", 0)
    return cp


def save_checkpoint(next_index, reason="running", retry_count=0):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "next_index": next_index,
                "retry_count": retry_count,
                "reason": reason,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            f,
            indent=2,
        )


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


def page_is_blocked(page):
    try:
        if "Access Denied" in (page.title() or ""):
            return True
        body = page.evaluate("document.body && document.body.innerText || ''", isolated_context=False) or ""
        return "Access Denied" in body and "edgesuite" in body
    except Exception:
        return False


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


def warm_up(page, duration_s=30, quiet=False):
    if not quiet:
        print(f"  [warm-up] {duration_s}s...")
    t0 = time.time()
    while time.time() - t0 < duration_s:
        try:
            page.evaluate(f"window.scrollBy(0, {random.randint(50, 350)})", isolated_context=False)
        except Exception:
            pass
        try:
            w = page.evaluate("window.innerWidth")
            h = page.evaluate("window.innerHeight")
            page.mouse.move(random.randint(100, w - 100), random.randint(100, h - 100))
        except Exception:
            pass
        time.sleep(random.uniform(1.5, 3.5))
    if not quiet:
        print("  [warm-up] listo.")


def human_f5_reload(page, wait_until="domcontentloaded", timeout=60000):
    try:
        page.evaluate("document.body.focus()")
    except Exception:
        pass
    try:
        page.keyboard.press("F5")
    except Exception:
        page.reload(wait_until=wait_until, timeout=timeout)
        return
    time.sleep(3)
    try:
        page.wait_for_load_state(wait_until, timeout=timeout)
    except Exception:
        pass


def parse_abck_score(value):
    parts = value.split("~", 2)
    if len(parts) >= 3:
        return parts[1]
    return "unknown"


def abck_status(context):
    for cookie in context.cookies():
        if cookie.get("name") != "_abck":
            continue
        value = cookie.get("value", "")
        if not value:
            return "ok", "_abck vacia"
        score = parse_abck_score(value)
        if score == "-1":
            return "blocked", f"_abck score=-1"
        if score == "0":
            return "ok", f"_abck score=0 ({len(value)} chars)"
        return "ok", f"_abck score={score} ({len(value)} chars)"
    return "ok", "_abck aun no existe"


def check_abck_health(context):
    status, _ = abck_status(context)
    return status != "blocked"


def detect_ip(page):
    for _ in range(3):
        try:
            result = page.evaluate(
                "async () => { const r = await fetch('https://httpbin.org/ip'); return (await r.json()).origin; }"
            )
            if result:
                return result
        except Exception:
            pass
        time.sleep(2)
    return "unknown"


def polite_pause(min_s, max_s):
    time.sleep(random.uniform(min_s, max_s))


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
        print(f"  [!] AuthTokenInterceptor no disponible tras 60s. Last error: {last_err}")
        return {}, []
    cookies = context.cookies()
    return headers, cookies


def reload_page_auth(page, context):
    human_f5_reload(page)
    time.sleep(4)
    if page_is_blocked(page):
        return None, None
    if not wait_angular(page, timeout_s=30):
        return None, None
    return extract_auth(page, context)


def recover_from_akamai(page, context, pw, http_session, vpn, bad_cities):
    for attempt in range(3):
        print(f"  [recover] F5 reload {attempt + 1}/3")
        h, c = reload_page_auth(page, context)
        if h:
            update_http_session(http_session, h, c)
            print("  [recover] Auth renovado OK.")
            return page, context
        time.sleep(3)

    if not vpn:
        print("  [recover] Sin VPN. Pausa 60s y ultimo intento...")
        time.sleep(60)
        h, c = reload_page_auth(page, context)
        if h:
            update_http_session(http_session, h, c)
            return page, context
        return None, None

    print("  [recover] Rotando VPN...")
    try:
        context.close()
    except Exception:
        pass
    time.sleep(2)

    vpn.rotate()
    bad_cities[0] += 1
    print(f"  [recover] Ciudad {bad_cities[0]}/3")

    if bad_cities[0] >= 3:
        print(f"  [recover] Pausa 600s...")
        time.sleep(600)
        bad_cities[0] = 0

    time.sleep(15)

    new_context = pw.chromium.launch_persistent_context(
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
    new_page = new_context.pages[0] if new_context.pages else new_context.new_page()
    new_page.add_init_script(ANTI_FINGERPRINT_JS)

    akamai_names = {"_abck", "bm_sz", "ak_bmsc", "bm_mi", "bm_sv"}
    for c in new_context.cookies():
        if c.get("name") in akamai_names:
            try:
                new_context.clear_cookies(name=c["name"])
            except Exception:
                pass

    new_page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)

    if page_is_blocked(new_page):
        print("  [recover] Nueva IP tambien bloqueada.")
        bad_cities[0] += 1
        return None, None

    warm_up(new_page, duration_s=20, quiet=True)
    if not wait_angular(new_page, timeout_s=60):
        print("  [recover] Angular no disponible.")
        return None, None

    h, c = extract_auth(new_page, new_context)
    update_http_session(http_session, h, c)
    bad_cities[0] = 0
    print("  [recover] Nueva sesion OK.")
    return new_page, new_context


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


def update_http_session(s, interceptor_headers, cookies):
    s.headers.clear()
    s.headers.update(HEADERS_CHROME)
    s.headers.update(interceptor_headers)
    s.cookies.clear()
    for c in cookies:
        s.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", "").lstrip(".") or "",
            path=c.get("path") or "/",
        )


def http_post(session, url, body, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.post(url, json=body, timeout=30)
            if resp.status_code == 403 and "Access Denied" in resp.text:
                return None, "AKAMAI_BLOCKED"
            if "Access Denied" in resp.text and "edgesuite" in resp.text:
                return None, "AKAMAI_BLOCKED"
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None, str(last_err)


def http_get(session, url, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 403 and "Access Denied" in resp.text:
                return None, "AKAMAI_BLOCKED"
            if "Access Denied" in resp.text and "edgesuite" in resp.text:
                return None, "AKAMAI_BLOCKED"
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None, str(last_err)


def api_search_bin(session, bin_num, street=""):
    st, data = http_post(session,
        f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
        {"BIN": bin_num, "SearchBy": "2", "StreetName": street})
    if st is None or isinstance(data, str):
        return None, data or "KO"
    if not data.get("IsSuccess") or st != 200:
        return None, "API_ERROR"
    jobs = data.get("ListBuildDetails", [])
    return (jobs[0] if jobs else None), None


def api_find_job(session, bin_num, job_filing, street=""):
    job, err = api_search_bin(session, bin_num, street)
    if err:
        return None, err
    if job is None:
        return None, "JOB_NOT_FOUND"
    return job, None


def api_get_pw1(session, guid):
    st, data = http_get(session, f"{SERVICE_BASE}/GetJobFilingPW1/{guid}")
    if st is None or isinstance(data, str):
        return "", "", False
    return (data.get("FilingIncludes", ""),
            data.get("CurrentFilingStatusValue", ""),
            data.get("IsPlanApproved", False))


def api_get_zd1wd(session, guid):
    st, data = http_post(session,
        f"{SERVICE_BASE}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid})
    if st is None or isinstance(data, str):
        if data == "AKAMAI_BLOCKED":
            return "AKAMAI_BLOCKED"
        return []
    return data.get("RequiredDocumentList") or []


def api_get_portal_docs(session, guid, fi, cstatus, isplan):
    st, data = http_post(session,
        f"{PUBLIC_BASE}/GetPublicPortalPartialJobFiling",
        {"Applicant": None, "RelatedEntityLogicalName": "dobnyc_documentlist",
         "JobFilingGUID": guid, "FilingIncludes": fi or "",
         "CurrentFilingStatusValue": cstatus or "",
         "IsPlanApproved": isplan or False})
    if st is None or isinstance(data, str):
        if data == "AKAMAI_BLOCKED":
            return "AKAMAI_BLOCKED"
        return []
    return data.get("RequiredDocumentList") or []


def api_get_download_url(session, doc_url, borough):
    bk = BOROUGH_MAP.get(borough, borough.upper())
    dp = f"\\\\PortalDownloadedDocuments\\{bk}\\TEST\\"
    st, data = http_post(session,
        f"{SERVICE_BASE}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": dp})
    if st is None or isinstance(data, str):
        if data == "AKAMAI_BLOCKED":
            return "AKAMAI_BLOCKED"
        return ""
    return data.get("downloadPath", "")


def cached_request(cache, http_session, method, url, body, pause_min, pause_max):
    key = json.dumps([method, url, body or {}], sort_keys=True)
    cached = cache.get(key)
    if cached is not None:
        return cached["status"], cached["data"]

    polite_pause(pause_min, pause_max)
    if method == "POST":
        status, data = http_post(http_session, url, body)
    else:
        status, data = http_get(http_session, url)

    if isinstance(data, str):
        return status, data

    cache.set(key, {"status": status, "data": data})
    cache.save()
    return status, data


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


def fallback_row(bin_num, status, csv_row):
    r = empty_row()
    r["Bin"] = bin_num
    r["Block"] = (csv_row.get("Block") or "").strip()
    r["LOT"] = (csv_row.get("LOT") or "").strip()
    r["result_status"] = status
    return r


def parse_args():
    parser = argparse.ArgumentParser(
        description="DOB NOW scraper hibrido: Patchright (auth) + curl_cffi (API calls)"
    )
    parser.add_argument("--input", default=INPUT_CSV, help="CSV de entrada (default: input.csv)")
    parser.add_argument("--output", default=OUTPUT_CSV, help="CSV de salida (default: resultado_hibrido.csv)")
    parser.add_argument("--max-rows", type=int, default=0, help="Max BINs a procesar (0 = todos desde start)")
    parser.add_argument("--start-index", type=int, default=None, help="Indice de inicio (default: desde checkpoint)")
    parser.add_argument("--fresh", action="store_true", help="Ignora checkpoint y cache, empieza desde 0")
    parser.add_argument("--pause-min", type=float, default=2.0, help="Pausa minima entre API calls (default: 2.0)")
    parser.add_argument("--pause-max", type=float, default=6.0, help="Pausa maxima entre API calls (default: 6.0)")
    parser.add_argument("--refresh-auth-every", type=int, default=15, help="Renovar auth cada N API calls (default: 15)")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.pause_min < 0 or args.pause_max < args.pause_min:
        print("[!] Pausas invalidas: usa --pause-min >= 0 y --pause-max >= --pause-min")
        sys.exit(1)
    if not os.path.exists(args.input):
        print(f"[!] No existe el CSV de entrada: {args.input}")
        sys.exit(1)

    cache = ResponseCache(CACHE_FILE)
    checkpoint = {"next_index": 0, "retry_count": 0} if args.fresh else load_checkpoint()
    start_index = args.start_index if args.start_index is not None else int(checkpoint.get("next_index", 0))
    retry_count = int(checkpoint.get("retry_count", 0))

    with open(args.input, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    if args.max_rows > 0:
        end_index = min(total, start_index + args.max_rows)
    else:
        end_index = total
    append = start_index > 0 and os.path.exists(args.output) and not args.fresh

    print("=" * 60)
    print("patchright_hybrid.py — Patchright + curl_cffi")
    print(f"impersonate={IMPERSONATE}")
    print(f"Input:    {args.input}")
    print(f"Output:   {args.output}")
    print(f"Filas:    {start_index + 1}..{end_index} de {total}")
    print(f"Pausa:    {args.pause_min}-{args.pause_max}s entre API calls")
    print(f"Auth ref: cada {args.refresh_auth_every} API calls")
    print(f"Retry:    {retry_count}/3 (cross-run)")
    print("=" * 60)

    vpn = None
    if VPN_AVAILABLE and ProtonVPN:
        vpn = ProtonVPN()
        print("[VPN] ProtonVPN detectado.")
        if "Connected" not in (vpn.status() or ""):
            print("[VPN] Conectando...")
            vpn.connect(country="US", city="New York")
            time.sleep(5)
    else:
        print("[VPN] Sin ProtonVPN (IP fija).")

    print("[*] Lanzando Patchright (Chrome real)...")
    pw, context, page = launch_browser()

    ip = detect_ip(page)
    print(f"[*] IP publica: {ip}")

    abck_state, abck_msg = abck_status(context)
    prefix = "[!]" if abck_state == "blocked" else "[*]"
    print(f"{prefix} _abck: {abck_msg}")

    if page_is_blocked(page):
        print("[!] IP bloqueada (Access Denied visible).")
        close_browser(pw, context)
        sys.exit(2)

    if abck_state == "blocked":
        print("[!] Sesion marcada (_abck=-1). Cambia VPN manualmente o reinicia.")
        close_browser(pw, context)
        sys.exit(3)

    warm_up(page, 20)
    print("[*] Esperando Angular (haz login si es necesario)...")
    if not wait_angular(page, 120):
        print("[!] Angular no detectado. Asegurate de haber hecho login.")
        print("    Presiona Enter para reintentar...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            close_browser(pw, context)
            sys.exit(1)
        if not wait_angular(page, 60):
            print("[!] Sin Angular. Abortando.")
            close_browser(pw, context)
            sys.exit(1)

    interceptor_h, cookies = extract_auth(page, context)
    print(f"[*] Auth extraido: {len(cookies)} cookies")
    http_s = build_http_session(interceptor_h, cookies)

    with open(args.output, "a" if append else "w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=COLS)
        if not append:
            writer.writeheader()

        processed = start_index
        total_zd = 0
        auth_counter = 0
        bad_cities = [0]
        stop_reason = "completed"

        try:
            for idx in range(start_index, end_index):
                row = rows[idx]
                bin_num = row.get("Bin", "").strip()
                job_filing = row.get("Job Filing Number", "").strip()
                borough = row.get("Borough", "").strip()
                street = row.get("Street Name", "").strip()

                if not bin_num or not job_filing:
                    writer.writerow(fallback_row(bin_num, "MISSING DATA", row))
                    processed = idx + 1
                    retry_count = 0
                    save_checkpoint(processed, retry_count=0)
                    f_out.flush()
                    continue

                if auth_counter >= args.refresh_auth_every:
                    print("  [refresh] Renovando auth...")
                    h, c = reload_page_auth(page, context)
                    if h:
                        update_http_session(http_s, h, c)
                        auth_counter = 0
                        abck_s, abck_m = abck_status(context)
                        if abck_s == "blocked":
                            print(f"  [refresh] _abck bloqueado ({abck_m}). Intentando recovery...")
                            recovered = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                            if recovered[0]:
                                page, context = recovered
                                auth_counter = 0
                            else:
                                raise StopForBlock("Auth refresh detecto sesion envenenada sin recuperacion")
                    else:
                        print("  [refresh] Fallo. Siguiendo con actual.")

                polite_pause(0.2, 0.5)
                auth_counter += 1
                t0 = time.time()
                print(f"\n[{idx + 1}/{end_index}] BIN {bin_num} | {job_filing}")

                job, err = cached_request(
                    cache, http_s, "POST",
                    f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
                    {"BIN": bin_num, "SearchBy": "2", "StreetName": street},
                    args.pause_min, args.pause_max,
                )
                if err == "AKAMAI_BLOCKED":
                    recovered = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                    if recovered[0]:
                        page, context = recovered
                        auth_counter = 0
                        status, data = http_post(http_s,
                            f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
                            {"BIN": bin_num, "SearchBy": "2", "StreetName": street})
                        if isinstance(data, str):
                            err = data
                        elif data and data.get("IsSuccess") and data.get("ListBuildDetails"):
                            job = data["ListBuildDetails"][0]
                            err = None
                        else:
                            err = "API_ERROR"
                    else:
                        retry_count += 1
                        if retry_count < 3:
                            save_checkpoint(processed, retry_count=retry_count)
                            writer.writerow(fallback_row(bin_num, "AKAMAI_BLOCKED", row))
                            f_out.flush()
                            raise StopForBlock("AKAMAI_BLOCKED — reintenta tras cambiar VPN")
                        else:
                            writer.writerow(fallback_row(bin_num, "BLOCKED_PERMANENT", row))
                            processed = idx + 1
                            retry_count = 0
                            save_checkpoint(processed, retry_count=0)
                            f_out.flush()
                            continue

                if isinstance(err, str) or job is None:
                    writer.writerow(fallback_row(bin_num, err or "JOB_NOT_FOUND", row))
                    processed = idx + 1
                    retry_count = 0
                    save_checkpoint(processed, retry_count=0)
                    f_out.flush()
                    continue

                guid = job.get("BuildID", "")
                base = row_from_job(job)
                base["guid"] = guid
                base["Block"] = (row.get("Block") or "").strip()
                base["LOT"] = (row.get("LOT") or "").strip()

                fi, cstatus, isplan = api_get_pw1(http_s, guid)
                base["filing_status"] = cstatus or ""

                zd1wd = api_get_zd1wd(http_s, guid)
                zd_err = zd1wd if zd1wd == "AKAMAI_BLOCKED" else None

                portal = api_get_portal_docs(http_s, guid, fi, cstatus, isplan)
                po_err = portal if portal == "AKAMAI_BLOCKED" else None

                if zd_err == "AKAMAI_BLOCKED" or po_err == "AKAMAI_BLOCKED":
                    recovered = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                    if recovered[0]:
                        page, context = recovered
                        auth_counter = 0
                        if zd_err == "AKAMAI_BLOCKED":
                            zd1wd = api_get_zd1wd(http_s, guid)
                            zd_err = zd1wd if zd1wd == "AKAMAI_BLOCKED" else None
                        if po_err == "AKAMAI_BLOCKED":
                            portal = api_get_portal_docs(http_s, guid, fi, cstatus, isplan)
                            po_err = portal if portal == "AKAMAI_BLOCKED" else None

                if zd_err == "AKAMAI_BLOCKED" or po_err == "AKAMAI_BLOCKED":
                    retry_count += 1
                    if retry_count < 3:
                        save_checkpoint(processed, retry_count=retry_count)
                        base["result_status"] = "AKAMAI_BLOCKED"
                        base["zoning_status"] = "BLOCKED"
                        writer.writerow(base)
                        f_out.flush()
                        raise StopForBlock("Blocked on docs — reintenta tras cambiar VPN")
                    else:
                        base["result_status"] = "BLOCKED_PERMANENT"
                        base["zoning_status"] = "BLOCKED"
                        writer.writerow(base)
                        processed = idx + 1
                        retry_count = 0
                        save_checkpoint(processed, retry_count=0)
                        f_out.flush()
                        continue

                zone = "HAS ZONING DOCUMENTS" if zd1wd else "NO ZONING DOCUMENTS"

                seen = {d.get("DocumentURL", "") for d in portal if d.get("DocumentURL")}
                for z in zd1wd:
                    u = z.get("DocumentURL", "")
                    if u and u not in seen:
                        portal.append(z)
                        seen.add(u)

                if not portal:
                    writer.writerow({**base, "zoning_status": zone, "result_status": "NO DOCUMENTS"})
                    processed = idx + 1
                    retry_count = 0
                    save_checkpoint(processed, retry_count=0)
                    f_out.flush()
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
                        dload = api_get_download_url(http_s, doc_url, borough)
                        if dload == "AKAMAI_BLOCKED":
                            recovered = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                            if recovered[0]:
                                page, context = recovered
                                auth_counter = 0
                                dload = api_get_download_url(http_s, doc_url, borough)
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
                print(f"  {zcount} docs ZD | {len(portal)} total | {elapsed:.2f}s | cache hits={cache.hits} misses={cache.misses}")
                processed = idx + 1
                retry_count = 0
                save_checkpoint(processed, retry_count=0)
                f_out.flush()

                if random.random() < 0.25:
                    long_pause = random.uniform(30, 90)
                    print(f"  [pause] Simulando lectura humana ({long_pause:.0f}s)...")
                    t_pause = time.time()
                    while time.time() - t_pause < long_pause:
                        try:
                            page.evaluate(f"window.scrollBy(0, {random.randint(50, 200)})", isolated_context=False)
                        except Exception:
                            pass
                        time.sleep(random.uniform(3, 8))

        except StopForBlock as e:
            stop_reason = f"blocked: {e}"
            print(f"\n[!] Detenido: {e}")
            cache.save()
            save_checkpoint(processed, stop_reason, retry_count=retry_count)
            close_browser(pw, context)
            sys.exit(3)
        except KeyboardInterrupt:
            stop_reason = "interrupted"
            print("\n[!] Interrumpido por usuario")
            cache.save()
            save_checkpoint(processed, stop_reason, retry_count=retry_count)
            close_browser(pw, context)
            sys.exit(3)

    cache.save()
    save_checkpoint(processed, stop_reason, retry_count=retry_count)
    print(f"\n{'=' * 60}")
    print(f"Procesadas:  {processed}")
    print(f"Docs ZD:     {total_zd}")
    print(f"Cache:       hits={cache.hits}, misses={cache.misses}")
    print(f"Checkpoint:  {CHECKPOINT_FILE}")
    print(f"CSV:         {args.output}")
    close_browser(pw, context)
    print("Hecho.")


if __name__ == "__main__":
    main()
