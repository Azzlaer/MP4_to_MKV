# Registro de conversiones y apagado opcional

La interfaz completa se inicia desde un único archivo: `UniversalVideoConverterPRO.py`.

- El registro se muestra en un Listbox dentro de la pestaña Cola. No se abre una ventana modal al terminar un archivo o la cola.
- `conversion.log` se guarda junto al ejecutable (o junto al script al ejecutar desde Python), en UTF-8.
- Cada archivo registra fecha/hora de inicio y fin, tiempo aproximado, extensión de origen, formato de salida, perfil H.264/H.265/AV1, dispositivo CPU/GPU, destino y resultado (completado, error, omitido, cancelado).
- En Opciones puedes escoger una carpeta personalizada o pulsar **Usar carpeta MKV del ejecutable**. El destino predeterminado es `MKV` junto al programa.
- El apagado automático de Windows está **desactivado por defecto**. Al habilitarlo, la cola completa dispara una cuenta regresiva configurable de 10 a 86400 segundos (30 predeterminados). Se puede cancelar desde Opciones.
- La opción de apagado no se ejecuta si el usuario cancela la cola. Sí puede ejecutarse si algún archivo falló y la cola terminó normalmente; revisa el LOG antes de habilitarla.
- La ejecución de `shutdown /s /t 0` ocurre solo al finalizar la cuenta regresiva. Se intenta escribir el LOG antes de solicitar el apagado.

**Limitación:** El perfil «Rápida» no está disponible en la GUI de la fase 2 (solo perfiles de recodificación). El registro refleja el modo real y no etiqueta conversiones como rápidas si no lo fueron.

**Pendiente:** validar GUI y empaquetado en Windows 11 x64 con FFmpeg real; no se han ejecutado pruebas de integración de este cambio.

## Configuración de FFmpeg

En **Opciones → Herramientas FFmpeg y bibliotecas DLL**, selecciona la carpeta que contiene `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` y los archivos `.dll` de la misma distribución. Usa **Validar y guardar** para comprobar los ejecutables y guardar la ruta en `ffmpeg_config.json` junto al programa. El programa usa esas rutas explícitas para codificar e inspeccionar medios; `ffplay.exe` se verifica para preparar su uso futuro, pero la GUI todavía no incorpora un reproductor. No mezcles DLL de versiones distintas de FFmpeg. La validación de presencia no garantiza que todas las funciones GPU estén disponibles.
