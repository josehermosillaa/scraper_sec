import csv
import json
import logging
import os
import random
import sys
import time

from patchright.sync_api import sync_playwright

try:
    from vpn import ProtonVPN

    VPN_AVAILABLE = True
except (ImportError, FileNotFoundError):
    ProtonVPN = None
    VPN_AVAILABLE = False

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
PUBLIC_BASE = "/Publish/WrapperPP/PublicPortal.svc"
SERVICE_BASE = "/Publish/WrapperServicePP/WrapperService.svc"

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(HERE, "input.csv")
OUTPUT_CSV = os.path.join(HERE, "resultado_browser_only.csv")
CHECKPOINT_FILE = os.path.join(HERE, "checkpoint_browser_only.json")
USER_DATA_DIR = os.path.join("/tmp", "browser_only_dobnow_profile")

KEYS = {"ZD1", "ZD2", "ZD1A", "ZRD"}
KEYS_LOWER = {k.lower() for k in KEYS}

LOG_FILE = os.path.join(HERE, "browser_only.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("browser_only")

BOROUGH_MAP = {
    "Manhattan": "MANHATTAN",
    "Bronx": "BRONX",
    "Brooklyn": "BROOKLYN",
    "Queens": "QUEENS",
    "Staten Island": "STATEN ISLAND",
}

COLS = [
    "Job Filing Number",
    "Filing Status",
    "Filing Date",
    "House No",
    "Street Name",
    "Borough",
    "Block",
    "LOT",
    "Bin",
    "Job Description",
    "Filing Review Type",
    "guid",
    "filing_status",
    "doc_description",
    "doc_name",
    "doc_url_original",
    "download_url",
    "result_status",
    "error_body",
    "zoning_status",
    "doc_create_on",
    "doc_category",
    "doc_type_name",
    "doc_status_label",
]

MAX_ROWS = 10
CHECKPOINT_EVERY = 50
MAX_VPN_BAD_CITIES = 3
VPN_COOLDOWN = 600
AKAMAI_RELOAD_TRIES = 3
WARM_UP_S = 20

# ═══════════════════════════════════════════════════════
# Anti-fingerprinting scripts
# ═══════════════════════════════════════════════════════

ANTI_FINGERPRINT_JS = """
// --- WebDriver concealment ---
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
delete navigator.__proto__.webdriver;
window.chrome = { runtime: {} };

// --- Navigator plugins spoofing ---
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [1, 2, 3, 4, 5];
        arr.item = (i) => arr[i];
        arr.namedItem = () => null;
        arr.refresh = () => {};
        return arr;
    }
});

// --- Canvas fingerprint spoofing ---
(function() {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = ctx.getImageData(0, 0, 1, 1);
                imageData.data[0] = imageData.data[0] ^ 1;
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}
        }
        return origToDataURL.apply(this, arguments);
    };

    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = ctx.getImageData(0, 0, 1, 1);
                imageData.data[0] = imageData.data[0] ^ 1;
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}
        }
        return origToBlob.apply(this, arguments);
    };

    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
        const data = origGetImageData.call(this, x, y, w, h);
        data.data[0] = data.data[0] ^ 1;
        return data;
    };
})();

// --- WebGL vendor spoofing ---
(function() {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    const handler = {
        apply: function(target, thisArg, args) {
            const param = args[0];
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return target.apply(thisArg, args);
        }
    };
    WebGLRenderingContext.prototype.getParameter = new Proxy(getParameter, handler);
    if (typeof WebGL2RenderingContext !== 'undefined') {
        WebGL2RenderingContext.prototype.getParameter = new Proxy(
            WebGL2RenderingContext.prototype.getParameter, handler
        );
    }
})();

// --- AudioContext fingerprint spoofing ---
(function() {
    if (typeof AudioBuffer === 'undefined') return;
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(channel) {
        const data = origGetChannelData.call(this, channel);
        for (let i = 0; i < Math.min(5, data.length); i++) {
            data[i] = data[i] + (Math.random() * 1e-12 - 5e-13);
        }
        return data;
    };

    if (typeof OfflineAudioContext !== 'undefined') {
        const origStartRendering = OfflineAudioContext.prototype.startRendering;
        OfflineAudioContext.prototype.startRendering = function() {
            return origStartRendering.call(this).then(function(buffer) {
                const ch = buffer.getChannelData(0);
                if (ch.length > 0) ch[0] = ch[0] + (Math.random() * 1e-12 - 5e-13);
                return buffer;
            });
        };
    }
})();

// --- Screen/colorDepth consistency ---
Object.defineProperty(screen, 'colorDepth', {get: () => 24});
Object.defineProperty(screen, 'pixelDepth', {get: () => 24});

// --- Permissions API ---
if (navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query;
    navigator.permissions.query = function(args) {
        if (args.name === 'notifications') {
            return Promise.resolve({state: 'prompt', onchange: null});
        }
        return origQuery.apply(this, arguments);
    };
}
"""

# ═══════════════════════════════════════════════════════
# Browser lifecycle
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Akamai detection
# ═══════════════════════════════════════════════════════


def page_is_blocked(page):
    try:
        if "Access Denied" in (page.title() or ""):
            return True
        body = (
            page.evaluate(
                "document.body && document.body.innerText || ''",
                isolated_context=False,
            )
            or ""
        )
        return "Access Denied" in body and "edgesuite" in body
    except Exception:
        return False


def wait_angular(page, timeout_s=120):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            ok = page.evaluate(
                """
                typeof angular !== 'undefined' &&
                angular.element(document.body).injector() !== undefined
            """,
                isolated_context=False,
            )
            if ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def warm_up(page, duration_s=WARM_UP_S, quiet=False):
    if not quiet:
        print(f"  [warm-up] {duration_s}s...")
    t0 = time.time()
    while time.time() - t0 < duration_s:
        try:
            page.evaluate(
                f"window.scrollBy(0, {random.randint(50, 350)})",
                isolated_context=False,
            )
        except Exception:
            pass
        time.sleep(random.uniform(1.5, 3.5))
    if not quiet:
        print("  [warm-up] listo.")


# ═══════════════════════════════════════════════════════
# _abck cookie monitoring
# ═══════════════════════════════════════════════════════


def check_abck_health(context):
    """
    Akamai flags bot sessions internally via the _abck cookie.
    Patterns that indicate poisoning:
      - value ends with ~-1~-1  (session flagged)
      - value contains abnormal number of ~ segments
    Returns (healthy: bool, value: str)
    """
    cookies = context.cookies()
    for c in cookies:
        if c.get("name") == "_abck":
            val = c.get("value", "")
            if not val:
                return True, ""
            if "~-1" in val:
                print(f"  [_abck] POISONED: {val[:80]}...")
                log.warning(f"_abck POISONED: {val[:80]}...")
                return False, val
            segments = val.count("~")
            if segments > 5:
                print(f"  [_abck] SUSPICIOUS ({segments} segments): {val[:80]}...")
                log.warning(f"_abck SUSPICIOUS ({segments} segments): {val[:80]}...")
                return False, val
            return True, val
    return True, ""


def monitor_abck(context, label=""):
    healthy, val = check_abck_health(context)
    prefix = f"[_abck {label}]" if label else "[_abck]"
    if healthy and val:
        print(f"  {prefix} OK ({len(val)} chars)")
    elif healthy:
        print(f"  {prefix} Not yet set")
    else:
        print(f"  {prefix} WARNING: flagged session")
    return healthy


# ═══════════════════════════════════════════════════════
# In-browser API (all requests via page.evaluate + fetch)
# ═══════════════════════════════════════════════════════


def browser_post(page, url_path, body, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            result = page.evaluate(
                """
                async ({url, body}) => {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method: "POST", url: url, headers: {}};
                    req = interceptor.request(req);
                    try {
                        const resp = await fetch("https://a810-dobnow.nyc.gov" + url, {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json",
                                "X-Requested-With": "XMLHttpRequest",
                                ...req.headers
                            },
                            body: JSON.stringify(body)
                        });
                        const text = await resp.text();
                        return {status: resp.status, body: text};
                    } catch(e) {
                        return {status: 0, body: e.message};
                    }
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
                    var req = {method: "GET", url: url, headers: {}};
                    req = interceptor.request(req);
                    try {
                        const resp = await fetch("https://a810-dobnow.nyc.gov" + url, {
                            method: "GET",
                            headers: {
                                "X-Requested-With": "XMLHttpRequest",
                                ...req.headers
                            }
                        });
                        const text = await resp.text();
                        return {status: resp.status, body: text};
                    } catch(e) {
                        return {status: 0, body: e.message};
                    }
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
    r = random.random()
    if r < 0.6:
        time.sleep(random.uniform(2, 5))
    elif r < 0.9:
        time.sleep(random.uniform(5, 12))
    else:
        time.sleep(random.uniform(15, 25))


def human_scroll(page):
    for _ in range(random.randint(1, 2)):
        delta_y = random.randint(100, 500)
        try:
            page.evaluate(f"window.scrollBy(0, {delta_y})", isolated_context=False)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 1.0))


# ═══════════════════════════════════════════════════════
# API wrappers (high-level)
# ═══════════════════════════════════════════════════════


def api_search_bin(page, bin_num, street=""):
    human_delay()
    human_scroll(page)
    log.debug(f"api_search_bin BIN={bin_num}")
    st, data = browser_post(
        page,
        f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
        {"BIN": bin_num, "SearchBy": "2", "StreetName": street},
    )
    if st is None or isinstance(data, str):
        log.warning(f"api_search_bin BIN={bin_num} FAIL: {data}")
        return None, data or "KO"
    if not data.get("IsSuccess") or st != 200:
        log.warning(f"api_search_bin BIN={bin_num} API_ERROR")
        return None, "API_ERROR"
    jobs = data.get("ListBuildDetails", [])
    log.debug(f"api_search_bin BIN={bin_num} OK: {len(jobs)} jobs")
    return (jobs[0] if jobs else None), None


def api_get_pw1(page, guid):
    human_delay()
    human_scroll(page)
    st, data = browser_get(page, f"{SERVICE_BASE}/GetJobFilingPW1/{guid}")
    if st is None or isinstance(data, str):
        return None, None, None
    return (
        data.get("FilingIncludes", ""),
        data.get("CurrentFilingStatusValue", ""),
        data.get("IsPlanApproved", False),
    )


def api_get_zd1wd(page, guid):
    human_delay()
    human_scroll(page)
    st, data = browser_post(
        page,
        f"{SERVICE_BASE}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid},
    )
    if st is None or isinstance(data, str) or st != 200:
        return []
    return data.get("RequiredDocumentList") or []


def api_get_portal_docs(page, guid, fi, cstatus, isplan):
    human_delay()
    human_scroll(page)
    st, data = browser_post(
        page,
        f"{PUBLIC_BASE}/GetPublicPortalPartialJobFiling",
        {
            "Applicant": None,
            "RelatedEntityLogicalName": "dobnyc_documentlist",
            "JobFilingGUID": guid,
            "FilingIncludes": fi or "",
            "CurrentFilingStatusValue": cstatus or "",
            "IsPlanApproved": isplan or False,
        },
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
        page,
        f"{SERVICE_BASE}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": dp},
    )
    if st is None or isinstance(data, str) or st != 200:
        return ""
    return data.get("downloadPath", "")


# ═══════════════════════════════════════════════════════
# Akamai recovery
# ═══════════════════════════════════════════════════════


def recover_from_akamai(context, page, pw, vpn, bad_cities):
    log.warning(f"recover_from_akamai START (bad_cities={bad_cities[0]})")
    for attempt in range(AKAMAI_RELOAD_TRIES):
        print(f"  [recover] Reload {attempt + 1}/{AKAMAI_RELOAD_TRIES}")
        log.info(f"Recovery reload attempt {attempt + 1}/{AKAMAI_RELOAD_TRIES}")
        try:
            page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        time.sleep(4)

        if page_is_blocked(page):
            print("  [recover] Sigue bloqueado tras reload.")
            continue
        if not wait_angular(page, timeout_s=30):
            print("  [recover] Angular no disponible.")
            continue
        _abck_ok = monitor_abck(context, "post-reload")
        if _abck_ok:
            print("  [recover] Auth renovado OK.")
            return page, context

    if not vpn:
        print("  [recover] Sin VPN. Pausa 60s y ultimo intento...")
        time.sleep(60)
        try:
            page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            return None, None
        time.sleep(4)
        if page_is_blocked(page):
            return None, None
        if wait_angular(page, timeout_s=30):
            return page, context
        return None, None

    print("  [recover] Rotando VPN...")
    close_browser(pw, context)
    vpn.rotate()
    bad_cities[0] += 1
    print(f"  [recover] Ciudad {bad_cities[0]}/{MAX_VPN_BAD_CITIES}")

    if bad_cities[0] >= MAX_VPN_BAD_CITIES:
        print(f"  [recover] Pausa {VPN_COOLDOWN}s...")
        time.sleep(VPN_COOLDOWN)
        bad_cities[0] = 0

    time.sleep(15)
    new_pw, new_context, new_page = launch_browser()

    if page_is_blocked(new_page):
        print("  [recover] Nueva IP tambien bloqueada.")
        bad_cities[0] += 1
        return None, None

    warm_up(new_page, duration_s=20, quiet=True)
    if not wait_angular(new_page, timeout_s=60):
        print("  [recover] Angular no disponible.")
        return None, None

    monitor_abck(new_context, "new-session")
    bad_cities[0] = 0
    print("  [recover] Nueva sesion OK.")
    return new_context, new_page


# ═══════════════════════════════════════════════════════
# CSV helpers
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════


def main():
    log.info("=" * 60)
    log.info("browser_only_scraper.py START")
    log.info(f"Anti-fingerprinting: canvas + WebGL + AudioContext | _abck: ON | max_rows={MAX_ROWS}")
    print("=" * 60)
    print("browser_only_scraper.py — 100% browser, sin curl_cffi")
    print("Anti-fingerprinting: canvas + WebGL + AudioContext")
    print(f"_abck monitoring: ON  |  max_rows={MAX_ROWS}")
    print("=" * 60)

    if not os.path.exists(INPUT_CSV):
        print(f"[!] {INPUT_CSV} no existe.")
        sys.exit(1)

    vpn = None
    if VPN_AVAILABLE and ProtonVPN:
        vpn = ProtonVPN()
        print("[VPN] ProtonVPN detectado.")
        if not vpn.status():
            print("[VPN] Conectando...")
            vpn.connect(country="US", city="New York")
            time.sleep(5)
    else:
        print("[VPN] Sin ProtonVPN (IP fija).")

    print("[*] Lanzando navegador con anti-fingerprinting...")
    pw, context, page = launch_browser()

    monitor_abck(context, "startup")

    if page_is_blocked(page):
        print("[!] IP bloqueada. Rota VPN y relanza.")
        close_browser(pw, context)
        if vpn:
            vpn.rotate()
            time.sleep(15)
            pw, context, page = launch_browser()
            if page_is_blocked(page):
                print("[!] Nueva IP tambien bloqueada.")
                close_browser(pw, context)
                sys.exit(1)
        else:
            sys.exit(1)

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

    monitor_abck(context, "post-login")

    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    end_at = min(MAX_ROWS, total)
    print(f"\n[*] {total} filas en CSV, procesando {end_at}")

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=COLS)
        writer.writeheader()

        processed = 0
        bad_cities = [0]
        total_zd = 0

        for idx, row in enumerate(rows):
            if idx >= end_at:
                break

            bin_num = row.get("Bin", "").strip()
            job_filing = row.get("Job Filing Number", "").strip()
            borough = row.get("Borough", "").strip()
            street = row.get("Street Name", "").strip()

            if not bin_num or not job_filing:
                writer.writerow(
                    {**empty_row(), "Bin": bin_num, "result_status": "MISSING DATA"}
                )
                processed = idx + 1
                continue

            # Periodic _abck health check
            if processed > 0 and processed % 10 == 0:
                healthy = monitor_abck(context, f"row-{processed}")
                if not healthy:
                    print("  [_abck] Recovering poisoned session...")
                    recovered = recover_from_akamai(
                        context, page, pw, vpn, bad_cities
                    )
                    if recovered[0]:
                        context, page = recovered

            t0 = time.time()
            print(f"\n[{idx + 1}/{end_at}] BIN {bin_num} | {job_filing}")

            job, err = api_search_bin(page, bin_num, street)
            if err == "AKAMAI_BLOCKED":
                log.warning(f"AKAMAI_BLOCKED on BIN={bin_num}, attempting recovery")
                recovered = recover_from_akamai(
                    context, page, pw, vpn, bad_cities
                )
                if recovered[0]:
                    context, page = recovered
                    pw_new = pw
                    job, err = api_search_bin(page, bin_num, street)
                else:
                    writer.writerow(
                        {
                            **empty_row(),
                            "Bin": bin_num,
                            "result_status": "BLOCKED_UNRECOVERABLE",
                        }
                    )
                    processed = idx + 1
                    continue

            if err or job is None:
                writer.writerow(
                    {
                        **empty_row(),
                        "Bin": bin_num,
                        "result_status": err or "JOB_NOT_FOUND",
                    }
                )
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
                writer.writerow(
                    {**base, "zoning_status": zone, "result_status": "NO DOCUMENTS"}
                )
                processed = idx + 1
                continue

            zcount = 0
            for doc in portal:
                doc_url = doc.get("DocumentURL", "")
                doc_name = doc.get("Name", "")
                matched = any(k in doc_name.lower() for k in KEYS_LOWER)

                if not matched:
                    writer.writerow(
                        {
                            **base,
                            "doc_description": doc_name,
                            "doc_name": doc_name,
                            "doc_url_original": doc_url,
                            "result_status": "FILTERED",
                            "zoning_status": zone,
                            "doc_create_on": doc.get("CreateOn", "") or "",
                            "doc_category": doc.get("DocumentCategory", "") or "",
                            "doc_type_name": doc.get("DocumentTypeName", "") or "",
                            "doc_status_label": doc.get(
                                "RequiredItemStatusLabel", ""
                            )
                            or "",
                        }
                    )
                    continue

                total_zd += 1
                dload = ""
                if doc_url:
                    dload = api_get_download_url(page, doc_url, borough)
                    if dload == "AKAMAI_BLOCKED":
                        recovered = recover_from_akamai(
                            context, page, pw, vpn, bad_cities
                        )
                        if recovered[0]:
                            context, page = recovered
                            dload = api_get_download_url(page, doc_url, borough)
                        else:
                            dload = ""

                writer.writerow(
                    {
                        **base,
                        "doc_description": doc_name,
                        "doc_name": doc_name,
                        "doc_url_original": doc_url,
                        "download_url": dload or "",
                        "result_status": "OK",
                        "zoning_status": zone,
                        "doc_create_on": doc.get("CreateOn", "") or "",
                        "doc_category": doc.get("DocumentCategory", "") or "",
                        "doc_type_name": doc.get("DocumentTypeName", "") or "",
                        "doc_status_label": doc.get("RequiredItemStatusLabel", "")
                        or "",
                    }
                )
                zcount += 1

            elapsed = time.time() - t0
            print(f"  {zcount} docs ZD | {len(portal)} total | {elapsed:.2f}s")
            processed = idx + 1
            f_out.flush()

            if processed % CHECKPOINT_EVERY == 0:
                with open(CHECKPOINT_FILE, "w") as cp:
                    json.dump({"processed": processed, "total": total}, cp)

    print(f"\n{'=' * 60}")
    print(f"OK: {total_zd} docs ZD en {processed} BINs")
    print(f"CSV: {OUTPUT_CSV}")
    log.info(f"DONE: {total_zd} docs ZD en {processed} BINs -> {OUTPUT_CSV}")
    close_browser(pw, context)
    print("Hecho.")


if __name__ == "__main__":
    main()
