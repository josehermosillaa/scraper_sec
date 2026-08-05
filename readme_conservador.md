# Scraper Conservador DOB NOW

Scraper conservador para extraer documentos de zonificacion (ZD1, ZD2, ZD1A, ZRD) del portal DOB NOW, con cache, checkpoint y recuperacion automatica ante bloqueos.

## Archivos Generados

| Archivo | Proposito |
|---|---|
| `resultado_conservador.csv` | Salida con los datos extraidos |
| `cache_conservador.json` | Respuestas cacheadas para no repetir consultas identicas |
| `checkpoint_conservador.json` | Punto de reanudacion + contador de reintentos |
| `conservative_scraper.log` | Log de ejecucion (timestamp + nivel + mensaje) |

## Columnas de Entrada

El `input.csv` debe tener al menos:

```text
Job Filing Number
Bin
Borough
Street Name
Block
LOT
```

Las columnas `Block` y `LOT` se copian tal cual del CSV de entrada a todas las filas de salida (aunque el BIN este bloqueado o no se encuentre).

## Instalacion

**Windows:**

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m patchright install chrome
```

**Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m patchright install chrome
```

Debes tener Google Chrome instalado (no Chromium). En Ubuntu/Debian:

```bash
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list'
sudo apt update && sudo apt install google-chrome-stable
```

## Uso

### Modo CDP (recomendado)

Usa tu Chrome real, conectado via puerto de depuracion.

1. Conecta VPN a EE.UU.
2. Cierra todas las ventanas de Chrome.
3. Lanza Chrome con el flag CDP:

**Windows:**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:TEMP\chrome_cdp_profile"
```

**Linux:**
```bash
google-chrome-stable --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_cdp_profile &
```

4. Abre `https://a810-dobnow.nyc.gov/Publish/`, navega, haz login si es necesario.
5. Verifica que `_abck` tiene score=0 en DevTools -> Application -> Cookies.
6. Sin cerrar Chrome, ejecuta el script:

**Windows:**
```powershell
python conservative_scraper.py --cdp-port 9222 --max-rows 5 --pause-min 20 --pause-max 45
```

**Linux:**
```bash
python3 conservative_scraper.py --cdp-port 9222 --max-rows 5 --pause-min 20 --pause-max 45
```

7. Si se bloquea, el script se desconecta pero tu Chrome sigue abierto.
8. Cambia VPN, recarga DOB NOW en la misma ventana, y repite desde el paso 6.

### Modo normal (lanzar navegador automatico)

**Windows:**
```powershell
python conservative_scraper.py --max-rows 10 --pause-min 10 --pause-max 25
```

**Linux:**
```bash
python3 conservative_scraper.py --max-rows 10 --pause-min 10 --pause-max 25
```

Usa Patchright para abrir Chrome con anti-fingerprinting y warm-up automatico.

## Pausas

`--pause-min` y `--pause-max` controlan el tiempo de espera (en segundos) antes de cada request NO cacheado. Es un valor aleatorio entre ambos.

Las respuestas ya cacheadas no requieren pausa.

```powershell
# Conservador
python conservative_scraper.py --max-rows 5 --pause-min 20 --pause-max 45

# Normal
python conservative_scraper.py --max-rows 10 --pause-min 10 --pause-max 25
```

## Cache y Checkpoint

| Concepto | Explicacion |
|---|---|
| **hits** | Consultas servidas desde cache. Sin pausa, sin llamada al endpoint |
| **misses** | Consultas nuevas que requirieron llamada real al endpoint + pausa |
| **checkpoint** | Guarda `next_index` y `retry_count`. Permite reanudar sin reprocesar |

Cada ejecucion muestra `hits=X misses=Y` al final y por cada BIN procesado.

## Reintentos Automaticos

Si un BIN devuelve `AKAMAI_BLOCKED` o `SESSION_UNHEALTHY`:

1. **Fase 1**: 3 recargas de pagina (F5) con pausa 5s/10s/15s.
2. **Fase 2** (si F5 no funciona): cierra Chrome, lo relanza con `--remote-debugging-port` + `--user-data-dir`, reconecta CDP, verifica `_abck`.
3. Si se recupera, reintenta la consulta y continua.
4. Si no se recupera:
   - `retry_count < 3` -> guarda checkpoint **sin avanzar** para reintentar en la siguiente ejecucion (tras cambiar VPN).
   - `retry_count = 3` -> avanza checkpoint, marca `BLOCKED_PERMANENT` en el CSV.

Flujo del usuario:

```powershell
# Ejecucion 1: BIN 3 bloqueado -> stop
python conservative_scraper.py --cdp-port 9222 --max-rows 5

# Cambiar VPN manualmente

# Ejecucion 2: BIN 3 se reintenta automaticamente
python conservative_scraper.py --cdp-port 9222 --max-rows 5
```

## Reanudacion

Ejecuta el mismo comando. El script lee `checkpoint_conservador.json` y continua desde donde se detuvo:

```powershell
python conservative_scraper.py --cdp-port 9222 --max-rows 5 --pause-min 20 --pause-max 45
```

Usa `--fresh` solo para empezar desde cero (ignora checkpoint, reescribe CSV de salida).

## Ejecucion Automatica (run_loop.py)

`run_loop.py` ejecuta `conservative_scraper.py` en bucle cada 5 minutos, automaticamente.

**Windows:**
```powershell
python run_loop.py --cdp-port 9222 --max-rows 5 --pause-min 20 --pause-max 45
```

