import customtkinter as ctk
from tkinter import filedialog, messagebox, Menu
import yt_dlp
import subprocess
import threading
import os
import sys
import json
import platform
import urllib.request
import zipfile
import stat
import shutil # Добавлен для безопасного скачивания
import ssl

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
            "vol_original": 60,
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
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.transient(parent)
        self.grab_set()
        self.focus_set()

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
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, path)

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
        
        self.title("Download Video Mixer v1.1")
        
        # 1. СНАЧАЛА определяем операционную систему
        self.os_name = platform.system()
        
        # 2. ЗАТЕМ устанавливаем иконку окна
        def resource_path(relative_path):
            """ Получаем путь к ресурсу, работающий и в скрипте, и в скомпилированном .exe """
            try:
                base_path = sys._MEIPASS
            except Exception:
                base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)

        if self.os_name == "Windows":
            icon_path = resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        
        window_width = 600
        window_height = 450
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = int((screen_width / 2) - (window_width / 2))
        y = int((screen_height / 2) - (window_height / 2))
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        self.settings = SettingsManager.load()
        self.translation_file = None
        self.video_title = "video"
        self.current_download_phase = "Подготовка"
        
        self.os_name = platform.system()
        self.ffmpeg_exe_name = "ffmpeg.exe" if self.os_name == "Windows" else "ffmpeg"
        self.ffmpeg_path = os.path.join(APP_DIR, self.ffmpeg_exe_name)

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

        key_cmd = "<Command-KeyPress>" if self.os_name == "Darwin" else "<Control-KeyPress>"
        self.url_entry.bind(key_cmd, self.handle_cyrillic_hotkeys)
        
        ctrl_key = "Command" if self.os_name == "Darwin" else "Control"
        self.url_entry.bind(f"<{ctrl_key}-v>", self.paste_text)
        self.url_entry.bind(f"<{ctrl_key}-c>", self.copy_text)
        self.url_entry.bind(f"<{ctrl_key}-x>", self.cut_text)
        self.url_entry.bind(f"<{ctrl_key}-a>", self.select_all)

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

        self.status_label = ctk.CTkLabel(self, text="Проверка ядра...", text_color="orange")
        self.status_label.pack()

        self.refresh_settings()
        self.last_url = ""
        self.last_percent = -1
        
        self.toggle_ui("disabled")
        threading.Thread(target=self.check_and_download_ffmpeg, daemon=True).start()

    # --- ИСПРАВЛЕННАЯ ЛОГИКА АВТОЗАГРУЗКИ FFMPEG ---
    def check_and_download_ffmpeg(self):
        if os.path.exists(self.ffmpeg_path):
            self.after(0, lambda: self.status_label.configure(text="Готов к работе", text_color="black"))
            self.after(0, lambda: self.toggle_ui("normal"))
            return

        self.after(0, lambda: self.status_label.configure(text="Загрузка FFmpeg (около 35-80 МБ)... Ждите", text_color="orange"))
        
        try:
            if self.os_name == "Windows":
                # Надежная ссылка на свежую сборку для Windows
                url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            else:
                # Надежная ссылка для macOS
                url = "https://evermeet.cx/ffmpeg/getrelease/zip"

            zip_path = os.path.join(APP_DIR, "ffmpeg_temp.zip")
            
            # Создаем контекст, игнорирующий строгую проверку SSL (специально для macOS)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Притворяемся браузером
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'})
            
            # Добавляем context=ctx в запрос
            with urllib.request.urlopen(req, context=ctx) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)

            # Распаковываем нужный файл
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith(self.ffmpeg_exe_name):
                        with zip_ref.open(file_info) as source, open(self.ffmpeg_path, "wb") as target:
                            target.write(source.read())
                        break
            
            if os.path.exists(zip_path):
                os.remove(zip_path)

            # На macOS выдаем права на запуск файла
            if self.os_name != "Windows":
                st = os.stat(self.ffmpeg_path)
                os.chmod(self.ffmpeg_path, st.st_mode | stat.S_IEXEC)

            self.after(0, lambda: self.status_label.configure(text="Готов к работе", text_color="black"))
            self.after(0, lambda: self.toggle_ui("normal"))
            
        except Exception as e:
            self.after(0, lambda: self.status_label.configure(text="❌ Ошибка установки FFmpeg", text_color="red"))
            self.after(0, lambda err=e: messagebox.showerror(
                "Ошибка загрузки", 
                f"Не удалось скачать ядро FFmpeg автоматически.\n\nДетали ошибки:\n{err}\n\nВы можете скачать файл {self.ffmpeg_exe_name} вручную и положить его в ту же папку, где находится эта программа."
            ))

    # --- ОСТАЛЬНАЯ ЛОГИКА ---
    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def handle_cyrillic_hotkeys(self, event):
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
        except Exception: pass
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
        self.res_combobox.configure(state=state)
        self.settings_btn.configure(state=state)
        self.start_btn.configure(state=state)
        if self.settings["add_translation"]: self.file_btn.configure(state=state)

    def refresh_settings(self):
        self.settings = SettingsManager.load()
        if self.settings["add_translation"]:
            self.file_btn.configure(state="normal")
            self.start_btn.configure(text="Скачать и склеить")
        else:
            self.file_btn.configure(state="disabled")
            self.start_btn.configure(text="Скачать")

    def open_settings(self): SettingsWindow(self)

    def get_standard_res(self, w, h):
        max_dim = max(w, h)
        if max_dim >= 7680: return 4320
        if max_dim >= 3840: return 2160
        if max_dim >= 2560: return 1440
        if max_dim >= 1920: return 1080
        if max_dim >= 1280: return 720
        if max_dim >= 854:  return 480
        if max_dim >= 640:  return 360
        if max_dim >= 426:  return 240
        return 0

    def on_url_change(self, _):
        url = self.url_entry.get().strip()
        if url == self.last_url or len(url) < 10: return
        self.last_url = url
        self.res_combobox.configure(state="disabled")
        self.status_label.configure(text="Анализ ссылки...")
        threading.Thread(target=self.fetch_info, args=(url,), daemon=True).start()

    def fetch_info(self, url):
        try:
            # Добавили 'noplaylist': True
            with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True, 'noplaylist': True}) as ydl:
                info = ydl.extract_info(url, download=False)
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
                    res_values = []
                    for h in heights:
                        fps = valid_resolutions[h]
                        fps_str = str(int(fps)) if fps and fps > 30 else ""
                        badge = " 8K" if h >= 4320 else " 4K" if h >= 2160 else " HD" if h >= 1080 else ""
                        res_values.append(f"{h}p{fps_str}{badge}")
                    self.after(0, lambda: self.update_res_list(res_values))
        except Exception: self.after(0, lambda: self.status_label.configure(text="❌ Ошибка анализа"))

    def update_res_list(self, values):
        self.res_combobox.configure(values=values, state="normal")
        self.res_combobox.set(values[0])
        self.status_label.configure(text="✅ Качество выбрано")

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.m4a")])
        if path:
            self.translation_file = path
            self.file_label.configure(text=os.path.basename(path))

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                percent = d.get('downloaded_bytes', 0) / total
                percent_int = int(percent * 100)
                if percent_int > self.last_percent:
                    self.last_percent = percent_int
                    self.after(0, lambda p=percent: (self.progress_bar.set(p), self.percent_label.configure(text=f"{int(p*100)}%")))

    def start_process(self):
        url = self.url_entry.get().strip()
        if not url: return
        res_raw = self.res_combobox.get()
        if not res_raw or "p" not in res_raw: return
        if not self.settings["save_path"]:
            path = filedialog.askdirectory()
            if not path: return
            self.settings["save_path"] = path
            SettingsManager.save(self.settings)
        if self.settings["add_translation"] and not self.translation_file: return
        
        res_num = int(res_raw.split("p")[0])
        safe_title = "".join([c for c in self.video_title if c.isalnum() or c in (' ', '.', '_', '-', '!')]).strip().rstrip('.')
        
        base_name = f"{safe_title} {res_num}p.mp4"
        base_path = os.path.join(self.settings["save_path"], base_name)
        final_name = f"{safe_title} {res_num}p (переведен).mp4" if self.settings["add_translation"] else base_name
        final_path = os.path.join(self.settings["save_path"], final_name)

        if os.path.exists(final_path) and not messagebox.askyesno("Файл есть", f"Перезаписать {final_name}?"): return
        
        skip_download = False
        if self.settings["add_translation"] and os.path.exists(base_path):
            if messagebox.askyesno("Найдено видео", "Использовать скачанный оригинал?"): skip_download = True

        self.toggle_ui("disabled")
        threading.Thread(target=self.work, args=(url, skip_download, base_path, final_path, final_name, res_num), daemon=True).start()

    def work(self, url, skip_download, base_path, final_path, final_name, res_num):
        try:
            MAX_DIMS = {4320: 7680, 2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854}
            max_dim = MAX_DIMS.get(res_num, 1920)
            temp_video = os.path.join(self.settings["save_path"], "temp_v.mp4")
            
            if not skip_download:
                self.after(0, lambda: self.status_label.configure(text="Скачивание...", text_color="black"))
                self.last_percent = -1
                ydl_opts = {
                    'format': f'bestvideo[width<={max_dim}][height<={max_dim}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                    'outtmpl': temp_video, 
                    'progress_hooks': [self.progress_hook], 
                    'quiet': True, 
                    'noprogress': True,
                    'noplaylist': True,
                    
                    # --- АНТИ-VPN НАСТРОЙКИ ---
                    'retries': 20,
                    'fragment_retries': 20,
                    'socket_timeout': 30,
                    'nocheckcertificate': True,
                    'source_address': '0.0.0.0',
                    'geo_bypass': True,
                    
                    # --- ФИКС ДЛЯ MACOS ---
                    'ffmpeg_location': self.ffmpeg_path  # <--- Указываем yt-dlp, где лежит наше ядро
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
                if os.path.exists(base_path): os.remove(base_path)
                os.rename(temp_video, base_path)

            if self.settings["add_translation"]:
                self.after(0, lambda: self.status_label.configure(text="Склейка (FFmpeg)...", text_color="black"))
                v1, v2 = self.settings["vol_original"]/100, self.settings["vol_translate"]/100
                cmd = [self.ffmpeg_path, '-y', '-i', base_path, '-i', self.translation_file,
                       '-filter_complex', f'[0:a]volume={v1}[a1];[1:a]volume={v2}[a2];[a1][a2]amix=inputs=2[aout]',
                       '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', final_path]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            self.after(0, lambda: self.status_label.configure(text=f"✅ Готово: {final_name}", text_color="green"))
            messagebox.showinfo("Успех", f"Файл сохранен в:\n{final_path}")
            
        except Exception as e: 
            # Теперь программа покажет всплывающее окно с точной причиной сбоя
            self.after(0, lambda: self.status_label.configure(text="❌ Ошибка обработки", text_color="red"))
            self.after(0, lambda err=e: messagebox.showerror("Ошибка", f"Процесс прерван:\n\n{err}"))
        finally:
            self.after(0, lambda: (self.progress_bar.set(0), self.percent_label.configure(text="0%", text_color="black"), self.toggle_ui("normal")))

if __name__ == "__main__":
    app = VideoApp()
    app.mainloop()
