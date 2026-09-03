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
        self.check_trans = ctk.CTkCheckBox(self, text="Добавить аудиодорожку с переводом", variable=self.trans_var)
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


# --- ОКНО ВЫБОРА ВИДЕО ИЗ ПЛЕЙЛИСТА ---
class PlaylistDialog(ctk.CTkToplevel):
    def __init__(self, parent, videos):
        super().__init__(parent)
        self.parent = parent
        self.videos = videos
        self.selected_videos = []
        
        self.title("Плейлист обнаружен")
        self.geometry("500x450")
        
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 225
        self.geometry(f"+{x}+{y}")
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text="Выберите видео для загрузки:", font=("Arial", 14, "bold")).pack(pady=10)
        
        # Общий скролл для видео
        self.scroll = ctk.CTkScrollableFrame(self, width=450, height=300)
        self.scroll.pack(pady=5, padx=10, fill="both", expand=True)

        self.checkboxes = []
        for vid in self.videos:
            var = ctk.BooleanVar(value=True) # По умолчанию выбраны все
            title = vid.get('title', 'Без названия')
            duration = vid.get('duration', 0)
            dur_str = f" ({duration//60}:{duration%60:02d})" if duration else ""
            
            cb = ctk.CTkCheckBox(self.scroll, text=f"{title}{dur_str}", variable=var)
            cb.pack(anchor="w", pady=2, padx=5)
            self.checkboxes.append((var, vid))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        ctk.CTkButton(btn_frame, text="Добавить выбранные", command=self.confirm, fg_color="green", hover_color="darkgreen").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Отмена", command=self.destroy, fg_color="gray").pack(side="left", padx=10)

    def confirm(self):
        for var, vid in self.checkboxes:
            if var.get():
                self.selected_videos.append(vid)
        self.parent.add_items_to_queue(self.selected_videos)
        self.destroy()


# --- КАРТОЧКА ОТДЕЛЬНОГО ВИДЕО В ОЧЕРЕДИ ---
class QueueItemWidget(ctk.CTkFrame):
    def __init__(self, master, app, video_info, mode, res_num):
        super().__init__(master)
        self.app = app
        self.url = video_info.get('url') or f"https://www.youtube.com/watch?v={video_info.get('id')}"
        self.title_text = video_info.get('title', 'Видео')
        self.mode = mode
        self.res_num = res_num
        self.status = "waiting" # waiting, downloading, processing, done, error
        self.translation_path = None
        
        # UI карточки
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=5, pady=2)
        
        # Название с ограничением длины
        display_title = (self.title_text[:45] + '...') if len(self.title_text) > 45 else self.title_text
        self.lbl_title = ctk.CTkLabel(top_frame, text=display_title, font=("Arial", 12, "bold"))
        self.lbl_title.pack(side="left")
        
        self.btn_remove = ctk.CTkButton(top_frame, text="❌", width=30, height=24, fg_color="transparent", text_color="red", hover_color="#ffcccc", command=self.remove_self)
        self.btn_remove.pack(side="right")

        mid_frame = ctk.CTkFrame(self, fg_color="transparent")
        mid_frame.pack(fill="x", padx=5)

        # Индивидуальная кнопка перевода (если режим Видео и включено в настройках)
        if mode == "Видео" and self.app.settings.get("add_translation"):
            self.btn_audio = ctk.CTkButton(mid_frame, text="🎵 Добавить перевод", height=24, width=120, command=self.select_audio)
            self.btn_audio.pack(side="left", pady=2)
        else:
            badge_text = "Аудио (MP3)" if mode != "Видео" else f"Видео ({res_num}p)"
            ctk.CTkLabel(mid_frame, text=f"[{badge_text}]", text_color="gray", font=("Arial", 10)).pack(side="left")

        self.lbl_status = ctk.CTkLabel(mid_frame, text="В очереди", text_color="gray", font=("Arial", 11))
        self.lbl_status.pack(side="right")

        bot_frame = ctk.CTkFrame(self, fg_color="transparent")
        bot_frame.pack(fill="x", padx=5, pady=(2, 5))
        
        self.progress = ctk.CTkProgressBar(bot_frame)
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.lbl_percent = ctk.CTkLabel(bot_frame, text="0%", width=35)
        self.lbl_percent.pack(side="right")

    def select_audio(self):
        path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.m4a")])
        if path:
            self.translation_path = path
            filename = os.path.basename(path)
            short_name = (filename[:15] + '...') if len(filename) > 15 else filename
            self.btn_audio.configure(text=f"🎵 {short_name}", fg_color="green", hover_color="darkgreen")

    def update_progress(self, percent):
        self.progress.set(percent / 100.0)
        self.lbl_percent.configure(text=f"{int(percent)}%")
        
    def set_status(self, text, color="black"):
        self.lbl_status.configure(text=text, text_color=color)

    def remove_self(self):
        if self.status in ["downloading", "processing"]:
            messagebox.showwarning("Внимание", "Дождитесь окончания или остановите очередь, чтобы удалить активный элемент.")
            return
        self.app.queue_items.remove(self)
        self.pack_forget()
        self.destroy()


