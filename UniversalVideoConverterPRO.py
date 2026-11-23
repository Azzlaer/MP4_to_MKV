"""Desktop video converter: Tkinter GUI, FFmpeg queue and GPU profiles."""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

EXTENSIONS = {".avi", ".mp4", ".mov", ".wmv", ".flv", ".webm", ".mpeg", ".mpg",
              ".ts", ".mts", ".m2ts", ".vob", ".m4v", ".3gp", ".ogv", ".mkv"}
OUTPUTS = {"MKV": "mkv", "MP4": "mp4", "WEBM": "webm", "AVI": "avi"}
ENCODERS = {
    "H.264": {"CPU": "libx264", "NVIDIA": "h264_nvenc", "Intel": "h264_qsv", "AMD": "h264_amf"},
    "H.265": {"CPU": "libx265", "NVIDIA": "hevc_nvenc", "Intel": "hevc_qsv", "AMD": "hevc_amf"},
    "AV1": {"CPU": "libsvtav1", "NVIDIA": "av1_nvenc", "Intel": "av1_qsv", "AMD": "av1_amf"},
}
# Conservative container compatibility: do not generate invalid codec/container pairs.
COMPAT = {
    "MKV": {"H.264", "H.265", "AV1"},
    "MP4": {"H.264", "H.265", "AV1"},
    "WEBM": {"AV1"},
    "AVI": {"H.264"},
}

def binary(name):
    return shutil.which(name) or str(Path(__file__).parent / (name + ".exe"))

