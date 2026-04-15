# 🖨️ Print Brother — sistema de impresión remota para Brother DCP-1610NW

> Imprimí PDFs en una **Brother DCP-1610NW** desde cualquier iPhone/iPad conectado al WiFi de tu casa, **sin Mac always-on, sin Pi, sin ningún hardware extra**. Solo cosas web.

---

## ¿Qué problema resuelve?

La **Brother DCP-1610NW** es una impresora de 2014 que solo entiende un formato propietario llamado **HBP (Host Based Printing)** — no PostScript, no PCL5e estándar, no PDF, no AirPrint nativo. Para imprimir hay que tener una computadora con CUPS + driver Brother que convierta los documentos a HBP.

Ese es el problema: **sin computadora, no se puede imprimir**.

Este proyecto resuelve eso poniendo el "computador" en la nube (Vercel Function), y dejando que el iPhone del usuario actúe de mensajero entre la nube y la impresora cuando está en la red local.

---

## Arquitectura

```
                   ┌──────────────────────────────────┐
                   │  https://print-brother.vercel.app │
                   │  Vercel Function (Python)         │
                   │  ┌──────────────────────────┐     │
                   │  │ POST /api/convert        │     │
                   │  │   PDF → CUPS Raster      │     │  ← GhostScript
                   │  │   Raster → HBP binary    │     │  ← brlaser
                   │  │   return HBP             │     │
                   │  └──────────────────────────┘     │
                   └──────────────┬───────────────────┘
                                  │
                                  │ HTTPS
                                  │
       ┌──────────────────────────┴────────────────────────┐
       │                                                    │
       │           Internet (cualquier red)                 │
       │                                                    │
       └──────────────────────────┬────────────────────────┘
                                  │
                                  │ TCP/443
                                  │
       ┌──────────────────────────┴────────────────────────┐
       │                                                    │
       │           Red local del eero (192.168.4.0/22)     │
       │                                                    │
       │   ┌────────────┐         ┌──────────────────────┐ │
       │   │ iPhone hijo│         │ Brother DCP-1610NW   │ │
       │   │ con iOS    │ ── POST raw HBP @ TCP/9100 ──→│ 192.168.4.48        │ │
       │   │ Shortcut   │         │ (imprime)            │ │
       │   │ instalado  │         │                      │ │
       │   └────────────┘         └──────────────────────┘ │
       │                                                    │
       └────────────────────────────────────────────────────┘
```

### Pipeline completo

1. **Hijo abre PDF** en cualquier app del iPhone (Mail, Drive, Files, WhatsApp, Safari, etc.)
2. **Tap Compartir → "Imprimir Brother"** (Atajo iOS instalado previamente)
3. **El Atajo hace 2 POSTs encadenados**:
   - **Paso 1**: POST del PDF (binario) a `https://print-brother.vercel.app/api/convert`
   - **Paso 2**: el response (HBP binario) se reenvía a `http://192.168.4.48:9100`
4. **La Brother imprime** el documento

**Requisito**: el iPhone debe estar conectado al WiFi del eero (red local) para alcanzar `192.168.4.48`.

---

## Componentes

### 1. Vercel Function (`api/convert.py`)

Function Python que recibe un PDF en POST body y devuelve el HBP equivalente listo para enviar al puerto raw 9100 de la Brother.

- **Runtime**: `@vercel/python@4.3.0`
- **Memoria**: 1024 MB
- **Timeout**: 60 segundos
- **Endpoint**: `POST /api/convert`
- **Content-Type input**: `application/pdf`
- **Content-Type output**: `application/octet-stream` (HBP binario)
- **Tamaño máximo**: 20 MB de PDF

**Pipeline interno**:

```python
PDF (input)
  → gs -sDEVICE=cups -r300x300 -dcupsBitsPerColor=1 -o /tmp/out.cupsraster
  → rastertobrlaser 1 vercel print 1 "" < /tmp/out.cupsraster > /tmp/out.hbp
  → return HBP (output)
```

### 2. Binarios Linux precompilados

El repo incluye los binarios necesarios precompilados para el runtime Linux de Vercel:

- `bin/gs` — GhostScript 9.55.0 (Ubuntu 22.04)
- `bin/rastertobrlaser` — driver brlaser open source (`pdewacht/brlaser`) para Brother HBP
- `lib/*.so*` — shared libraries de las que dependen los binarios (libgs, libfreetype, libpng, libjpeg, etc.) **excluyendo** las de la libc del sistema (Vercel runtime las tiene)
- `gs_share/Resource/` — archivos de inicialización PostScript de GhostScript (`gs_init.ps`, CMaps, etc.)
- `gs_share/iccprofiles/` — color profiles ICC (`default_gray.icc`, `default_rgb.icc`, etc.)

