# Nota: arquitectura consolidada
La interfaz y la lógica de conversión actuales se encuentran en `UniversalVideoConverterPRO.py`. Los comandos CLI descritos abajo corresponden a una versión anterior retirada.

# Conversor universal a MKV (nueva versión CLI)

Esta versión complementa los scripts existentes, sin reemplazarlos.

## Requisitos
- Python 3.8+
- FFmpeg y ffprobe instalados en PATH o indicados con --ffmpeg y --ffprobe.

## Ejemplos (PowerShell / CMD)
```powershell
python universal_to_mkv.py "D:\Videos\pelicula.avi"
python universal_to_mkv.py "D:\Videos" --recursive
python universal_to_mkv.py "D:\Videos\clip.mov" --mode encode
python universal_to_mkv.py "D:\Videos" --recursive --output "D:\Convertidos"
```

**copy** (predeterminado): remultiplexa sin recodificar. Es rápido y no altera la calidad, pero algunos códecs o subtítulos no son compatibles con Matroska y pueden fallar.

**encode**: recodifica video a H.264, audio a AAC y subtítulos de texto compatibles a SRT. Los subtítulos gráficos pueden necesitar tratamiento específico; no se promete compatibilidad universal.

Formatos de entrada reconocidos por extensión: AVI, MP4, MOV, WMV, FLV, WEBM, MPEG/MPG, TS, MTS, M2TS, VOB, M4V, 3GP, OGV y MKV. La lectura real depende de los demuxers y codecs disponibles en FFmpeg.

El programa no sobrescribe archivos existentes ni elimina los originales. Escribe primero un archivo temporal .partial.mkv y lo valida con ffprobe antes de renombrarlo. Si falla, elimina el temporal creado. Evita ejecutar dos conversiones simultáneas hacia el mismo destino.

### Próximos pasos sugeridos
- Interfaz gráfica Windows con cola, progreso y cancelación.
- Análisis de pistas y elección de audio/subtítulos.
- Detección de aceleración de hardware y perfiles de salida.
- Pruebas automatizadas y empaquetado EXE.
