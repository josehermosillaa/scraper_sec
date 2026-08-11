# Analisis: Servicio de descarga de PDFs desde Documentum via DOB Now

## 1. Contexto

- **Entrada:** URL DCTM REST (`http://bscan-broker.csc.nycnet:18080/dctm-rest/repositories/bscan_prod_rep/objects/0900303985c75fc6`)
- **Salida:** URL de descarga del PDF obtenida via `downloadFromDocumentum` (API de DOB Now)
- **Uso:** Click en boton de plataforma web → peticion HTTP al servicio → respuesta con URL de descarga en ~1-2 segundos
- **Autenticacion:** Sesion SSO de DOB Now en navegador Chrome real (AuthTokenInterceptor de Angular + cookies). Se requiere un perfil de Chrome con sesion activa.

## 2. Script base

`documentum_download.py` — archivo unico e independiente.

**Funcionamiento:**
1. Lanza Chrome via Patchright con perfil persistente + anti-fingerprinting JS
2. Navega a DOB Now y espera a que Angular este disponible
3. Extrae headers del `AuthTokenInterceptor` + cookies del contexto
4. Construye sesion `curl_cffi` autenticada
5. POST a `downloadFromDocumentum` con la URL DCTM REST como `uploadedPath`
6. Cierra navegador y devuelve la URL de descarga

**Dependencias:** `patchright`, `curl_cffi`

## 3. Opciones de despliegue en AWS

### Opcion A: Lightsail VPS / EC2 (navegador siempre vivo)

**Arquitectura:** VM con FastAPI + Chrome siempre abierto + refresh periodico de auth.

```
┌──────────────────────────────────────────┐
│  EC2 / Lightsail VPS (Linux)             │
│                                           │
│  Arranque del servicio:                   │
│    → Xvfb :99 (display virtual)           │
│    → google-chrome --display=:99          │
│    → launch_browser()                     │
│    → extract_auth()                       │
│    → build_http_session()  (curl_cffi)    │
│                                           │
│  Background task (cada 10-15 min):        │
│    → refresca auth con el mismo Chrome    │
│                                           │
│  POST /download-url   ← tu plataforma    │
│    → http_post(downloadFromDocumentum)    │
│    → {"download_url": "https://..."}      │
│                                           │
│  GET /health            ← monitoreo      │
└──────────────────────────────────────────┘
```

| Aspecto | Detalle |
|---|---|
| **Costo mensual** | $10-20 (Lightsail $10 plan o EC2 t3.small) |
| **Tiempo de setup** | ~30 minutos |
| **Latencia por request** | 1-2 segundos (HTTP directo, sin browser) |
| **Mantenimiento** | Gestion manual de la VM (parches, reinicios) |
| **Escalabilidad** | Limitada a la VM. Para escalar: auto-scaling group o mas instancias |
| **VPN** | Posible si se necesita rotar IP (ProtonVPN CLI en la VM) |
| **Riesgo Akamai** | Bajo — Chrome no-headless real, igual que en local |

**Setup minimo:**
```bash
# En la VM
sudo apt install google-chrome-stable xvfb
pip install fastapi uvicorn patchright curl_cffi
xvfb-run --auto-servernum uvicorn service:app --host 0.0.0.0 --port 80
```

### Opcion B: Lambda (lo mencionado por Jose)

