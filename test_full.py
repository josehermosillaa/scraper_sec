import csv
import json
import os
import sys
import time

from curl_cffi import requests

AUTH_DATA_FILE = os.path.join(os.path.dirname(__file__), "auth_data.json")
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "resultado_directo.csv")
PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"
SERVICE_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperServicePP/WrapperService.svc"
IMPERSONATE = "chrome146"

TEST_BINS = [
    "3429586",
    "4624658",
    "3331440",
    "1037605",
    "2012957",
]

KEYS = {"ZD1", "ZD2", "ZD1A", "ZRD"}

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


def load_auth():
    with open(AUTH_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_session(auth_data):
    session = requests.Session(impersonate=IMPERSONATE)
    session.headers.update({
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
    })
    session.headers.update(auth_data["interceptor_headers"])
    for c in auth_data["cookies"]:
        session.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", "").lstrip(".") or "",
            path=c.get("path") or "/",
        )
    return session


def _handle_akamai_block():
    print("\n[!] BLOQUEADO por Akamai. Los tokens/cookies expiraron o la IP esta quemada.")
    print("[!] Vuelve a ejecutar:")
    print("[!]   python newimplement/extract_auth.py && python newimplement/test_full.py")
    print("[!]   (NO cierres el navegador entre ambos comandos)")
    sys.exit(1)


def api_post(session, url, body, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.post(url, json=body, timeout=30)
            if resp.status_code == 403 and "Access Denied" in resp.text:
                _handle_akamai_block()
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            emsg = str(e)
            if "HTTP/2" in emsg or "INTERNAL_ERROR" in emsg or "CurlError" in emsg:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"    Retry {attempt + 1}/{retries} en {wait}s ({emsg[:80]})")
                    time.sleep(wait)
                    continue
            raise
    raise last_err


def api_get(session, url, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 403 and "Access Denied" in resp.text:
                _handle_akamai_block()
            return resp.status_code, resp.json()
        except Exception as e:
            last_err = e
            emsg = str(e)
            if "HTTP/2" in emsg or "INTERNAL_ERROR" in emsg or "CurlError" in emsg:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"    Retry {attempt + 1}/{retries} en {wait}s ({emsg[:80]})")
                    time.sleep(wait)
                    continue
            raise
    raise last_err


def search_bin(session, bin_number):
    status, data = api_post(
        session,
        f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
        {"BIN": bin_number, "SearchBy": "2", "StreetName": ""},
    )
    if not data.get("IsSuccess") or status != 200:
        return None
    jobs = data.get("ListBuildDetails", [])
    return jobs[0] if jobs else None


def get_pw1(session, guid):
    status, data = api_get(session, f"{SERVICE_BASE}/GetJobFilingPW1/{guid}")
    if status != 200:
        return None, None, None
    return (
        data.get("FilingIncludes", ""),
        data.get("CurrentFilingStatusValue", ""),
        data.get("IsPlanApproved", False),
    )


