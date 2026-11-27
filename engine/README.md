# Painting Renamer

> **Proyecto unificado con la galería web.** Este código vive ahora en `\\192.168.1.2\Web\cuadros\engine`
> (`W:\cuadros\engine`). La antigua carpeta `N:\dev\painting_renamer` solo contiene un README que apunta aquí.
>
> ```
> cuadros/
> ├── index.html          # Galería web: solo el HTML (lista, visor con zoom, botón "+" para subir cuadros)
> ├── index.php           # Sirve index.html añadiendo ?v=<mtime> a css/ y js/ (Cloudflare fuerza 4h de caché)
> ├── css/app.css         # Todos los estilos (incluido el tema oscuro, html.dark)
> ├── js/app.js           # Toda la lógica de la web (cargado al final del <body>)
> ├── js/theme-init.js    # Aplica el tema guardado antes de pintar (cargado en el <head> para evitar parpadeo)
> ├── api/                # PHP: paintings.php (catálogo), account.php (registro/login), marks.php (vistos/favoritos),
> │                       #      collections.php (colecciones), upload.php + job.php (subida, solo superusuarios)
> ├── data/               # cuadros.sqlite (cuadros, descripciones, usuarios, vistos, favoritos) + sesiones PHP propias.
> │                       # Bloqueado por .htaccess
> ├── paintings/          # Imágenes. painting_library.json es solo una COPIA legible que el motor regenera tras cada
> │                       # cambio (nada la lee). painting_library.pre-db-backup.json = JSON original antes de migrar
> └── engine/             # Este proyecto (bloqueado por .htaccess: config.json contiene la API key)
>     ├── schema.sql      # Esquema único de la BD, compartido por PHP y Python
>     ├── .venv/          # venv de Python 3.12 del NAS (QPKG Python3)
>     ├── jobs/           # Trabajos de subida (log.txt, result.json); se borran a los 7 días
>     └── tools/          # migrate_json_to_db.py (migración ya hecha) y scripts antiguos de encoding
> ```
>
> **Base de datos:** `data/cuadros.sqlite` (SQLite) es la fuente de verdad de todo, independiente de cualquier otra BD
> del NAS. `library_manager.py` carga los cuadros como diccionarios (mismo formato que el antiguo JSON) y al guardar
> escribe solo los que han cambiado; las descripciones nunca se borran, se van acumulando por idioma.
> Cada cuadro tiene un `id` estable, que el motor conserva aunque renombre el archivo; vistos, favoritos y enlaces
> compartidos (`?cuadro=<id>&desc=<n>`) lo usan.
>
> **Usuarios:** cookie de sesión propia (`CUADROS_SID`, limitada a `/cuadros/`). Cualquiera puede registrarse para
> guardar vistos y favoritos. **Superusuarios** = el propietario `ggonmar` + todo usuario con `users.can_upload = 1`; todos tienen los mismos poderes (subir, editar/borrar cuadros, panel de usuarios, IA de procesado). El propietario es `ggonmar` (constante `ADMIN_USERNAME` en `api/_common.php`, decidido por
> nombre de usuario, no por la BD): ve el panel **👥 Usuarios** (`api/admin.php`: totales, lista paginada de 20 en 20,
> búsqueda) desde el que concede o retira a cada usuario el permiso de subir cuadros (`users.can_upload`), y es el
> único que puede editar cuadros. Cada usuario solo ve el progreso de sus propias subidas.
> Cambiar la contraseña cierra las demás sesiones de ese usuario. Solo se crea archivo de sesión (`data/sessions/`) al
> iniciar sesión; las visitas anónimas no generan ninguno, y logout o sesiones inválidas borran archivo y cookie.
>
> **Colecciones** (`api/collections.php`, tablas `collections` y `collection_paintings`): cada usuario registrado crea
> las suyas con el "+" junto al título (solo se pide el nombre, máx. 100 por usuario) y añade/quita cuadros con el
> botón 📁 del detalle. El selector de la cabecera limita lista, mapa y filtros a la colección activa (recordada en
> `localStorage`); ⚙️ permite renombrarla, copiar su enlace o borrarla. Son privadas, pero el id (16 hex aleatorios) es
> también un enlace de solo lectura: `?coleccion=<id>` la muestra a cualquiera, sin poder modificarla. Borrar un
> usuario, una colección o un cuadro limpia sus entradas en cascada.
> Cada usuario tiene además la colección fija **❤️ Favoritos** (`collections.kind = 'favorites'`, creada al vuelo, una
> por usuario): sus cuadros son los marcados con ❤️ (tabla `favorites`), no se puede renombrar ni borrar, no aparece en
> el menú 📁 (para eso está el corazón) y, compartida, se muestra como «Favoritos de <usuario>».
>
> **Edición desde la web (superusuarios):** botón ✏️ en el detalle del cuadro → `api/painting.php`. Panel de tamaño fijo
> con pestañas **General** (título, título original, artista, año, ubicación, tags), **Imagen** (sustituirla),
> **Descripción** (versiones, escribir una nueva, pedir a una IA) y **Avanzado** (pendiente/confirmado, eliminar). Los
> cambios de todas las pestañas quedan pendientes (punto naranja en la pestaña) y se aplican juntos con **Guardar**;
> cerrar con cambios sin guardar pide confirmación. Pedir una descripción a una IA y eliminar el cuadro son acciones
> inmediatas. Permite cambiar
> título, título original, artista, año, ubicación y "confirmado", añadir una descripción propia y pedir una nueva a
> una IA configurada (Gemini u Ollama, vía `tools/generate_description.py` como trabajo en segundo plano). Tras cada
> cambio, `tools/after_edit.py` geocodifica la ubicación nueva y regenera el JSON. Las descripciones nuevas nunca
> sustituyen a las anteriores (pasan a ser la versión más reciente), pero desde el mismo formulario se puede editar el
> texto o borrar cualquier versión concreta. "Eliminar cuadro" borra el cuadro, sus descripciones y las marcas de
> visto/favorito, y mueve la imagen a `data/trash/` (junto a un `.json` con sus datos, por si hay que recuperarlo).
> La papelera se vacía sola: lo que lleva más de 30 días (`TRASH_RETENTION_SECONDS` en `api/_common.php`) se borra
> al tirar algo nuevo o, como mucho una vez al día, al cargar el catálogo.
> Cambiar el título no renombra el archivo (el cuadro se identifica por `id`).
>
> **Tags:** cada cuadro tiene formato (`paintings.orientation`: horizontal/vertical/cuadrado, calculado de la imagen),
> época (1-2) y temática (1+), con un máximo de 6 en total. Época y temática están en la tabla `painting_tags` y salen
> de un vocabulario cerrado (`tags_vocabulary.json`, compartido por `tags.py` y la API PHP); la IA (Gemini u Ollama)
> los devuelve al identificar un cuadro nuevo y `normalize_tags()` unifica variantes ("Religioso" → religión) y
> descarta lo que no está en la lista. `tools/tag_paintings.py [--all] [--limit N]` pide solo los tags a Gemini para
> los cuadros que no los tienen. Se pueden editar desde ✏️, filtrar por ellos y el buscador también los encuentra.
>
> **Sustituir la imagen** (✏️, `api/replace_image.php`): cambia solo el archivo (y tamaño, dimensiones y formato);
> no consulta a ninguna IA. La imagen anterior va a `data/trash/`.
>
> **IA de procesado (solo ggonmar, menú de usuario → 🤖 IA de procesado, `api/settings.php`):** elige Gemini (y su
> modelo) u Ollama (y cualquiera de los modelos instalados en `ollama_host`; se marcan los que ven imágenes), y el
> estilo y la longitud máxima de las descripciones. Se
> guarda en `engine/ai_settings.json`, que se superpone a `config.json` tanto en PHP (`engine_config()`) como en
> Python (`ConfigManager`), así que también afecta a la CLI. Borrar ese archivo vuelve a lo de `config.json`.
> "🏷️ Sugerir tags con IA" (✏️) ejecuta `tools/suggest_tags.py`: envía imagen + título/artista/año a esa IA y
> solo propone época y temática (no guarda nada hasta pulsar «Guardar cambios»).
>
> **Tema claro/oscuro:** toggle en la cabecera; se guarda en `localStorage` y, con sesión, en `users.theme`.
>
> **Mapa:** `geocoder.py` traduce cada `location` distinta a coordenadas con OpenStreetMap Nominatim (solo acepta
> museos, galerías, edificios… y como último recurso la ciudad) y lo guarda en la tabla `locations`. El motor
> geocodifica automáticamente las ubicaciones nuevas al guardar; para el histórico o para reintentar:
> `.venv/bin/python tools/geocode_locations.py [--retry-not-found | --all]`. La web carga Leaflet desde unpkg.
>
> **Subida desde la web:** `api/upload.php` guarda la imagen en `paintings/`, crea al momento una entrada
> **pendiente de revisión** (`paintings.status = 'pending'`, título = nombre del archivo) y ejecuta
> `.venv/bin/python painting_renamer.py <imagen> --result-json jobs/<id>/result.json` en el NAS.
> Si la IA lo identifica, el motor completa esa misma entrada y la pasa a `ready`; si falla (cuota, cuadro
> desconocido…) se queda pendiente. Los pendientes solo los ven quienes pueden subir cuadros, que tienen un filtro
> "⏳ Revisión" y un botón "🔄 Reintentar con IA" (`api/reprocess.php`); desde ✏️ se puede marcar como revisado a mano.
> `tools/register_orphans.py` registra como pendiente cualquier imagen de `paintings/` sin entrada en la BD.
> Las rutas se pasan al motor con `shell_quote()` (no `escapeshellarg()`, que en el NAS elimina tildes y eñes).
> El motor identifica el cuadro, lo renombra y lo guarda en la BD; un bloqueo (`library_lock.py`) evita que dos
> ejecuciones escriban a la vez.
>
> **El motor solo se ejecuta en el NAS** (SQLite no es fiable escribiendo a través de SMB; desde Windows se niega a
> arrancar). Por SSH:
> `ssh ggonmar@192.168.1.2` → `cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python painting_renamer.py [opciones]`
> (sin argumentos procesa todo `../paintings`).
>
> **Cambios en PHP:** el opcache del NAS revalida los scripts cada 60 s, así que una edición puede tardar hasta un
> minuto en verse.
>
> **Reinstalar el venv del NAS** (el NAS tiene glibc 2.21 y un `/tmp` de 64 MB):
> `cd engine && /share/CACHEDEV1_DATA/.qpkg/Python3/opt/python3/bin/python3 -m venv .venv &&
> TMPDIR=$PWD/jobs/tmp .venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements.txt`

