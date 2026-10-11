# CompareFollows

Herramienta local para analizar tus seguidores de Instagram. Compara tus listas de followers/following, muestra mutuos con sus métricas y te ayuda a decidir a quién dejar de seguir.

![CI](https://github.com/marianozamora/comparefollows/actions/workflows/ci.yml/badge.svg)

## Funcionalidades

- **Comparación** de followers vs following a partir de los archivos exportados de Instagram
- **Mutuos** con follower count, following count, ratio y cantidad de posts
- **Ordenar** por cualquier columna (ratio, followers, posts…)
- **Buscar** dentro de cada lista
- **Copiar / descargar** cada lista como `.txt` o `.csv` (con métricas de los mutuos)
- **Autoguardado** en `localStorage` — los resultados persisten al recargar
- Soporte para **múltiples archivos** (Instagram divide los followers en varios archivos)
- El procesamiento de archivos ocurre en el navegador. Solo si pedís métricas de mutuos se envían al servidor esos usernames y tu `sessionid` (se usan en memoria, no se almacenan)
- **Cambios desde la última comparación**: quién dejó de seguirte, nuevos seguidores, a quién dejaste de seguir y a quién empezaste a seguir (el historial vive en tu `localStorage`; hay botón para olvidarlo)
- **Pausar / reanudar / detener** la consulta de métricas; si el servidor se reinicia, lo ya obtenido se conserva y podés reanudar

## Instalación

```bash
git clone https://github.com/marianozamora/comparefollows.git
cd comparefollows
pip install -r requirements.txt
python app.py
```

Abrí `http://localhost:5001` en el navegador.

## Uso

### 1. Exportar datos de Instagram

Desde la app de Instagram:  
**Configuración → Tu actividad → Descargar tu información**

Seleccioná formato **HTML** o **JSON** y descargá el ZIP. Los archivos que necesitás son:
- `followers_1.html` (puede haber varios: `followers_2.html`, etc.)
- `following.html`

### 2. Comparar

Subí los archivos en las zonas de carga (podés arrastrar varios a la vez) y hacé click en **Comparar**.

### 3. Obtener métricas de mutuos (opcional)

Para ver followers, following, ratio y posts de cada mútuo necesitás el cookie `sessionid` de Instagram:

1. Abrí [instagram.com](https://www.instagram.com) en Chrome/Firefox
2. `F12` → **Application** → **Cookies** → `https://www.instagram.com`
3. Copiá el valor de `sessionid`
4. En la app, hacé click en **Obtener followers** y pegá el valor

Los datos se cachean localmente por 7 días (`follower_cache.db`, SQLite).

### Interpretar el ratio

| Ratio | Significado |
|-------|-------------|
| 🟢 ≥ 1x | Más seguidores que seguidos — cuenta real o influyente |
| 🟡 0.3x – 1x | Normal |
| 🔴 < 0.3x | Sigue a mucha gente — probablemente follow-for-follow |

## Formatos soportados

| Formato | Ejemplo |
|---------|---------|
| HTML de Instagram | `following.html`, `followers_1.html` |
| JSON de Instagram | `following.json` |
| Texto plano | `usuarios.txt` (un usuario por línea) |

## Archivos locales generados

| Archivo | Contenido |
|---------|-----------|
| `ig_sessionid` | Cookie de sesión de Instagram |
| `follower_cache.db` | Cache SQLite de métricas (7 días de TTL; importa el viejo `follower_cache.json` si existe) |

Ambos están en `.gitignore` — no se suben al repositorio.

## Producción y tests

- En Railway (`RAILWAY_ENVIRONMENT`) o con `REQUIRE_AUTH=1`, la app **no arranca** sin `APP_USER` y `APP_PASSWORD`.
- **Caché persistente:** montá un volumen en Railway; la app usa `$RAILWAY_VOLUME_MOUNT_PATH/follower_cache.db` automáticamente (o definí `CACHE_DB`). Sin volumen, la caché se pierde en cada deploy.
- `GET /healthz` responde sin autenticación (usalo como healthcheck en Railway).
- Se envían cabeceras de seguridad (CSP, `X-Frame-Options`, etc.) y los perfiles vencidos de la caché se purgan al arrancar.
- Hay rate limit por IP en `/validate-session` y `/fetch-counts`.
- Usar un solo worker de gunicorn: el progreso de los jobs vive en memoria.
- Ante un 429 de Instagram se aplica backoff exponencial (30 s → 8 min).
- **Privacidad del sessionid:** viaja al servidor de la app en cada consulta. Quien aloje la app podría verlo en tránsito (o en logs de infraestructura propios); la app no lo guarda ni lo registra. Desplegala solo si confiás en quien la opera.
- Consultar muchas cuentas con una sesión real puede hacer que Instagram la limite; usalo con moderación.

### Estructura

| Archivo | Rol |
|---------|-----|
| `app.py` | Rutas Flask, Basic Auth |
| `jobs.py` | Jobs en segundo plano (pausa, stop, backoff) |
| `instagram.py` | Cliente de la API web de Instagram |
| `cache.py` | Caché SQLite |
| `ratelimit.py` | Rate limit por IP |
| `static/lib.js` | Parser de exports, diff entre corridas, CSV (sin DOM) |
| `static/app.js` | UI |

### Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt && pytest
npm ci && npm run lint && npm test
```
