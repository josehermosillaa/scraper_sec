import argparse
import csv
import json
import logging
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from patchright.sync_api import sync_playwright


DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
PUBLIC_PATH = "/Publish/WrapperPP/PublicPortal.svc"
SERVICE_PATH = "/Publish/WrapperServicePP/WrapperService.svc"

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(HERE, "input.csv")
OUTPUT_CSV = os.path.join(HERE, "resultado_conservador.csv")
CACHE_FILE = os.path.join(HERE, "cache_conservador.json")
CHECKPOINT_FILE = os.path.join(HERE, "checkpoint_conservador.json")
USER_DATA_DIR = os.path.join(tempfile.gettempdir(), "dobnow_conservative_profile")
DEFAULT_CDP_PROFILE = os.path.join(tempfile.gettempdir(), "chrome_cdp_profile")
LOG_FILE = os.path.join(HERE, "conservative_scraper.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("conservative")

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


def launch_browser(headless=False, profile_dir=USER_DATA_DIR):
    os.makedirs(profile_dir, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        channel="chrome",
        headless=headless,
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
    try:
        pw.stop()
    except Exception:
        pass


def detach_browser(pw):
    try:
        pw.stop()
    except Exception:
        pass


def try_recover_session(page, context, max_attempts=3):
    for attempt in range(max_attempts):
        wait = 5 + attempt * 5
        print(f"  [recover] Recargando pagina (intento {attempt + 1}/{max_attempts}, espera {wait}s)...")
        log.warning(f"Session recovery attempt {attempt + 1}/{max_attempts} (wait={wait}s)")
        try:
            page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning(f"Recovery reload failed: {e}")
            time.sleep(wait)
            continue
        time.sleep(wait)
        abck_state, abck_msg = abck_status(context)
        if abck_state != "blocked":
            print(f"  [recover] Sesion recuperada: {abck_msg}")
            log.info(f"Session recovered after {attempt + 1} attempts: {abck_msg}")
            if not wait_angular(page, 30):
                log.warning("Angular not ready after recovery reload")
            return True
        log.warning(f"Recovery attempt {attempt + 1} failed: {abck_msg}")
    return False


def _find_chrome_path():
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return "chrome.exe"
    candidates = ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path
    return "google-chrome"


def _kill_chrome():
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "chrome"], capture_output=True)


def _launch_chrome_cdp(port, profile=None):
    chrome_path = _find_chrome_path()
    if profile is None:
        profile = os.path.join(tempfile.gettempdir(), f"cdp_recovery_{int(time.time())}")
    print(f"  [recover] Chrome: {chrome_path}")
    log.info(f"Launching Chrome CDP: {chrome_path} port={port} profile={profile}")
    cmd = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_cdp_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def restart_browser_cdp(port, pw, profile=None):
    print("  [recover] Fase 2: Reiniciando Chrome...")
    log.warning("Phase 2: restarting Chrome via CDP")
    detach_browser(pw)
    time.sleep(1)
    _kill_chrome()
    time.sleep(3)
    _launch_chrome_cdp(port, profile)
    if not _wait_for_cdp_port(port, timeout=15):
        print("  [recover] No se pudo reconectar al puerto CDP.")
        log.error("Failed to reconnect CDP port after restart")
        return None, None, None
    print("  [recover] Puerto CDP listo. Conectando...")
    new_pw = sync_playwright().start()
    try:
        new_browser = new_pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    except Exception as e:
        log.error(f"CDP connect failed after restart: {e}")
        detach_browser(new_pw)
        return None, None, None
    new_ctx = new_browser.contexts[0]
    new_page = new_ctx.pages[0] if new_ctx.pages else new_ctx.new_page()

    try:
        new_page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.warning(f"Navigation to DOB NOW failed: {e}")
    time.sleep(5)

    if not wait_angular(new_page, 10):
        print("  [recover] DOB NOW pide iniciar sesion o continuar sin sesion.")
        print("            Haz clic en la opcion deseada en la ventana de Chrome.")
        print("            Esperando hasta 60s...")
        log.info("Waiting for user to handle DOB NOW guest/login page (60s)")
        if not wait_angular(new_page, 60):
            print("  [recover] Angular no detectado tras 60s.")
            log.error("Angular not ready after restart + 60s wait")
            detach_browser(new_pw)
            return None, None, None

    print("  [recover] Warm-up 30s para que Akamai evalue la nueva sesion...")
    warm_up(new_page, 30)

    for attempt in range(3):
        abck_state, abck_msg = abck_status(new_ctx)
        if abck_state != "blocked":
            print(f"  [recover] Fase 2 OK: {abck_msg}")
            log.info(f"Phase 2 success: {abck_msg}")
            return new_pw, new_ctx, new_page
        print(f"  [recover] _abck bloqueado en verificacion {attempt + 1}/3. Esperando 20s...")
        log.warning(f"Phase 2 _abck check {attempt + 1}/3 still blocked, waiting 20s")
        time.sleep(20)

    print("  [recover] Fase 2 fallida tras warm-up + 3 verificaciones")
    log.error("Phase 2 failed: _abck still blocked after warm-up + retries")
    detach_browser(new_pw)
    return None, None, None


