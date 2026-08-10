import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPER_CONSERVATIVE = os.path.join(HERE, "conservative_scraper.py")
SCRAPER_HYBRID = os.path.join(HERE, "patchright_hybrid.py")
DEFAULT_PROFILE = os.path.join(tempfile.gettempdir(), "chrome_cdp_profile")

try:
    from vpn import ProtonVPN
    VPN_AVAILABLE = True
except (ImportError, FileNotFoundError):
    ProtonVPN = None
    VPN_AVAILABLE = False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ejecuta scraper en bucle automatico"
    )
    parser.add_argument("--scraper", choices=["conservative", "hybrid"], default="conservative",
                        help="Scraper a ejecutar (default: conservative)")
    parser.add_argument("--interval", type=int, default=300,
                        help="Segundos entre ejecuciones (default: 300 = 5 min)")
    parser.add_argument("--max-failures", type=int, default=20,
                        help="Fallos consecutivos antes de detener el bucle (default: 20)")
    parser.add_argument("--vpn", action="store_true",
                        help="Rotar ProtonVPN automaticamente ante bloqueos")
    parser.add_argument("--vpn-rotate-every", type=int, default=0, metavar="N",
                        help="Rotar VPN + limpiar cookies cada N iteraciones (0=off)")
    parser.add_argument("--vpn-rotate-on-failures", type=int, default=5, metavar="N",
                        help="Rotar VPN + limpiar cookies tras N fallos consecutivos (default: 5)")
    parser.add_argument("--profile", default=None, metavar="DIR",
                        help="user-data-dir de Chrome para CDP (solo modo conservative, default: TEMP/chrome_cdp_profile)")
    args, scraper_args = parser.parse_known_args()
    return args, scraper_args


def exit_message(code):
    if code == 0:
        return "OK"
    if code == 2:
        return "ACCESS DENIED en la pagina — se necesita cambiar VPN"
    if code == 3:
        return "Sesion bloqueada — cambia VPN manualmente"
    return "ERROR"


def _find_chrome():
    import platform, shutil
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
    for c in ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]:
        path = shutil.which(c)
        if path:
            return path
    return "google-chrome"


def _kill_chrome():
    import platform
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "chrome"], capture_output=True)


def _wait_for_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def ensure_chrome_cdp(port, profile):
    print("[loop] Verificando Chrome CDP...")

    print("[loop] Matando Chrome existente...")
    _kill_chrome()
    time.sleep(3)

    chrome_path = _find_chrome()
    print(f"[loop] Lanzando Chrome: {chrome_path} --remote-debugging-port={port} --user-data-dir={profile}")
    cmd = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not _wait_for_port(port, timeout=15):
        print("[loop] No se pudo conectar al puerto CDP.")
        return False

    print("[loop] Puerto CDP listo. Verificando pagina...")
    try:
        from patchright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://a810-dobnow.nyc.gov/Publish/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        title = page.title() or ""
        print(f"[loop] Titulo: {title}")
        if "Access Denied" in title:
            print("[loop] La pagina sigue mostrando Access Denied. Prueba otra ciudad VPN.")
            try:
                pw.stop()
            except Exception:
                pass
            return False
        print("[loop] Pagina OK. Verificando _abck...")
        time.sleep(10)
        for cookie in ctx.cookies():
            if cookie.get("name") == "_abck":
                val = cookie.get("value", "")
                if "~-1" in val:
                    print(f"[loop] _abck marcada. Espera unos segundos y reintenta.")
                    print(f"[loop] _abck: {val[:120]}...")
                else:
                    print(f"[loop] _abck OK ({len(val)} chars)")
                break
        try:
            pw.stop()
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[loop] Error al conectar: {e}")
        return False


def clear_akamai_cookies(port):
    akamai_names = {"_abck", "bm_sz", "ak_bmsc", "bm_mi", "bm_sv"}
    try:
        from patchright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0]
        cleared = []
        for c in ctx.cookies():
            name = c.get("name", "")
            if name in akamai_names:
                ctx.clear_cookies(name=name)
                cleared.append(name)
        pw.stop()
        if cleared:
            print(f"[clear] Cookies de Akamai eliminadas: {', '.join(cleared)}")
        else:
            print("[clear] No se encontraron cookies de Akamai")
        return True
    except Exception as e:
        print(f"[clear] Error limpiando cookies: {e}")
        return False