**Arquitectura:** 2 Lambdas separadas + EFS + DynamoDB + API Gateway + EventBridge.

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│  EventBridge (cada 5-10 min)                           │
│       │                                                 │
│  ┌────▼───────────────────────────────────┐            │
│  │ Lambda Auth Refresher (container)      │            │
│  │ - Chrome + Xvfb + Patchright           │            │
│  │ - Monta EFS con perfil Chrome          │            │
│  │ - Extrae auth del Angular Interceptor  │            │
│  │ - Guarda tokens en DynamoDB            │            │
│  └────┬───────────────────────────────────┘            │
│       │                                                 │
│  ┌────▼───────────────────────────────────┐            │
│  │ DynamoDB                                │            │
│  │ { auth_headers, cookies, updated_at }   │            │
│  └────┬───────────────────────────────────┘            │
│       │                                                 │
│  ┌────▼───────────────────────────────────┐            │
│  │ API Gateway → Lambda Download Service  │            │
│  │ - Lee auth de DynamoDB                 │            │
│  │ - curl_cffi → downloadFromDocumentum   │            │
│  │ - Responde {"download_url": "..."}     │            │
│  │ - ~1-2 segundos, sin navegador         │            │
│  └────────────────────────────────────────┘            │
│                                                        │
│  EFS: perfil Chrome persistente (sesion SSO)           │
└────────────────────────────────────────────────────────┘
```

| Aspecto | Detalle |
|---|---|
| **Costo mensual** | $15-30 (Lambda + EFS + DynamoDB + API Gateway) |
| **Tiempo de setup** | 2-4 horas (Docker image + ECR + EFS + DynamoDB + EventBridge + API Gateway) |
| **Latencia por request** | 1-2s con auth caliente. Si auth expiro y el refresher aun no corrio, el request falla |
| **Mantenimiento** | Serverless — AWS gestiona infraestructura. Solo mantener la imagen Docker |
| **Escalabilidad** | Automatica (Lambda escala por concurrencia, API Gateway maneja trafico) |
| **VPN** | No viable — Lambda no soporta TUN/TAP. IPs de AWS datacenter |
| **Riesgo Akamai** | **Alto** — Chrome en Lambda debe correr headless (no hay GPU real) + IP de datacenter de AWS. Akamai puede detectarlo y bloquear la sesion |

**Recursos AWS necesarios:**

| Recurso | Proposito |
|---|---|
| ECR | Imagen Docker con Chrome + Xvfb + Python + curl_cffi + patchright |
| Lambda (container, 3GB RAM, 5 min timeout) | Auth Refresher |
| Lambda (standard, 256MB) | Download Service |
| API Gateway | Exponer POST /download-url |
| EFS | Persistir perfil Chrome |
| DynamoDB | Cache de tokens auth |
| EventBridge | Disparar refresher cada 5-10 min |

**Riesgos especificos de Lambda:**
- Chrome debe ejecutarse en modo headless con Xvfb (no hay display real). DOB Now/Akamai podrian detectar la diferencia de fingerprinting y bloquear la sesion.
- Si el refresher falla (bloqueo, timeout, error de Chrome), el Download Service queda sin auth hasta el siguiente ciclo.
- Cold start del refresher: 10-30 segundos para levantar Chrome en cada invocacion.
- EFS agrega latencia a las operaciones de archivo de Chrome (cookies, localStorage, perfil).

### Opcion C: ECS Fargate (produccion)

**Arquitectura:** Contenedor Docker con FastAPI + Chrome + Xvfb, tarea siempre activa.

```
┌──────────────────────────────────────────┐
│  ECS Fargate Task (4 vCPU / 8 GB RAM)    │
│                                           │
│  Contenedor unico:                        │
│    - Xvfb :99                             │
│    - google-chrome --display=:99          │
│    - FastAPI (uvicorn)                    │
│    - Background auth refresh              │
│                                           │
│  ALB / API Gateway → POST /download-url  │
│  EFS → persistencia de perfil Chrome      │
│  Auto-recovery: si falla, ECS reinicia    │
└──────────────────────────────────────────┘
```

| Aspecto | Detalle |
|---|---|
| **Costo mensual** | $40-60 (Fargate spot + EFS) |
| **Tiempo de setup** | 1-2 horas |
| **Latencia por request** | 1-2 segundos |
| **Mantenimiento** | Bajo — ECS maneja reinicios, solo actualizar imagen Docker |
| **Escalabilidad** | Multiples tareas, auto-scaling |
| **VPN** | Posible con sidecar container (gluetun) |
| **Riesgo Akamai** | Bajo — igual que opcion A |

## 4. Tabla comparativa

| Criterio | A: Lightsail/EC2 | B: Lambda | C: ECS Fargate |
|---|---|---|---|
| **Costo/mes** | $10-20 | $15-30 | $40-60 |
| **Setup inicial** | ~30 min | 2-4 horas | 1-2 horas |
| **Latencia request** | 1-2s | 1-2s | 1-2s |
| **Escalabilidad** | Baja (manual) | Alta (auto) | Alta (auto) |
| **Mantenimiento** | Medio (gestionar VM) | Bajo (serverless) | Bajo (solo imagen) |
| **Chrome headless** | No (navegador real) | Si (headless forzado) | No (navegador real con Xvfb) |
| **Riesgo deteccion Akamai** | Bajo | Alto | Bajo |
| **VPN / rotacion IP** | Si | No | Si (sidecar) |
| **Recuperacion ante fallos** | Manual | Automatica | Automatica |
| **Complejidad** | Simple | Alta | Media |

## 5. Recomendacion

**Para empezar rapido y validar:** Opcion A (Lightsail VPS $10/mes). Una VM Linux con el servicio corriendo en ~30 min. Si funciona bien y se necesita escalar, migrar a Opcion C (ECS Fargate).

**Si el requisito de jefatura es Lambda:** Opcion B es viable tecnicamente, pero con el riesgo real de que Akamai detecte el Chrome headless + IP de AWS y bloquee la sesion de DOB Now. Esto requeriria rehacer el login SSO manualmente cada vez que ocurra.