def try_full_recovery(page, context, pw, cdp_port, profile=None):
    print("  [recover] Fase 1: Recargas de pagina...")
    log.warning("Full recovery: Phase 1 (reloads)")
    if try_recover_session(page, context):
        return pw, context, page
    if not cdp_port:
        log.warning("No CDP port, cannot do Phase 2")
        return None, None, None
    return restart_browser_cdp(cdp_port, pw, profile)


def connect_to_existing_browser(port):
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    contexts = browser.contexts
    if not contexts:
        print("[!] No hay contextos de navegador en el puerto CDP.")
        detach_browser(pw)
        sys.exit(1)
    context = contexts[0]
    for p in context.pages:
        url = p.url or ""
        if "dobnow" in url.lower():
            return pw, context, p
    print("[!] No se encontro ninguna pestana con DOB NOW abierta.")
    print("    Abre https://a810-dobnow.nyc.gov/Publish/ en Chrome y vuelve a ejecutar.")
    detach_browser(pw)
    sys.exit(1)


def page_block_reason(page):
    try:
        title = page.title() or ""
        if "Access Denied" in title:
            return f"Access Denied en titulo: {title}"
        body = page.evaluate("document.body && document.body.innerText || ''", isolated_context=False) or ""
        if "Access Denied" in body and "edgesuite" in body:
            return "Access Denied en cuerpo de pagina"
        return ""
    except Exception as e:
        return f"No se pudo revisar la pagina: {e}"


def page_is_blocked(page):
    return bool(page_block_reason(page))


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
        segments = value.count("~")
        if score == "-1":
            return "blocked", f"_abck score={score} {value[:120]}..."
        if score == "0":
            return "ok", f"_abck score={score} ({len(value)} chars, {segments} segmentos)"
        if segments > 5:
            return "warning", f"_abck score={score}, {segments} segmentos; se continua con precaucion"
        return "ok", f"_abck score={score} ({len(value)} chars, {segments} segmentos)"
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


def warm_up(page, duration_s=20):
    print(f"[*] Warm-up {duration_s}s para que Akamai evalue la sesion...")
    t0 = time.time()
    while time.time() - t0 < duration_s:
        try:
            page.evaluate(f"window.scrollBy(0, {random.randint(50, 350)})", isolated_context=False)
        except Exception:
            pass
        time.sleep(random.uniform(1.5, 3.5))
    print("[*] Warm-up completado.")