def get_zd1wd_docs(session, guid):
    status, data = api_post(
        session,
        f"{SERVICE_BASE}/GetPartialJobFilingServiceZD1WD",
        {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": guid},
    )
    if status != 200:
        return []
    return data.get("RequiredDocumentList") or []


def get_portal_docs(session, guid, filing_includes, current_status, is_plan_approved):
    status, data = api_post(
        session,
        f"{PUBLIC_BASE}/GetPublicPortalPartialJobFiling",
        {
            "Applicant": None,
            "RelatedEntityLogicalName": "dobnyc_documentlist",
            "JobFilingGUID": guid,
            "FilingIncludes": filing_includes or "",
            "CurrentFilingStatusValue": current_status or "",
            "IsPlanApproved": is_plan_approved or False,
        },
    )
    if status != 200:
        return []
    return data.get("RequiredDocumentList") or []


def get_download_url(session, doc_url, borough):
    borough_key = BOROUGH_MAP.get(borough, borough.upper())
    download_path = f"\\\\PortalDownloadedDocuments\\{borough_key}\\TEST\\"
    status, data = api_post(
        session,
        f"{SERVICE_BASE}/downloadFromDocumentum",
        {"uploadedPath": doc_url, "downloadPath": download_path},
    )
    if status != 200:
        return f"ERROR: status {status}"
    return data.get("downloadPath", "")


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


def main():
    print("=" * 60)
    print("test_full.py — Pipeline completo HTTP directo")
    print("=" * 60)

    auth_data = load_auth()
    session = build_session(auth_data)

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=COLS)
        writer.writeheader()

        total_docs = 0
        total_zd_docs = 0

        for idx, bin_num in enumerate(TEST_BINS, 1):
            print(f"\n--- [{idx}/{len(TEST_BINS)}] BIN {bin_num} ---")

            t_start = time.time()

            job = search_bin(session, bin_num)
            if job is None:
                print(f"  No se encontro trabajo para BIN {bin_num}")
                row = empty_row()
                row["Bin"] = bin_num
                row["result_status"] = "JOB NOT FOUND"
                writer.writerow(row)
                continue

            guid = job.get("BuildID", "")
            borough = job.get("Borough", "")

            print(f"  GUID: {guid} | Borough: {borough} | "
                  f"Job: {job.get('JobNumber_FilingNumber', 'N/A')}")

            base_row = row_from_job(job)

            filing_includes, current_status, is_plan_approved = get_pw1(session, guid)
            zoning_status = ""

            zd1wd_docs = get_zd1wd_docs(session, guid)
            zoning_status = "HAS ZONING DOCUMENTS" if zd1wd_docs else "NO ZONING DOCUMENTS"

            portal_docs = get_portal_docs(
                session, guid, filing_includes, current_status, is_plan_approved
            )

            existing_urls = {d.get("DocumentURL", "") for d in portal_docs if d.get("DocumentURL")}
            for zd in zd1wd_docs:
                url = zd.get("DocumentURL", "")
                if url and url not in existing_urls:
                    portal_docs.append(zd)
                    existing_urls.add(url)

            if not portal_docs:
                row = dict(base_row)
                row["guid"] = guid
                row["filing_status"] = current_status or ""
                row["zoning_status"] = zoning_status
                row["result_status"] = "NO DOCUMENTS"
                writer.writerow(row)
                print(f"  Sin documentos.")
                continue

            row_count = 0
            for doc in portal_docs:
                doc_url = doc.get("DocumentURL", "")
                doc_name = doc.get("Name", "")
                doc_name_lower = doc_name.lower()
                matched = any(key.lower() in doc_name_lower for key in KEYS)

                if not matched:
                    row = dict(base_row)
                    row["guid"] = guid
                    row["filing_status"] = current_status or ""
                    row["doc_description"] = doc_name
                    row["doc_name"] = doc_name
                    row["doc_url_original"] = doc_url
                    row["result_status"] = "FILTERED"
                    row["zoning_status"] = zoning_status
                    row["doc_create_on"] = doc.get("CreateOn", "") or ""
                    row["doc_category"] = doc.get("DocumentCategory", "") or ""
                    row["doc_type_name"] = doc.get("DocumentTypeName", "") or ""
                    row["doc_status_label"] = doc.get("RequiredItemStatusLabel", "") or ""
                    writer.writerow(row)
                    continue

                total_zd_docs += 1
                download_url = ""
                if doc_url:
                    try:
                        download_url = get_download_url(session, doc_url, borough) or ""
                    except Exception as e:
                        download_url = f"ERROR: {e}"

                row = dict(base_row)
                row["guid"] = guid
                row["filing_status"] = current_status or ""
                row["doc_description"] = doc_name
                row["doc_name"] = doc_name
                row["doc_url_original"] = doc_url
                row["download_url"] = download_url
                row["result_status"] = "OK"
                row["zoning_status"] = zoning_status
                row["doc_create_on"] = doc.get("CreateOn", "") or ""
                row["doc_category"] = doc.get("DocumentCategory", "") or ""
                row["doc_type_name"] = doc.get("DocumentTypeName", "") or ""
                row["doc_status_label"] = doc.get("RequiredItemStatusLabel", "") or ""
                writer.writerow(row)
                row_count += 1

            elapsed = time.time() - t_start
            print(f"  {row_count} docs ZD | {len(portal_docs)} total docs | {elapsed:.2f}s")
            total_docs += len(portal_docs)

            f_out.flush()

    print(f"\n{'='*60}")
    print(f"Completado: {total_zd_docs} documentos ZD1/ZD2/ZRD "
          f"de {total_docs} totales en {len(TEST_BINS)} BINs")
    print(f"CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