A Python script that automatically renames painting image files with complete metadata and builds a comprehensive JSON library of your collection.

## Features

- 🎨 **Automatic Painting Identification**: Uses Wikipedia API and/or Ollama LLM
- 🌐 **Wikipedia Integration**: Free, accurate data from Wikipedia (no API key needed!)
- 🌍 **Multi-language Support**: Get painting titles and descriptions in your language
- 🤖 **Optional Ollama Support**: Use AI for descriptions and as fallback
- 📝 **Complete Metadata**: Extracts painting name, artist, year, and location
- 🖼️ **Orientation Detection**: Automatically determines landscape/portrait/square orientation
- 📚 **JSON Library**: Creates a searchable library with rich descriptions
- 🔍 **Duplicate Detection**: Identifies duplicate paintings and marks smaller files for review
- 📖 **Source Tracking**: Records where information came from (Wikipedia or Ollama)

## Prerequisites

### 1. Python
Make sure you have Python 3.7 or higher installed.

### 2. Ollama Server (Optional)

This script can optionally use an Ollama server for AI-generated descriptions.

**If using Wikipedia only** (`data_source: "wikipedia"`), you don't need Ollama at all!

**If using Ollama:**
- Default configuration uses Ollama at `http://192.168.1.3:11434`
- You can also access it via OpenUI at `ai.ggonmar.com`
- Set `data_source` to `"ollama"` or `"both"` in config.json