def print_startup_diagnostics(page, context):
    try:
        print(f"[*] URL inicial: {page.url}")
        print(f"[*] Titulo inicial: {page.title() or '(sin titulo)'}")
    except Exception as e:
        print(f"[*] No se pudo leer URL/titulo inicial: {e}")

    ip = detect_ip(page)
    print(f"[*] IP publica: {ip}")

    reason = page_block_reason(page)
    if reason:
        print(f"[!] Diagnostico pagina: {reason}")
    else:
        print("[*] Diagnostico pagina: sin Access Denied visible")

    warm_up(page, 20)

    status, message = abck_status(context)
    prefix = "[!]" if status == "blocked" else "[~]" if status == "warning" else "[*]"
    print(f"{prefix} Diagnostico _abck (tras warm-up): {message}")
    return reason, status


def wait_angular(page, timeout_s=120):
    started = time.time()
    while time.time() - started < timeout_s:
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


def polite_pause(min_s, max_s):
    time.sleep(random.uniform(min_s, max_s))


def small_user_activity(page):
    try:
        page.evaluate(f"window.scrollBy(0, {random.randint(80, 300)})", isolated_context=False)
    except Exception:
        pass


def session_healthy(page, context):
    if page_block_reason(page):
        return False
    abck_state, _ = abck_status(context)
    if abck_state == "blocked":
        return False
    return True


def browser_request(page, context, method, url_path, body=None):
    if not session_healthy(page, context):
        return None, "SESSION_UNHEALTHY"

    result = page.evaluate(
        """
        async ({method, url, body}) => {
            try {
                const injector = angular.element(document.body).injector();
                const interceptor = injector.get("AuthTokenInterceptor");
                let req = {method: method, url: url, headers: {}};
                req = interceptor.request(req);
                const options = {
                    method: method,
                    headers: {"X-Requested-With": "XMLHttpRequest", ...req.headers}
                };
                if (method === "POST") {
                    options.headers["Content-Type"] = "application/json";
                    options.body = JSON.stringify(body || {});
                }
                const resp = await fetch("https://a810-dobnow.nyc.gov" + url, options);
                const text = await resp.text();
                return {status: resp.status, body: text};
            } catch (e) {
                return {status: 0, body: e.message};
            }
        }
        """,
        {"method": method, "url": url_path, "body": body},
        isolated_context=False,
    )

    status = result.get("status", 0)
    text = result.get("body", "")
    if status == 0:
        return None, f"NETWORK_ERROR: {text}"
    if status == 403 and "Access Denied" in text:
        return None, "AKAMAI_BLOCKED"
    if "Access Denied" in text and "edgesuite" in text:
        return None, "AKAMAI_BLOCKED"
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


def cached_request(cache, page, context, method, url_path, body, pause_min, pause_max):
    key = json.dumps([method, url_path, body or {}], sort_keys=True)
    cached = cache.get(key)
    if cached is not None:
        return cached["status"], cached["data"]

    polite_pause(pause_min, pause_max)
    small_user_activity(page)
    status, data = browser_request(page, context, method, url_path, body)
    if data in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
        return None, data
    cache.set(key, {"status": status, "data": data})
    cache.save()
    return status, data


def empty_row():
    return {k: "" for k in COLS}


def row_from_job(job):
    row = empty_row()
    row["Bin"] = job.get("Bin", "")
    row["Borough"] = job.get("Borough", "")
    row["Street Name"] = job.get("StreetName", "")
    row["House No"] = job.get("HouseNo", "")
    row["Block"] = job.get("Block", "")
    row["LOT"] = job.get("LOT", "")
    row["Job Description"] = job.get("JobDescription", "")
    row["Job Filing Number"] = job.get("JobNumber_FilingNumber", "")
    row["Filing Date"] = job.get("FilingDate", "")
    row["Filing Status"] = job.get("FilingStatusDescription", "")
    row["Filing Review Type"] = job.get("FilingReviewType", "")
    return row