def inspect(path, ffprobe=None):
    p = subprocess.run([ffprobe or binary("ffprobe"), "-v", "error", "-show_streams",
                        "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "ffprobe failed")
    return json.loads(p.stdout)

def available_encoders(ffmpeg=None):
    try:
        p = subprocess.run([ffmpeg or binary("ffmpeg"), "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=20)
        # FFmpeg flags contain V/A/S followed by six capability positions.
        # Examples: " V....D libx264" and " V..... h264_nvenc".
        if p.returncode:
            return set()
        found = set()
        for line in p.stdout.splitlines():
            match = re.match(r"^\\s*([VAS])([.A-Z]{5})\\s+(\\S+)", line)
            if match:
                found.add(match.group(3))
        return found
    except (OSError, subprocess.TimeoutExpired):
        return set()

@dataclass
class Job:
    source: Path
    status: str = "Pendiente"
    progress: float = 0.0
    detail: str = ""

def selected_streams(info, kind, selection):
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == kind]
    if selection == "Ninguna":
        return []
    if selection == "Todas":
        return [s["index"] for s in streams]
    try:
        index = int(selection.split(":", 1)[0])
    except (ValueError, IndexError):
        return [s["index"] for s in streams]
    return [index] if any(s["index"] == index for s in streams) else []

def build_command(ffmpeg, source, output, info, fmt, codec, device, audio, subtitles, encoders):
    if codec not in COMPAT[fmt]:
        raise ValueError(f"{codec} no es compatible con el perfil {fmt}")
    encoder = ENCODERS[codec][device]
    if encoder not in encoders:
        if device == "CPU" and codec == "AV1":
            encoder = next((item for item in ("libsvtav1", "libaom-av1", "librav1e")
                            if item in encoders), encoder)
        elif device == "CPU" and codec == "H.264":
            encoder = next((item for item in ("libx264", "libopenh264", "h264")
                            if item in encoders), encoder)
        if encoder not in encoders:
            raise ValueError(f"Codificador no disponible en FFmpeg: {encoder}")
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise ValueError("No hay pista de video")
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source)]
    args += ["-map", "0:v:0"]
    for index in selected_streams(info, "audio", audio):
        args += ["-map", f"0:{index}"]
    for index in selected_streams(info, "subtitle", subtitles):
        args += ["-map", f"0:{index}"]
    args += ["-map_metadata", "0", "-map_chapters", "0", "-c:v", encoder]
    if device == "CPU":
        args += ["-crf", "25" if codec == "AV1" else "22"]
    else:
        args += ["-b:v", "5M"]
    if fmt == "WEBM":
        args += ["-c:a", "libopus", "-c:s", "webvtt"]
    elif fmt == "AVI":
        args += ["-c:a", "libmp3lame", "-sn"]
    else:
        args += ["-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text" if fmt == "MP4" else "srt"]
    args += ["-progress", "pipe:1", "-nostats", str(output)]
    return args

class DesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Universal Video Converter PRO — Fase 2")
        self.geometry("1050x700")
        self.minsize(820, 540)
        self.configure(bg="#111827")
        self.jobs = []
        self.events = queue.Queue()
        self.worker = None
        self.process = None
        self.cancel = threading.Event()
        self.ffmpeg = binary("ffmpeg")
        self.ffprobe = binary("ffprobe")
        self.encoders = available_encoders(self.ffmpeg)
        self.format = tk.StringVar(value="MKV")
        self.codec = tk.StringVar(value="H.264")
        self.device = tk.StringVar(value="CPU")
        self.audio = tk.StringVar(value="Todas")
        self.subtitles = tk.StringVar(value="Ninguna")
        self.output = tk.StringVar(value="")
        self.recursive = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Listo")
        self._layout()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _layout(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#111827", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(22, 12), font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 10))
        title = tk.Label(self, text="UNIVERSAL VIDEO CONVERTER PRO",
                         bg="#111827", fg="#f9fafb", font=("Segoe UI", 20, "bold"))
        title.pack(anchor="w", padx=22, pady=(18, 5))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=10)
        self.queue_tab = ttk.Frame(self.tabs, padding=15)
        self.profile_tab = ttk.Frame(self.tabs, padding=15)
        self.tracks_tab = ttk.Frame(self.tabs, padding=15)
        self.settings_tab = ttk.Frame(self.tabs, padding=15)
        for tab, name in [(self.queue_tab, "Cola"), (self.profile_tab, "Codificación"),
                          (self.tracks_tab, "Audio y subtítulos"), (self.settings_tab, "Opciones")]:
            self.tabs.add(tab, text=name)
        buttons = ttk.Frame(self.queue_tab)
        buttons.pack(fill="x", pady=(0, 12))
        for label, callback in [("Añadir archivos", self._files), ("Añadir carpeta", self._folder),
                                ("Eliminar selección", self._remove), ("Iniciar", self._start),
                                ("Cancelar", self._cancel)]:
            ttk.Button(buttons, text=label, command=callback).pack(side="left", padx=3)
        self.tree = ttk.Treeview(self.queue_tab, columns=("file", "state", "progress"),
                                 show="headings", selectmode="extended")
        for name, heading, width in [("file", "Archivo", 590), ("state", "Estado", 160),
                                      ("progress", "Progreso", 100)]:
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, stretch=name == "file")
        self.tree.pack(fill="both", expand=True)
        ttk.Label(self.queue_tab, textvariable=self.status).pack(anchor="w", pady=10)
        self._combo(self.profile_tab, "Formato de salida", self.format, list(OUTPUTS))
        self._combo(self.profile_tab, "Códec de video", self.codec, list(ENCODERS))
        self._combo(self.profile_tab, "Dispositivo de codificación", self.device,
                    ["CPU", "NVIDIA", "Intel", "AMD"])
        ttk.Label(self.profile_tab, text="GPU requiere hardware, controladores y codificador FFmpeg compatibles.").pack(anchor="w", pady=20)
        self._combo(self.tracks_tab, "Pista de audio", self.audio, ["Todas", "Ninguna"])
        self._combo(self.tracks_tab, "Subtítulos", self.subtitles, ["Todas", "Ninguna"])
        ttk.Button(self.tracks_tab, text="Inspeccionar archivo seleccionado",
                   command=self._tracks).pack(anchor="w", pady=15)
        ttk.Label(self.tracks_tab, text="Las pistas gráficas pueden no convertirse a subtítulos de texto.").pack(anchor="w")
        ttk.Label(self.settings_tab, text="Carpeta de salida (vacío: junto al original)").pack(anchor="w")
        ttk.Entry(self.settings_tab, textvariable=self.output, width=85).pack(anchor="w", pady=8)
        ttk.Button(self.settings_tab, text="Examinar", command=self._output).pack(anchor="w")
        ttk.Checkbutton(self.settings_tab, text="Buscar archivos en subcarpetas",
                        variable=self.recursive).pack(anchor="w", pady=20)
        ttk.Label(self.settings_tab, text=f"FFmpeg: {self.ffmpeg}\nFFprobe: {self.ffprobe}").pack(anchor="w")

    def _combo(self, parent, label, var, values):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(14, 3))
        widget = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=40)
        widget.pack(anchor="w")
        return widget

    def _add(self, paths):
        known = {j.source.resolve() for j in self.jobs}
        for path in paths:
            p = Path(path)
            if p.suffix.lower() in EXTENSIONS and p.is_file() and p.resolve() not in known:
                self.jobs.append(Job(p))
                known.add(p.resolve())
        self._refresh()

    def _files(self):
        self._add(filedialog.askopenfilenames(title="Seleccionar videos"))

    def _folder(self):
        folder = filedialog.askdirectory()
        if folder:
            iterator = Path(folder).rglob("*") if self.recursive.get() else Path(folder).glob("*")
            self._add(p for p in iterator if p.is_file())

    def _output(self):
        value = filedialog.askdirectory()
        if value:
            self.output.set(value)

    def _remove(self):
        if self.worker and self.worker.is_alive():
            return
        selected = set(self.tree.selection())
        self.jobs = [j for i, j in enumerate(self.jobs) if str(i) not in selected]
        self._refresh()

    def _tracks(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Pistas", "Selecciona un archivo de la cola.")
            return
        try:
            info = inspect(self.jobs[int(selection[0])].source, self.ffprobe)
        except Exception as exc:
            messagebox.showerror("FFprobe", str(exc))
            return
        audio = ["Todas", "Ninguna"]
        subtitles = ["Todas", "Ninguna"]
        for stream in info.get("streams", []):
            kind = stream.get("codec_type")
            if kind not in ("audio", "subtitle"):
                continue
            language = stream.get("tags", {}).get("language", "sin idioma")
            entry = f"{stream['index']}: {stream.get('codec_name', '?')} ({language})"
            (audio if kind == "audio" else subtitles).append(entry)
        for tab, variable, values in [(self.tracks_tab, self.audio, audio),
                                       (self.tracks_tab, self.subtitles, subtitles)]:
            for child in tab.winfo_children():
                if isinstance(child, ttk.Combobox) and child.cget("textvariable") == str(variable):
                    child.configure(values=values)
            variable.set(values[0])
        messagebox.showinfo("Pistas", "Pistas detectadas. Selecciona las que deseas conservar.")

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, job in enumerate(self.jobs):
            self.tree.insert("", "end", iid=str(i),
                             values=(str(job.source), job.status, f"{job.progress:.1f}%"))

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.jobs:
            messagebox.showinfo("Cola", "Añade videos antes de iniciar.")
            return
        if self.codec.get() not in COMPAT[self.format.get()]:
            messagebox.showerror("Perfil", "El códec elegido no es compatible con el contenedor.")
            return
        if ENCODERS[self.codec.get()][self.device.get()] not in self.encoders:
            messagebox.showerror("Codificador", "El codificador seleccionado no está disponible en FFmpeg.")
            return
        settings = (self.format.get(), self.codec.get(), self.device.get(),
                    self.audio.get(), self.subtitles.get(), self.output.get())
        self.cancel.clear()
        self.worker = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self.worker.start()

    def _run(self, settings):
        fmt, codec, device, audio, subs, output_dir = settings
        for index, job in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            if job.status == "Completado":
                continue
            dest = (Path(output_dir) if output_dir else job.source.parent) / (job.source.stem + "." + OUTPUTS[fmt])
            temp = dest.with_name(dest.stem + ".converting." + OUTPUTS[fmt])
            if dest.resolve() == job.source.resolve() or dest.exists() or temp.exists():
                self.events.put((index, "Omitido (destino existente)", 0))
                continue
            try:
                info = inspect(job.source, self.ffprobe)
                duration = float(info.get("format", {}).get("duration") or 0)
                dest.parent.mkdir(parents=True, exist_ok=True)
                cmd = build_command(self.ffmpeg, job.source, temp, info, fmt, codec,
                                    device, audio, subs, self.encoders)
                self.events.put((index, "Convirtiendo", 0))
                error_log = root_dir() / "ffmpeg_last_error.log"
                with error_log.open("w", encoding="utf-8", errors="replace") as error_handle:
                    self.process = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=error_handle,
                        text=True, encoding="utf-8", errors="replace")
                    for line in self.process.stdout:
                        if self.cancel.is_set():
                            self.process.terminate()
                            break
                        if line.startswith(("out_time_us=", "out_time_ms=")):
                            try:
                                seconds = int(line.split("=", 1)[1]) / 1_000_000
                                progress = min(99.9, seconds / duration * 100) if duration else 0
                                self.events.put((index, "Convirtiendo", progress))
                            except ValueError:
                                pass
                returncode = self.process.wait()
                self.process = None
                if self.cancel.is_set():
                    result_state = "Cancelado"
                    detail = "Cancelado por usuario"
                    self.events.put((index, result_state, 0))
                    break
                if returncode:
                    try:
                        diagnostics = error_log.read_text(encoding="utf-8", errors="replace")[-1600:]
                    except OSError:
                        diagnostics = ""
                    raise RuntimeError(f"FFmpeg terminó con código {returncode}: {diagnostics.strip()[-400:]}")
                output_info = inspect(temporary, self.ffprobe)
                if not any(stream.get("codec_type") == "video" for stream in output_info.get("streams", [])):
                    raise RuntimeError("La salida no contiene video")
                temporary.replace(destination)
                result_state = "Completado"
                self.events.put((index, result_state, 100))
            except Exception as error:
                detail = str(error)
                self.events.put((index, "Error: " + detail[:90], 0))
            finally:
                self.process = None
                temporary.unlink(missing_ok=True)
                totals[result_state] += 1
                finished = datetime.now().astimezone()
                elapsed = time.monotonic() - start_tick
                self.events.put(("log", f"FIN archivo={job.source.name} estado={result_state} inicio={started.isoformat(timespec='seconds')} fin={finished.isoformat(timespec='seconds')} duración={elapsed:.1f}s origen={job.source.suffix.lower()} salida={destination.suffix.lower()} modo={profile} destino={destination} detalle={detail}"))
        self.events.put(("complete", totals, self.shutdown_requested and not self.cancel.is_set()
                         and totals["Error"] == 0))

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self._log(event[1])
                elif event[0] == "complete":
                    _, totals, poweroff = event
                    summary = "Cola finalizada: " + ", ".join(f"{key}={value}" for key, value in totals.items())
                    self.status.set(summary)
                    self._log(summary)
                    if poweroff:
                        self.shutdown_left = self.shutdown_delay
                        self._log(f"Apagado programado en {self.shutdown_left} segundos. Usa Cancelar apagado para evitarlo.")
                        self._shutdown_tick()
                else:
                    index, state, progress = event
                    if index < len(self.jobs):
                        self.jobs[index].status = state
                        self.jobs[index].progress = progress
                        self.tree.item(str(index), values=(str(self.jobs[index].source),
                                                           state, f"{progress:.1f}%"))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _shutdown_tick(self):
        self.shutdown_after_id = None
        if self.shutdown_left <= 0:
            self._log("Cuenta regresiva completada; solicitando apagado de Windows.")
            if os.name != "nt":
                self._log("ERROR: apagado automático disponible solo en Windows.")
                return
            try:
                result = subprocess.run(["shutdown", "/s", "/t", "0"],
                                        capture_output=True, text=True, timeout=10)
                if result.returncode:
                    self._log(f"ERROR: Windows rechazó el apagado: {result.stderr.strip()}")
            except (OSError, subprocess.TimeoutExpired) as error:
                self._log(f"ERROR de apagado: {error}")
            return
        self.status.set(f"Cola terminada. Apagado en {self.shutdown_left} segundos.")
        self.shutdown_left -= 1
        self.shutdown_after_id = self.after(1000, self._shutdown_tick)

    def _stop_shutdown(self):
        if self.shutdown_after_id is not None:
            self.after_cancel(self.shutdown_after_id)
            self.shutdown_after_id = None
            self._log("Apagado automático cancelado.")
        self.shutdown_left = 0

    def _cancel(self):
        super()._cancel()
        self._log("Cancelación solicitada por el usuario.")

    def _close(self):
        if self.worker and self.worker.is_alive():
            self._cancel()
            self._log("Cierre pospuesto hasta que el proceso termine.")
            return
        self._stop_shutdown()
        self.destroy()


if __name__ == '__main__':
    EnhancedApp().mainloop()