Make sure the Ollama server has a suitable model installed (e.g., `llama3.2`).

## Installation

1. **Clone or download this repository**

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure your settings (recommended):**

Edit [config.json](config.json) to set your defaults:
```json
{
  "ollama_host": "http://192.168.1.3:11434",
  "api_key": "your_api_key_here",
  "library_file": "painting_library.json",
  "ollama_model": "llama3.2",
  "default_folder": ".",
  "data_source": "both"
}
```

**Configuration options:**
- `ollama_host`: Your Ollama server URL (can use `http://ai.ggonmar.com:11434`)
- `api_key`: API key for authentication (use `null` if not needed)
- `library_file`: Default name for the JSON library file
- `ollama_model`: Which Ollama model to use (e.g., `llama3.2`, `llama3.1`, `mistral`)
- `default_folder`: Default folder to process (`.` for current folder)
- **`data_source`**: Comma-separated list of data sources in priority order
  - `"wikipedia,ollama"` - Query Wikipedia first, then enhance with Ollama (recommended)
    - Wikipedia provides facts, Ollama validates and generates rich descriptions
    - Ollama receives Wikipedia results to enhance/verify
  - `"ollama,wikipedia"` - Query Ollama first, then validate with Wikipedia
    - Ollama provides initial data, Wikipedia validates and adds URLs
  - `"wikipedia"` - Wikipedia only (no enhancement)
  - `"ollama"` - Ollama only (no validation)
  - **Note:** With multiple sources, each one ENHANCES the previous, not replaces it
  - Future: easily add more sources like `"wikipedia,ollama,google"` etc.