def search_bin(cache, page, context, bin_num, street, job_filing, pause_min, pause_max):
    status, data = cached_request(
        cache,
        page,
        context,
        "POST",
        f"{PUBLIC_PATH}/getPublicPortalBuildDisplay",
        {"BIN": bin_num, "SearchBy": "2", "StreetName": street},
        pause_min,
        pause_max,
    )
    if data == "AKAMAI_BLOCKED":
        return None, "AKAMAI_BLOCKED"
    if data == "SESSION_UNHEALTHY":
        return None, "SESSION_UNHEALTHY"
    if status is None or status != 200 or not isinstance(data, dict) or not data.get("IsSuccess"):
        return None, None
    jobs = data.get("ListBuildDetails", [])
    if not jobs:
        return None, None
    if job_filing:
        for j in jobs:
            if (j.get("JobNumber_FilingNumber") or "").strip() == job_filing:
                return j, None
        log.warning(f"search_bin BIN={bin_num}: no match for {job_filing} among {len(jobs)} jobs, using first")
    return jobs[0], None


def get_pw1(cache, page, context, guid, pause_min, pause_max):
    status, data = cached_request(
        cache, page, context, "GET", f"{SERVICE_PATH}/GetJobFilingPW1/{guid}", None, pause_min, pause_max
    )
    if status != 200 or not isinstance(data, dict):
        return "", "", False
    return data.get("FilingIncludes", ""), data.get("CurrentFilingStatusValue", ""), data.get("IsPlanApproved", False)


def get_zd1wd(cache, page, context, guid, pause_min, pause_max):
    status, data = cached_request(
        cache,
        page,
        context,
        "POST",
        f"{SERVICE_PATH}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid},
        pause_min,
        pause_max,
    )
    if data == "AKAMAI_BLOCKED":
        return [], "AKAMAI_BLOCKED"
    if data == "SESSION_UNHEALTHY":
        return [], "SESSION_UNHEALTHY"
    if status is None or status != 200 or not isinstance(data, dict):
        return [], None
    return data.get("RequiredDocumentList") or [], None


def get_portal_docs(cache, page, context, guid, fi, cstatus, isplan, pause_min, pause_max):
    status, data = cached_request(
        cache,
        page,
        context,
        "POST",
        f"{PUBLIC_PATH}/GetPublicPortalPartialJobFiling",
        {
            "Applicant": None,
            "RelatedEntityLogicalName": "dobnyc_documentlist",
            "JobFilingGUID": guid,
            "FilingIncludes": fi or "",
            "CurrentFilingStatusValue": cstatus or "",
            "IsPlanApproved": isplan or False,
        },
        pause_min,
        pause_max,
    )
    if data == "AKAMAI_BLOCKED":
        return [], "AKAMAI_BLOCKED"
    if data == "SESSION_UNHEALTHY":
        return [], "SESSION_UNHEALTHY"
    if status is None or status != 200 or not isinstance(data, dict):
        return [], None
    return data.get("RequiredDocumentList") or [], None


def get_download_url(cache, page, context, doc_url, borough, pause_min, pause_max):
    borough_key = BOROUGH_MAP.get(borough, borough.upper())
    download_path = f"\\\\PortalDownloadedDocuments\\{borough_key}\\TEST\\"
    status, data = cached_request(
        cache,
        page,
        context,
        "POST",
        f"{SERVICE_PATH}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": download_path},
        pause_min,
        pause_max,
    )
    if status != 200 or not isinstance(data, dict):
        return ""
    return data.get("downloadPath", "")


def write_doc_rows(writer, base, portal, zd1wd, cache, page, context, borough, pause_min, pause_max):
    seen = {d.get("DocumentURL", "") for d in portal if d.get("DocumentURL")}
    for doc in zd1wd:
        url = doc.get("DocumentURL", "")
        if url and url not in seen:
            portal.append(doc)
            seen.add(url)

    zone = "HAS ZONING DOCUMENTS" if zd1wd else "NO ZONING DOCUMENTS"
    if not portal:
        writer.writerow({**base, "zoning_status": zone, "result_status": "NO DOCUMENTS"})
        return 0

    zd_count = 0
    for doc in portal:
        doc_url = doc.get("DocumentURL", "")
        doc_name = doc.get("Name", "")
        matched = any(k in doc_name.lower() for k in KEYS_LOWER)
        download_url = ""
        status = "FILTERED"

        if matched:
            zd_count += 1
            status = "OK"
            if doc_url:
                download_url = get_download_url(cache, page, context, doc_url, borough, pause_min, pause_max)

        writer.writerow(
            {
                **base,
                "doc_description": doc_name,
                "doc_name": doc_name,
                "doc_url_original": doc_url,
                "download_url": download_url,
                "result_status": status,
                "zoning_status": zone,
                "doc_create_on": doc.get("CreateOn", "") or "",
                "doc_category": doc.get("DocumentCategory", "") or "",
                "doc_type_name": doc.get("DocumentTypeName", "") or "",
                "doc_status_label": doc.get("RequiredItemStatusLabel", "") or "",
            }
        )
    return zd_count


