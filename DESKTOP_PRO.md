# Universal Video Converter PRO — Fase 2

Interfaz gráfica con pestañas para Windows 11 x64, basada en Tkinter y FFmpeg.

## Uso local
1. Instala Python 3.10+ y una distribución de FFmpeg con **ffmpeg.exe** y **ffprobe.exe**.
2. Añade ambos ejecutables al PATH o colócalos junto a `desktop_converter.py` (junto al EXE en la versión empaquetada).
3. Ejecuta `python desktop_converter.py`.
4. Añade archivos o carpetas a la cola. En **Codificación**, selecciona formato, códec y dispositivo. En **Audio y subtítulos**, selecciona un archivo de la cola y pulsa **Inspeccionar** para enumerar sus pistas. En **Opciones**, elige carpeta de salida.
5. Inicia la cola y consulta el progreso. **Cancelar** detiene la tarea actual y deja intactos los originales.

## Exportación
- MKV: H.264, H.265 o AV1.
- MP4: H.264, H.265 o AV1 (depende de compatibilidad del reproductor).
- WEBM: AV1, Opus y subtítulos WebVTT.
- AVI: H.264 + MP3, sin subtítulos. AVI es un contenedor heredado y esta combinación no está garantizada en todos los reproductores.

El selector GPU admite CPU, NVIDIA NVENC, Intel QSV y AMD AMF según el codificador instalado. Que aparezca un codificador en FFmpeg **no garantiza** que el hardware/driver pueda ejecutarlo. No hay fallback silencioso a CPU.

## Compilación EXE
El workflow **Windows EXE** en GitHub Actions empaqueta la interfaz con PyInstaller y publica el artefacto `UniversalVideoConverterPRO-Windows-x64` en la ejecución. **No incluye FFmpeg ni ffprobe**, que deben instalarse por separado o distribuirse conforme a sus licencias.

## Límites conocidos
- La selección de pistas es global para la cola y los índices seleccionados deben existir en cada video. Para distintos archivos, inspecciona y convierte por separado.
- Los subtítulos gráficos (PGS/DVD) no se pueden convertir automáticamente a SRT/WebVTT: requiere OCR o selección **Ninguna**.
- No se implementó drag-and-drop ni un indicador visual de capacidad real de GPU.
- El progreso se basa en la duración reportada por FFprobe, por lo que puede ser aproximado.
- El programa no sobrescribe salidas y usa archivos temporales, pero no está diseñado para múltiples instancias trabajando sobre el mismo destino.
- Se requiere probar archivos reales en Windows y revisar compatibilidad de cada combinación antes de producción.