def main():
    args, scraper_args = parse_args()

    is_hybrid = args.scraper == "hybrid"
    scraper_path = SCRAPER_HYBRID if is_hybrid else SCRAPER_CONSERVATIVE
    scraper_name = "patchright_hybrid.py" if is_hybrid else "conservative_scraper.py"

    if not scraper_args:
        print(f"[loop] No hay argumentos para {scraper_name}.")
        print("[loop] Pasa los mismos que usarias normalmente:")
        if is_hybrid:
            print("[loop]   python run_loop.py --scraper hybrid --max-rows 100")
        else:
            print("[loop]   python run_loop.py --cdp-port 9222 --max-rows 5")
        sys.exit(1)

    vpn = None
    if args.vpn:
        if not VPN_AVAILABLE or ProtonVPN is None:
            print("[!] --vpn requiere protonvpn CLI instalado. Instalalo o quita el flag.")
            sys.exit(1)
        vpn = ProtonVPN()
        print("[VPN] ProtonVPN detectado. Rotacion automatica ante bloqueos.")

    profile = args.profile or DEFAULT_PROFILE

    print("=" * 60)
    print(f"run_loop.py — ejecucion automatica de {scraper_name}")
    print(f"Scraper:           {args.scraper}")
    print(f"Intervalo:          {args.interval}s ({args.interval // 60} min)")
    print(f"Max fallos:         {args.max_failures}")
    print(f"VPN auto:           {'SI' if vpn else 'NO'}")
    if vpn:
        print(f"VPN rotate every:   {f'cada {args.vpn_rotate_every} iter' if args.vpn_rotate_every else 'solo reactivo'}")
        print(f"VPN rotate on fail: {args.vpn_rotate_on_failures} fallos consecutivos")
    if not is_hybrid:
        print(f"Perfil Chrome:      {profile}")
    print(f"Comando:            python {scraper_name} {' '.join(scraper_args)}")
    print("Ctrl+C para detener el bucle")
    print("=" * 60)

    iteration = 0
    consecutive_failures = 0

    while True:
        iteration += 1
        print(f"\n{'=' * 60}")
        print(f"[loop #{iteration}] Ejecutando {scraper_name}...")
        print(f"          {time.strftime('%Y-%m-%d %H:%M:%S')}  |  fallos consecutivos: {consecutive_failures}/{args.max_failures}")
        print(f"{'=' * 60}")

        result = subprocess.run(
            [sys.executable, scraper_path] + scraper_args,
            cwd=HERE,
        )

        code = result.returncode
        msg = exit_message(code)

        should_rotate_vpn = False

        if code in (2, 3) and vpn:
            consecutive_failures += 1
            should_rotate_vpn = True
        elif code == 0:
            consecutive_failures = 0
            print(f"\n[loop #{iteration}] OK. Fallos reseteados a 0.")
        elif code == 2 and not vpn:
            consecutive_failures += 1
            print(f"\n[loop #{iteration}] {msg} (fallos={consecutive_failures}/{args.max_failures})")
            print("                Si tienes ProtonVPN, usa --vpn para rotacion automatica.")
        else:
            consecutive_failures += 1
            print(f"\n[loop #{iteration}] {msg} (fallos={consecutive_failures}/{args.max_failures})")

        if vpn and args.vpn_rotate_every > 0 and iteration % args.vpn_rotate_every == 0:
            print(f"\n[loop #{iteration}] Rotacion VPN proactiva (cada {args.vpn_rotate_every} iteraciones)...")
            should_rotate_vpn = True

        if vpn and args.vpn_rotate_on_failures > 0 and consecutive_failures >= args.vpn_rotate_on_failures:
            print(f"\n[loop #{iteration}] Rotacion VPN por fallos ({consecutive_failures}/{args.vpn_rotate_on_failures})...")
            should_rotate_vpn = True

        if should_rotate_vpn and vpn:
            print(f"                Rotando ProtonVPN a siguiente ciudad US...")
            try:
                vpn.rotate()
            except Exception as e:
                print(f"                Error al rotar VPN: {e}")
            time.sleep(15)
            if is_hybrid:
                print("                [hybrid] VPN rotada. Reiniciando Chrome con nueva IP...")
                _kill_chrome()
                time.sleep(3)
                chrome_path = _find_chrome()
                subprocess.Popen(
                    [chrome_path, "--remote-debugging-port=9222", f"--user-data-dir={profile}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if _wait_for_port(9222, timeout=15):
                    clear_akamai_cookies(9222)
                    print("                [hybrid] Chrome CDP listo. Reintentando scraper...")
                else:
                    print("                [hybrid] No se pudo lanzar Chrome CDP.")
                consecutive_failures = 0
            else:
                print("                Reiniciando Chrome con nueva IP...")
                if ensure_chrome_cdp(9222, profile):
                    clear_akamai_cookies(9222)
                    print("                Chrome CDP listo. Reintentando scraper...")
                    consecutive_failures = 0
                else:
                    print("                No se pudo restablecer Chrome CDP. Proxima iteracion...")

        if consecutive_failures >= args.max_failures:
            print(f"\n[loop] {args.max_failures} fallos consecutivos. Deteniendo bucle.")
            print("[loop] Revisa la VPN, Chrome y dependencias antes de reintentar.")
            break

        next_time = time.strftime('%H:%M:%S', time.localtime(time.time() + args.interval))
        print(f"[loop] Proxima ejecucion en {args.interval}s ({next_time}). Ctrl+C para detener.")

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[loop] Detenido por el usuario.")
            break


if __name__ == "__main__":
    main()