def parse_args():
    parser = argparse.ArgumentParser(description="DOB NOW scraper conservador con cache y checkpoint")
    parser.add_argument("--input", default=INPUT_CSV)
    parser.add_argument("--output", default=OUTPUT_CSV)
    parser.add_argument("--max-rows", type=int, default=25)
    parser.add_argument("--pause-min", type=float, default=8.0)
    parser.add_argument("--pause-max", type=float, default=20.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Ignora checkpoint previo y reescribe el CSV de salida")
    parser.add_argument("--new-profile", action="store_true", help="Usa un perfil temporal nuevo de Chrome")
    parser.add_argument("--cdp-port", type=int, default=0, metavar="PORT",
                        help="Conecta a Chrome existente via CDP en vez de lanzar uno nuevo")
    parser.add_argument("--chrome-profile", default=None, metavar="DIR",
                        help="user-data-dir de Chrome usado con --cdp-port (default: %TEMP%/chrome_cdp_profile)")
    return parser.parse_args()


def fallback_row(bin_num, status, csv_row):
    r = empty_row()
    r["Bin"] = bin_num
    r["Block"] = (csv_row.get("Block") or "").strip()
    r["LOT"] = (csv_row.get("LOT") or "").strip()
    r["result_status"] = status
    return r


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
    start_index = int(checkpoint.get("next_index", 0))
    retry_count = int(checkpoint.get("retry_count", 0))

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    end_index = min(total, start_index + args.max_rows)
    append = start_index > 0 and os.path.exists(args.output) and not args.fresh

    cdp_mode = bool(args.cdp_port)
    cdp_profile = args.chrome_profile or DEFAULT_CDP_PROFILE

    print("=" * 60)
    mode_label = f"modo CDP (puerto {args.cdp_port})" if cdp_mode else "modo conservador"
    print(f"conservative_scraper.py - {mode_label}")
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Filas: {start_index + 1}..{end_index} de {total}")
    print(f"Pausa por request no cacheado: {args.pause_min}-{args.pause_max}s")
    print(f"BINs bloqueados se reintentan hasta 3 veces (retry actual: {retry_count}/3)")
    print("Si aparece bloqueo, el proceso se detiene sin recuperar ni rotar IP.")
    print("=" * 60)
    log.info(f"START | cdp={cdp_mode} max_rows={args.max_rows} pause={args.pause_min}-{args.pause_max}s start_index={start_index}")

    if cdp_mode:
        print(f"[*] Conectando a Chrome en puerto {args.cdp_port}...")
        pw, context, page = connect_to_existing_browser(args.cdp_port)
        print(f"[*] Pestana encontrada: {page.url[:80]}")
        print(f"[*] Titulo: {page.title() or '(sin titulo)'}")
        ip = detect_ip(page)
        print(f"[*] IP publica: {ip}")
        block_reason = page_block_reason(page)
        if block_reason:
            print(f"[!] Diagnostico pagina: {block_reason}")
        else:
            print("[*] Diagnostico pagina: sin Access Denied visible")
        abck_state, abck_msg = abck_status(context)
        prefix = "[!]" if abck_state == "blocked" else "[~]" if abck_state == "warning" else "[*]"
        print(f"{prefix} Diagnostico _abck: {abck_msg}")
        if block_reason:
            detach_browser(pw)
            sys.exit(2)
        if abck_state == "blocked":
            print("[!] La sesion ya esta marcada. Cambia de VPN/ciudad, cierra Chrome, abre uno nuevo y vuelve a intentar.")
            detach_browser(pw)
            sys.exit(3)
    else:
        profile_dir = USER_DATA_DIR
        if args.new_profile:
            profile_dir = os.path.join(tempfile.gettempdir(), f"dobnow_conservative_profile_{int(time.time())}")
        print(f"Perfil Chrome: {profile_dir}")
        pw, context, page = launch_browser(headless=args.headless, profile_dir=profile_dir)
    processed = start_index
    total_zd = 0
    stop_reason = "completed"

    try:
        if not cdp_mode:
            block_reason, abck_state = print_startup_diagnostics(page, context)
            if block_reason:
                raise StopForBlock(f"Sesion bloqueada al iniciar: {block_reason}")
            if abck_state == "blocked":
                _, abck_message = abck_status(context)
                raise StopForBlock(f"Sesion marcada al iniciar: {abck_message}")

        if not cdp_mode or not wait_angular(page, 30):
            print("[*] Esperando Angular. Si hace falta login, hazlo en la ventana de Chrome.")
            if not wait_angular(page, 120):
                print("[!] Angular no detectado. Presiona Enter para reintentar o Ctrl+C para salir.")
                input()
                if not wait_angular(page, 60):
                    raise RuntimeError("Angular no detectado")

        with open(args.output, "a" if append else "w", encoding="utf-8", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=COLS)
            if not append:
                writer.writeheader()

            for idx in range(start_index, end_index):
                row = rows[idx]
                bin_num = row.get("Bin", "").strip()
                job_filing = row.get("Job Filing Number", "").strip()
                borough = row.get("Borough", "").strip()
                street = row.get("Street Name", "").strip()

                print(f"\n[{idx + 1}/{end_index}] BIN {bin_num} | {job_filing}")
                log.info(f"BIN {bin_num} | {job_filing} START")
                t0 = time.time()
                if not bin_num or not job_filing:
                    writer.writerow(fallback_row(bin_num, "MISSING DATA", row))
                    processed = idx + 1
                    retry_count = 0
                    save_checkpoint(processed, retry_count=0)
                    log.info(f"BIN {bin_num} MISSING DATA")
                    continue

                job, err = search_bin(cache, page, context, bin_num, street, job_filing, args.pause_min, args.pause_max)
                if err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                    log.warning(f"{err} on search_bin BIN={bin_num}")
                    recovered = try_full_recovery(page, context, pw, args.cdp_port, cdp_profile)
                    if recovered[0]:
                        pw, context, page = recovered
                        log.info(f"Retrying search_bin after full recovery for BIN={bin_num}")
                        job, err = search_bin(cache, page, context, bin_num, street, job_filing, args.pause_min, args.pause_max)

                if err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                    retry_count += 1
                    if retry_count < 3:
                        status = "AKAMAI_BLOCKED"
                        save_checkpoint(processed, retry_count=retry_count)
                    else:
                        status = "BLOCKED_PERMANENT"
                        processed = idx + 1
                        retry_count = 0
                        save_checkpoint(processed, retry_count=0)
                    log.warning(f"BIN {bin_num}: {status} (retry {retry_count}/3)")
                    writer.writerow(fallback_row(bin_num, status, row))
                    f_out.flush()
                    if status == "AKAMAI_BLOCKED":
                        print(f"\n[!] BIN bloqueado. Reintentos restantes: {3 - retry_count}")
                        print("    Cambia de VPN/ciudad y vuelve a ejecutar el mismo comando.")
                        raise StopForBlock(f"{err} — reintenta tras cambiar VPN")
                    continue
                if not job:
                    log.warning(f"BIN {bin_num}: {err or 'JOB_NOT_FOUND'}")
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

                fi, cstatus, isplan = get_pw1(cache, page, context, guid, args.pause_min, args.pause_max)
                base["filing_status"] = cstatus or ""

                zd1wd, zd_err = get_zd1wd(cache, page, context, guid, args.pause_min, args.pause_max)
                portal, po_err = get_portal_docs(cache, page, context, guid, fi, cstatus, isplan, args.pause_min, args.pause_max)

                if zd_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY") or po_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                    reason = f"zd_err={zd_err}, po_err={po_err}"
                    log.warning(f"Block on zd1wd/portal_docs for guid={guid[:12]}: {reason}")
                    recovered = try_full_recovery(page, context, pw, args.cdp_port, cdp_profile)
                    if recovered[0]:
                        pw, context, page = recovered
                        log.info(f"Retrying zd1wd/portal_docs after recovery for guid={guid[:12]}")
                        if zd_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                            zd1wd, zd_err = get_zd1wd(cache, page, context, guid, args.pause_min, args.pause_max)
                        if po_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                            portal, po_err = get_portal_docs(cache, page, context, guid, fi, cstatus, isplan, args.pause_min, args.pause_max)

                if zd_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY") or po_err in ("AKAMAI_BLOCKED", "SESSION_UNHEALTHY"):
                    retry_count += 1
                    if retry_count < 3:
                        status = "AKAMAI_BLOCKED"
                        save_checkpoint(processed, retry_count=retry_count)
                    else:
                        status = "BLOCKED_PERMANENT"
                        processed = idx + 1
                        retry_count = 0
                        save_checkpoint(processed, retry_count=0)
                    log.warning(f"BIN {bin_num}: {status} on docs (retry {retry_count}/3)")
                    base["result_status"] = status
                    base["zoning_status"] = "BLOCKED"
                    writer.writerow(base)
                    f_out.flush()
                    if status == "AKAMAI_BLOCKED":
                        print(f"\n[!] BIN bloqueado. Reintentos restantes: {3 - retry_count}")
                        print("    Cambia de VPN/ciudad y vuelve a ejecutar el mismo comando.")
                        raise StopForBlock("Blocked on docs — reintenta tras cambiar VPN")
                    continue

                count = write_doc_rows(
                    writer, base, portal, zd1wd,
                    cache, page, context, borough, args.pause_min, args.pause_max
                )
                total_zd += count
                processed = idx + 1
                retry_count = 0
                save_checkpoint(processed, retry_count=0)
                f_out.flush()
                print(f"  ZD encontrados: {count} | cache hits={cache.hits} misses={cache.misses}")
                log.info(f"BIN {bin_num}: {count} docs ZD | hits={cache.hits} misses={cache.misses} | {time.time() - t0:.1f}s")

    except StopForBlock as e:
        stop_reason = f"blocked: {e}"
        log.error(stop_reason)
        print(f"\n[!] Detenido por seguridad: {e}")
        sys.exit(3)
    except KeyboardInterrupt:
        stop_reason = "interrupted"
        log.warning("Script interrupted by user")
        print("\n[!] Interrumpido por usuario")
        sys.exit(3)
    finally:
        cache.save()
        save_checkpoint(processed, stop_reason, retry_count=retry_count)
        if cdp_mode:
            detach_browser(pw)
            print("[*] Desconectado del Chrome CDP. El navegador sigue abierto.")
        else:
            close_browser(pw, context)

    print("\n" + "=" * 60)
    print(f"Procesadas en esta ejecucion hasta indice: {processed}")
    print(f"Documentos ZD escritos en esta ejecucion: {total_zd}")
    print(f"Cache: hits={cache.hits}, misses={cache.misses}, archivo={CACHE_FILE}")
    print(f"Checkpoint: {CHECKPOINT_FILE} ({stop_reason})")
    print(f"CSV: {args.output}")
    log.info(f"DONE | processed={processed} total_zd={total_zd} hits={cache.hits} misses={cache.misses} stop_reason={stop_reason} | log={LOG_FILE}")


if __name__ == "__main__":
    main()
