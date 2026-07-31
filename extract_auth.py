import json
import os
import sys
import time

from seleniumbase import Driver

DOBNOW_URL = "https://a810-dobnow.nyc.gov/Publish/"
AUTH_DATA_FILE = os.path.join(os.path.dirname(__file__), "auth_data.json")
PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"


def main():
    print("[*] Lanzando navegador UC...")
    driver = Driver(uc=True, headless=False)
    driver.set_script_timeout(120)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {} };
        """
    })

    driver.get(DOBNOW_URL)
    print(f"[*] Pagina cargada: {driver.title}")

    if "Access Denied" in driver.title:
        print("[!] Acceso denegado por Akamai. Cambia de IP/VPN e intenta de nuevo.")
        driver.quit()
        sys.exit(1)

    print("[*] Esperando Angular (AuthTokenInterceptor)...")
    interceptor_ready = False
    for i in range(120):
        try:
            ready = driver.execute_script("""
                try {
                    var injector = angular.element(document.body).injector();
                    return !!injector.get("AuthTokenInterceptor");
                } catch(e) { return false; }
            """)
            if ready:
                interceptor_ready = True
                break
        except Exception:
            pass
        if i % 10 == 0 and i > 0:
            print(f"  ... {i}s")
        time.sleep(1)

    if not interceptor_ready:
        print("[!] Angular/AuthTokenInterceptor no detectado tras 120s.")
        driver.quit()
        sys.exit(1)

    print("[*] Angular listo. Extrayendo headers del interceptor...")
    interceptor_headers = driver.execute_script("""
        var injector = angular.element(document.body).injector();
        var interceptor = injector.get("AuthTokenInterceptor");
        var req = {method: "POST", url: "/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", headers: {}};
        req = interceptor.request(req);
        return req.headers;
    """)

    print(f"[*] Headers del interceptor: {json.dumps(interceptor_headers, indent=2)}")

    cookies = driver.get_cookies()
    print(f"[*] Cookies obtenidas: {len(cookies)}")

    auth_data = {
        "interceptor_headers": interceptor_headers,
        "cookies": cookies,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2, default=str)

    print(f"[+] Datos de autenticacion guardados en {AUTH_DATA_FILE}")
    print(f"[*] Deja el navegador ABIERTO mientras corres test_full.py / test_direct.py")
    print(f"    Presiona Enter para cerrar el navegador...")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    driver.quit()


if __name__ == "__main__":
    main()
