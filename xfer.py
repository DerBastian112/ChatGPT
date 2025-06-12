import tkinter as tk
from tkinter import ttk, messagebox
import os
import threading
import serial
import zlib
import time

BLOCK_SIZE = 1024

def is_windows():
    return os.name == "nt"

def join_remote_path(a, b):
    """Hilfsfunktion: baut Remote-Pfade systemunabhängig"""
    if b in ("", ".", "./"): return a
    if b == "..":
        if "/" not in a.strip("/"): return "/"
        return "/".join(a.strip("/").split("/")[:-1]) or "/"
    if a in ("", "/"): return "/" + b
    return a.rstrip("/") + "/" + b

class SerialCommander:
    def __init__(self, port, baud, gui_callback_update_remote=None, gui_callback_progress=None, gui_callback_recv=None):
        self.ser = serial.Serial(port, baud, timeout=3)
        self.stop_flag = threading.Event()
        self.gui_callback_update_remote = gui_callback_update_remote
        self.gui_callback_progress = gui_callback_progress
        self.gui_callback_recv = gui_callback_recv
        self.partner_files = []
        self.remote_dir = "/"  # Root im Remote-Panel

    def send_files(self, filenames):
        for filename in filenames:
            basename = os.path.basename(filename)
            with open(filename, "rb") as f:
                rawdata = f.read()
            compdata = zlib.compress(rawdata)
            if len(compdata) < len(rawdata):
                data = compdata
                flag = "COMP"
            else:
                data = rawdata
                flag = "RAW"
            self.ser.write(f"HEADER {basename} {len(rawdata)} {len(data)} {flag}\n".encode())
            ack = self.ser.readline()
            if ack.startswith(b'SKIP'):
                continue
            if not ack.startswith(b'OK'):
                continue
            block_num = 0
            sent = 0
            size = len(data)
            while sent < size:
                chunk = data[sent:sent+BLOCK_SIZE]
                crc = zlib.crc32(chunk)
                self.ser.write(f"BLOCK {block_num} {len(chunk)} {crc}\n".encode())
                self.ser.write(chunk)
                response = self.ser.readline()
                if response.startswith(b'OK'):
                    sent += len(chunk)
                    if self.gui_callback_progress:
                        self.gui_callback_progress(sent, size)
                    block_num += 1
                else:
                    continue
            self.ser.write(b'ENDFILE\n')
            _ = self.ser.readline()
        self.ser.write(b'END\n')

    def request_remote_list(self, path="/"):
        self.ser.write(f"LIST {path}\n".encode())

    def request_file(self, remotepath):
        # Ruft eine Datei aus aktuellem remote-Verzeichnis ab
        self.ser.write(f"GET {remotepath}\n".encode())

    def recv_forever(self, destdir):
        while not self.stop_flag.is_set():
            line = self.ser.readline()
            if not line:
                time.sleep(0.1)
                continue
            line_str = line.decode(errors="ignore").strip()
            # Remote-Panel: LISTDATA-Einträge
            if line_str.startswith("LISTDATA "):
                try:
                    daten = line_str[9:]
                    self.partner_files = []
                    for entry in daten.split("|"):
                        if not entry: continue
                        typ, name, size = entry.split(":")
                        self.partner_files.append( (typ, name, int(size)) )
                    if self.gui_callback_update_remote:
                        self.gui_callback_update_remote(self.partner_files)
                except Exception:
                    pass
                continue
            # Verzeichnisabfrage: LIST <Pfad>
            if line_str.startswith("LIST "):
                pfad = line_str[5:] or "."
                entries = []
                try:
                    for entry in os.scandir(pfad):
                        typ = "D" if entry.is_dir() else "F"
                        size = entry.stat().st_size if not entry.is_dir() else 0
                        entries.append(f"{typ}:{entry.name}:{size}")
                except Exception:
                    entries = []
                antwort = "LISTDATA " + "|".join(entries) + "\n"
                self.ser.write(antwort.encode())
                continue
            # Dateianforderung: GET <RemotePfad>
            if line_str.startswith("GET "):
                filepath = line_str[4:]
                if os.path.exists(filepath):
                    self.send_files([filepath])
                else:
                    self.ser.write(b"SKIP\n")
                continue
            # Dateiempfang: HEADER etc.
            if line_str.startswith("HEADER "):
                parts = line_str.split(" ")
                if len(parts) != 5:
                    continue
                name, origsize, compsize, flag = parts[1], int(parts[2]), int(parts[3]), parts[4]
                # Im aktuellen lokalen Verzeichnis speichern
                path = os.path.join(destdir, name)
                self.ser.write(b'OK\n')
                buf = bytearray()
                bytes_written = 0
                while True:
                    line2 = self.ser.readline()
                    if line2.startswith(b'ENDFILE'):
                        self.ser.write(b'OK\n')
                        with open(path, 'wb') as f:
                            if flag == "COMP":
                                try:
                                    f.write(zlib.decompress(buf))
                                except Exception as e:
                                    print("Fehler beim Entpacken:", e)
                            else:
                                f.write(buf)
                        if self.gui_callback_recv:
                            self.gui_callback_recv(name)
                        break
                    if not line2.startswith(b'BLOCK'):
                        continue
                    try:
                        _, num, length, crc = line2.decode().strip().split(' ')
                        length = int(length)
                        crc = int(crc)
                    except Exception:
                        self.ser.write(b'RESEND\n')
                        continue
                    chunk = self.ser.read(length)
                    if len(chunk) != length or zlib.crc32(chunk) != crc:
                        self.ser.write(b'RESEND\n')
                        continue
                    buf.extend(chunk)
                    bytes_written += length
                    if self.gui_callback_progress:
                        self.gui_callback_progress(bytes_written, compsize)
                    self.ser.write(b'OK\n')
            # ... andere Befehle ignorieren

    def close(self):
        self.stop_flag.set()
        self.ser.close()

class FileCommanderGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Serial Commander – Norton-Style")
        self.left_files = []
        self.right_files = []
        self.serial = None
        self.recv_thread = None
        self.progress_var = tk.DoubleVar()
        self.status_var = tk.StringVar()
        self.local_dir = os.path.abspath(".")
        self.remote_dir = "/"
        self.remote_panel_entries = []
        self.remote_poll_job = None

        # Verbindungspanel
        conn_frame = tk.Frame(master)
        conn_frame.pack(fill="x")
        tk.Label(conn_frame, text="Port:").pack(side="left")
        self.port_entry = tk.Entry(conn_frame, width=8)
        self.port_entry.pack(side="left")
        self.port_entry.insert(0, "COM5")
        tk.Label(conn_frame, text="Baud:").pack(side="left")
        self.baud_entry = tk.Entry(conn_frame, width=8)
        self.baud_entry.pack(side="left")
        self.baud_entry.insert(0, "115200")
        self.connect_btn = tk.Button(conn_frame, text="Verbinden", command=self.connect_serial)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = tk.Button(conn_frame, text="Trennen", command=self.disconnect_serial, state="disabled")
        self.disconnect_btn.pack(side="left")

        panels = tk.Frame(master)
        panels.pack(fill="both", expand=True)

        # Lokales Dateifenster (links)
        left_frame = tk.LabelFrame(panels, text="Lokal")
        left_frame.pack(side="left", fill="both", expand=True)
        self.local_path_var = tk.StringVar(value=self.local_dir)
        tk.Entry(left_frame, textvariable=self.local_path_var, state="readonly", width=50).pack(fill="x")
        self.left_list = tk.Listbox(left_frame, selectmode="extended")
        self.left_list.pack(fill="both", expand=True)
        self.left_list.bind("<Double-Button-1>", self.local_double_click)
        btns_left = tk.Frame(left_frame)
        btns_left.pack(fill="x")
        tk.Button(btns_left, text="Öffnen", command=self.local_open_selected).pack(side="left", fill="x", expand=True)
        tk.Button(btns_left, text="..", command=self.local_up).pack(side="left", fill="x", expand=True)
        tk.Button(btns_left, text="Senden ➔", command=self.send_selected_files).pack(side="left", fill="x", expand=True)

        # Remote-Dateifenster (rechts)
        right_frame = tk.LabelFrame(panels, text="Remote")
        right_frame.pack(side="right", fill="both", expand=True)
        self.remote_path_var = tk.StringVar(value=self.remote_dir)
        tk.Entry(right_frame, textvariable=self.remote_path_var, state="readonly", width=50).pack(fill="x")
        self.right_list = tk.Listbox(right_frame, selectmode="extended")
        self.right_list.pack(fill="both", expand=True)
        self.right_list.bind("<Double-Button-1>", self.remote_double_click)
        btns_right = tk.Frame(right_frame)
        btns_right.pack(fill="x")
        tk.Button(btns_right, text="Öffnen", command=self.remote_open_selected).pack(side="left", fill="x", expand=True)
        tk.Button(btns_right, text="..", command=self.remote_up).pack(side="left", fill="x", expand=True)
        tk.Button(btns_right, text="⬅ Empfangen", command=self.receive_selected_remote).pack(side="left", fill="x", expand=True)
        tk.Button(right_frame, text="Aktualisieren", command=self.update_remote_files).pack(fill="x")

        self.progress = ttk.Progressbar(master, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x")
        self.status = tk.Label(master, textvariable=self.status_var, anchor="w")
        self.status.pack(fill="x")

        self.update_local_files()
        self.update_remote_files()

    def connect_serial(self):
        port = self.port_entry.get().strip()
        baud = int(self.baud_entry.get().strip())
        try:
            self.serial = SerialCommander(
                port, baud,
                gui_callback_update_remote=self.update_remote_files_callback,
                gui_callback_progress=self.update_progress,
                gui_callback_recv=self.file_received
            )
        except Exception as e:
            messagebox.showerror("Fehler", f"Kann Port nicht öffnen: {e}")
            return
        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")
        self.recv_thread = threading.Thread(target=self.serial.recv_forever, args=(self.local_dir,), daemon=True)
        self.recv_thread.start()
        self.status_var.set(f"Verbunden: {port} @ {baud}")
        self.update_remote_files()

    def disconnect_serial(self):
        if self.serial:
            self.serial.close()
        self.serial = None
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.status_var.set("Getrennt")

    def update_local_files(self):
        self.left_files = []
        try:
            for entry in os.scandir(self.local_dir):
                typ = "[DIR]" if entry.is_dir() else "     "
                size = "" if entry.is_dir() else f"{entry.stat().st_size}"
                self.left_files.append( (typ, entry.name, size) )
        except Exception:
            self.left_files = []
        self.left_list.delete(0, tk.END)
        for typ, name, size in self.left_files:
            self.left_list.insert(tk.END, f"{typ} {name} {size}")

    def local_double_click(self, event):
        idx = self.left_list.curselection()
        if not idx:
            return
        i = idx[0]
        typ, name, size = self.left_files[i]
        if typ.strip() == "[DIR]":
            self.local_dir = os.path.abspath(os.path.join(self.local_dir, name))
            self.local_path_var.set(self.local_dir)
            self.update_local_files()

    def local_open_selected(self):
        self.local_double_click(None)

    def local_up(self):
        self.local_dir = os.path.abspath(os.path.join(self.local_dir, ".."))
        self.local_path_var.set(self.local_dir)
        self.update_local_files()

    def send_selected_files(self):
        if not self.serial:
            messagebox.showwarning("Nicht verbunden", "Bitte zuerst eine serielle Verbindung herstellen.")
            return
        selected = self.left_list.curselection()
        if not selected:
            messagebox.showinfo("Keine Auswahl", "Bitte mindestens eine Datei auswählen.")
            return
        files = []
        for i in selected:
            typ, name, size = self.left_files[i]
            if typ.strip() != "[DIR]":
                files.append(os.path.join(self.local_dir, name))
        if not files:
            messagebox.showinfo("Nur Dateien", "Nur Dateien können gesendet werden.")
            return
        threading.Thread(target=self.serial.send_files, args=(files,), daemon=True).start()
        self.status_var.set(f"Sende: {', '.join(os.path.basename(f) for f in files)}")

    # --- Remote Panel
    def update_remote_files(self):
        if self.serial:
            self.serial.request_remote_list(self.remote_dir)

    def update_remote_files_callback(self, entries):
        self.right_files = entries
        self.right_list.delete(0, tk.END)
        for typ, name, size in self.right_files:
            pre = "[DIR]" if typ == "D" else "     "
            size_str = "" if typ == "D" else f"{size}"
            self.right_list.insert(tk.END, f"{pre} {name} {size_str}")

    def remote_double_click(self, event):
        idx = self.right_list.curselection()
        if not idx:
            return
        i = idx[0]
        typ, name, size = self.right_files[i]
        if typ == "D":
            self.remote_dir = join_remote_path(self.remote_dir, name)
            self.remote_path_var.set(self.remote_dir)
            self.update_remote_files()

    def remote_open_selected(self):
        self.remote_double_click(None)

    def remote_up(self):
        self.remote_dir = join_remote_path(self.remote_dir, "..")
        self.remote_path_var.set(self.remote_dir)
        self.update_remote_files()

    def receive_selected_remote(self):
        if not self.serial:
            messagebox.showwarning("Nicht verbunden", "Bitte zuerst eine serielle Verbindung herstellen.")
            return
        selected = self.right_list.curselection()
        if not selected:
            messagebox.showinfo("Keine Auswahl", "Bitte mindestens eine Datei auswählen.")
            return
        for i in selected:
            typ, name, size = self.right_files[i]
            if typ == "F":
                remote_file = join_remote_path(self.remote_dir, name)
                threading.Thread(target=self.serial.request_file, args=(remote_file,), daemon=True).start()
                self.status_var.set(f"Hole: {name}")

    def update_progress(self, value, total):
        percent = int(value * 100 / total) if total else 100
        self.progress_var.set(percent)
        self.status_var.set(f"Fortschritt: {percent}%")

    def file_received(self, name):
        self.status_var.set(f"Empfangen: {name}")
        self.update_local_files()

def main():
    root = tk.Tk()
    app = FileCommanderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
