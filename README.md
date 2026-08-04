# DOB Now Scraper

Scraper híbrido para extraer documentos de zonificación (ZD1, ZD2, ZD1A, ZRD) del portal público de NYC Department of Buildings (`a810-dobnow.nyc.gov`), protegido por **Akamai Bot Manager**.

## Requisitos

```bash
pip install -r requirements.txt
```

Dependencias: `curl_cffi`, `seleniumbase`, `patchright`

Opcional: **ProtonVPN CLI** para rotación automática de IP.

## Flujo de trabajo

Hay dos modos de operación:

### A) Modo directo (HTTP con auth extraída del navegador)

```bash
# 1. Abrir navegador y extraer tokens de autenticación
python extract_auth.py

# (Loguéate manualmente si es necesario, luego NO cierres el navegador)

# 2. Probar que la auth funciona
python test_direct.py

# 3. Pipeline completo (5 BINs hardcodeados) -> resultado_directo.csv
python test_full.py
```

### B) Modo híbrido (producción) — Patchright + curl_cffi

```bash
# Lee input.csv, abre Chrome real, extrae auth, dispara HTTP
python patchright_hybrid.py

# Output: resultado_hibrido.csv
# Checkpoint: checkpoint_hybrid.json
```

El CSV de entrada (`input.csv`) debe tener columnas: `Job Filing Number`, `Bin`, `Borough`, `Street Name`.

### Benchmark

```bash
# Compara velocidad browser vs HTTP directo
python test_compare.py
```

## Endpoints atacados

Todos los endpoints pertenecen a `https://a810-dobnow.nyc.gov`:

### PublicPortal.svc

| Método | Endpoint | Body | Respuesta |
|--------|----------|------|-----------|
| `POST` | `/Publish/WrapperPP/PublicPortal.svc/getPublicPortalBuildDisplay` | `{"BIN":"...","SearchBy":"2","StreetName":"..."}` | `ListBuildDetails[]` con GUID del job filing |
| `POST` | `/Publish/WrapperPP/PublicPortal.svc/GetPublicPortalPartialJobFiling` | `{"Applicant":null,"RelatedEntityLogicalName":"dobnyc_documentlist","JobFilingGUID":"...","FilingIncludes":"...","CurrentFilingStatusValue":"...","IsPlanApproved":false}` | `RequiredDocumentList[]` con documentos del job |

### WrapperService.svc

| Método | Endpoint | Body | Respuesta |
|--------|----------|------|-----------|
| `POST` | `/Publish/WrapperServicePP/WrapperService.svc/GetPartialJobFilingService` | `{"RelatedEntityLogicalName":"dobnyc_delegates","JobFilingGUID":"..."}` | Delegados del filing |
| `GET` | `/Publish/WrapperServicePP/WrapperService.svc/GetJobFilingPW1/{guid}` | — | `FilingIncludes`, `CurrentFilingStatusValue`, `IsPlanApproved` |
| `GET` | `/Publish/WrapperServicePP/WrapperService.svc/GetScopeOfWorkST/{guid}` | — | Scope of work |
| `POST` | `/Publish/WrapperServicePP/WrapperService.svc/GetPW1Configuration` | `{"WorkType":[{"WorkTypeName":"...","JobType":"..."}],"JobType":"..."}` | Configuración PW1 |
| `POST` | `/Publish/WrapperServicePP/WrapperService.svc/GetPartialJobFilingServiceZD1WD` | `{"RelatedEntityLogicalName":"dobnyc_documentlist","JobFilingGUID":"..."}` | `RequiredDocumentList[]` de documentos de zonificación |
| `POST` | `/Publish/WrapperServicePP/WrapperService.svc/downloadFromDocumentum` | `{"uploadedPath":"...","downloadPath":"\\\\PortalDownloadedDocuments\\{BOROUGH}\\TEST\\"}` | `downloadPath` (URL de descarga del documento) |

### Flujo de llamadas

```
input.csv (BIN + Job Filing Number)
  │
  ▼
getPublicPortalBuildDisplay  ──►  obtiene GUID del job
  │
  ├──► GetJobFilingPW1/{guid}  ──►  FilingIncludes, Status, IsPlanApproved
  │
  ├──► GetPartialJobFilingServiceZD1WD  ──►  documentos de zonificación
  │
  ├──► GetPublicPortalPartialJobFiling  ──►  todos los documentos
  │
  └──► downloadFromDocumentum  ──►  URL de descarga final
```

## Mecanismos anti-Akamai implementados

| Técnica | Implementación |
|---------|---------------|
| TLS fingerprint impersonation | `curl_cffi` impersonando Chrome 146 |
| Chrome Headers + Client Hints | `sec-ch-ua`, `sec-ch-ua-platform`, `sec-ch-ua-mobile` |
| WebDriver concealment | `navigator.webdriver = undefined`, `window.chrome.runtime = {}` |
| Akamai block detection | Búsqueda de `Access Denied` + `edgesuite` en HTML |
| IP rotation | ProtonVPN 22 ciudades US (c/ min 30s interval) |
| Human behavior (warm-up) | Scroll aleatorio, mouse simulado, delays random |
| API request timing | Delays: 60% 2-5s, 30% 5-12s, 10% 15-25s |
| Browser persistence | Chrome user data dir persistente (`/tmp/patchright_dobnow_profile`) |
| Token extraction | `AuthTokenInterceptor` extraído del inyector AngularJS en runtime |
| Retry con backoff | Exponential backoff (1s, 2s, 4s) para HTTP/2 INTERNAL_ERROR |
| Akamai recovery multi-tier | Reload → VPN rotate → nuevo browser → cooldown |

## Output CSV

Columnas en `resultado_hibrido.csv` / `resultado_directo.csv`:

`Job Filing Number`, `Filing Status`, `Filing Date`, `House No`, `Street Name`, `Borough`, `Block`, `LOT`, `Bin`, `Job Description`, `Filing Review Type`, `guid`, `filing_status`, `doc_description`, `doc_name`, `doc_url_original`, `download_url`, `result_status`, `error_body`, `zoning_status`, `doc_create_on`, `doc_category`, `doc_type_name`, `doc_status_label`
