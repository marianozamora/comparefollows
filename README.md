# CompareFollows

Herramienta local para analizar tus seguidores de Instagram. Compara tus listas de followers/following, muestra mutuos con sus métricas y te ayuda a decidir a quién dejar de seguir.

![CI](https://github.com/marianozamora/comparefollows/actions/workflows/ci.yml/badge.svg)

## Funcionalidades

- **Comparación** de followers vs following a partir de los archivos exportados de Instagram
- **Mutuos** con follower count, following count, ratio y cantidad de posts
- **Ordenar** por cualquier columna (ratio, followers, posts…)
- **Buscar** dentro de cada lista
- **Copiar / descargar** cada lista como `.txt`
- **Autoguardado** en `localStorage` — los resultados persisten al recargar
- Soporte para **múltiples archivos** (Instagram divide los followers en varios archivos)
- Todo el procesamiento de archivos ocurre en el navegador — ningún dato de tus listas se envía al servidor

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

Los datos se cachean localmente por 7 días (`follower_cache.json`).

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
| `follower_cache.json` | Cache de métricas (7 días de TTL) |

Ambos están en `.gitignore` — no se suben al repositorio.
