import base64
import json
import logging
import os
import platform
import random
import shutil
import socket
import subprocess
import threading
import time
from playwright.sync_api import sync_playwright


class ProxyRelay:

    def __init__(self, host, port, user, password):
        self.upstream_host = host
        self.upstream_port = int(port)
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.local_port = random.randint(10000, 60000)
        self.server = None
        self._thread = None

    def start(self):
        self.server = threading.Thread(target=self._run, daemon=True)
        self.server.start()
        time.sleep(0.5)
        return self.local_port

    def stop(self):
        self.running = False
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", self.local_port))
        except Exception:
            pass
        s.close()

    def _run(self):
        self.running = True
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.local_port))
        srv.listen(50)
        srv.settimeout(1)
        while self.running:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except socket.timeout:
                pass
            except Exception:
                pass
        srv.close()

    def _handle(self, conn):
        try:
            data = conn.recv(4096)
            if not data:
                conn.close()
                return
            request = data.decode("latin-1", errors="replace")
            first_line = request.split("\r\n")[0]
            parts = first_line.split(" ")
            method = parts[0]
            target = parts[1]

            if method == "CONNECT":
                self._handle_connect(conn, target)
            else:
                self._handle_http(conn, data)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_connect(self, conn, target):
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.settimeout(30)
        upstream.connect((self.upstream_host, self.upstream_port))
        auth_hdr = f"Proxy-Authorization: Basic {self.auth}\r\n"
        upstream.sendall(f"CONNECT {target} HTTP/1.1\r\n{auth_hdr}\r\n".encode())
        resp = upstream.recv(4096)
        if b"200" in resp:
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._relay_two_way(conn, upstream)
        else:
            conn.sendall(resp)
        try:
            upstream.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    def _handle_http(self, conn, data):
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.settimeout(30)
        upstream.connect((self.upstream_host, self.upstream_port))
        auth_hdr = f"Proxy-Authorization: Basic {self.auth}\r\n"
        req_str = data.decode("latin-1", errors="replace")
        if "Proxy-Authorization" not in req_str:
            idx = req_str.find("\r\n\r\n")
            if idx != -1:
                data = (req_str[:idx+2] + auth_hdr + req_str[idx+2:]).encode()
            else:
                data = (req_str + f"\r\n{auth_hdr}").encode()
        upstream.sendall(data)
        self._relay(upstream, conn)
        upstream.close()
        conn.close()

    def _relay(self, src, dst):
        try:
            while self.running:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass

    def _relay_two_way(self, c1, c2):
        done = [False]
        def forward(a, b):
            try:
                while self.running and not done[0]:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
            except Exception:
                pass
            done[0] = True
        t1 = threading.Thread(target=forward, args=(c1, c2), daemon=True)
        t2 = threading.Thread(target=forward, args=(c2, c1), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()


class BrowserSession:

    def __init__(self, browser_type="chrome", debugger_url="http://127.0.0.1:9222",
                 profile_dir=None, chrome_path=None, proxy=None, proxy_api_key=None, vpn=None):

        self.browser_type = browser_type
        self.port = int(debugger_url.split(":")[-1])
        self.is_linux = platform.system() == "Linux"

        self.chrome_path = chrome_path or self._detect_chrome()
        self.profile_dir = profile_dir or (
            os.path.expanduser("~/.config/chrome-dob") if self.is_linux else "C:\\ChromeDebug"
        )

        self.proxy = self._parse_proxy(proxy) if proxy else None
        self.proxy_api_key = proxy_api_key
        self.vpn = vpn
        self._proxy_selenium = None
        self._proxy_chrome_flag = None
        self._relay = None
        if self.proxy:
            h, p, u, pw = self.proxy
            if browser_type == "uc":
                self._relay = ProxyRelay(h, p, u, pw)
                relay_port = self._relay.start()
                self._proxy_selenium = f"http://127.0.0.1:{relay_port}"
                logging.info(f"Relay local activo en puerto {relay_port}")
            else:
                self._proxy_selenium = f"http://{u}:{pw}@{h}:{p}"
                self._proxy_chrome_flag = f"{h}:{p}"

        self._uc_profile_dir = os.path.expanduser("~/.config/chrome-dob-uc") if browser_type == "uc" else None

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.driver = None

        if browser_type == "uc":
            self._init_uc()
        elif browser_type == "firefox":
            self._init_firefox()
        else:
            if self.proxy:
                self._init_chrome_proxy()
            else:
                self._init_chrome_cdp()

    @staticmethod
    def _detect_chrome():
        if platform.system() != "Linux":
            return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        candidates = [
            "google-chrome-stable",
            "google-chrome",
            "chromium",
            "chromium-browser",
        ]
        for name in candidates:
            path = shutil.which(name)
            if path:
                return path
        return "google-chrome"

    @staticmethod
    def _parse_proxy(proxy_str):
        if not proxy_str:
            return None
        if "://" in proxy_str:
            rest = proxy_str.split("://", 1)[1]
            if "@" in rest:
                auth, hostport = rest.split("@")
                user_pass = auth.split(":")
                hp = hostport.split(":")
                return hp[0], hp[1], user_pass[0], user_pass[1]
        parts = proxy_str.split(":")
        if len(parts) == 4:
            return parts[0], parts[1], parts[2], parts[3]
        return None

    def _init_chrome_proxy(self):
        os.makedirs(self.profile_dir, exist_ok=True)
        self.playwright = sync_playwright().start()
        h, p, u, pw = self.proxy
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=False,
            channel="chrome",
            proxy={
                "server": f"http://{h}:{p}",
                "username": u,
                "password": pw,
            },
        )
        pages = [pg for pg in self.context.pages if "dobnow" in pg.url.lower()]
        self.page = pages[0] if pages else self.context.new_page()
        self.page.goto("https://a810-dobnow.nyc.gov/Publish/")
        time.sleep(3)
        title = self.page.title()
        if "Access Denied" in title:
            ip_info = self.page.evaluate("""async () => {
                const r = await fetch("https://httpbin.org/ip");
                return await r.json();
            }""")
            print(f"  ⚠  Bloqueado por Akamai. Proxy IP: {ip_info.get('origin', 'desconocida')}")
            logging.info(f"Proxy bloqueado. IP del proxy: {ip_info.get('origin', 'desconocida')}")
        if self.load_cookies():
            self.page.goto("https://a810-dobnow.nyc.gov/Publish/")
            time.sleep(3)
        print("  Verificando acceso a la API...")
        logging.info("Verificando acceso a la API")
        if self.wait_for_angular(timeout=120):
            time.sleep(3)
            if not self._verify_proxy():
                print("  API bloqueada en esta IP. Cambiando de IP...")
                logging.info("API bloqueada en proxy IP")
                self._verify_proxy()

    def _page_is_blocked(self):
        if not self.driver:
            return False
        try:
            source = self.driver.page_source
            return "Access Denied" in source and "edgesuite" in source
        except Exception:
            return True

    def _open_uc_browser(self):

        from seleniumbase import Driver
        kwargs = {"uc": True}
        if self._proxy_selenium:
            kwargs["proxy"] = self._proxy_selenium
        if self._uc_profile_dir:
            os.makedirs(self._uc_profile_dir, exist_ok=True)
            kwargs["user_data_dir"] = self._uc_profile_dir
        for attempt in range(3):
            try:
                self.driver = Driver(**kwargs)
                self.driver.set_script_timeout(120)

                # fingerprint: ocultar webdriver + chrome runtime
                self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        delete navigator.__proto__.webdriver;
                        window.chrome = { runtime: {} };
                    """
                })
                # viewport aleatorio (1280..1920 x 720..1080)
                w = random.randint(1280, 1920)
                h = random.randint(720, 1080)
                self.driver.set_window_size(w, h)

                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
                if not self._page_is_blocked():
                    return True
                print(f"  Pagina bloqueada por Akamai ({attempt+1}/3). Browser nuevo...")
            except Exception:
                print(f"  Error abriendo browser ({attempt+1}/3). Reintentando...")
            try:
                self.driver.quit()
            except Exception:
                pass
            time.sleep(3)
        return False

    def _init_uc(self):
        if not self._open_uc_browser():
            print("  ERROR: No se pudo abrir el navegador.")
            return
        for attempt in range(3):
            if self.load_cookies():
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
                if self._page_is_blocked():
                    print("  Cookies envenenadas. Borrando y empezando fresco...")
                    self._delete_cookies()
                    continue
            print("  Esperando que DOB Now cargue...")
            if self.wait_for_angular(timeout=120):
                time.sleep(3)
                self._warm_up()
                print("  Verificando acceso a la API...")
                if self._verify_proxy():
                    return
                print("  API bloqueada en esta IP. Rotando IP...")
                logging.info("API bloqueada en _init_uc. Rotando IP")
                self._rotate_ip()
                time.sleep(5)
                try:
                    self.driver.quit()
                except Exception:
                    pass
                if not self._open_uc_browser():
                    logging.error("No se pudo reabrir navegador tras rotar proxy")
                    return
                self._delete_cookies()
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
            if attempt < 2:
                print(f"  Reintentando ({attempt+1}/3)...")
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
        print("  ERROR: No se pudo acceder a DOB Now tras 3 intentos.")
        print("  Posiblemente el proxy no funciona. Intenta cambiar de IP.")

    def _init_firefox(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.firefox.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto("https://a810-dobnow.nyc.gov/Publish/", wait_until="load")
        print("Logueate en DOB Now en Firefox (tienes 120s)...")
        self.wait_for_angular(timeout=120)

    def _init_chrome_cdp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.port}"
        )
        self.context = self.browser.contexts[0]
        self.page = next(
            p for p in self.context.pages
            if "dobnow" in p.url.lower()
        )

    def wait_for_angular(self, timeout=20):
        started = time.time()
        while time.time() - started < timeout:
            try:
                if self.driver:
                    ok = self.driver.execute_script("""
                        return typeof angular !== 'undefined' &&
                            angular.element(document.body).injector() !== undefined
                    """)
                else:
                    ok = self.page.evaluate("""
                        typeof angular !== 'undefined' &&
                        angular.element(document.body).injector() !== undefined
                    """)
                if ok:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _cookie_path(self):
        if self.browser_type == "uc":
            return "cookies_uc.json"
        suffix = self.browser_type if self.browser_type != "chrome" else f"p{self.port}"
        return f"cookies_{suffix}.json"

    def _delete_cookies(self):
        path = self._cookie_path()
        if os.path.exists(path):
            os.remove(path)
        try:
            if self.driver:
                self.driver.delete_all_cookies()
        except Exception:
            pass

    def save_cookies(self, path=None):
        if path is None:
            path = self._cookie_path()
        if self.driver:
            cookies = self.driver.get_cookies()
        else:
            cookies = self.context.cookies()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, default=str)

    def load_cookies(self, path=None):
        if path is None:
            path = self._cookie_path()
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as f:
            cookies = json.load(f)
        if self.driver:
            for c in cookies:
                try:
                    self.driver.add_cookie(c)
                except Exception as e:
                    name = c.get("name", "?")
                    logging.debug(f"Cookie no se pudo inyectar: {name} ({e})")
        else:
            self.context.add_cookies(cookies)
        return True

    def _find_chrome_pid(self):
        if self.is_linux:
            result = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{self.port}" in line and "LISTEN" in line:
                    import re
                    m = re.search(r'pid=(\d+)', line)
                    if m:
                        return m.group(1)
            return None
        else:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{self.port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        return parts[-1]
            return None

    def restart_session(self):
        if self.browser_type == "uc":
            try:
                self.driver.quit()
            except Exception:
                pass
            time.sleep(2)
            if not self._open_uc_browser():
                logging.warning("No se pudo abrir browser. Rotando IP")
                print("  No se pudo abrir nuevo browser. Rotando IP...")
                self._rotate_ip()
                time.sleep(5)
                self._delete_cookies()
                if not self._open_uc_browser():
                    msg = "No se pudo establecer sesion. Probablemente IP bloqueado."
                    print(f"  ERROR: {msg}")
                    logging.error(msg)
                    return
                self._delete_cookies()
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
            if self.load_cookies():
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
                if self._page_is_blocked():
                    print("  Cookies envenenadas. Usando sesion fresca...")
                    self._delete_cookies()
            if self.wait_for_angular(timeout=60):
                time.sleep(3)
                self._warm_up()
                if self._verify_proxy():
                    print("  Sesion verificada. Continuando...")
                    logging.info("Sesion verificada tras restart")
                    return
                print("  API bloqueada. Rotando IP...")
                logging.info("API bloqueada en restart_session. Rotando IP")
                self._rotate_ip()
                time.sleep(5)
                try:
                    self.driver.quit()
                except Exception:
                    pass
                if not self._open_uc_browser():
                    logging.error("No se pudo reabrir navegador tras rotar proxy")
                    return
                self._delete_cookies()
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(3)
            self.wait_for_angular(timeout=60)
        elif self.proxy:
            if self.playwright:
                self.playwright.stop()
            self._init_chrome_proxy()
        else:
            self.restart_chrome()

    def restart_chrome(self):
        if self.playwright:
            self.playwright.stop()

        pid = self._find_chrome_pid()
        if pid:
            if self.is_linux:
                subprocess.run(["kill", pid], capture_output=True)
            else:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True)
            time.sleep(3)

        os.makedirs(self.profile_dir, exist_ok=True)

        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
        ]
        subprocess.Popen(cmd)

        for _ in range(60):
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version",
                                       timeout=2)
                break
            except Exception:
                pass
            time.sleep(1)

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.port}"
        )
        self.context = self.browser.contexts[0]

        pages = [p for p in self.context.pages if "dobnow" in p.url.lower()]
        if pages:
            self.page = pages[0]
        else:
            pages = [p for p in self.context.pages if p.url != "about:blank"]
            if pages:
                self.page = pages[0]
            else:
                self.page = self.context.new_page()

        self.page.goto("https://a810-dobnow.nyc.gov/Publish/",
                        wait_until="load")
        time.sleep(3)

        if self.load_cookies():
            self.page.goto("https://a810-dobnow.nyc.gov/Publish/",
                            wait_until="load")
            time.sleep(3)
            if self.wait_for_angular(timeout=30):
                print("  Sesion restaurada con cookies.")
            else:
                print("  Cookies cargadas pero Angular no disponible. Logueate?")
                self.wait_for_angular(timeout=90)
        else:
            print("  No hay cookies guardadas. Logueate en DOB Now (tienes 120s)...")
            self.wait_for_angular(timeout=120)

    def refresh_page(self):
        if self.driver:
            for attempt in range(3):
                try:
                    self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                    time.sleep(5)
                    if self._page_is_blocked():
                        print("  Acceso denegado al refrescar.")
                        return False
                    if self.wait_for_angular(timeout=15):
                        return True
                    print(f"  Angular no disponible, recargando ({attempt+1}/3)...")
                except Exception:
                    print(f"  Error refrescando pagina ({attempt+1}/3)...")
                    time.sleep(3)
            return False
        else:
            self.page.goto(
                "https://a810-dobnow.nyc.gov/Publish/",
                wait_until="load"
            )
            time.sleep(3)
            self.wait_for_angular(timeout=20)
            return True

    def refresh_session(self):
        if self.driver:
            try:
                self.driver.get("https://a810-dobnow.nyc.gov/Publish/")
                time.sleep(5)
                return self.wait_for_angular(timeout=30)
            except Exception:
                return False
        else:
            try:
                self.page.goto(
                    "https://a810-dobnow.nyc.gov/Publish/",
                    wait_until="load"
                )
                time.sleep(3)
                return self.wait_for_angular(timeout=30)
            except Exception:
                return False

    def is_logged_in(self):
        try:
            if self.driver:
                cookies = self.driver.get_cookies()
            else:
                cookies = self.context.cookies()
            for c in cookies:
                name = c.get("name", "")
                if ".ASPXAUTH" in name or "FedAuth" in name:
                    return True
        except Exception:
            pass
        return False

    def _rotate_proxy_ip(self):
        if not self.proxy_api_key:
            return False
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://proxy.webshare.io/api/v2/proxy/replacement/rotate/",
                method="POST",
                headers={"Authorization": f"Token {self.proxy_api_key}"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            logging.info(f"Proxy IP rotado via API: {result}")
            print("  IP del proxy rotado via Webshare API.")
            return True
        except Exception as e:
            logging.warning(f"Rotacion via API fallo (fallback a relay): {e}")
            return False

    def _rotate_proxy_relay(self):
        if self._rotate_proxy_ip():
            return True
        if not self._relay or not self.proxy:
            msg = "No hay relay activo o proxy configurado."
            print(f"  {msg}")
            logging.warning(msg)
            return False
        msg = "Rotando proxy via nuevo relay (nueva conexion TCP)..."
        print(f"  {msg}")
        logging.info(msg)
        try:
            self._relay.stop()
            time.sleep(3)
        except Exception:
            pass
        h, p, u, pw = self.proxy
        self._relay = ProxyRelay(h, p, u, pw)
        relay_port = self._relay.start()
        self._proxy_selenium = f"http://127.0.0.1:{relay_port}"
        logging.info(f"Nuevo relay en puerto {relay_port}")
        print(f"  Nuevo relay en puerto {relay_port} (IP fresco del proxy)")
        return True

    def _rotate_ip(self):
        self._delete_cookies()
        if self._rotate_proxy_relay():
            return True
        if self.vpn:
            print("  Rotando VPN...")
            logging.info("Rotando VPN")
            self.vpn.rotate()
            time.sleep(15)
            return True
        return False

    def _verify_proxy(self):
        _PROBE_BINS = [
            "4624658", "3331440", "1037605", "2012957", "2063767",
            "3060844", "2130975", "4112476", "3002558", "3201080",
        ]
        probe_bin = random.choice(_PROBE_BINS)
        try:
            if self.driver:
                result = self.driver.execute_async_script("""
                    var done = arguments[arguments.length - 1];
                    var probeBin = arguments[0];
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = interceptor.request({method:"POST", url:"/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", headers:{}});
                    fetch("https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", {
                        method:"POST",
                        headers:{"Content-Type":"application/json", "X-Requested-With":"XMLHttpRequest", ...req.headers},
                        body:JSON.stringify({"BIN": probeBin, "SearchBy":"2", "StreetName":""})
                    }).then(function(r) { done({status: r.status}); })
                    .catch(function(err) { done({status: 0, error: err.message}); });
                """, probe_bin)
            else:
                result = self.page.evaluate("""
                    async (probeBin) => {
                        var injector = angular.element(document.body).injector();
                        var interceptor = injector.get("AuthTokenInterceptor");
                        var req = interceptor.request({method:"POST", url:"/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", headers:{}});
                        try {
                            const r = await fetch("https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay", {
                                method:"POST",
                                headers:{"Content-Type":"application/json", "X-Requested-With":"XMLHttpRequest", ...req.headers},
                                body:JSON.stringify({"BIN": probeBin, "SearchBy":"2", "StreetName":""})
                            });
                            return {status: r.status};
                        } catch(err) { return {status: 0, error: err.message}; }
                    }
                """, probe_bin)
            return isinstance(result, dict) and result.get("status") == 200
        except Exception:
            return False

    def human_scroll(self):
        if self.driver:
            for _ in range(random.randint(1, 2)):
                delta_y = random.randint(100, 500)
                try:
                    self.driver.execute_script(f"window.scrollBy(0, {delta_y})")
                except Exception:
                    pass
                time.sleep(random.uniform(0.3, 1.0))
        else:
            for _ in range(random.randint(1, 2)):
                delta_y = random.randint(100, 500)
                try:
                    self.page.evaluate(f"window.scrollBy(0, {delta_y})")
                except Exception:
                    pass
                time.sleep(random.uniform(0.3, 1.0))

    def _human_mouse(self):
        if not self.driver:
            return
        try:
            w = self.driver.execute_script("return window.innerWidth")
            h = self.driver.execute_script("return window.innerHeight")
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, w - 100)
                y = random.randint(100, h - 100)
                self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": x, "y": y, "button": "none"
                })
                time.sleep(random.uniform(0.3, 0.8))
            for _ in range(random.randint(1, 3)):
                dy = random.randint(-300, -50)
                self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                    "type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy
                })
                time.sleep(random.uniform(0.5, 1.5))
        except Exception:
            pass

    def _warm_up(self):
        if not self.driver:
            return
        print("  Calentando sesion...")
        logging.info("Warm-up: simulando navegacion post-rotacion")
        t0 = time.time()
        duration = random.uniform(15, 30)
        self._human_mouse()
        while time.time() - t0 < duration:
            try:
                scroll_y = random.randint(100, 500)
                self.driver.execute_script(f"window.scrollBy(0, {scroll_y})")
                time.sleep(random.uniform(2, 5))
                self._human_mouse()
            except Exception:
                break
        print("  Sesion caliente.")

    def _api_delay(self):
        r = random.random()
        if r < 0.6:
            time.sleep(random.uniform(2, 5))
        elif r < 0.9:
            time.sleep(random.uniform(5, 12))
        else:
            time.sleep(random.uniform(15, 25))

    def _uc_exec(self, script, *args):
        try:
            return self.driver.execute_async_script(script, *args)
        except Exception as e:
            emsg = str(e).lower()
            if "no such window" in emsg or "target window already closed" in emsg:
                return {"status": -1, "body": "WINDOW_CLOSED"}
            if "script timeout" in emsg:
                return {"status": -1, "body": "SCRIPT_TIMEOUT"}
            raise

    def browser_fetch(self, url, body):
        self._api_delay()
        self.human_scroll()
        if self.driver:
            return self._uc_exec("""
                var done = arguments[arguments.length - 1];
                var url = arguments[0];
                var body = arguments[1];
                try {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method: "POST", url: url, headers: {}};
                    req = interceptor.request(req);
                    fetch(url, {
                        method: "POST",
                        headers: {"Content-Type": "application/json", "X-Requested-With":"XMLHttpRequest", ...req.headers},
                        body: JSON.stringify(body)
                    })
                    .then(function(r) {
                        return r.text().then(function(t) {
                            done({status: r.status, body: t});
                        });
                    })
                    .catch(function(err) {
                        done({status: 0, body: err.message});
                    });
                } catch(err) {
                    done({status: 0, body: err.message});
                }
            """, url, body)
        else:
            return self.page.evaluate("""
    async ({url, body}) => {

        var injector = angular.element(document.body).injector();
        var interceptor = injector.get("AuthTokenInterceptor");

        var req = {
            method: "POST",
            url: url,
            headers: {}
        };

        req = interceptor.request(req);

        const response = await fetch(url,{
            method:"POST",
            headers:{
                "Content-Type":"application/json",
                "X-Requested-With":"XMLHttpRequest",
                ...req.headers
            },
            body:JSON.stringify(body)
        });

        return {
            status:response.status,
            body:await response.text()
        };

    }
    """, {"url": url, "body": body})

    def browser_get(self, url):
        self._api_delay()
        self.human_scroll()
        if self.driver:
            return self._uc_exec("""
                var done = arguments[arguments.length - 1];
                var url = arguments[0];
                try {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method: "GET", url: url, headers: {}};
                    req = interceptor.request(req);
                    fetch(url, {
                        method: "GET",
                        headers: {"X-Requested-With":"XMLHttpRequest", ...req.headers}
                    })
                    .then(function(r) {
                        return r.text().then(function(t) {
                            done({status: r.status, body: t});
                        });
                    })
                    .catch(function(err) {
                        done({status: 0, body: err.message});
                    });
                } catch(err) {
                    done({status: 0, body: err.message});
                }
            """, url)
        else:
            return self.page.evaluate("""
    async ({url}) => {

        var injector = angular.element(document.body).injector();
        var interceptor = injector.get("AuthTokenInterceptor");

        var req = {
            method: "GET",
            url: url,
            headers: {}
        };

        req = interceptor.request(req);

        const response = await fetch(url,{
            method:"GET",
            headers:{
                "X-Requested-With":"XMLHttpRequest",
                ...req.headers
            }
        });

        return {
            status:response.status,
            body:await response.text()
        };

    }
    """, {"url": url})

    def browser_download(self, url):
        time.sleep(random.uniform(3, 8))
        self.human_scroll()
        if self.driver:
            return self._uc_exec("""
                var done = arguments[arguments.length - 1];
                var url = arguments[0];
                try {
                    var injector = angular.element(document.body).injector();
                    var interceptor = injector.get("AuthTokenInterceptor");
                    var req = {method: "GET", url: url, headers: {}};
                    req = interceptor.request(req);
                    fetch(url, {
                        method: "GET",
                        headers: {...req.headers}
                    })
                    .then(function(r) {
                        return Promise.all([r.status, r.blob()]);
                    })
                    .then(function(data) {
                        var status = data[0];
                        var blob = data[1];
                        var reader = new FileReader();
                        reader.onloadend = function() {
                            done({
                                status: status,
                                size: blob.size,
                                type: blob.type,
                                base64: reader.result
                            });
                        };
                        reader.readAsDataURL(blob);
                    })
                    .catch(function(err) {
                        done({status: 0, size: 0, type: "", base64: "", error: err.message});
                    });
                } catch(err) {
                    done({status: 0, size: 0, type: "", base64: "", error: err.message});
                }
            """, url)
        else:
            return self.page.evaluate("""
    async ({url}) => {

        var injector = angular.element(document.body).injector();
        var interceptor = injector.get("AuthTokenInterceptor");

        var req = {
            method: "GET",
            url: url,
            headers: {}
        };

        req = interceptor.request(req);

        const response = await fetch(url,{
            method:"GET",
            headers:{
                ...req.headers
            }
        });

        const blob = await response.blob();

        const base64 = await new Promise(resolve=>{
            const reader = new FileReader();
            reader.onloadend = ()=>resolve(reader.result);
            reader.readAsDataURL(blob);
        });

        return {
            status: response.status,
            size: blob.size,
            type: blob.type,
            base64: base64
        };

    }
    """, {"url": url})

    def close(self):
        if self.driver:
            self.driver.quit()
        else:
            if self.playwright:
                self.playwright.stop()
        if self._relay:
            self._relay.stop()
