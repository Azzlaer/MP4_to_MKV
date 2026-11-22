"""Non-blocking conversion activity log, persistent audit and optional shutdown."""
import os
import sys
import time
import queue
import subprocess
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from desktop_converter import DesktopApp, OUTPUTS, inspect, build_command

def root_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

class EnhancedApp(DesktopApp):
    def __init__(self):
        self.log_file = root_dir() / "conversion.log"
        self.shutdown_after_id = None
        self.shutdown_left = 0
        self.shutdown_requested = False
        self.shutdown_delay = 30
        super().__init__()
        self.output.set(str(root_dir() / "MKV"))
        self._log("Aplicación iniciada; registro persistente: " + str(self.log_file))

    def _layout(self):
        super()._layout()
        ttk.Label(self.queue_tab, text="Registro de actividad (no bloqueante)").pack(anchor="w")
        self.log_box = tk.Listbox(self.queue_tab, height=8, bg="#162033", fg="#f1f5f9",
                                  font=("Consolas", 9))
        self.log_box.pack(fill="x", pady=(4, 10))
        controls = ttk.Frame(self.settings_tab)
        controls.pack(anchor="w", pady=10)
        ttk.Button(controls, text="Guardar en carpeta seleccionada", command=self._output).pack(side="left", padx=4)
        ttk.Button(controls, text="Usar carpeta MKV del ejecutable", command=self._use_mkv).pack(side="left", padx=4)
        self.shutdown_flag = tk.BooleanVar(value=False)
        self.shutdown_wait = tk.StringVar(value="30")
        ttk.Checkbutton(self.settings_tab, text="Apagar Windows al terminar toda la cola",
                        variable=self.shutdown_flag).pack(anchor="w", pady=(12, 4))
        ttk.Label(self.settings_tab, text="Espera antes del apagado (segundos, 10 a 86400)").pack(anchor="w")
        ttk.Entry(self.settings_tab, textvariable=self.shutdown_wait, width=10).pack(anchor="w", pady=4)
        ttk.Button(self.settings_tab, text="Cancelar apagado", command=self._stop_shutdown).pack(anchor="w", pady=8)

    def _log(self, text):
        line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {text}"
        try:
            with self.log_file.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
                file.flush()
                os.fsync(file.fileno())
        except OSError as error:
            self.status.set(f"No se pudo guardar LOG: {error}")
        self.log_box.insert(tk.END, line)
        self.log_box.yview_moveto(1.0)

    def _use_mkv(self):
        self.output.set(str(root_dir() / "MKV"))
        self._log("Destino establecido: " + self.output.get())

    def _start(self):
        try:
            delay = int(self.shutdown_wait.get())
            if not 10 <= delay <= 86400:
                raise ValueError
        except ValueError:
            self._log("ERROR: el tiempo de apagado debe estar entre 10 y 86400 segundos.")
            return
        self._stop_shutdown()
        self.shutdown_requested = self.shutdown_flag.get()
        self.shutdown_delay = delay
        if not self.output.get().strip():
            self._use_mkv()
        self._log(f"Configuración: destino={self.output.get()}, formato={self.format.get()}, modo=Encode {self.codec.get()} ({self.device.get()})")
        super()._start()

    def _run(self, settings):
        fmt, codec, device, audio, subs, output_dir = settings
        totals = {"Completado": 0, "Error": 0, "Omitido": 0, "Cancelado": 0}
        for index, job in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            if job.status == "Completado":
                continue
            started = datetime.now().astimezone()
            start_tick = time.monotonic()
            destination = (Path(output_dir) if output_dir else root_dir() / "MKV") / (job.source.stem + "." + OUTPUTS[fmt])
            temporary = destination.with_name(destination.stem + ".converting." + OUTPUTS[fmt])
            profile = f"Encode {codec} / {device}"
            self.events.put(("log", f"INICIO archivo={job.source} tipo={job.source.suffix.lower()} modo={profile} hora={started.isoformat(timespec='seconds')}"))
            result_state = "Error"
            detail = "sin errores"
            try:
                if destination.resolve() == job.source.resolve() or destination.exists() or temporary.exists():
                    result_state = "Omitido"
                    detail = "Destino existente o igual al origen"
                    self.events.put((index, "Omitido (destino existente)", 0))
                    continue
                info = inspect(job.source, self.ffprobe)
                duration = float(info.get("format", {}).get("duration") or 0)
                destination.parent.mkdir(parents=True, exist_ok=True)
                cmd = build_command(self.ffmpeg, job.source, temporary, info, fmt, codec,
                                    device, audio, subs, self.encoders)
                self.events.put((index, "Convirtiendo", 0))
                self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, text=True,
                                                encoding="utf-8", errors="replace")
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
                    raise RuntimeError(f"FFmpeg terminó con código {returncode}")
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
        self.events.put(("complete", totals, self.shutdown_requested and not self.cancel.is_set()))

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
