import customtkinter as ctk
from tkinter import filedialog, messagebox, Menu
import subprocess
import threading
import os
import sys
import json
import platform
import urllib.request
import zipfile
import stat
import shutil
import ssl
import re

# --- ПОРТАТИВНАЯ ЛОГИКА ПУТЕЙ ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_DIR = BASE_DIR
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

class SettingsManager:
    @staticmethod
    def load():
        defaults = {
            "add_translation": False,
            "vol_original": 15,
            "vol_translate": 100,
            "save_path": ""
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return {**defaults, **json.load(f)}
            except:
                return defaults
        return defaults

    @staticmethod
    def save(settings):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Настройки")
        
        window_width = 400
        window_height = 360
        
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (window_width // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (window_height // 2)
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.transient(parent)
        self.grab_set()
        self.focus_set()

        if getattr(parent, 'icon_path', None):
            self.after(250, lambda: self.wm_iconbitmap(parent.icon_path))

        self.settings = SettingsManager.load()

        ctk.CTkLabel(self, text="Параметры аудио", font=("Arial", 16, "bold")).pack(pady=(10, 5))

        self.trans_var = ctk.BooleanVar(value=self.settings["add_translation"])
        self.check_trans = ctk.CTkCheckBox(self, text="Добавить аудиодорожку с переводом", 
                                           variable=self.trans_var, command=self.toggle_sliders)
        self.check_trans.pack(pady=5)

        self.lbl_vol1 = ctk.CTkLabel(self, text=f"Громкость оригинала: {self.settings['vol_original']}%")
        self.lbl_vol1.pack()
        self.slider_vol1 = ctk.CTkSlider(self, from_=0, to=100, command=self.update_labels)
        self.slider_vol1.set(self.settings["vol_original"])
        self.slider_vol1.pack(pady=5)

        self.lbl_vol2 = ctk.CTkLabel(self, text=f"Громкость перевода: {self.settings['vol_translate']}%")
        self.lbl_vol2.pack()
        self.slider_vol2 = ctk.CTkSlider(self, from_=0, to=100, command=self.update_labels)
        self.slider_vol2.set(self.settings["vol_translate"])
        self.slider_vol2.pack(pady=5)

        ctk.CTkLabel(self, text="Путь сохранения", font=("Arial", 16, "bold")).pack(pady=(15, 5))
        self.path_entry = ctk.CTkEntry(self, width=300)
        self.path_entry.insert(0, self.settings["save_path"])
        self.path_entry.pack(pady=5)
        ctk.CTkButton(self, text="Обзор", command=self.browse_folder).pack(pady=5)

        self.toggle_sliders()

    def toggle_sliders(self):
        state = "normal" if self.trans_var.get() else "disabled"
        self.slider_vol1.configure(state=state)
        self.slider_vol2.configure(state=state)

    def update_labels(self, _=None):
        self.lbl_vol1.configure(text=f"Громкость оригинала: {int(self.slider_vol1.get())}%")
        self.lbl_vol2.configure(text=f"Громкость перевода: {int(self.slider_vol2.get())}%")

    def browse_folder(self):
        current_path = self.path_entry.get()
        initial = os.path.abspath(current_path) if current_path and os.path.exists(current_path) else BASE_DIR
        path = filedialog.askdirectory(initialdir=initial)
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, os.path.abspath(path))

    def on_close(self):
        new_settings = {
            "add_translation": self.trans_var.get(),
            "vol_original": int(self.slider_vol1.get()),
            "vol_translate": int(self.slider_vol2.get()),
            "save_path": self.path_entry.get()
        }
        SettingsManager.save(new_settings)
        self.parent.refresh_settings()
        self.grab_release()
        self.destroy()


class VideoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Download Video Mixer v2.0")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.os_name = platform.system()
        self.stop_requested = False
        self.is_downloading = False
        
        def resource_path(relative_path):
            try:
                base_path = sys._MEIPASS
            except Exception:
                base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)

        self.icon_path = None
        if self.os_name == "Windows":
            icon_path = resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.icon_path = icon_path
                self.iconbitmap(icon_path)
        
        window_width = 600
        window_height = 380 
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = int((screen_width / 2) - (window_width / 2))
        y = int((screen_height / 2) - (window_height / 2))
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.resizable(False, False)
        
        self.settings = SettingsManager.load()
        self.translation_file = None
        self.video_title = "video"
        self.last_percent = -1
        
        if self.os_name == "Windows":
            self.ffmpeg_exe_name = "ffmpeg.exe"
            self.ytdlp_exe_name = "yt-dlp.exe"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        else:
            self.ffmpeg_exe_name = "ffmpeg"
            self.ytdlp_exe_name = "yt-dlp"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
            
        self.ffmpeg_path = os.path.join(APP_DIR, self.ffmpeg_exe_name)
        self.ytdlp_path = os.path.join(APP_DIR, self.ytdlp_exe_name)

        self.startupinfo = None
        if self.os_name == "Windows":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # --- UI ---
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(pady=15, padx=20, fill="x")

        self.settings_btn = ctk.CTkButton(top_frame, text="⚙", width=40, command=self.open_settings)
        self.settings_btn.pack(side="left", padx=(0, 10))

        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="Вставьте ссылку на видео сюда...", width=400)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.url_entry.bind("<KeyRelease>", self.on_url_change)
        
        self.context_menu = Menu(self, tearoff=0, font=("Arial", 10))
        self.context_menu.add_command(label="Вставить", command=self.paste_text)
        self.context_menu.add_command(label="Копировать", command=self.copy_text)
        self.context_menu.add_command(label="Вырезать", command=self.cut_text)
        self.context_menu.add_command(label="Выделить всё", command=self.select_all)
        
        self.url_entry.bind("<Button-3>", self.show_context_menu)
        self.url_entry.bind("<Button-2>", self.show_context_menu)

        # Только перехват кириллицы. Английский Ctrl+V теперь работает нативно!
        key_cmd = "<Command-KeyPress>" if self.os_name == "Darwin" else "<Control-KeyPress>"
        self.url_entry.bind(key_cmd, self.handle_cyrillic_hotkeys)
        
        self.res_label = ctk.CTkLabel(self, text="Качество видео:")
        self.res_label.pack()
        
        self.res_combobox = ctk.CTkComboBox(self, values=["Нет данных"], state="disabled", width=200)
        self.res_combobox.pack(pady=5)

        self.file_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.file_frame.pack(pady=5)
        self.file_btn = ctk.CTkButton(self.file_frame, text="Выбрать доп. аудиодорожку", command=self.select_file)
        self.file_btn.pack(pady=5)
        self.file_label = ctk.CTkLabel(self.file_frame, text="Файл не выбран", text_color="gray")
        self.file_label.pack()

        self.progress_bar = ctk.CTkProgressBar(self, width=400)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(15, 5))
        self.percent_label = ctk.CTkLabel(self, text="0%")
        self.percent_label.pack()

        self.start_btn = ctk.CTkButton(self, text="Скачать", command=self.start_process, fg_color="green", height=40)
        self.start_btn.pack(pady=10)

        self.status_label = ctk.CTkLabel(self, text="Проверка ядер (FFmpeg и yt-dlp)...", text_color="orange")
        self.status_label.pack()

        self.refresh_settings()
        self.last_url = ""
        
        self.toggle_ui("disabled")
        threading.Thread(target=self.check_dependencies, daemon=True).start()

    def on_closing(self):
        if self.is_downloading:
            if messagebox.askyesno("Подтверждение", "Процесс скачивания активен.\n\nПрервать и закрыть программу?"):
                self.stop_requested = True
                self.status_label.configure(text="Очистка кэша и выход...", text_color="orange")
                self.attributes('-disabled', True) 
                self.after(1500, self._perform_exit)
        else:
            self._perform_exit()

    def _perform_exit(self):
        self.clean_temp_files()
        self.destroy()
        os._exit(0)

    def clean_temp_files(self):
        save_dir = self.settings.get("save_path", "")
        if save_dir and os.path.exists(save_dir):
            for file_name in os.listdir(save_dir):
                if file_name.startswith("temp_v"):
                    try: os.remove(os.path.join(save_dir, file_name))
                    except: pass

    def check_dependencies(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        headers = {'User-Agent': 'Mozilla/5.0'}

        if not os.path.exists(self.ytdlp_path):
            self.after(0, lambda: self.status_label.configure(text="Скачивание загрузчика yt-dlp...", text_color="orange"))
            try:
                req = urllib.request.Request(self.ytdlp_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx) as response, open(self.ytdlp_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                if self.os_name != "Windows":
                    os.chmod(self.ytdlp_path, os.stat(self.ytdlp_path).st_mode | stat.S_IEXEC)
            except Exception:
                self.after(0, lambda: self.status_label.configure(text="❌ Ошибка скачивания yt-dlp", text_color="red"))
                return

        if not os.path.exists(self.ffmpeg_path):
            self.after(0, lambda: self.status_label.configure(text="Скачивание ядра FFmpeg...", text_color="orange"))
            try:
                url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" if self.os_name == "Windows" else "https://evermeet.cx/ffmpeg/getrelease/zip"
                zip_path = os.path.join(APP_DIR, "ffmpeg_temp.zip")
                
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx) as response, open(zip_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    for file_info in zip_ref.infolist():
                        if file_info.filename.endswith(self.ffmpeg_exe_name):
                            with zip_ref.open(file_info) as source, open(self.ffmpeg_path, "wb") as target:
                                target.write(source.read())
                            break
                if os.path.exists(zip_path): os.remove(zip_path)
                if self.os_name != "Windows":
                    os.chmod(self.ffmpeg_path, os.stat(self.ffmpeg_path).st_mode | stat.S_IEXEC)
            except Exception:
                self.after(0, lambda: self.status_label.configure(text="❌ Ошибка установки FFmpeg", text_color="red"))
                return

        self.after(0, lambda: self.status_label.configure(text="Проверка обновлений движка...", text_color="orange"))
        try:
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            subprocess.run([self.ytdlp_path, "-U"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        except:
            pass

        self.after(0, lambda: self.status_label.configure(text="Готов к работе", text_color="black"))
        self.after(0, lambda: self.toggle_ui("normal"))

    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def handle_cyrillic_hotkeys(self, event):
        # Отрабатывает только если нажата русская буква при зажатом Ctrl/Cmd
        char = event.char.lower() if event.char else ""
        if char == 'м': return self.paste_text()
        elif char == 'с': return self.copy_text()
        elif char == 'ч': return self.cut_text()
        elif char == 'ф': return self.select_all()

    def paste_text(self, event=None):
        try:
            text = self.clipboard_get()
            self.url_entry.delete(0, "end") 
            self.url_entry.insert(0, text)
            self.on_url_change(None)
        except: pass
        return "break"

    def copy_text(self, event=None):
        if self.url_entry.get():
            self.clipboard_clear()
            self.clipboard_append(self.url_entry.get())
        return "break"

    def cut_text(self, event=None):
        self.copy_text()
        self.url_entry.delete(0, "end")
        self.on_url_change(None)
        return "break"

    def select_all(self, event=None):
        self.url_entry.select_range(0, "end")
        self.url_entry.icursor("end")
        return "break"

    def toggle_ui(self, state):
        self.url_entry.configure(state=state)
        self.settings_btn.configure(state=state)
        if self.settings.get("add_translation"): 
            self.file_btn.configure(state=state)
        if state == "disabled":
            self.res_combobox.configure(state="disabled")
        else:
            if self.res_combobox.cget("values") != ["Нет данных"]:
                self.res_combobox.configure(state="readonly")

    def refresh_settings(self):
        self.settings = SettingsManager.load()
        if self.settings.get("add_translation"):
            self.start_btn.configure(text="Скачать и склеить")
            self.file_btn.configure(state="normal")
        else:
            self.start_btn.configure(text="Скачать")
            self.file_btn.configure(state="disabled")

    def open_settings(self): SettingsWindow(self)

    def get_standard_res(self, w, h):
        max_dim = max(w, h)
        res_map = {7680: 4320, 3840: 2160, 2560: 1440, 1920: 1080, 1280: 720, 854: 480, 640: 360, 426: 240}
        for threshold, res in res_map.items():
            if max_dim >= threshold: return res
        return 0

    def on_url_change(self, _):
        url = self.url_entry.get().strip()
        if url == self.last_url or len(url) < 10: return
        self.last_url = url
        self.res_combobox.configure(state="disabled")
        self.status_label.configure(text="Анализ ссылки...", text_color="black")
        threading.Thread(target=self.fetch_info, args=(url,), daemon=True).start()

    def fetch_info(self, url):
        try:
            cmd = [self.ytdlp_path, '--dump-json', '--no-playlist', '--no-check-certificate', url]
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            
            process = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
            if process.returncode != 0:
                raise Exception("Ошибка yt-dlp")
                
            info = json.loads(process.stdout)
            self.video_title = info.get('title', 'video')
            formats = info.get('formats', [])
            
            valid_resolutions = {} 
            for f in formats:
                w, h, fps = f.get('width', 0), f.get('height', 0), f.get('fps', 0)
                if w and h:
                    std_res = self.get_standard_res(w, h)
                    if std_res >= 240:
                        if std_res not in valid_resolutions or (fps and fps > valid_resolutions.get(std_res, 0)):
                            valid_resolutions[std_res] = fps if fps else 30
            heights = sorted(list(valid_resolutions.keys()), reverse=True)
            if heights:
                res_values = [f"{h}p{str(int(valid_resolutions[h])) if valid_resolutions[h] > 30 else ''}{' 8K' if h >= 4320 else ' 4K' if h >= 2160 else ' HD' if h >= 1080 else ''}" for h in heights]
                self.after(0, lambda: self.update_res_list(res_values))
        except: 
            self.after(0, lambda: self.status_label.configure(text="❌ Ошибка анализа", text_color="red"))

    def update_res_list(self, values):
        self.res_combobox.configure(values=values, state="readonly")
        self.res_combobox.set(values[0])
        self.status_label.configure(text="✅ Качество выбрано", text_color="green")

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.m4a")])
        if path:
            self.translation_file = path
            self.file_label.configure(text=os.path.basename(path))

    def stop_process(self):
        self.stop_requested = True
        self.status_label.configure(text="Остановка процессов...", text_color="orange")
        self.start_btn.configure(state="disabled")

    def update_progress_ui(self, percent):
        percent_int = int(percent)
        if percent_int > self.last_percent:
            self.last_percent = percent_int
            self.progress_bar.set(percent / 100.0)
            self.percent_label.configure(text=f"{percent_int}%")

    def start_process(self):
        url = self.url_entry.get().strip()
        if not url: return
        res_raw = self.res_combobox.get()
        if not res_raw or "p" not in res_raw: return
        if not self.settings["save_path"]:
            path = filedialog.askdirectory()
            if not path: return
            self.settings["save_path"] = os.path.abspath(path)
            SettingsManager.save(self.settings)
        if self.settings["add_translation"] and not self.translation_file: return
        
        self.stop_requested = False
        self.is_downloading = True
        self.last_percent = -1
        self.start_btn.configure(text="Остановить", command=self.stop_process, fg_color="red", hover_color="darkred")
        self.toggle_ui("disabled")
        
        res_num = int(res_raw.split("p")[0])
        safe_title = "".join([c for c in self.video_title if c.isalnum() or c in (' ', '.', '_', '-', '!')]).strip().rstrip('.')
        base_name = f"{safe_title} {res_num}p.mp4"
        base_path = os.path.join(self.settings["save_path"], base_name)
        final_name = f"{safe_title} {res_num}p (переведен).mp4" if self.settings["add_translation"] else base_name
        final_path = os.path.join(self.settings["save_path"], final_name)

        if os.path.exists(final_path) and not messagebox.askyesno("Файл есть", f"Перезаписать {final_name}?"): 
            self.restore_ui_state()
            return
        
        skip_download = False
        if self.settings["add_translation"] and os.path.exists(base_path):
            if messagebox.askyesno("Найдено видео", "Использовать скачанный оригинал?"): skip_download = True

        threading.Thread(target=self.work, args=(url, skip_download, base_path, final_path, final_name, res_num), daemon=True).start()

    def restore_ui_state(self):
        self.is_downloading = False
        self.progress_bar.set(0)
        self.percent_label.configure(text="0%")
        self.start_btn.configure(text="Скачать и склеить" if self.settings.get("add_translation") else "Скачать", 
                                 command=self.start_process, fg_color="green", hover_color="darkgreen", state="normal")
        self.toggle_ui("normal")

    def show_success_dialog(self, final_path):
        self.status_label.configure(text="✅ Готово", text_color="green")
        if messagebox.askyesno("Успех", f"Видео успешно сохранено:\n{os.path.basename(final_path)}\n\nОткрыть папку с файлом?"):
            path = os.path.abspath(final_path)
            if platform.system() == "Windows":
                subprocess.run(['explorer', '/select,', path])
            elif platform.system() == "Darwin":
                subprocess.run(['open', '-R', path])
            else:
                subprocess.run(['xdg-open', os.path.dirname(path)])

    def work(self, url, skip_download, base_path, final_path, final_name, res_num):
        process = None
        try:
            temp_video = os.path.join(self.settings["save_path"], "temp_v.mp4")
            
            # --- ФИКС ДЛЯ SHORTS ---
            MAX_DIMS = {4320: 7680, 2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640, 240: 426}
            max_dim = MAX_DIMS.get(res_num, 1920)
            
            if not skip_download:
                self.after(0, lambda: self.status_label.configure(text="Скачивание...", text_color="black"))
                
                # Теперь мы ограничиваем и ширину, и высоту. 
                # Shorts (1080x1920) и обычное видео (1920x1080) теперь оба скачаются без ошибок!
                cmd = [
                    self.ytdlp_path,
                    '-f', f'bestvideo[width<={max_dim}][height<={max_dim}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                    '-o', temp_video,
                    '--newline',               
                    '--no-playlist', 
                    '--retries', '20', 
                    '--fragment-retries', '20',
                    '--no-check-certificate',
                    '--ffmpeg-location', self.ffmpeg_path,
                    url
                ]
                
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)
                
                for line in process.stdout:
                    if self.stop_requested:
                        process.terminate()
                        raise Exception("Процесс остановлен пользователем")
                        
                    match = re.search(r'\[download\]\s+([\d\.]+)%', line)
                    if match:
                        percent = float(match.group(1))
                        self.after(0, self.update_progress_ui, percent)
                        
                process.wait()
                if process.returncode != 0 and not self.stop_requested:
                    raise Exception("Ошибка скачивания. Возможно, требуется включить VPN или подождать.")

                if os.path.exists(base_path): os.remove(base_path)
                os.rename(temp_video, base_path)

            if getattr(self, 'stop_requested', False): raise Exception("Процесс остановлен пользователем")

            if self.settings["add_translation"]:
                self.after(0, lambda: self.status_label.configure(text="Склейка (FFmpeg)...", text_color="black"))
                v1, v2 = self.settings["vol_original"]/100, self.settings["vol_translate"]/100
                cmd_ffmpeg = [self.ffmpeg_path, '-y', '-i', base_path, '-i', self.translation_file,
                       '-filter_complex', f'[0:a]volume={v1}[a1];[1:a]volume={v2}[a2];[a1][a2]amix=inputs=2[aout]',
                       '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', final_path]
                       
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                subprocess.run(cmd_ffmpeg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

            self.after(0, lambda: self.show_success_dialog(final_path))
            
        except Exception as e:
            if process and process.poll() is None:
                process.terminate() 
            err_msg = str(e)
            self.after(0, lambda: self.status_label.configure(text="⏹ Загрузка отменена" if "остановлен" in err_msg else "❌ Ошибка", text_color="orange" if "остановлен" in err_msg else "red"))
            if "остановлен" not in err_msg: self.after(0, lambda err=err_msg: messagebox.showerror("Ошибка", f"Процесс прерван:\n\n{err}"))
        finally:
            self.clean_temp_files()
            self.after(0, self.restore_ui_state)

if __name__ == "__main__":
    app = VideoApp()
    app.mainloop()
