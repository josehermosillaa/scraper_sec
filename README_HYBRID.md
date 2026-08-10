# patchright_hybrid.py — Scraper hibrido DOB NOW

## Que hace

Extrae auth (headers + cookies) desde un navegador Chrome real con anti-fingerprinting, y luego hace **todas las API calls via `curl_cffi`** (libreria HTTP que suplanta Chrome sin ejecutar JS). El navegador solo se usa para renovar el auth periodicamente y para recovery si Akamai bloquea.

### Ventajas sobre conservative_scraper.py
- **3-5x mas rapido** por BIN (~30-50s vs ~2-3 min)
- Menos exposicion a Akamai (el navegador esta idle el 90% del tiempo)
- Menor consumo de RAM (las API calls no pasan por el browser)

---

## Uso basico

```bash
# Procesar todos los BINs del CSV (usa checkpoint)
python patchright_hybrid.py --max-rows 50 --pause-min 2 --pause-max 6

# Empezar desde un indice especifico
python patchright_hybrid.py --max-rows 100 --start-index 50

# Ignorar checkpoint y cache, empezar fresco
python patchright_hybrid.py --fresh --max-rows 100

# Cambiar pausas (mas lentas = menos deteccion)
python patchright_hybrid.py --pause-min 5 --pause-max 12 --refresh-auth-every 10
```

### Parametros

| Parametro | Default | Descripcion |
|-----------|---------|-------------|
| `--input PATH` | `input.csv` | CSV de entrada con BINs |
| `--output PATH` | `resultado_hibrido.csv` | CSV de salida |
| `--max-rows N` | `0` (todos) | Max BINs a procesar |
| `--start-index N` | desde checkpoint | Indice de inicio |
| `--fresh` | false | Ignorar checkpoint y cache |
| `--pause-min S` | `2.0` | Pausa minima entre API calls |
| `--pause-max S` | `6.0` | Pausa maxima entre API calls |
| `--refresh-auth-every N` | `15` | Renovar auth del navegador cada N API calls |

---

## Uso con run_loop.py (autonomo)

```bash
# Con VPN — el scraper se auto-recupera y run_loop rota VPN
python run_loop.py --scraper hybrid --vpn --vpn-rotate-every 10 --vpn-rotate-on-failures 3 --max-rows 100

# Sin VPN — reintenta pero eventualmente la IP se quema
python run_loop.py --scraper hybrid --max-rows 100 --pause-min 5 --pause-max 12
```

### run_loop.py parametros para modo hybrid

| Parametro | Descripcion |
|-----------|-------------|
| `--scraper hybrid` | Usar patchright_hybrid.py (default: conservative) |
| `--vpn` | Activar rotacion ProtonVPN |
| `--vpn-rotate-every N` | Rotar VPN cada N iteraciones (proactivo) |
| `--vpn-rotate-on-failures N` | Rotar VPN tras N fallos consecutivos |
| `--max-failures N` | Fallos consecutivos antes de parar el loop |
| `--interval S` | Segundos entre ejecuciones del loop |

---

## Flujo del scraper

1. **Inicio**: Abre Chrome con anti-fingerprinting, navega a DOB NOW, verifica `_abck`
2. **Extraccion auth**: Obtiene headers del `AuthTokenInterceptor` de Angular + cookies de sesion
3. **Bucle principal**:
   - Cada `--refresh-auth-every` API calls: F5 refresh en el navegador + re-extrae auth
   - Por cada BIN: cache check → API call via curl_cffi → procesar documentos
   - Si API retorna AKAMAI_BLOCKED: recovery (F5 → VPN rotation → nuevo browser context)
   - 25% chance de pausa larga 30-90s entre BINs (simula lectura humana)
4. **Checkpoint**: Se guarda despues de cada BIN. Si el script muere, retoma donde quedo.

### Codigos de salida

| Codigo | Significado |
|--------|-------------|
| 0 | Completado OK |
| 1 | Error (CSV no existe, pausas invalidas) |
| 2 | Access Denied en pagina (IP bloqueada) |
| 3 | Sesion bloqueada (`_abck`=-1 o `StopForBlock`) |

---

## Paralelismo

Para acelerar con multiples instancias:

```bash
# Terminal 1 — BINs 0-9999
python patchright_hybrid.py --output resultado_p1.csv --start-index 0 --max-rows 10000

# Terminal 2 — BINs 10000-19999
python patchright_hybrid.py --output resultado_p2.csv --start-index 10000 --max-rows 10000

# Terminal 3 — BINs 20000-29999
python patchright_hybrid.py --output resultado_p3.csv --start-index 20000 --max-rows 10000
```

**IMPORTANTE para paralelismo**: Cada instancia necesita su propia IP (VPN distinta) y su propio perfil de Chrome. Para esto ejecuta cada terminal con una VPN conectada a una ciudad distinta de US.

---

## Probar

### Prueba basica (5 BINs, rapido)
```bash
python patchright_hybrid.py --fresh --max-rows 5 --pause-min 1 --pause-max 2
```

### Verificar que checkpoint funciona
```bash
# Primera ejecucion — procesa 5 BINs
python patchright_hybrid.py --fresh --max-rows 5

# Segunda ejecucion — deberia retomar en BIN #6
python patchright_hybrid.py --max-rows 5
```

### Verificar que cache funciona
```bash
# Primera ejecucion — cache miss para todos
python patchright_hybrid.py --fresh --max-rows 5

# Segunda ejecucion — todos deberian ser cache hit (mismas BINs)
python patchright_hybrid.py --fresh --max-rows 5 --start-index 0
```

### Verificar recovery (simular bloqueo)
```bash
# Ejecutar muchos BINs sin VPN para forzar bloqueo por Akamai
# Verificar que sale con codigo 3 y guarda checkpoint
python patchright_hybrid.py --max-rows 200 --pause-min 0.5 --pause-max 1
```

### Verificar integracion run_loop
```bash
# Modo loop con VPN — debe rotar IP y reintentar tras bloqueo
python run_loop.py --scraper hybrid --vpn --max-rows 50 --interval 60 --max-failures 3
```

---

## Archivos generados

| Archivo | Contenido |
|---------|-----------|
| `resultado_hibrido.csv` | Resultados (append si retoma) |
| `checkpoint_hybrid.json` | Progreso (`next_index`, `retry_count`) |
| `cache_hibrido.json` | Cache de respuestas API |

---

## Formato CSV de entrada (input.csv)

```csv
Bin,House No,Street Name,Borough,Job Filing Number,Block,LOT
4624658,123,Main St,Manhattan,Q00848877-I1,01234,0056
3331440,456,Oak Ave,Brooklyn,B00738255-P1,05678,0123
```

Columnas minimas requeridas: `Bin`, `Job Filing Number`
