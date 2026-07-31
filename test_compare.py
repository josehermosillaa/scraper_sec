import json
import os
import time

from curl_cffi import requests
from session import BrowserSession
from api import DobNowAPI

AUTH_DATA_FILE = os.path.join(os.path.dirname(__file__), "auth_data.json")
PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"
IMPERSONATE = "chrome146"

TEST_BINS = [
    ("3429586", ""),
    ("4624658", ""),
    ("3331440", ""),
    ("1037605", ""),
    ("2012957", ""),
]


def load_auth():
    if not os.path.exists(AUTH_DATA_FILE):
        print(f"[!] {AUTH_DATA_FILE} no existe. Ejecuta extract_auth.py primero.")
        sys.exit(1)
    with open(AUTH_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_direct_session(auth_data):
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


def test_via_browser(bin_num, street, browser_session, api):
    t0 = time.time()
    try:
        result = api.build_display(bin_num, street)
        body = json.loads(result["body"]) if isinstance(result["body"], str) else result["body"]
        ok = result.get("status") == 200 and "Access Denied" not in str(body)
        elapsed = time.time() - t0
        return ok, elapsed, body
    except Exception as e:
        elapsed = time.time() - t0
        return False, elapsed, str(e)


def test_via_direct(bin_num, direct_session):
    t0 = time.time()
    try:
        resp = direct_session.post(
            f"{PUBLIC_BASE}/getPublicPortalBuildDisplay",
            json={"BIN": bin_num, "SearchBy": "2", "StreetName": ""},
            timeout=30,
        )
        elapsed = time.time() - t0
        ok = resp.status_code == 200 and "Access Denied" not in resp.text
        body = resp.text[:200]
        return ok, elapsed, body
    except Exception as e:
        elapsed = time.time() - t0
        return False, elapsed, str(e)


def main():
    print("=" * 60)
    print("test_compare.py — Comparativa browser vs HTTP directo")
    print("=" * 60)

    auth_data = load_auth()
    direct_session = build_direct_session(auth_data)

    print("\n[*] Iniciando sesion de navegador UC...")
    browser_session = BrowserSession(browser_type="uc")
    api = DobNowAPI(browser_session)

    print(f"\n{'='*60}")
    print(f"{'BIN':<12} {'Browser':>10} {'Directo':>10} {'Diferencia':>12}")
    print(f"{'='*60}")

    browser_times = []
    direct_times = []

    for bin_num, street in TEST_BINS:
        bok, btime, _ = test_via_browser(bin_num, street, browser_session, api)
        dok, dtime, _ = test_via_direct(bin_num, direct_session)

        if bok and btime:
            browser_times.append(btime)
        if dok and dtime:
            direct_times.append(dtime)

        bstatus = f"{btime:.2f}s" if bok else "FAIL"
        dstatus = f"{dtime:.2f}s" if dok else "FAIL"
        diff = f"{btime - dtime:.2f}s" if bok and dok else "-"

        print(f"{bin_num:<12} {bstatus:>10} {dstatus:>10} {diff:>12}")

    print(f"{'='*60}")
    if browser_times and direct_times:
        avg_b = sum(browser_times) / len(browser_times)
        avg_d = sum(direct_times) / len(direct_times)
        print(f"Promedio browser:  {avg_b:.2f}s ({len(browser_times)} requests)")
        print(f"Promedio directo:  {avg_d:.2f}s ({len(direct_times)} requests)")
        if avg_b > avg_d:
            speedup = avg_b / avg_d
            print(f"Speedup:           {speedup:.1f}x mas rapido con HTTP directo")
        elif avg_d > avg_b:
            print(f"HTTP directo fue {avg_d/avg_b:.1f}x mas lento")
    else:
        print("No hay suficientes datos para comparar.")

    browser_session.close()


if __name__ == "__main__":
    main()
