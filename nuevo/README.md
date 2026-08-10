# Scraper DOB NOW — Modo agrupado

Variante que hace **1 sola API call `getPublicPortalBuildDisplay` por BIN** y procesa todos los Job Filings asociados, en vez de 1 call por cada combinación BIN+Job.

## 1. Preparar el CSV agrupado

```bash
cd nuevo/
python formato.py
```

Esto lee `../input.csv`, agrupa por BIN, y genera `input_agrupado.csv` con formato:

```csv
Bin,House No,Street Name,Borough,Job Filing Number,Block,LOT
4624658,123,Main St,Manhattan,Q00848877-I1|B00738255-P1|X01110102-I1,01234,0056
3331440,456,Oak Ave,Bronx,B01020304-P3,09999,0001
```

- **1 fila por BIN**
- `Job Filing Number`: pipe-separated (`|`) si hay varios
- Duplicados de Job Filing automáticamente eliminados (con warning)
- Conflictos en otras columnas usan el primer valor (con warning)

---

## 2. Ejecutar el scraper

**No necesitas abrir Chrome manualmente.** El script lanza su propio navegador con anti-fingerprinting.

```bash
# Procesar todos los BINs
python patchright_hybrid.py --max-rows 0

# Probar con 10 BINs
python patchright_hybrid.py --fresh --max-rows 10

# Retomar desde donde quedo
python patchright_hybrid.py --max-rows 500
```

### Parámetros

| Parametro | Default | Descripcion |
|-----------|---------|-------------|
| `--input` | `input_agrupado.csv` | CSV agrupado |
| `--output` | `resultado_hibrido.csv` | CSV de salida |
| `--max-rows N` | `0` (todos) | Max BINs a procesar |
| `--start-index N` | checkpoint | Indice de inicio |
| `--fresh` | false | Ignorar checkpoint y cache |
| `--pause-min S` | `2.0` | Pausa minima entre API calls |
| `--pause-max S` | `6.0` | Pausa maxima |
| `--refresh-auth-every N` | `15` | Renovar auth cada N API calls |

---

---

## Diferencia con conservative_scraper.py

| | conservative_scraper.py | patchright_hybrid.py (nuevo/) |
|---|---|---|
| Chrome | **Manual**: abrir Chrome en puerto 9222 (`--remote-debugging-port=9222`) | **Automatico**: el script lanza su propio Chrome |
| CDP | Requiere `--cdp-port 9222` | No usa CDP, no necesita flags |
| Auth | Todas las requests via browser | curl_cffi (solo auth via browser) |
| input.csv | 1 fila por combinación BIN+Job | 1 fila por BIN (Job Filing pipe-separated) |

---

## 3. Loop automatico (con VPN)

```bash
# Desde la raiz del proyecto
python run_loop.py --scraper hybrid --vpn --vpn-rotate-every 10 --max-rows 500 --pause-min 3 --pause-max 8
```

**IMPORTANTE:** `run_loop.py` ejecuta el scraper de la **raiz** por defecto. Para usar el de `nuevo/`, ejecuta directamente:

```bash
# Loop manual con el agrupado
cd nuevo/
while true; do
    python patchright_hybrid.py --max-rows 200
    code=$?
    if [ $code -eq 0 ]; then
        echo "Completado. Break."
        break
    fi
    echo "Codigo $code. Rotando VPN..."
    protonvpn-cli c -r
    sleep 15
done
```

---

## 4. Paralelismo

Con `--start-index` y `--max-rows` puedes partir el CSV en rangos:

```bash
# Instancia 1: BINs 0-9999
python patchright_hybrid.py --output r1.csv --start-index 0 --max-rows 10000

# Instancia 2: BINs 10000-19999
python patchright_hybrid.py --output r2.csv --start-index 10000 --max-rows 10000

# Instancia 3: BINs 20000-29999
python patchright_hybrid.py --output r3.csv --start-index 20000 --max-rows 10000
```

**Cada instancia necesita su propia IP** (VPN conectada a distinta ciudad US).

---

## Estimacion de rendimiento

| | Antes (no agrupado) | Despues (agrupado) |
|---|---|---|
| API calls `search_bin` | 240,594 | **89,741** (-62%) |
| Exposicion a Akamai | 240k llamadas | 89k llamadas |
| BINs/dia (3x paralelo, 2-6s pause) | ~120-150 | **~240-300** |
| Dias estimados | ~160-200 | **~90-120** |

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `formato.py` | Script para generar el CSV agrupado |
| `patchright_hybrid.py` | Scraper agrupado |
| `input_agrupado.csv` | CSV de entrada (generado por formato.py) |
| `resultado_hibrido.csv` | Resultados |
| `checkpoint_hybrid.json` | Progreso |
| `cache_hibrido.json` | Cache de respuestas API |
