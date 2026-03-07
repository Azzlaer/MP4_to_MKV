#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import threading
import queue
import subprocess
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------- Config / Logging ----------------
APP_TITLE = "🎬 Video Converter GUI PRO"
CONFIG_FILE = "config.json"
LOG_FILE = "conversion.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

COMMON_VIDEO_EXTS = ["mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "mpg", "mpeg", "m4v", "3gp"]

# ---------------- Helpers ----------------
def load_config():
    cfg = {
        "ffmpeg_path": "ffmpeg",
        "ffprobe_path": "ffprobe",
        "default_output_ext": "mkv",
        "default_mode": "copy",  # copy | encode
        "overwrite": False,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def normalize_ext(ext):
    return ext.lower().replace(".", "").strip()

def human_size(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def safe_basename(path):
    try:
        return os.path.basename(path)
    except Exception:
        return str(path)

def probe_duration(ffprobe, file):
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "").strip()
    if not out:
        raise RuntimeError("No pude obtener duración con ffprobe.")
    return float(out)

def open_file_in_os(path):
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", path])
        else:
            subprocess.Popen(["open", path])
    except Exception as e:
        raise RuntimeError(f"No se pudo abrir el archivo: {e}")

def which_exists(exe_path):
    # Si es ruta directa
    if exe_path and os.path.isfile(exe_path):
        return True
    # Si es comando del PATH
    try:
        p = subprocess.run([exe_path, "-version"], capture_output=True, text=True)
        return p.returncode == 0
    except Exception:
        return False

def fmt_time(seconds):
    try:
        seconds = max(0.0, float(seconds))
    except Exception:
        return "--:--"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"

# ---------------- Worker ----------------
class ConverterWorker(threading.Thread):
    """
    Envía eventos a la UI via queue:
      - ("duration", float)
      - ("progress", float_seconds)
      - ("stats", dict { 'pct','eta','speed','elapsed' })
      - ("log", str)
      - ("done", dict { 'success': bool, 'out_file': str, 'returncode': int })
      - ("error", str)
    """
    def __init__(self, q_ui, cfg, in_file, out_file, mode, overwrite):
        super().__init__(daemon=True)
        self.q_ui = q_ui
        self.cfg = cfg
        self.in_file = in_file
        self.out_file = out_file
        self.mode = mode
        self.overwrite = overwrite
        self._stop_event = threading.Event()
        self.process = None
        self.start_time = None
        self.duration = None

    def send(self, k, v=None):
        self.q_ui.put((k, v))

    def stop(self):
        self._stop_event.set()
        try:
            if self.process and self.process.poll() is None:
                # Terminar ffmpeg
                self.process.terminate()
                time.sleep(0.2)
                if self.process.poll() is None:
                    self.process.kill()
        except Exception:
            pass

    def run(self):
        try:
            if not which_exists(self.cfg["ffprobe_path"]):
                raise FileNotFoundError("ffprobe no encontrado. Revisa config.json o PATH.")
            if not which_exists(self.cfg["ffmpeg_path"]):
                raise FileNotFoundError("ffmpeg no encontrado. Revisa config.json o PATH.")

            self.duration = probe_duration(self.cfg["ffprobe_path"], self.in_file)
            self.send("duration", self.duration)

            cmd = [self.cfg["ffmpeg_path"]]
            cmd += ["-y"] if self.overwrite else ["-n"]
            cmd += ["-i", self.in_file]

            if self.mode == "copy":
                cmd += ["-c", "copy"]
            else:
                cmd += [
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-b:a", "192k"
                ]

            cmd += [
                "-progress", "pipe:1",
                "-nostats",
                self.out_file
            ]

            logging.info("CMD: %s", " ".join(cmd))
            self.send("log", "CMD: " + " ".join(cmd))

            self.start_time = time.time()

            # Unificamos stdout+stderr para no colgarnos por buffer
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            out_time_sec = 0.0

            # Parseo -progress (key=value por línea)
            for raw in self.process.stdout:
                if self._stop_event.is_set():
                    break

                line = raw.strip()
                if not line:
                    continue

                # Log liviano (solo algunas líneas útiles)
                if line.startswith("frame=") or line.startswith("fps=") or line.startswith("speed="):
                    self.send("log", line)

                if line.startswith("out_time_ms="):
                    # microsegundos -> segundos
                    try:
                        out_time_sec = int(line.split("=", 1)[1]) / 1_000_000.0
                        self.send("progress", out_time_sec)
                    except Exception:
                        pass

                elif line.startswith("out_time="):
                    # HH:MM:SS.micro
                    try:
                        t = line.split("=", 1)[1]
                        h, m, s = t.split(":")
                        out_time_sec = int(h) * 3600 + int(m) * 60 + float(s)
                        self.send("progress", out_time_sec)
                    except Exception:
                        pass

                elif line.startswith("speed="):
                    # speed=1.23x
                    speed = line.split("=", 1)[1].strip()
                    # Stats cada tick si ya tenemos duración
                    if self.duration and self.start_time:
                        elapsed = time.time() - self.start_time
                        pct = min(100.0, (out_time_sec / self.duration) * 100.0) if self.duration > 0 else 0.0
                        eta = max(0.0, self.duration - out_time_sec)
                        self.send("stats", {
                            "pct": pct,
                            "eta": eta,
                            "speed": speed,
                            "elapsed": elapsed
                        })

                elif line.startswith("progress="):
                    # progress=continue / progress=end
                    if line.endswith("end"):
                        break

            # Esperar salida
            try:
                self.process.wait(timeout=5)
            except Exception:
                pass

            rc = self.process.returncode if self.process else 1
            success = (rc == 0) and (not self._stop_event.is_set())

            if self._stop_event.is_set():
                self.send("done", {"success": False, "out_file": self.out_file, "returncode": rc})
                return

            self.send("done", {"success": success, "out_file": self.out_file, "returncode": rc})

        except Exception as e:
            logging.exception("Worker error")
            self.send("error", str(e))
            self.send("done", {"success": False, "out_file": self.out_file, "returncode": 1})


# ---------------- GUI ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1050x650")
        self.minsize(980, 610)

        self.cfg = load_config()
        self.q_ui = queue.Queue()
        self.worker = None

        # Cola
        self.queue_files = []
        self.queue_index = 0
        self.running_queue = False
        self.last_out_file = None

        # Vars
        self.folder_var = tk.StringVar(value=os.getcwd())
        self.out_ext_var = tk.StringVar(value=self.cfg.get("default_output_ext", "mkv"))
        self.mode_var = tk.StringVar(value=self.cfg.get("default_mode", "copy"))
        self.overwrite_var = tk.BooleanVar(value=bool(self.cfg.get("overwrite", False)))

        self.ffmpeg_var = tk.StringVar(value=self.cfg.get("ffmpeg_path", "ffmpeg"))
        self.ffprobe_var = tk.StringVar(value=self.cfg.get("ffprobe_path", "ffprobe"))

        self.pct_var = tk.StringVar(value="0%")
        self.eta_var = tk.StringVar(value="ETA: --:--")
        self.speed_var = tk.StringVar(value="Speed: --")
        self.elapsed_var = tk.StringVar(value="Elapsed: --:--")

        self._build_ui()
        self.after(120, self._poll_ui_queue)
        self._load_folder()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Carpeta:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="📂 Buscar", command=self._choose_folder).grid(row=0, column=2, padx=(0,6))
        ttk.Button(top, text="🔄 Refrescar", command=self._load_folder).grid(row=0, column=3)

        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)

        cols = ("name", "ext", "size", "path")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("name", text="Archivo")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("size", text="Tamaño")
        self.tree.heading("path", text="Ruta")
        self.tree.column("name", width=360)
        self.tree.column("ext", width=60, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("path", width=420)
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(mid, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        # Opciones
        right = ttk.LabelFrame(self, text="Opciones", padding=10)
        right.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        for i in range(6):
            right.columnconfigure(i, weight=1)

        ttk.Label(right, text="Formato destino").grid(row=0, column=0, sticky="w")
        ttk.Combobox(right, values=COMMON_VIDEO_EXTS, textvariable=self.out_ext_var,
                     state="readonly", width=10).grid(row=0, column=1, sticky="w", padx=(0,10))

        ttk.Radiobutton(right, text="Copy (rápido)", variable=self.mode_var, value="copy").grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(right, text="Encode (H.264)", variable=self.mode_var, value="encode").grid(row=0, column=3, sticky="w")

        ttk.Checkbutton(right, text="Sobrescribir", variable=self.overwrite_var).grid(row=0, column=4, sticky="w")

        ttk.Button(right, text="⚙ Config FFmpeg", command=self._open_cfg_window).grid(row=0, column=5, sticky="e")

        # Botones
        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.grid(row=3, column=0, sticky="ew")
        for i in range(6):
            btns.columnconfigure(i, weight=1)

        ttk.Button(btns, text="▶ Convertir 1", command=self._convert_single).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(btns, text="▶ Convertir seleccionados", command=self._convert_selected).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(btns, text="▶ Convertir TODOS", command=self._convert_all).grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        ttk.Button(btns, text="⛔ Cancelar", command=self._cancel_queue).grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        ttk.Button(btns, text="📂 Abrir carpeta", command=self._open_folder).grid(row=0, column=4, sticky="ew", padx=4, pady=4)
        ttk.Button(btns, text="🎞 Abrir convertido", command=self._open_last_output).grid(row=0, column=5, sticky="ew", padx=4, pady=4)

        # Progreso
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")

        stats = ttk.Frame(bottom)
        stats.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for i in range(4):
            stats.columnconfigure(i, weight=1)

        ttk.Label(stats, textvariable=self.pct_var).grid(row=0, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.eta_var).grid(row=0, column=1, sticky="w")
        ttk.Label(stats, textvariable=self.speed_var).grid(row=0, column=2, sticky="w")
        ttk.Label(stats, textvariable=self.elapsed_var).grid(row=0, column=3, sticky="w")

        self.lbl_status = ttk.Label(bottom, text="Listo.")
        self.lbl_status.grid(row=2, column=0, sticky="w", pady=(6, 0))

        # Log panel
        log_frame = ttk.LabelFrame(self, text="Log", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(5, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.txt_log = tk.Text(log_frame, height=8, wrap="word")
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        self.txt_log.configure(state="disabled")

        log_sb = ttk.Scrollbar(log_frame, command=self.txt_log.yview)
        log_sb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=log_sb.set)

    # ---------------- Actions ----------------
    def _log(self, msg):
        logging.info(msg)
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _open_folder(self):
        folder = self.folder_var.get().strip()
        if folder and os.path.isdir(folder):
            try:
                open_file_in_os(folder)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _open_last_output(self):
        if not self.last_out_file or not os.path.isfile(self.last_out_file):
            messagebox.showinfo("Nada", "Aún no hay un archivo convertido para abrir.")
            return
        try:
            open_file_in_os(self.last_out_file)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or os.getcwd())
        if not folder:
            return
        self.folder_var.set(folder)
        self._load_folder()

    def _load_folder(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            return

        self.tree.delete(*self.tree.get_children())

        try:
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if os.path.isfile(p):
                    ext = normalize_ext(os.path.splitext(f)[1])
                    if ext in COMMON_VIDEO_EXTS:
                        self.tree.insert(
                            "", "end",
                            values=(f, ext, human_size(os.path.getsize(p)), p)
                        )
            self.lbl_status.config(text=f"Listo. Archivos cargados desde: {folder}")
        except Exception as e:
            self._log("ERROR cargando carpeta: " + str(e))

    def _selected_paths(self):
        sel = self.tree.selection()
        if not sel:
            return []
        paths = []
        for iid in sel:
            vals = self.tree.item(iid, "values")
            if vals and len(vals) >= 4:
                paths.append(vals[3])
        return paths

    def _convert_single(self):
        paths = self._selected_paths()
        if not paths:
            messagebox.showwarning("Nada", "Selecciona un archivo.")
            return
        self.queue_files = [paths[0]]
        self._start_queue()

    def _convert_selected(self):
        paths = self._selected_paths()
        if not paths:
            messagebox.showwarning("Nada", "Selecciona archivos.")
            return
        self.queue_files = paths
        self._start_queue()

    def _convert_all(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showwarning("Vacío", "No hay archivos.")
            return
        all_paths = []
        for iid in items:
            vals = self.tree.item(iid, "values")
            if vals and len(vals) >= 4:
                all_paths.append(vals[3])
        self.queue_files = all_paths
        self._start_queue()

    def _start_queue(self):
        if self.running_queue:
            messagebox.showinfo("En progreso", "Ya hay una cola ejecutándose.")
            return

        # Guardar config actual
        self.cfg["ffmpeg_path"] = self.ffmpeg_var.get().strip() or "ffmpeg"
        self.cfg["ffprobe_path"] = self.ffprobe_var.get().strip() or "ffprobe"
        self.cfg["default_output_ext"] = self.out_ext_var.get().strip() or "mkv"
        self.cfg["default_mode"] = self.mode_var.get().strip() or "copy"
        self.cfg["overwrite"] = bool(self.overwrite_var.get())
        save_config(self.cfg)

        self.queue_index = 0
        self.running_queue = True
        self._reset_progress_ui()
        self._process_next()

    def _reset_progress_ui(self):
        self.progress["value"] = 0
        self.progress["maximum"] = 100
        self.pct_var.set("0%")
        self.eta_var.set("ETA: --:--")
        self.speed_var.set("Speed: --")
        self.elapsed_var.set("Elapsed: --:--")

    def _process_next(self):
        if self.queue_index >= len(self.queue_files):
            self.running_queue = False
            self.lbl_status.config(text="✅ Todas las conversiones completadas.")
            messagebox.showinfo("Listo", "✅ Todas las conversiones fueron completadas.")
            return

        in_file = self.queue_files[self.queue_index]
        out_file = os.path.splitext(in_file)[0] + "." + normalize_ext(self.out_ext_var.get())

        self.last_out_file = out_file
        self.queue_index += 1

        self.progress["value"] = 0
        self.progress["maximum"] = 1  # luego lo ajusta duration
        self.pct_var.set("0%")
        self.eta_var.set("ETA: --:--")
        self.speed_var.set("Speed: --")
        self.elapsed_var.set("Elapsed: --:--")

        self.lbl_status.config(
            text=f"Procesando {self.queue_index}/{len(self.queue_files)}: {safe_basename(in_file)}"
        )
        self._log(f"--- Iniciando: {in_file}")

        self.worker = ConverterWorker(
            self.q_ui,
            self.cfg,
            in_file,
            out_file,
            self.mode_var.get(),
            self.overwrite_var.get()
        )
        self.worker.start()

    def _cancel_queue(self):
        if self.worker:
            try:
                self.worker.stop()
            except Exception:
                pass
        self.queue_files = []
        self.running_queue = False
        self.lbl_status.config(text="⛔ Cola cancelada.")
        self._log("⛔ Cola cancelada por el usuario.")

    def _open_cfg_window(self):
        win = tk.Toplevel(self)
        win.title("⚙ Configuración FFmpeg")
        win.geometry("720x240")
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="ffmpeg (ruta o comando):").grid(row=0, column=0, sticky="w")
        e1 = ttk.Entry(frm, textvariable=self.ffmpeg_var)
        e1.grid(row=0, column=1, sticky="ew", padx=8)

        ttk.Label(frm, text="ffprobe (ruta o comando):").grid(row=1, column=0, sticky="w")
        e2 = ttk.Entry(frm, textvariable=self.ffprobe_var)
        e2.grid(row=1, column=1, sticky="ew", padx=8)

        def browse_ffmpeg():
            p = filedialog.askopenfilename(title="Selecciona ffmpeg.exe")
            if p:
                self.ffmpeg_var.set(p)

        def browse_ffprobe():
            p = filedialog.askopenfilename(title="Selecciona ffprobe.exe")
            if p:
                self.ffprobe_var.set(p)

        ttk.Button(frm, text="Buscar...", command=browse_ffmpeg).grid(row=0, column=2, padx=6)
        ttk.Button(frm, text="Buscar...", command=browse_ffprobe).grid(row=1, column=2, padx=6)

        info = (
            "Tip: Si no quieres editar el PATH, puedes apuntar directo a:\n"
            "  C:\\ffmpeg\\bin\\ffmpeg.exe\n"
            "  C:\\ffmpeg\\bin\\ffprobe.exe\n"
        )
        ttk.Label(frm, text=info).grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))

        def save_and_close():
            self.cfg["ffmpeg_path"] = self.ffmpeg_var.get().strip() or "ffmpeg"
            self.cfg["ffprobe_path"] = self.ffprobe_var.get().strip() or "ffprobe"
            save_config(self.cfg)
            self._log("✅ Config guardada en config.json")
            win.destroy()

        ttk.Button(frm, text="Guardar", command=save_and_close).grid(row=3, column=2, sticky="e", pady=12)

    # ---------------- UI Queue polling ----------------
    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.q_ui.get_nowait()

                if kind == "duration":
                    # progressbar usa segundos
                    try:
                        dur = float(payload)
                        self.progress["maximum"] = max(1.0, dur)
                        self._log(f"Duración detectada: {dur:.2f}s")
                    except Exception:
                        pass

                elif kind == "progress":
                    try:
                        sec = float(payload)
                        self.progress["value"] = sec
                    except Exception:
                        pass

                elif kind == "stats":
                    # pct/eta/speed/elapsed
                    try:
                        pct = float(payload.get("pct", 0.0))
                        eta = float(payload.get("eta", 0.0))
                        elapsed = float(payload.get("elapsed", 0.0))
                        speed = str(payload.get("speed", "--"))

                        self.pct_var.set(f"{pct:.1f}%")
                        self.eta_var.set(f"ETA: {fmt_time(eta)}")
                        self.speed_var.set(f"Speed: {speed}")
                        self.elapsed_var.set(f"Elapsed: {fmt_time(elapsed)}")
                    except Exception:
                        pass

                elif kind == "log":
                    self._log(str(payload))

                elif kind == "error":
                    self._log("ERROR: " + str(payload))

                elif kind == "done":
                    success = bool(payload.get("success", False))
                    out_file = payload.get("out_file", "")
                    rc = payload.get("returncode", -1)

                    if success:
                        # Visual: completar barra
                        self.progress["value"] = self.progress["maximum"]
                        self.lbl_status.config(text=f"✅ Terminado: {safe_basename(out_file)}")
                        self._log(f"✅ Conversión OK (rc={rc}): {out_file}")
                        messagebox.showinfo("Conversión finalizada", f"✅ Listo:\n{out_file}")
                    else:
                        self.lbl_status.config(text="❌ Error o cancelado")
                        self._log(f"❌ Conversión falló/cancelada (rc={rc})")
                        messagebox.showerror("Error", f"❌ La conversión falló o fue cancelada.\nRevisa {LOG_FILE}.")

                    # Reset barra para siguiente archivo (si hay cola)
                    self.progress["value"] = 0
                    self.pct_var.set("0%")
                    self.eta_var.set("ETA: --:--")
                    self.speed_var.set("Speed: --")
                    self.elapsed_var.set("Elapsed: --:--")

                    if self.running_queue:
                        self._process_next()

        except queue.Empty:
            pass

        self.after(120, self._poll_ui_queue)


if __name__ == "__main__":
    App().mainloop()