**Estos binarios se compilan automáticamente** con un GitHub Actions workflow (`.github/workflows/build-binaries.yml`) en una VM Ubuntu 22.04 cada vez que cambia el código (excepto los propios binarios para evitar loops). El workflow:

1. Instala `ghostscript` + `printer-driver-brlaser` via `apt`
2. Copia los binarios y deps a `bin/`, `lib/`, `gs_share/`
3. Hace commit y push de los binarios al repo
4. Vercel detecta el push y deploya automáticamente

### 3. iOS Shortcut

Atajo iOS plist binario (`Imprimir_Brother_v2.shortcut`, ~1.4 KB) con dos acciones encadenadas:

- **Acción 1**: `Get Contents of URL` con method=POST, body=Shortcut Input (PDF), URL=`https://print-brother.vercel.app/api/convert`
- **Acción 2**: `Get Contents of URL` con method=POST, body=output de Acción 1 (HBP), URL=`http://192.168.4.48:9100`

Configurado para aparecer en el **Share Sheet** de iOS para todos los content types (PDF, imagen, archivo, URL).

**URL pública del Shortcut**: <https://files.catbox.moe/7rvzad.shortcut> (hosteada permanentemente en catbox.moe sin cuenta).

---

## Uso

### Para el padre/admin (1 vez)

1. **Abrir Safari en el iPhone**
2. Ir a **`https://files.catbox.moe/7rvzad.shortcut`**
3. Safari descarga el archivo `.shortcut`
4. Tap en **Descargas → Imprimir_Brother_v2.shortcut**
5. La app **Atajos** se abre automáticamente → **"Añadir Atajo"**

#### Si dice "No se pueden importar atajos no confiables"

iOS 15+ por seguridad bloquea atajos no firmados. Hay que activar la opción una vez:

1. Configuración → Atajos → **"Permitir Atajos No Confiables"** → ON
2. > Esa opción solo aparece si **alguna vez ejecutaste UN atajo firmado**. Si nunca usaste Atajos: abrí la app Atajos → Galería → ejecutá CUALQUIER atajo simple (ej. "Calculadora de propinas") UNA vez. Después la opción aparece en Configuración.

### Para los hijos (compartir el Shortcut)

Una vez instalado en el iPhone del padre:

1. Abrir **Atajos** → mantener presionado **"Imprimir Brother"**
2. **Compartir** → **"Copiar enlace de iCloud"**
3. Mandar ese link a los hijos por WhatsApp/Mail
4. Los hijos abren el link → **"Añadir Atajo"** → listo

Cuando vos compartís via iCloud, **Apple firma el atajo automáticamente con tu cuenta**, así los hijos lo importan sin necesidad de habilitar "Untrusted Shortcuts".

### Para imprimir (uso normal)

Desde **cualquier app** (Mail, Drive, Files, WhatsApp, Safari, Fotos):

1. Abrir el documento (PDF, imagen, etc.)
2. Tap el botón **Compartir** (cuadrado con flecha hacia arriba)
3. Scrollear abajo → tap **"Imprimir Brother"**
4. Esperar ~3-8 segundos
5. **La Brother imprime** ✅

### Para imprimir desde una Mac (sin pasar por Vercel)

Las Macs pueden imprimir directamente vía CUPS local con el driver Brother oficial — **no necesitan la Vercel function**. Solo:

1. Instalar el driver Brother oficial para macOS:
   - Bajar de <https://support.brother.com/g/b/downloadtop.aspx?c=cl&lang=es&prod=dcp1617nw_us>
   - Buscar "Full Driver & Software Package" para macOS
   - Instalar el `.dmg`
2. **System Settings → Printers & Scanners → Add Printer**
3. La Brother debería aparecer en la lista (descubierta vía Bonjour)
4. Seleccionarla → Add
5. **File → Print** desde cualquier app → seleccionar la Brother → Print

---

## Limitaciones

- **El iPhone debe estar en el WiFi del eero** (red `192.168.4.0/22`) para que el segundo POST llegue a `192.168.4.48`. Fuera de la red local no funciona inmediatamente.
- **Solo PDF** como input (la function valida el header `%PDF`). Si quieres imprimir imágenes, hay que convertirlas a PDF primero (iOS lo hace automáticamente al compartir desde Fotos).
- **Tamaño máximo 20 MB** por PDF.
- **Latencia ~3-8 segundos** entre tap y papel saliendo (1 seg conversión Vercel + transfer + Brother).
- La impresora física **debe estar encendida y conectada al eero** (obvio).

---

## Troubleshooting

### "La Brother no imprime"

