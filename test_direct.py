import json
import os
import sys
import time

from curl_cffi import requests

AUTH_DATA_FILE = os.path.join(os.path.dirname(__file__), "auth_data.json")
PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"
SERVICE_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperServicePP/WrapperService.svc"

TEST_BINS = ["3429586", "4624658", "3331440", "1037605", "2012957"]
TEST_GUIDS = {
    "3429586": "b08ee445-fe55-ef11-8006-001dd8053fbd",
}
IMPERSONATE = "chrome146"


def load_auth():
    if not os.path.exists(AUTH_DATA_FILE):
        print(f"[!] {AUTH_DATA_FILE} no existe. Ejecuta extract_auth.py primero.")
        sys.exit(1)

    with open(AUTH_DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    print(f"[*] Auth cargado: {len(data['cookies'])} cookies, "
          f"{len(data['interceptor_headers'])} headers del interceptor")
    print(f"[*] Timestamp: {data.get('timestamp', 'N/A')}")
    return data


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
        cookie_kwargs = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", "").lstrip("."),
            "path": c.get("path", "/"),
        }
        session.cookies.set(**cookie_kwargs)

    return session


def test_endpoint(session, label, method, url, body=None):
    print(f"\n  [{label}]", end=" ")
    try:
        t0 = time.time()
        if method == "POST":
            resp = session.post(url, json=body, timeout=30)
        else:
            resp = session.get(url, timeout=30)
        elapsed = time.time() - t0

        body_text = resp.text[:300]

        if resp.status_code == 200 and "Access Denied" not in body_text:
            print(f"OK ({resp.status_code}) [{elapsed:.2f}s]")
            if resp.text:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"    Body preview: {body_preview}")
            return True
        elif "Access Denied" in body_text or "edgesuite" in body_text:
            print(f"BLOQUEADO por Akamai ({resp.status_code}) [{elapsed:.2f}s]")
            print(f"    Body: {body_text}")
            return False
        else:
            print(f"FALLO ({resp.status_code}) [{elapsed:.2f}s]")
            print(f"    Body: {body_text}")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    print("=" * 60)
    print("test_direct.py — Prueba HTTP directa contra DOB Now")
    print(f"Impersonando: {IMPERSONATE}")
    print("=" * 60)

    auth_data = load_auth()
    session = build_session(auth_data)

    print(f"\n[*] Headers enviados:")
    for k, v in session.headers.items():
        if k.lower() not in ("cookie",):
            print(f"    {k}: {v}")

    results = {}

    # --- Test 1: getPublicPortalBuildDisplay ---
    print(f"\n{'='*40}")
    print("Test 1: getPublicPortalBuildDisplay")
    print(f"{'='*40}")
    for bin_num in TEST_BINS[:3]:
        ok = test_endpoint(
            session,
            f"BIN {bin_num}",
            "POST",
            f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
            {"BIN": bin_num, "SearchBy": "2", "StreetName": ""},
        )
        results[f"build_display_{bin_num}"] = ok
        if not ok:
            break

    # --- Test 2: GetJobFilingPW1 ---
    test_guid = TEST_GUIDS.get("3429586")
    if test_guid:
        print(f"\n{'='*40}")
        print("Test 2: GetJobFilingPW1")
        print(f"{'='*40}")
        ok = test_endpoint(
            session,
            f"GUID {test_guid}",
            "GET",
            f"{SERVICE_BASE}/GetJobFilingPW1/{test_guid}",
        )
        results["pw1"] = ok

    # --- Test 3: GetPartialJobFilingServiceZD1WD ---
    if test_guid and results.get("build_display_3429586"):
        print(f"\n{'='*40}")
        print("Test 3: GetPartialJobFilingServiceZD1WD")
        print(f"{'='*40}")
        ok = test_endpoint(
            session,
            f"GUID {test_guid}",
            "POST",
            f"{SERVICE_BASE}/GetPartialJobFilingServiceZD1WD",
            {"RelatedEntityLogicalName": "dobnyc_documentlist", "JobFilingGUID": test_guid},
        )
        results["zd1wd"] = ok

    # --- Resumen ---
    print(f"\n{'='*60}")
    print("RESUMEN")
    print(f"{'='*60}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for test_name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {test_name}")
    print(f"\n  {passed}/{total} tests pasaron")

    if passed == total:
        print("\n[+] Todas las pruebas pasaron. HTTP directo funciona!")
    elif passed > 0:
        print("\n[~] Algunas pruebas pasaron. Posible problema de expiracion de tokens.")
    else:
        print("\n[-] Ninguna prueba paso. HTTP directo no viable con estos datos de auth.")


if __name__ == "__main__":
    main()