**Linux:**
```bash
python3 run_loop.py --cdp-port 9222 --max-rows 5 --pause-min 20 --pause-max 45
```

**Parametros de run_loop.py:**

```text
--interval N      Segundos entre ejecuciones (default: 300 = 5 min)
--max-failures N  Fallos consecutivos antes de detener (default: 20)
--vpn             Rotar ProtonVPN automaticamente ante Access Denied
--profile DIR     user-data-dir de Chrome para CDP (default: TEMP/chrome_cdp_profile)
```

Todos los demas argumentos se pasan directamente a `conservative_scraper.py`.

**Comportamiento:**

| Codigo salida | Significado | run_loop.py sin --vpn | run_loop.py con --vpn |
|---|---|---|---|
| 0 | OK | Esperar, re-ejecutar | Esperar, re-ejecutar |
| 2 | Access Denied en pagina | Avisar, esperar, reintentar | Rotar ProtonVPN, reiniciar Chrome CDP, verificar pagina limpia, re-ejecutar |
| 3 | Sesion/API bloqueada | Avisar, esperar, reintentar | Avisar, esperar, reintentar |

**Con VPN automatica:**

**Windows:**
```powershell
python run_loop.py --cdp-port 9222 --vpn --max-rows 5 --pause-min 20 --pause-max 45
```

**Linux:**
```bash
python3 run_loop.py --cdp-port 9222 --vpn --max-rows 5 --pause-min 20 --pause-max 45
```

Requiere ProtonVPN CLI instalado (`protonvpn` en PATH). Cuando el scraper detecta Access Denied en la pagina (codigo 2), `run_loop.py`:

1. Rota ProtonVPN a la siguiente ciudad de EE.UU.
2. Espera 15s.
3. Mata Chrome, lo relanza con CDP + perfil.
4. Verifica que la pagina carga sin Access Denied.
5. Verifica `_abck` limpio.
6. Re-ejecuta `conservative_scraper.py`.

El usuario no interviene. Si tras cambiar VPN la pagina sigue bloqueada, se acumula en `consecutive_failures` como cualquier otro fallo.

**Salida tipica:**

```text
[loop #1] Ejecutando conservative_scraper.py...
          2026-08-05 14:00:00
...
[loop #1] Script termino con codigo 0.
[loop] Proxima ejecucion en 300s (14:05:00)

[loop #2] Ejecutando conservative_scraper.py...
          2026-08-05 14:05:00
```

5 minutos son suficientes para cambiar de ciudad VPN entre ejecuciones si hay bloqueo.

## Log

El archivo `conservative_scraper.log` registra:

```text
2026-08-05 12:00:00 [INFO] START | cdp=True max_rows=5 pause=20.0-45.0s
2026-08-05 12:00:01 [INFO] BIN 4624658 | Q00848877-I1 START
2026-08-05 12:00:45 [INFO] BIN 4624658: 2 docs ZD | hits=0 misses=4 | 44.2s
2026-08-05 12:01:30 [WARNING] SESSION_UNHEALTHY on search_bin BIN=3331440
2026-08-05 12:01:30 [WARNING] Session recovery attempt 1/3 (wait=5s)
2026-08-05 12:01:40 [INFO] Session recovered after 1 attempts: abck score=0
2026-08-05 12:02:30 [ERROR] blocked: AKAMAI_BLOCKED — reintenta tras cambiar VPN
2026-08-05 12:02:30 [INFO] DONE | processed=2 total_zd=2 hits=0 misses=8 stop_reason=blocked:...
```

## Columnas de Salida

El CSV de salida incluye las mismas columnas que los otros scrapers del proyecto. Ademas:

- `Block` y `LOT` se copian del `input.csv` en todas las filas.
- `result_status` puede ser: `OK`, `FILTERED`, `NO DOCUMENTS`, `JOB_NOT_FOUND`, `MISSING DATA`, `AKAMAI_BLOCKED`, `BLOCKED_PERMANENT`.
- `zoning_status` puede ser: `HAS ZONING DOCUMENTS`, `NO ZONING DOCUMENTS`, `BLOCKED`.

## Parametros

```text
--input        CSV de entrada. Default: input.csv
--output       CSV de salida. Default: resultado_conservador.csv
--max-rows     Maximo de filas por ejecucion. Default: 25
--pause-min    Pausa minima entre requests no cacheados (segundos). Default: 8.0
--pause-max    Pausa maxima entre requests no cacheados (segundos). Default: 20.0
--headless     Ejecuta Chrome sin ventana visible
--fresh        Ignora checkpoint previo y reescribe el CSV de salida
--new-profile  Usa un perfil temporal nuevo de Chrome (solo modo normal)
--cdp-port     Conecta a Chrome existente via CDP (ej: --cdp-port 9222)
--chrome-profile  user-data-dir del Chrome abierto con --cdp-port (para recovery)
```

## Endpoints

Todas las consultas se hacen via `fetch()` desde el navegador:

```text
POST /Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay
GET  /Publish/WrapperServicePP/WrapperService.svc/GetJobFilingPW1/{guid}
POST /Publish/WrapperServicePP/WrapperService.svc/GetPartialJobFilingServiceZD1WD
POST /Publish/WrapperPP/PublicPortal.svc/GetPublicPortalPartialJobFiling
POST /Publish/WrapperServicePP/WrapperService.svc/downloadFromDocumentum
```