- **`naming_format`**: Custom filename format template (see below)
- **`language`**: Language code for painting titles and descriptions
  - `"en"` - English (default)
  - `"es"` - Spanish
  - `"fr"` - French
  - `"de"` - German
  - `"it"` - Italian
  - `"pt"` - Portuguese
  - And more...
  - **Note:** Orientation and location remain in their original language

### Filename Format Customization

Use placeholders to customize how files are renamed:

**Available placeholders:**
- `%title%` or `%painting%` - Painting title
- `%artist%` or `%painter%` - Artist name
- `%year%` - Year painted
- `%location%` - Museum/current location
- `%orientation%` - Image orientation (landscape/portrait/square)

**Examples:**
```json
// Default format
"naming_format": "%artist% - %title% (%year%) %location% [%orientation%]"
// Result: Vincent van Gogh - The Starry Night (1889) Museum of Modern Art [landscape].jpg

// Simple format
"naming_format": "%painting% - %painter%"
// Result: The Starry Night - Vincent van Gogh.jpg

// Year first
"naming_format": "(%year%) %title% by %artist%"
// Result: (1889) The Starry Night by Vincent van Gogh.jpg

// With custom separators
"naming_format": "%artist% · %title% · %year%"
// Result: Vincent van Gogh · The Starry Night · 1889.jpg
```

Empty placeholders (like unknown year) are automatically cleaned up.

Command-line arguments will override these config values.

## Usage

### Basic Usage

**Process images (uses config.json defaults):**
```bash
python painting_renamer.py
```

Process images in the current folder:
```bash
python painting_renamer.py
```

### Specify a Folder

Process images in a specific folder:
```bash
python painting_renamer.py "C:\Users\YourName\Pictures\Paintings"
```

Or on Windows with PowerShell:
```powershell
python painting_renamer.py "l:\painting_renamer"
```

### Command Line Options

```bash
python painting_renamer.py [folder] [options]

Arguments:
  folder                Folder containing painting images (default: current folder)
                        Examples: "C:\paintings" or "L:\my_art_collection"

Options:
  --ollama-host URL     Ollama server URL (default: http://192.168.1.3:11434)
  --api-key KEY         API key for Ollama authentication (if required)
  --library FILE        Output JSON library file (default: painting_library.json)
  --dry-run            Show what would be done without renaming files
  --force-reprocess    Force reprocessing all files, ignoring cache
  -h, --help           Show help message
```

### Intelligent Caching

The script caches painting data in the library JSON to avoid redundant API calls:

**✅ Uses cache when:**
- Same language
- Same naming format
- Same data sources
- Painting already has complete info

**⟳ Reprocesses when:**
- Language changed (e.g., `"en"` → `"es"`)
- Naming format changed
- Data sources changed
- Missing essential information

**Examples:**

First run - queries all sources:
```bash
python painting_renamer.py "W:\cuadros"
# Queries Wikipedia and Ollama for each painting
```

Second run - uses cache (no config changes):
```bash
python painting_renamer.py "W:\cuadros"
# ✓ Using cached data - much faster!
```

After changing language in config.json:
```bash
# Changed "language": "en" → "language": "es"
python painting_renamer.py "W:\cuadros"
# ⟳ Reprocessing (language changed)
```

Force complete reprocessing:
```bash
python painting_renamer.py "W:\cuadros" --force-reprocess
```

### Examples

**Use defaults from config.json:**
```bash
python painting_renamer.py
```

**Process a specific folder (overrides config):**
```bash
python painting_renamer.py "C:\Users\YourName\Pictures\Paintings"
# or
python painting_renamer.py "L:\my_paintings"
```

**Override config settings:**
```bash
# Use different Ollama server
python painting_renamer.py --ollama-host http://ai.ggonmar.com:11434

# Use different API key
python painting_renamer.py --api-key different_key

# Different library file
python painting_renamer.py --library special_collection.json
```

**Dry run to preview changes:**
```bash
python painting_renamer.py "L:\paintings" --dry-run
```

## How It Works

