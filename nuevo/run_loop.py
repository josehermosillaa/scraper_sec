import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
SCRAPER = os.path.join(HERE, "patchright_hybrid.py")
DEFAULT_PROFILE = os.path.join(tempfile.gettempdir(), "chrome_cdp_profile")

sys.path.insert(0, PARENT)
try:
    from vpn import ProtonVPN
    VPN_AVAILABLE = True
except (ImportError, FileNotFoundError):
    ProtonVPN = None
    VPN_AVAILABLE = False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Loop automatico para patchright_hybrid.py (modo CDP)"
    )
    parser.add_argument("--interval", type=int, default=300,
                        help="Segundos entre ejecuciones (default: 300 = 5 min)")
    parser.add_argument("--max-failures", type=int, default=20,
                        help="Fallos consecutivos antes de detener el bucle (default: 20)")
    parser.add_argument("--vpn", action="store_true",
                        help="Rotar ProtonVPN automaticamente ante bloqueos")
    parser.add_argument("--vpn-rotate-every", type=int, default=0, metavar="N",
                        help="Rotar VPN cada N iteraciones (0=off)")
    parser.add_argument("--vpn-rotate-on-failures", type=int, default=5, metavar="N",
                        help="Rotar VPN tras N fallos consecutivos (default: 5)")
    parser.add_argument("--profile", default=None, metavar="DIR",
                        help="user-data-dir de Chrome (default: TEMP/chrome_cdp_profile)")
    args, scraper_args = parser.parse_known_args()

    has_cdp = any(a.startswith("--cdp-port") for a in scraper_args)
    if not has_cdp:
        scraper_args = ["--cdp-port", "9222"] + scraper_args

    return args, scraper_args


def exit_message(code):
    if code == 0:
        return "OK"
    if code == 2:
        return "ACCESS DENIED en la pagina"
    if code == 3:
        return "Sesion bloqueada"
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


def launch_chrome_cdp(port, profile):
    print("[loop] Matando Chrome existente...")
    _kill_chrome()
    time.sleep(3)

    chrome_path = _find_chrome()
    print(f"[loop] Lanzando Chrome: {chrome_path} --remote-debugging-port={port}")
    cmd = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not _wait_for_port(port, timeout=15):
        print("[loop] No se pudo conectar al puerto CDP.")
        return False

    print("[loop] Puerto CDP listo.")
    return True


def clear_akamai_cookies(port):
    akamai_names = {"_abck", "bm_sz", "ak_bmsc", "bm_mi", "bm_sv"}
    try:
        from patchright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        cleared = []
        for c in ctx.cookies():
            name = c.get("name", "")
            if name in akamai_names:
                ctx.clear_cookies(name=name)
                cleared.append(name)
        try:
            page.evaluate("localStorage.clear()", isolated_context=False)
            page.evaluate("sessionStorage.clear()", isolated_context=False)
            page.evaluate("""
                indexedDB.databases().then(dbs => {
                    dbs.forEach(db => indexedDB.deleteDatabase(db.name));
                });
            """, isolated_context=False)
            print("[loop] localStorage, sessionStorage, indexedDB limpiados")
        except Exception as e:
            print(f"[loop] Error limpiando storage del navegador: {e}")
        pw.stop()
        if cleared:
            print(f"[loop] Cookies Akamai eliminadas: {', '.join(cleared)}")
        else:
            print("[loop] No se encontraron cookies de Akamai")
        return True
    except Exception as e:
        print(f"[loop] Error limpiando cookies: {e}")
        return False


def nuke_browser_state(port):
    akamai = clear_akamai_cookies(port)
    return akamai


def main():
    args, scraper_args = parse_args()

    if not scraper_args:
        print("[loop] No hay argumentos para patchright_hybrid.py.")
        print("[loop] Pasa los mismos que usarias normalmente:")
        print("[loop]   python run_loop.py --max-rows 100 --pause-min 6 --pause-max 15")
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
    print("run_loop.py — loop automatico para patchright_hybrid.py (CDP)")
    print(f"Intervalo:          {args.interval}s ({args.interval // 60} min)")
    print(f"Max fallos:         {args.max_failures}")
    print(f"VPN auto:           {'SI' if vpn else 'NO'}")
    if vpn:
        print(f"VPN rotate every:   {f'cada {args.vpn_rotate_every} iter' if args.vpn_rotate_every else 'solo reactivo'}")
        print(f"VPN rotate on fail: {args.vpn_rotate_on_failures} fallos consecutivos")
    print(f"Perfil Chrome:      {profile}")
    print(f"Comando:            python patchright_hybrid.py {' '.join(scraper_args)}")
    print("Ctrl+C para detener el bucle")
    print("=" * 60)

    iteration = 0
    consecutive_failures = 0

    while True:
        iteration += 1
        print(f"\n{'=' * 60}")
        print(f"[loop #{iteration}] Ejecutando patchright_hybrid.py...")
        print(f"          {time.strftime('%Y-%m-%d %H:%M:%S')}  |  fallos consecutivos: {consecutive_failures}/{args.max_failures}")
        print(f"{'=' * 60}")

        result = subprocess.run(
            [sys.executable, SCRAPER] + scraper_args,
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
            extra_wait = 0
            if consecutive_failures >= 6:
                extra_wait = 300
            elif consecutive_failures >= 5:
                extra_wait = 120
            elif consecutive_failures >= 3:
                extra_wait = 60
            if extra_wait:
                print(f"                Cooldown progresivo: +{extra_wait}s (fallos={consecutive_failures})")
                time.sleep(extra_wait)
            print(f"                Rotando ProtonVPN a siguiente ciudad US...")
            try:
                vpn.rotate()
            except Exception as e:
                print(f"                Error al rotar VPN: {e}")
            time.sleep(15)
            print("                Reiniciando Chrome con nueva IP...")
            if launch_chrome_cdp(9222, profile):
                nuke_browser_state(9222)
                print("                Chrome CDP listo. Reintentando scraper...")
            else:
                print("                No se pudo lanzar Chrome CDP. Proxima iteracion...")

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