1. Verificar que el iPhone está conectado al WiFi del eero (no a datos móviles ni a otra red)
2. Verificar que la Brother está encendida y conectada
3. Probar imprimir desde una Mac vía `lp -d Brother_DCP_1610NW_series /ruta/al.pdf` para confirmar que la Brother está accesible
4. Revisar los logs de Vercel: `vercel logs print-brother.vercel.app`

### "Pasa la hoja en blanco"

Significa que el HBP llegó pero la conversión fue incorrecta. Verificar:

1. La cola de impresión de la Brother (vía web admin <http://192.168.4.48>)
2. Si el PDF de origen es válido (`file documento.pdf` debe decir "PDF document")
3. Re-deploy de la Vercel function por si los binarios están corruptos

### "Vercel function devuelve 500"

```bash
curl -X POST -H "Content-Type: application/pdf" --data-binary @test.pdf https://print-brother.vercel.app/api/convert
```

Si devuelve JSON con `error`, leer el mensaje:

- `gs failed (1): Can't find initialization file gs_init.ps` → faltan los `gs_share/Resource` files. Re-trigger GitHub Action.
- `gs failed (...) stack smashing detected` → glibc incompatible. Re-build en Ubuntu 22.04 (no 24.04, no 20.04).
- `brlaser failed: Cannot read raster data` → el raster generado por gs no es 1-bit B/W. Verificar flags `-dcupsBitsPerColor=1 -dcupsColorSpace=3`.

### "El Atajo iOS no aparece en el Share Sheet"

1. Atajos → tap "Imprimir Brother" → ícono ⓘ (rueda dental) → activar **"Mostrar en hoja de compartir"**
2. Verificar que en "Tipos aceptados" estén tildados PDF, Imágenes, Archivos

### "Atajos dice 'No se puede conectar al servidor' en el segundo paso"

El iPhone no está en el WiFi del eero. Conectarlo y reintentar.

---

## Repositorio

- **Código fuente**: <https://github.com/KSS-Develop/print-brother>
- **Vercel deployment**: <https://print-brother.vercel.app>
- **iOS Shortcut**: <https://files.catbox.moe/7rvzad.shortcut>

---

## Tecnologías usadas

| Componente | Tecnología | Versión |
|---|---|---|
| Function runtime | `@vercel/python` | 4.3.0 |
| GhostScript | `gs` (Ubuntu apt) | 9.55.0 |
| brlaser | `pdewacht/brlaser` (Ubuntu apt) | 6 |
| iOS Atajos | nativo Apple | iOS 15+ |
| Hosting Shortcut | catbox.moe | gratis, sin cuenta |
| CI binarios | GitHub Actions | ubuntu-22.04 |

---

## Notas técnicas

### Por qué necesitamos brlaser

La Brother DCP-1610NW pertenece a la línea "GDI/HBP" (Host-Based Printing) de Brother. Estas impresoras NO tienen un parser PostScript ni PCL en el firmware — dependen completamente del driver host para generar la matriz raster final que la impresora va a marcar en el papel. **brlaser** (de Peter De Wachter, GitHub `pdewacht/brlaser`) es el filter CUPS open source que sabe convertir CUPS Raster genérico al formato HBP propietario que entiende la Brother.

### Cómo se descubrió que la Brother imprime PDF... pero no como pensábamos

En las pruebas iniciales, mandar un PDF crudo al puerto 9100 hacía que **avance el papel pero salga en blanco** — eso confirmó que la Brother NO procesa PDF directamente. Por eso pasamos por GhostScript (que rasteriza el PDF) y luego brlaser (que convierte el raster al formato HBP).

### Sobre el SNMP write community `internal`

Durante el debugging descubrimos que la Brother expone una community SNMP write `internal` que permite modificar variables NVRAM del firmware. Eso resultó NO ser útil para activar AirPrint (porque el firmware Brother de 2014 no tiene OIDs para configurar `pdl` en mDNS), pero podría usarse para otras tareas administrativas (cambiar nombre del servicio mDNS, activar/desactivar protocolos, etc.).

### Sobre por qué no usamos AirPrint nativo

iOS solo muestra impresoras AirPrint que publican `_ipp._tcp` en mDNS con un campo `pdl=` correcto (`application/pdf`, `image/pwg-raster`, `image/urf`). La Brother DCP-1610NW publica `_ipp._tcp` pero con `pdl=` **vacío**, así que iOS no la reconoce como impresora válida. **Y no hay forma de cambiar ese campo** desde el firmware (no existe ningún parámetro SNMP, web admin ni PJL para hacerlo). Por eso usamos un Atajo iOS que hace POST raw a la impresora — saltándose AirPrint completamente.

---

## Licencia

MIT. Hecho con cariño para que los hijos puedan imprimir sus tareas.