1. **Scans the folder** for image files (jpg, png, gif, bmp, tiff, webp)
2. **Analyzes each image** to determine orientation (landscape/portrait)
3. **Queries data sources in sequence** (each enhancing the previous):
   - **Wikipedia**: Searches Wikipedia and extracts verified information
   - **Ollama**: Receives Wikipedia context, validates, and generates rich descriptions
   - Sources work together, not as fallback
4. **Detects duplicates** by comparing painting titles and artists
5. **Renames files** using your custom format from config.json
6. **Creates JSON library** with all metadata, descriptions, and source tracking

### Filename Format

**Default format:**
```
[Artist] - [Title] ([Year]) [Location] [Orientation].ext
```

**Examples:**
- `Vincent van Gogh - The Starry Night (1889) Museum of Modern Art, New York [landscape].jpg`
- `CHECK_DUPE - Leonardo da Vinci - Mona Lisa (1503-1519) Louvre Museum [portrait].jpg`

You can customize the format in [config.json](config.json) using the `naming_format` option.

## JSON Library Structure

The generated `painting_library.json` contains:

```json
{
  "metadata": {
    "created": "2026-01-28T10:30:00",
    "last_updated": "2026-01-28T10:35:00",
    "total_paintings": 5
  },
  "paintings": [
    {
      "title": "The Starry Night",
      "artist": "Vincent van Gogh",
      "year": "1889",
      "location": "Museum of Modern Art, New York",
      "orientation": "landscape",
      "description": "Rich AI-generated description with historical context...",
      "data_source": "Wikipedia",
      "wikipedia_url": "https://en.wikipedia.org/wiki/The_Starry_Night",
      "original_filename": "starry_night.jpg",
      "renamed_filename": "Vincent van Gogh - The Starry Night (1889)...",
      "file_size": 2458624,
      "added_to_library": "2026-01-28T10:32:15"
    }
  ]
}
```

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- BMP (.bmp)
- TIFF (.tiff, .tif)
- WebP (.webp)

## Tips

1. **Data Source Chain**:
   - **`"wikipedia,ollama"`**: Wikipedia provides facts → Ollama enhances with context and descriptions
   - **`"ollama,wikipedia"`**: Ollama provides initial data → Wikipedia validates and adds references
   - **`"wikipedia"`**: Wikipedia only (fast, accurate, free)
   - **`"ollama"`**: Ollama only (creative, but may hallucinate)
   - Multiple sources work together, each enhancing the previous one

2. **Ollama Model**: The script uses the model specified in `ollama_model` (default: `llama3.2`). You can change it to any model installed on your Ollama server: `llama3.1`, `mistral`, `mixtral`, etc.

3. **Filename Conventions**: The better your original filenames, the better the identification works. Include artist or painting names when possible.

4. **Processing Time**: 
   - Wikipedia lookups are fast (1-2 seconds per image)
   - Ollama queries take longer (varies by model and server)
   - Using `"wikipedia,ollama"` adds minimal time since Wikipedia is tried first

5. **Duplicate Detection**: The script identifies duplicates by matching title and artist. The smaller file (by size) is marked with "CHECK_DUPE" prefix for your review.

6. **Library Updates**: Running the script multiple times on the same folder will update the library rather than creating duplicates.

## Troubleshooting

**"Could not connect to Ollama":**
- Ensure your network Ollama server at `192.168.1.3` is running
- Try pinging the server: `ping 192.168.1.3`
- Check the Ollama host URL with `--ollama-host`
- Verify your firewall/network allows connections to the Ollama server

**"Could not find information for [filename]":**
- The AI couldn't identify the painting from the filename
- Try renaming the file with more specific information
- Check that your Ollama server is working and has a suitable model

**"Module not found" errors:**
- Install dependencies: `pip install -r requirements.txt`

## Project Structure

```
painting_renamer/
├── painting_renamer.py      # Main script
├── config_manager.py         # Configuration file handler
├── image_utils.py            # Image analysis utilities
├── painting_lookup.py        # Ollama LLM interface
├── wikipedia_lookup.py       # Wikipedia API interface
├── file_manager.py           # File operations and duplicate detection
├── library_manager.py        # JSON library management
├── config.json               # Configuration file (edit this!)
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## License

This project is free to use and modify as needed.

## Contributing

Feel free to enhance the script with additional features such as:
- Support for other AI providers (OpenAI, Claude, etc.)
- Web scraping as fallback for painting identification
- GUI interface
- Batch processing optimizations
- More metadata fields

---

Enjoy organizing your painting collection! 🎨
