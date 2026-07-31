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

MAX_ROWS = 10
REFRESH_AUTH_EVERY = 15
CHECKPOINT_EVERY = 50
MAX_VPN_BAD_CITIES = 3
VPN_COOLDOWN = 600
AKAMAI_RELOAD_TRIES = 3

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


# ═══════════════════════════════════════════════════════
# Patchright browser
# ═══════════════════════════════════════════════════════

def launch_browser():
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,
        no_viewport=True,
        args=["--no-first-run", "--no-default-browser-check"],
    )
    page = context.pages[0] if context.pages else context.new_page()
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
        time.sleep(random.uniform(1.5, 3.5))
    if not quiet:
        print("  [warm-up] listo.")


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
    page.goto(DOBNOW_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)
    if page_is_blocked(page):
        return None, None
    if not wait_angular(page, timeout_s=30):
        return None, None
    return extract_auth(page, context)


# ═══════════════════════════════════════════════════════
# Akamai recovery
# ═══════════════════════════════════════════════════════

def recover_from_akamai(page, context, pw, http_session, vpn, bad_cities):
    """Intent recovery. Returns (new_page, new_context) or (None, None)."""
    for attempt in range(AKAMAI_RELOAD_TRIES):
        print(f"  [recover] Reload {attempt + 1}/{AKAMAI_RELOAD_TRIES}")
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
    print(f"  [recover] Ciudad {bad_cities[0]}/{MAX_VPN_BAD_CITIES}")

    if bad_cities[0] >= MAX_VPN_BAD_CITIES:
        print(f"  [recover] Pausa {VPN_COOLDOWN}s...")
        time.sleep(VPN_COOLDOWN)
        bad_cities[0] = 0

    time.sleep(15)

    new_context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,
        no_viewport=True,
        args=["--no-first-run", "--no-default-browser-check"],
    )
    new_page = new_context.pages[0] if new_context.pages else new_context.new_page()
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


# ═══════════════════════════════════════════════════════
# curl_cffi HTTP
# ═══════════════════════════════════════════════════════

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
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None, str(last_err)


# ═══════════════════════════════════════════════════════
# API wrappers
# ═══════════════════════════════════════════════════════

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
        return None, None, None
    return (data.get("FilingIncludes", ""),
            data.get("CurrentFilingStatusValue", ""),
            data.get("IsPlanApproved", False))


def api_get_zd1wd(session, guid):
    st, data = http_post(session,
        f"{SERVICE_BASE}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid})
    if st is None or isinstance(data, str) or st != 200:
        return []
    return data.get("RequiredDocumentList") or []


def api_get_portal_docs(session, guid, fi, cstatus, isplan):
    st, data = http_post(session,
        f"{PUBLIC_BASE}/GetPublicPortalPartialJobFiling",
        {"Applicant": None, "RelatedEntityLogicalName": "dobnyc_documentlist",
         "JobFilingGUID": guid, "FilingIncludes": fi or "",
         "CurrentFilingStatusValue": cstatus or "",
         "IsPlanApproved": isplan or False})
    if st is None or isinstance(data, str) or st != 200:
        return []
    return data.get("RequiredDocumentList") or []


def api_get_download_url(session, doc_url, borough):
    bk = BOROUGH_MAP.get(borough, borough.upper())
    dp = f"\\\\PortalDownloadedDocuments\\{bk}\\TEST\\"
    st, data = http_post(session,
        f"{SERVICE_BASE}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": dp})
    if st is None or isinstance(data, str) or st != 200:
        return ""
    return data.get("downloadPath", "")


# ═══════════════════════════════════════════════════════
# CSV
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
    print("=" * 60)
    print("patchright_hybrid.py — Patchright + curl_cffi")
    print(f"impersonate={IMPERSONATE}  max_rows={MAX_ROWS}")
    print("=" * 60)

    if not os.path.exists(INPUT_CSV):
        print(f"[!] {INPUT_CSV} no existe. Pega el CSV con BINs ahi.")
        sys.exit(1)

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

    if page_is_blocked(page):
        print("[!] IP bloqueada. Rota VPN y relanza.")
        close_browser(pw, context)
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

    interceptor_h, cookies = extract_auth(page, context)
    print(f"[*] Auth extraido: {len(cookies)} cookies, headers={json.dumps(interceptor_h)}")

    http_s = build_http_session(interceptor_h, cookies)

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
        auth_counter = 0
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
                writer.writerow({**empty_row(), "Bin": bin_num, "result_status": "MISSING DATA"})
                processed = idx + 1
                continue

            if auth_counter >= REFRESH_AUTH_EVERY:
                print("  [refresh] Renovando auth...")
                h, c = reload_page_auth(page, context)
                if h:
                    update_http_session(http_s, h, c)
                    auth_counter = 0
                else:
                    print("  [refresh] Fallo. Siguiendo con actual.")

            time.sleep(random.uniform(0.2, 0.5))
            auth_counter += 1

            t0 = time.time()
            print(f"\n[{idx + 1}/{end_at}] BIN {bin_num} | {job_filing}")

            job, err = api_find_job(http_s, bin_num, job_filing, street)
            if err == "AKAMAI_BLOCKED":
                new_page, new_ctx = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                if new_page:
                    page, context = new_page, new_ctx
                    auth_counter = 0
                    job, err = api_find_job(http_s, bin_num, job_filing, street)
                else:
                    writer.writerow({**empty_row(), "Bin": bin_num, "result_status": "BLOCKED_UNRECOVERABLE"})
                    processed = idx + 1
                    continue

            if err or job is None:
                writer.writerow({**empty_row(), "Bin": bin_num, "result_status": err or "JOB_NOT_FOUND"})
                processed = idx + 1
                continue

            guid = job.get("BuildID", "")
            base = row_from_job(job)
            base["guid"] = guid

            fi, cstatus, isplan = api_get_pw1(http_s, guid)
            base["filing_status"] = cstatus or ""

            zd1wd = api_get_zd1wd(http_s, guid)
            zone = "HAS ZONING DOCUMENTS" if zd1wd else "NO ZONING DOCUMENTS"

            portal = api_get_portal_docs(http_s, guid, fi, cstatus, isplan)

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
                    dload = api_get_download_url(http_s, doc_url, borough)
                    if dload == "AKAMAI_BLOCKED":
                        new_page, new_ctx = recover_from_akamai(page, context, pw, http_s, vpn, bad_cities)
                        if new_page:
                            page, context = new_page, new_ctx
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
            print(f"  {zcount} docs ZD | {len(portal)} total | {elapsed:.2f}s")
            processed = idx + 1
            f_out.flush()

            if processed % CHECKPOINT_EVERY == 0:
                with open(CHECKPOINT_FILE, "w") as cp:
                    json.dump({"processed": processed, "total": total}, cp)

    print(f"\n{'=' * 60}")
    print(f"OK: {total_zd} docs ZD en {processed} BINs")
    print(f"CSV: {OUTPUT_CSV}")
    close_browser(pw, context)
    print("Hecho.")


if __name__ == "__main__":
    main()
