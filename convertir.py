import os
import sys
import json
import logging
import ffmpeg
from rich.console import Console
from rich.table import Table
from rich.prompt import IntPrompt
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

# ---------- Configuración ----------
CONFIG_FILE = "config.json"
console = Console()

# Cargar config
ffmpeg_path = "ffmpeg"
ffprobe_path = "ffprobe"
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
        ffmpeg_path = cfg.get("ffmpeg_path") or ffmpeg_path
        ffprobe_path = cfg.get("ffprobe_path") or ffprobe_path
else:
    console.print("[yellow]⚠️ No se encontró config.json. Se usará el PATH del sistema.[/yellow]")

# Logging
logging.basicConfig(
    filename='conversion.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------- Funciones ----------
def listar_archivos_mp4():
    return [f for f in os.listdir('.') if f.lower().endswith('.mp4')]

def seleccionar_archivo(archivos):
    table = Table(title="Archivos MP4 disponibles", header_style="bold cyan")
    table.add_column("N°", justify="right")
    table.add_column("Archivo", justify="left")
    for i, a in enumerate(archivos, start=1):
        table.add_row(str(i), a)
    console.print(table)
    return archivos[IntPrompt.ask("Selecciona el número del archivo", choices=[str(i) for i in range(1,len(archivos)+1)])-1]

def convertir_a_mkv(archivo):
    salida = os.path.splitext(archivo)[0] + ".mkv"
    console.rule(f"[bold green]Convirtiendo: {archivo} -> {salida}")
    try:
        probe = ffmpeg.probe(archivo, cmd=ffprobe_path)
        duracion = float(probe['format']['duration'])

        with Progress(
            SpinnerColumn(),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeRemainingColumn(),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Procesando", total=duracion)

            process = (
                ffmpeg
                .input(archivo)
                .output(salida, c='copy')
                .global_args('-progress', 'pipe:1', '-nostats')
                .run_async(pipe_stdout=True, pipe_stderr=True, cmd=ffmpeg_path)
            )

            for line in iter(process.stdout.readline, b''):
                line = line.decode().strip()
                if line.startswith("out_time="):
                    h, m, s = line.split('=')[1].split(':')
                    segundos = int(h)*3600 + int(m)*60 + float(s)
                    progress.update(task, completed=segundos)

            process.wait()

        if process.returncode == 0:
            logging.info(f"Conversión exitosa: {archivo} -> {salida}")
            console.print(f"[bold green]✅ Conversión completada:[/bold green] {salida}")
        else:
            logging.error(f"Error en la conversión de {archivo}")
            console.print("[bold red]❌ Ocurrió un error. Revisa conversion.log[/bold red]")

    except Exception as e:
        logging.exception(f"Excepción durante la conversión: {e}")
        console.print("[bold red]❌ Error inesperado. Detalles en conversion.log[/bold red]")

def main():
    console.print("[bold cyan]=== Convertidor MP4 → MKV ===[/bold cyan]")
    archivos = listar_archivos_mp4()
    if not archivos:
        console.print("[bold yellow]No se encontraron archivos MP4 en esta carpeta.[/bold yellow]")
        return
    archivo = seleccionar_archivo(archivos)
    convertir_a_mkv(archivo)

if __name__ == "__main__":
    main()
