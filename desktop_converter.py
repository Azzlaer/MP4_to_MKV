"""Desktop video converter: Tkinter GUI, FFmpeg queue and GPU profiles."""
from __future__ import annotations

import json
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
        return set(re.findall(r"^\s*[VAS\.]{6}\s+(\S+)", p.stdout, re.M))
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
                self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, text=True,
                                                encoding="utf-8", errors="replace")
                for line in self.process.stdout:
                    if self.cancel.is_set():
                        self.process.terminate()
                        break
                    if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                        try:
                            seconds = int(line.split("=", 1)[1]) / 1_000_000
                            self.events.put((index, "Convirtiendo", min(99.9, seconds / duration * 100) if duration else 0))
                        except ValueError:
                            pass
                code = self.process.wait()
                self.process = None
                if self.cancel.is_set():
                    self.events.put((index, "Cancelado", 0))
                    break
                if code:
                    raise RuntimeError(f"FFmpeg terminó con código {code}")
                result = inspect(temp, self.ffprobe)
                if not any(s.get("codec_type") == "video" for s in result.get("streams", [])):
                    raise RuntimeError("La salida no contiene video")
                temp.replace(dest)
                self.events.put((index, "Completado", 100))
            except Exception as exc:
                self.events.put((index, "Error: " + str(exc)[:90], 0))
            finally:
                temp.unlink(missing_ok=True)
        self.events.put((-1, "Cola finalizada", 0))

    def _poll(self):
        try:
            while True:
                index, state, percent = self.events.get_nowait()
                if index < 0:
                    self.status.set(state)
                elif index < len(self.jobs):
                    self.jobs[index].status = state
                    self.jobs[index].progress = percent
                    self.tree.item(str(index), values=(str(self.jobs[index].source),
                                                       state, f"{percent:.1f}%"))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _cancel(self):
        self.cancel.set()
        self.status.set("Cancelando al terminar el proceso actual...")

    def _close(self):
        if self.worker and self.worker.is_alive():
            self._cancel()
            messagebox.showinfo("Conversión", "Cancelación solicitada. Cierra la ventana al finalizar.")
            return
        self.destroy()

if __name__ == "__main__":
    DesktopApp().mainloop()
