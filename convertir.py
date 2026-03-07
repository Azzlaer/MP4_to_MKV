import os
import json
import threading
import queue
import subprocess
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------- Config / Logging ----------------
CONFIG_FILE = "config.json"

logging.basicConfig(
    filename="conversion.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

COMMON_VIDEO_EXTS = [
    "mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "mpg", "mpeg", "m4v", "3gp"
]

def load_config():
    cfg = {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg["ffmpeg_path"] = data.get("ffmpeg_path") or cfg["ffmpeg_path"]
                cfg["ffprobe_path"] = data.get("ffprobe_path") or cfg["ffprobe_path"]
        except Exception:
            pass
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def normalize_ext(ext: str) -> str:
    ext = (ext or "").strip().lower()
    if ext.startswith("."):
        ext = ext[1:]
    return ext

def build_ext_set(selection: str):
    selection = (selection or "").strip().lower()
    if selection == "all":
        return set(COMMON_VIDEO_EXTS)
    parts = [normalize_ext(x) for x in selection.split(",") if x.strip()]
    return set([p for p in parts if p])

def list_files_in_folder(folder, exts_set):
    out = []
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            if ext in exts_set:
                out.append(path)
    except Exception:
        return []
    return sorted(out)

def human_size(num_bytes: int) -> str:
    try:
        n = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024.0:
                return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
            n /= 1024.0
        return f"{n:.2f} PB"
    except Exception:
        return "-"

# ---------------- FFprobe helpers ----------------
def probe_duration_seconds(ffprobe_path, input_file) -> float:
    """
    Lee duración usando ffprobe.
    """
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_file
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "ffprobe falló.")
    val = (p.stdout or "").strip()
    if not val:
        raise RuntimeError("No se pudo leer duración.")
    return float(val)

# ---------------- Conversion worker ----------------
class ConverterWorker(threading.Thread):
    def __init__(self, q_ui, cfg, input_file, output_file, mode, overwrite):
        super().__init__(daemon=True)
        self.q_ui = q_ui
        self.cfg = cfg
        self.input_file = input_file
        self.output_file = output_file
        self.mode = mode  # "copy" o "encode"
        self.overwrite = overwrite

    def send(self, kind, payload=None):
        self.q_ui.put((kind, payload))

    def run(self):
        ffmpeg_path = self.cfg["ffmpeg_path"]
        ffprobe_path = self.cfg["ffprobe_path"]

        try:
            dur = probe_duration_seconds(ffprobe_path, self.input_file)
            self.send("duration", dur)

            # Armamos comando ffmpeg
            # Progreso: -progress pipe:1  (stdout)
            # No stats: -nostats
            cmd = [ffmpeg_path]

            if self.overwrite:
                cmd += ["-y"]
            else:
                cmd += ["-n"]

            cmd += ["-i", self.input_file]

            if self.mode == "copy":
                # remux sin recomprimir
                cmd += ["-c", "copy"]
            else:
                # re-encode compatible
                cmd += [
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k"
                ]
                out_ext = os.path.splitext(self.output_file)[1].lower().lstrip(".")
                if out_ext in ("mp4", "m4v", "mov"):
                    cmd += ["-movflags", "+faststart"]

            cmd += ["-progress", "pipe:1", "-nostats", self.output_file]

            logging.info("CMD: %s", " ".join(cmd))
            self.send("log", "Ejecutando ffmpeg...")

            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Leemos stdout para progreso (key=value)
            # out_time_ms=1234567 o out_time=HH:MM:SS.micro
            while True:
                line = p.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("out_time_ms="):
                    try:
                        ms = int(line.split("=", 1)[1])
                        sec = ms / 1_000_000.0
                        self.send("progress", sec)
                    except Exception:
                        pass
                elif line.startswith("out_time="):
                    t = line.split("=", 1)[1]
                    try:
                        h, m, s = t.split(":")
                        sec = int(h) * 3600 + int(m) * 60 + float(s)
                        self.send("progress", sec)
                    except Exception:
                        pass
                elif line.startswith("progress=") and line.endswith("end"):
                    # final
                    pass

            p.wait()

            if p.returncode == 0:
                logging.info("Conversión OK: %s -> %s", self.input_file, self.output_file)
                self.send("done", True)
            else:
                err = (p.stderr.read() or "").strip()
                logging.error("Conversión FAIL: %s", err)
                self.send("error", err or "FFmpeg falló sin mensaje.")
                self.send("done", False)

        except Exception as e:
            logging.exception("Excepción: %s", str(e))
            self.send("error", str(e))
            self.send("done", False)

# ---------------- GUI App ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎬 Video Converter GUI (FFmpeg)")
        self.geometry("920x560")
        self.minsize(860, 520)

        self.cfg = load_config()
        self.q_ui = queue.Queue()
        self.worker = None

        self.folder_var = tk.StringVar(value=os.getcwd())
        self.exts_var = tk.StringVar(value="mp4")
        self.out_ext_var = tk.StringVar(value="mkv")
        self.mode_var = tk.StringVar(value="copy")
        self.overwrite_var = tk.BooleanVar(value=False)

        self.ffmpeg_var = tk.StringVar(value=self.cfg["ffmpeg_path"])
        self.ffprobe_var = tk.StringVar(value=self.cfg["ffprobe_path"])

        self.selected_input = None
        self.duration = 0.0

        self._build_ui()
        self._refresh_file_list()

        self.after(100, self._poll_ui_queue)

    def _build_ui(self):
        # Top: Folder + extension filters
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Carpeta:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Buscar...", command=self._choose_folder).grid(row=0, column=2, padx=4)

        ttk.Label(top, text="Ext a listar (all o mp4,mkv,...):").grid(row=1, column=0, sticky="w", pady=(10,0))
        ttk.Entry(top, textvariable=self.exts_var).grid(row=1, column=1, sticky="ew", padx=6, pady=(10,0))
        ttk.Button(top, text="Refrescar", command=self._refresh_file_list).grid(row=1, column=2, padx=4, pady=(10,0))

        top.columnconfigure(1, weight=1)

        # Middle: Files list + options
        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.pack(fill="both", expand=True)

        # Left: Treeview
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)

        cols = ("name", "ext", "size")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)
        self.tree.heading("name", text="Archivo")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("size", text="Tamaño")
        self.tree.column("name", width=560, anchor="w")
        self.tree.column("ext", width=70, anchor="center")
        self.tree.column("size", width=110, anchor="e")

        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select_file)

        # Right: Options panel
        right = ttk.LabelFrame(mid, text="Opciones", padding=10)
        right.pack(side="right", fill="y", padx=(10, 0))

        ttk.Label(right, text="Formato destino:").pack(anchor="w")
        out_combo = ttk.Combobox(right, textvariable=self.out_ext_var, values=COMMON_VIDEO_EXTS, state="readonly", width=18)
        out_combo.pack(anchor="w", pady=(2, 10))

        ttk.Label(right, text="Modo:").pack(anchor="w")
        ttk.Radiobutton(right, text="Copy (remux rápido)", value="copy", variable=self.mode_var).pack(anchor="w")
        ttk.Radiobutton(right, text="Re-encode (x264+aac)", value="encode", variable=self.mode_var).pack(anchor="w", pady=(0, 10))

        ttk.Checkbutton(right, text="Sobrescribir si existe", variable=self.overwrite_var).pack(anchor="w", pady=(0, 10))

        self.btn_convert = ttk.Button(right, text="Convertir", command=self._start_convert, state="disabled")
        self.btn_convert.pack(fill="x", pady=(6, 6))

        ttk.Separator(right).pack(fill="x", pady=10)

        ttk.Label(right, text="FFmpeg:").pack(anchor="w")
        ttk.Entry(right, textvariable=self.ffmpeg_var, width=28).pack(anchor="w", pady=(2, 4))
        ttk.Button(right, text="Elegir ffmpeg.exe", command=lambda: self._pick_exe(self.ffmpeg_var)).pack(fill="x", pady=(0, 8))

        ttk.Label(right, text="FFprobe:").pack(anchor="w")
        ttk.Entry(right, textvariable=self.ffprobe_var, width=28).pack(anchor="w", pady=(2, 4))
        ttk.Button(right, text="Elegir ffprobe.exe", command=lambda: self._pick_exe(self.ffprobe_var)).pack(fill="x")

        ttk.Button(right, text="Guardar config.json", command=self._save_cfg).pack(fill="x", pady=(12, 0))

        # Bottom: Progress + log
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        self.progress = ttk.Progressbar(bottom, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x")

        self.lbl_status = ttk.Label(bottom, text="Listo.")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        self.txt_log = tk.Text(self, height=7, wrap="word")
        self.txt_log.pack(fill="both", padx=10, pady=(0, 10))
        self.txt_log.configure(state="disabled")

    def _log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or os.getcwd())
        if folder:
            self.folder_var.set(folder)
            self._refresh_file_list()

    def _pick_exe(self, var):
        path = filedialog.askopenfilename(
            title="Seleccionar ejecutable",
            filetypes=[("Ejecutables", "*.exe"), ("Todos", "*.*")]
        )
        if path:
            var.set(path)

    def _save_cfg(self):
        self.cfg["ffmpeg_path"] = self.ffmpeg_var.get().strip() or "ffmpeg"
        self.cfg["ffprobe_path"] = self.ffprobe_var.get().strip() or "ffprobe"
        try:
            save_config(self.cfg)
            messagebox.showinfo("OK", "config.json guardado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar config.json:\n{e}")

    def _refresh_file_list(self):
        folder = self.folder_var.get().strip() or os.getcwd()
        exts = build_ext_set(self.exts_var.get())
        if not exts:
            exts = {"mp4"}

        files = list_files_in_folder(folder, exts)

        # Reset selection
        self.selected_input = None
        self.btn_convert.configure(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = 100
        self.lbl_status.configure(text=f"{len(files)} archivo(s) encontrados.")

        for item in self.tree.get_children():
            self.tree.delete(item)

        for fpath in files:
            name = os.path.basename(fpath)
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            size = human_size(os.path.getsize(fpath))
            self.tree.insert("", "end", values=(name, ext, size), tags=(fpath,))

    def _on_select_file(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            self.selected_input = None
            self.btn_convert.configure(state="disabled")
            return
        item = sel[0]
        # Recuperamos ruta desde tag
        tags = self.tree.item(item, "tags")
        if tags:
            self.selected_input = tags[0]
            self.btn_convert.configure(state="normal")
            self.lbl_status.configure(text=f"Seleccionado: {os.path.basename(self.selected_input)}")

    def _start_convert(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("En progreso", "Ya hay una conversión en curso.")
            return

        if not self.selected_input:
            messagebox.showwarning("Sin archivo", "Selecciona un archivo primero.")
            return

        out_ext = normalize_ext(self.out_ext_var.get())
        if not out_ext:
            messagebox.showwarning("Formato destino", "Elige un formato destino.")
            return

        in_file = self.selected_input
        base = os.path.splitext(in_file)[0]
        out_file = base + "." + out_ext

        if os.path.abspath(in_file) == os.path.abspath(out_file):
            messagebox.showerror("Error", "El archivo de salida sería igual al de entrada.")
            return

        overwrite = self.overwrite_var.get()
        if os.path.exists(out_file) and not overwrite:
            messagebox.showwarning("Existe", "El archivo destino ya existe. Activa 'Sobrescribir' o cambia el destino.")
            return

        # Guardar cfg actual (en memoria)
        self.cfg["ffmpeg_path"] = self.ffmpeg_var.get().strip() or "ffmpeg"
        self.cfg["ffprobe_path"] = self.ffprobe_var.get().strip() or "ffprobe"

        mode = self.mode_var.get()
        self.progress["value"] = 0
        self.progress["maximum"] = 100
        self.lbl_status.configure(text="Iniciando...")
        self.btn_convert.configure(state="disabled")

        self._log(f"Input : {in_file}")
        self._log(f"Output: {out_file}")
        self._log(f"Modo  : {mode} | Overwrite: {overwrite}")

        self.worker = ConverterWorker(
            self.q_ui, self.cfg, in_file, out_file, mode, overwrite
        )
        self.worker.start()

    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.q_ui.get_nowait()
                if kind == "duration":
                    self.duration = float(payload) if payload else 0.0
                    # Progressbar en segundos
                    self.progress["value"] = 0
                    self.progress["maximum"] = max(self.duration, 1.0)
                    self.lbl_status.configure(text=f"Duración detectada: {self.duration:.1f}s")
                elif kind == "progress":
                    sec = float(payload) if payload else 0.0
                    self.progress["value"] = min(sec, self.progress["maximum"])
                    pct = (self.progress["value"] / self.progress["maximum"]) * 100.0
                    self.lbl_status.configure(text=f"Convirtiendo... {pct:.0f}%")
                elif kind == "log":
                    self._log(str(payload))
                elif kind == "error":
                    self._log("ERROR: " + str(payload))
                    messagebox.showerror("Error FFmpeg", str(payload))
                elif kind == "done":
                    ok = bool(payload)
                    if ok:
                        self._log("✅ Conversión completada.")
                        self.lbl_status.configure(text="✅ Conversión completada.")
                        messagebox.showinfo("Listo", "Conversión completada.")
                    else:
                        self._log("❌ Conversión fallida. Revisa conversion.log")
                        self.lbl_status.configure(text="❌ Falló. Revisa conversion.log")
                    self.btn_convert.configure(state="normal" if self.selected_input else "disabled")
        except queue.Empty:
            pass

        self.after(120, self._poll_ui_queue)

if __name__ == "__main__":
    app = App()
    app.mainloop()