# --- ОСНОВНОЕ ПРИЛОЖЕНИЕ ---
class VideoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Download Video Mixer v3.0 (Queue)")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.os_name = platform.system()
        self.stop_requested = False
        self.is_downloading = False
        self.queue_items = [] # Хранилище объектов QueueItemWidget
        
        def resource_path(relative_path):
            try: base_path = sys._MEIPASS
            except: base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)

        self.icon_path = None
        if self.os_name == "Windows":
            icon_path = resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.icon_path = icon_path
                self.iconbitmap(icon_path)
        
        # Окно стало выше для комфортной очереди
        self.geometry("650x600")
        
        self.settings = SettingsManager.load()
        
        if self.os_name == "Windows":
            self.ffmpeg_exe_name, self.ytdlp_exe_name = "ffmpeg.exe", "yt-dlp.exe"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        else:
            self.ffmpeg_exe_name, self.ytdlp_exe_name = "ffmpeg", "yt-dlp"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
            
        self.ffmpeg_path = os.path.join(APP_DIR, self.ffmpeg_exe_name)
        self.ytdlp_path = os.path.join(APP_DIR, self.ytdlp_exe_name)

        self.startupinfo = None
        if self.os_name == "Windows":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.build_ui()
        threading.Thread(target=self.check_dependencies, daemon=True).start()

    def build_ui(self):
        # Панель URL и добавления
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(pady=10, padx=20, fill="x")

        self.settings_btn = ctk.CTkButton(top_frame, text="⚙", width=40, command=self.open_settings)
        self.settings_btn.pack(side="left", padx=(0, 10))

        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="Вставьте ссылку на видео или плейлист...", width=380)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        # Меню и Хоткеи
        self.context_menu = Menu(self, tearoff=0, font=("Arial", 10))
        self.context_menu.add_command(label="Вставить", command=self.paste_text)
        self.context_menu.add_command(label="Копировать", command=self.copy_text)
        self.context_menu.add_command(label="Вырезать", command=self.cut_text)
        self.context_menu.add_command(label="Выделить всё", command=self.select_all)
        self.url_entry.bind("<Button-3>", lambda e: self.context_menu.tk_popup(e.x_root, e.y_root))
        self.url_entry.bind("<Button-2>", lambda e: self.context_menu.tk_popup(e.x_root, e.y_root))
        
        self.btn_add = ctk.CTkButton(top_frame, text="Добавить", width=100, command=self.fetch_and_add)
        self.btn_add.pack(side="right")

        # Панель параметров
        param_frame = ctk.CTkFrame(self, fg_color="transparent")
        param_frame.pack(pady=5)
        
        self.mode_var = ctk.StringVar(value="Видео")
        self.mode_seg = ctk.CTkSegmentedButton(param_frame, values=["Видео", "Только Аудио (MP3)"], variable=self.mode_var, command=self.on_mode_change)
        self.mode_seg.pack(side="left", padx=10)
        
        # Статичный список качеств для мгновенного добавления
        self.res_combobox = ctk.CTkComboBox(param_frame, values=["1080p HD", "720p HD", "480p SD", "360p", "4K (2160p)"], state="readonly", width=150)
        self.res_combobox.pack(side="left", padx=10)
        self.res_combobox.set("1080p HD")

        # ОЧЕРЕДЬ (Scrollable Frame)
        self.queue_frame = ctk.CTkScrollableFrame(self, width=600, height=300)
        self.queue_frame.pack(pady=10, padx=20, fill="both", expand=True)

        # Нижняя панель управления
        bot_frame = ctk.CTkFrame(self, fg_color="transparent")
        bot_frame.pack(pady=10)

        self.start_btn = ctk.CTkButton(bot_frame, text="▶ Запустить очередь", command=self.start_queue, fg_color="green", hover_color="darkgreen", height=40, width=200)
        self.start_btn.pack(side="left", padx=10)
        
        self.status_label = ctk.CTkLabel(self, text="Ожидание ссылок...", text_color="gray")
        self.status_label.pack(pady=(0, 10))

    # --- УПРАВЛЕНИЕ UI ---
    def paste_text(self, event=None):
        try:
            self.url_entry.delete(0, "end") 
            self.url_entry.insert(0, self.clipboard_get())
        except: pass
        return "break"
    def copy_text(self, event=None):
        if self.url_entry.get(): self.clipboard_clear(); self.clipboard_append(self.url_entry.get())
        return "break"
    def cut_text(self, event=None): self.copy_text(); self.url_entry.delete(0, "end"); return "break"
    def select_all(self, event=None): self.url_entry.select_range(0, "end"); self.url_entry.icursor("end"); return "break"

    def on_mode_change(self, value):
        if value == "Видео":
            self.res_combobox.configure(state="readonly")
        else:
            self.res_combobox.configure(state="disabled")

    def toggle_ui(self, state):
        self.url_entry.configure(state=state)
        self.settings_btn.configure(state=state)
        self.btn_add.configure(state=state)
        self.mode_seg.configure(state=state)
        if state == "disabled" or self.mode_var.get() != "Видео":
            self.res_combobox.configure(state="disabled")
        else:
            self.res_combobox.configure(state="readonly")

    def refresh_settings(self):
        self.settings = SettingsManager.load()
    def open_settings(self): SettingsWindow(self)


    # --- ДОБАВЛЕНИЕ В ОЧЕРЕДЬ (Анализ Плейлистов) ---
    def fetch_and_add(self):
        url = self.url_entry.get().strip()
        if len(url) < 10: return
        
        self.btn_add.configure(state="disabled", text="Анализ...")
        threading.Thread(target=self._analyze_url_thread, args=(url,), daemon=True).start()

    def _analyze_url_thread(self, url):
        try:
            # Используем --flat-playlist для мгновенного получения списка (без скачивания деталей форматов)
            cmd = [self.ytdlp_path, '--dump-json', '--flat-playlist', '--no-check-certificate', url]
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            
            process = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
            if process.returncode != 0: raise Exception("Ошибка yt-dlp")
                
            videos = []
            for line in process.stdout.splitlines():
                try: videos.append(json.loads(line))
                except: pass
                
            if not videos: raise Exception("Видео не найдено")

            # Если это плейлист (больше 1 видео), показываем диалог выбора
            if len(videos) > 1:
                self.after(0, lambda: PlaylistDialog(self, videos))
            else:
                self.after(0, lambda: self.add_items_to_queue(videos))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось проанализировать ссылку:\n{e}"))
        finally:
            self.after(0, lambda: self.btn_add.configure(state="normal", text="Добавить"))
            self.after(0, lambda: self.url_entry.delete(0, "end"))

    def add_items_to_queue(self, videos_list):
        mode = self.mode_var.get()
        res_raw = self.res_combobox.get()
        res_num = int(res_raw.split("p")[0]) if "p" in res_raw else 1080
        
        for vid in videos_list:
            item = QueueItemWidget(self.queue_frame, self, vid, mode, res_num)
            item.pack(fill="x", pady=5)
            self.queue_items.append(item)


    # --- ЛОГИКА ОБРАБОТКИ ОЧЕРЕДИ ---
    def stop_process(self):
        self.stop_requested = True
        self.status_label.configure(text="Остановка текущей загрузки...", text_color="orange")
        self.start_btn.configure(state="disabled")

    def start_queue(self):
        if not self.queue_items:
            messagebox.showinfo("Очередь пуста", "Добавьте видео в очередь перед запуском.")
            return
            
        if not self.settings["save_path"]:
            path = filedialog.askdirectory(title="Выберите папку для сохранения")
            if not path: return
            self.settings["save_path"] = os.path.abspath(path)
            SettingsManager.save(self.settings)

        self.stop_requested = False
        self.is_downloading = True
        self.start_btn.configure(text="⏹ Остановить очередь", command=self.stop_process, fg_color="red", hover_color="darkred")
        self.toggle_ui("disabled")
        
        threading.Thread(target=self._process_queue_thread, daemon=True).start()

    def _process_queue_thread(self):
        for item in self.queue_items:
            if self.stop_requested: break
            if item.status == "waiting" or item.status == "error":
                self.download_item(item)
                
        # По завершении очереди (или при остановке)
        self.after(0, self.restore_ui_state)
        
    def download_item(self, item):
        process = None
        try:
            item.status = "downloading"
            self.after(0, lambda: item.set_status("Скачивание...", "blue"))
            
            safe_title = "".join([c for c in item.title_text if c.isalnum() or c in (' ', '.', '_', '-', '!')]).strip().rstrip('.')
            is_audio = (item.mode == "Только Аудио (MP3)")
            
            if is_audio:
                base_name = f"{safe_title}.mp3"
                final_name = base_name
            else:
                base_name = f"{safe_title} {item.res_num}p.mp4"
                final_name = f"{safe_title} {item.res_num}p (переведен).mp4" if item.translation_path else base_name
                
            base_path = os.path.join(self.settings["save_path"], base_name)
            final_path = os.path.join(self.settings["save_path"], final_name)

            # Пропуск, если файл уже есть
            if os.path.exists(final_path):
                item.status = "done"
                self.after(0, lambda: (item.set_status("✅ Файл уже существует", "green"), item.update_progress(100)))
                return

            temp_template = os.path.join(self.settings["save_path"], "temp_v.%(ext)s")
            temp_video = os.path.join(self.settings["save_path"], "temp_v.mp4")
            temp_mp3 = os.path.join(self.settings["save_path"], "temp_v.mp3")
            
            # --- СКАЧИВАНИЕ ---
            if not (not is_audio and item.translation_path and os.path.exists(base_path)): # Условие: если оригинал уже скачан, пропускаем
                if is_audio:
                    cmd = [
                        self.ytdlp_path, '-f', 'bestaudio', '--extract-audio', '--audio-format', 'mp3',
                        '--audio-quality', '0', '-o', temp_template, '--newline', '--no-playlist', 
                        '--retries', '20', '--fragment-retries', '20', '--no-check-certificate',
                        '--ffmpeg-location', self.ffmpeg_path, item.url
                    ]
                else:
                    MAX_DIMS = {4320: 7680, 2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640, 240: 426}
                    max_dim = MAX_DIMS.get(item.res_num, 1920)
                    cmd = [
                        self.ytdlp_path, '-f', f'bestvideo[width<={max_dim}][height<={max_dim}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                        '-o', temp_video, '--newline', '--no-playlist', '--retries', '20', '--fragment-retries', '20',
                        '--no-check-certificate', '--ffmpeg-location', self.ffmpeg_path, item.url
                    ]
                
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)
                
                last_percent = -1
                for line in process.stdout:
                    if self.stop_requested:
                        process.terminate()
                        raise Exception("Остановлено")
                        
                    match = re.search(r'\[download\]\s+([\d\.]+)%', line)
                    if match:
                        percent = float(match.group(1))
                        if int(percent) > last_percent:
                            last_percent = int(percent)
                            self.after(0, item.update_progress, percent)
                            
                process.wait()
                if process.returncode != 0 and not self.stop_requested:
                    raise Exception("Ошибка загрузки")

                actual_temp = temp_mp3 if is_audio else temp_video
                if os.path.exists(actual_temp):
                    if os.path.exists(base_path): os.remove(base_path)
                    os.rename(actual_temp, base_path)

            if getattr(self, 'stop_requested', False): raise Exception("Остановлено")

            # --- СКЛЕЙКА ПЕРЕВОДА ---
            if not is_audio and item.translation_path:
                item.status = "processing"
                self.after(0, lambda: item.set_status("Склейка...", "orange"))
                
                v1, v2 = self.settings["vol_original"]/100, self.settings["vol_translate"]/100
                cmd_ffmpeg = [self.ffmpeg_path, '-y', '-i', base_path, '-i', item.translation_path,
                       '-filter_complex', f'[0:a]volume={v1}[a1];[1:a]volume={v2}[a2];[a1][a2]amix=inputs=2[aout]',
                       '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', final_path]
                       
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                subprocess.run(cmd_ffmpeg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

            item.status = "done"
            self.after(0, lambda: (item.set_status("✅ Готово", "green"), item.update_progress(100)))
            
        except Exception as e:
            if process and process.poll() is None: process.terminate() 
            item.status = "error"
            err_msg = str(e)
            self.after(0, lambda: item.set_status("⏹ Остановлено" if "Остановлено" in err_msg else "❌ Ошибка", "red"))
        finally:
            self.clean_temp_files()

    def restore_ui_state(self):
        self.is_downloading = False
        self.start_btn.configure(text="▶ Запустить очередь", command=self.start_queue, fg_color="green", hover_color="darkgreen", state="normal")
        
        # Подсчет результатов
        done = sum(1 for i in self.queue_items if i.status == "done")
        total = len(self.queue_items)
        
        if self.stop_requested:
            self.status_label.configure(text=f"Очередь остановлена. Завершено: {done}/{total}")
        elif done == total and total > 0:
            self.status_label.configure(text="🎉 Все загрузки успешно завершены!")
            # Убрали назойливое popup-окно для очереди, так как оно мешает при пакетной загрузке
        else:
            self.status_label.configure(text=f"Очередь завершена с ошибками. Успешно: {done}/{total}")
            
        self.toggle_ui("normal")


    # --- ЯДРА И ВЫХОД ---
    def on_closing(self):
        if self.is_downloading:
            if messagebox.askyesno("Подтверждение", "Очередь активна. Прервать и закрыть?"):
                self.stop_requested = True
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

        for path, url, name in [(self.ytdlp_path, self.ytdlp_url, "yt-dlp"), (self.ffmpeg_path, None, "FFmpeg")]:
            if not os.path.exists(path):
                self.after(0, lambda n=name: self.status_label.configure(text=f"Скачивание {n}...", text_color="orange"))
                try:
                    if name == "FFmpeg":
                        dl_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" if self.os_name == "Windows" else "https://evermeet.cx/ffmpeg/getrelease/zip"
                        zip_path = os.path.join(APP_DIR, "ffmpeg_temp.zip")
                        req = urllib.request.Request(dl_url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx) as response, open(zip_path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            for file_info in zip_ref.infolist():
                                if file_info.filename.endswith(self.ffmpeg_exe_name):
                                    with zip_ref.open(file_info) as source, open(self.ffmpeg_path, "wb") as target:
                                        target.write(source.read())
                                    break
                        if os.path.exists(zip_path): os.remove(zip_path)
                    else:
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx) as response, open(path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                    
                    if self.os_name != "Windows": os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
                except Exception:
                    self.after(0, lambda n=name: self.status_label.configure(text=f"❌ Ошибка скачивания {n}", text_color="red"))
                    return

        self.after(0, lambda: self.status_label.configure(text="Проверка обновлений движка...", text_color="orange"))
        try:
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            subprocess.run([self.ytdlp_path, "-U"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        except: pass

        self.after(0, lambda: self.status_label.configure(text="Готов к работе", text_color="black"))
        self.after(0, lambda: self.toggle_ui("normal"))


if __name__ == "__main__":
    app = VideoApp()
    app.mainloop()
