import logging
import subprocess
import time


US_CITIES = [
    "New York", "Ashburn", "Atlanta", "Boston", "Charlotte",
    "Chicago", "Columbus", "Dallas", "Denver", "Detroit",
    "Houston", "Los Angeles", "McAllen", "Memphis", "Miami",
    "Philadelphia", "Phoenix", "Salt Lake City", "San Jose",
    "Seattle", "Secaucus", "Washington",
]


class ProtonVPN:

    def __init__(self):
        self._last_rotate = 0
        self.min_interval = 30
        self._city_index = 0

    def _next_city(self):
        city = US_CITIES[self._city_index % len(US_CITIES)]
        self._city_index += 1
        self._city_index %= len(US_CITIES)
        return city

    def disconnect(self):
        r = subprocess.run(
            ["protonvpn", "disconnect"],
            capture_output=True, text=True, timeout=30
        )
        time.sleep(3)
        return r.returncode == 0

    def connect(self, country="US", city=None):
        cmd = ["protonvpn", "connect", "--country", country]
        if city:
            cmd.extend(["--city", city])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        time.sleep(5)
        return r.returncode == 0

    def rotate(self):
        now = time.time()
        if now - self._last_rotate < self.min_interval:
            wait = self.min_interval - (now - self._last_rotate)
            time.sleep(wait)
        city = self._next_city()
        logging.info(f"VPN: rotando IP ({city})...")
        self.disconnect()
        time.sleep(2)
        ok = self.connect(country="US", city=city)
        self._last_rotate = time.time()
        return ok

    def status(self):
        r = subprocess.run(
            ["protonvpn", "status"],
            capture_output=True, text=True, timeout=10
        )
        return "Connected" in r.stdout or "connected" in r.stdout.lower()
