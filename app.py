import flet as ft
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
import queue
import time
import logging

# --- ЛОГИКА ПУТЕЙ ---
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_data_dir():
    if platform.system() == "Windows":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif platform.system() == "Darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(root, "Download Video Mixer")
    os.makedirs(path, exist_ok=True)
    return path

APP_DIR = get_data_dir()
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

if platform.system() == "Windows":
    LOG_FILE = os.path.join(BASE_DIR, "mixer_debug.log")
else:
    LOG_FILE = os.path.join(APP_DIR, "mixer_debug.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(threadName)s: %(message)s',
    encoding='utf-8'
)
logging.info("="*40)
logging.info("--- ЗАПУСК ПРИЛОЖЕНИЯ v4.0 (Native Tkinter Dialogs) ---")

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
            except Exception as e:
                logging.error(f"Ошибка загрузки настроек: {e}")
                return defaults
        return defaults

    @staticmethod
    def save(settings):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"Ошибка сохранения настроек: {e}")

# --- ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ ---
class VideoMixerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "YTD Mixer v4.0"
        self.page.theme_mode = "dark"
        self.page.bgcolor = "#0E0E12" 
        self.page.window.width = 700
        self.page.window.height = 750
        self.page.padding = 20
        self.page.window.center()
        
        self.page.window.prevent_close = False
        self.page.window.on_event = self.window_event

        self.os_name = platform.system()
        self.settings = SettingsManager.load()
        self.queue_items = []
        self.stop_requested = False
        self.is_downloading = False

        self.arch = platform.machine().lower()

        if self.os_name == "Windows":
            self.ffmpeg_exe_name, self.ytdlp_exe_name, self.vot_exe_name = "ffmpeg.exe", "yt-dlp.exe", "vot-cli.exe"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
            self.vot_url = "https://github.com/FOSWLY/vot-cli/releases/latest/download/vot-windows-x64.exe.zip"
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        else:
            self.ffmpeg_exe_name, self.ytdlp_exe_name, self.vot_exe_name = "ffmpeg", "yt-dlp", "vot-cli"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
            vot_arch = "arm64" if self.arch in ("arm64", "aarch64") else "x64"
            self.vot_url = f"https://github.com/FOSWLY/vot-cli/releases/latest/download/vot-macos-{vot_arch}.zip"
            self.startupinfo = None

        self.ffmpeg_path = os.path.join(APP_DIR, self.ffmpeg_exe_name)
        self.ytdlp_path = os.path.join(APP_DIR, self.ytdlp_exe_name)
        self.vot_path = os.path.join(APP_DIR, self.vot_exe_name)

        self.format_fetch_queue = queue.Queue()
        
        self.setup_ui()
        
        threading.Thread(target=self.check_dependencies, daemon=True).start()
        threading.Thread(target=self.format_fetch_worker, daemon=True).start()

    def window_event(self, e):
        if e.data == "close":
            self._perform_exit()

    def _perform_exit(self):
        logging.info("Выход из программы...")
        self.clean_temp_files()
        try:
            self.page.window.destroy()
        except:
            pass
        os._exit(0)

    def clean_temp_files(self):
        save_dir = self.settings.get("save_path", "")
        if save_dir and os.path.exists(save_dir):
            for file_name in os.listdir(save_dir):
                if file_name.startswith("temp_v") or file_name.startswith("temp_trans_"):
                    try: os.remove(os.path.join(save_dir, file_name))
                    except: pass

    # Универсальная функция для открытия диалогов (поддержка старого и нового Flet)
    def open_dialog(self, dialog):
        if hasattr(self.page, "open"):
            self.page.open(dialog)
        else:
            self.page.dialog = dialog
            dialog.open = True
            self.page.update()

    def close_dialog(self, dialog):
        if hasattr(self.page, "close"):
            self.page.close(dialog)
        else:
            dialog.open = False
            self.page.update()

    def setup_ui(self):
        self.url_input = ft.TextField(
            hint_text="https://www.youtube.com/watch?v=...",
            expand=True,
            border_radius=8,
            filled=True,
            bgcolor="#1C1C1E",
            border_color="transparent",
            content_padding=15,
            prefix=ft.Icon("link")
        )
        
        self.btn_add = ft.ElevatedButton(
            content=ft.Row([ft.Icon("add"), ft.Text(value="Добавить")], alignment="center", spacing=5),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), bgcolor="#1976D2", color="#FFFFFF"),
            height=48,
            on_click=self.fetch_and_add
        )
        
        self.btn_settings = ft.Container(
            content=ft.Icon("settings"),
            on_click=self.open_settings,
            padding=10,
            ink=True,
            border_radius=8
        )

        top_row = ft.Row([self.btn_settings, self.url_input, self.btn_add], alignment="spaceBetween")

        self.mode_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option(key="Видео", text="Режим: Видео"),
                ft.dropdown.Option(key="Только Аудио (MP3)", text="Режим: Аудио (MP3)"),
            ],
            value="Видео",
            width=220,
            border_radius=8,
            filled=True,
            bgcolor="#1C1C1E",
            border_color="transparent"
        )
        # Динамическая привязка события (обход переименования on_change -> on_select во Flet 0.24)
        if hasattr(self.mode_dropdown, "on_select"):
            self.mode_dropdown.on_select = self.on_mode_change
        else:
            self.mode_dropdown.on_change = self.on_mode_change
        
        self.global_res_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option(key="4K (2160p)", text="4K (2160p)"),
                ft.dropdown.Option(key="1080p FullHD", text="1080p FullHD"),
                ft.dropdown.Option(key="720p HD", text="720p HD"),
                ft.dropdown.Option(key="480p SD", text="480p SD"),
                ft.dropdown.Option(key="360p SD", text="360p SD"),
            ],
            value="4K (2160p)",
            width=160,
            border_radius=8,
            filled=True,
            bgcolor="#1C1C1E",
            border_color="transparent"
        )

        controls_row = ft.Container(
            content=ft.Row([
                self.mode_dropdown, 
                ft.Row([ft.Text(value="Макс. качество:", color="#B3B3B3"), self.global_res_dropdown])
            ], alignment="spaceBetween"),
            padding=10
        )

        self.queue_list = ft.ListView(expand=True, spacing=10, auto_scroll=False)

        self.status_text = ft.Text(value="Ожидание ссылок...", color="#8A8A8A", size=13)
        self.btn_clear = ft.TextButton(
            content=ft.Row([ft.Icon("delete_outline"), ft.Text(value="Очистить очередь")], alignment="center", spacing=5), 
            on_click=self.clear_queue
        )
        
        self.btn_start = ft.ElevatedButton(
            content=ft.Row([ft.Icon("play_arrow_rounded"), ft.Text(value="ЗАПУСТИТЬ ОЧЕРЕДЬ")], alignment="center", spacing=5),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8), 
                bgcolor="#43A047", 
                color="#FFFFFF",
                padding=20
            ),
            on_click=self.start_queue
        )

        bottom_row = ft.Row([
            ft.Column([self.btn_clear, self.status_text], spacing=2),
            self.btn_start
        ], alignment="spaceBetween")

        self.page.add(
            top_row,
            controls_row,
            ft.Divider(color="#2C2C2E"),
            self.queue_list,
            ft.Divider(color="#2C2C2E"),
            bottom_row
        )

    # --- UI ЛОГИКА ---
    def show_snack(self, message, color="#4CAF50"):
        snack = ft.SnackBar(content=ft.Text(value=message), bgcolor=color)
        if hasattr(self.page, "open"):
            self.page.open(snack)
        else:
            self.page.snack_bar = snack
            self.page.snack_bar.open = True
            self.page.update()

    def update_status(self, text, color="#8A8A8A"):
        self.status_text.value = text
        self.status_text.color = color
        self.page.update()

    def toggle_ui(self, disabled: bool):
        self.url_input.disabled = disabled
        self.btn_add.disabled = disabled
        self.btn_settings.disabled = disabled
        self.mode_dropdown.disabled = disabled
        self.btn_clear.disabled = disabled
        self.global_res_dropdown.disabled = disabled if not disabled else True
        if not disabled and self.mode_dropdown.value != "Видео":
            self.global_res_dropdown.disabled = True
            
        for item in self.queue_items:
            item.set_disabled(disabled)
        self.page.update()

    def on_mode_change(self, e):
        selected = self.mode_dropdown.value
        self.global_res_dropdown.disabled = (selected != "Видео")
        logging.info(f"Глобальный режим изменен на: {selected}")
        
        if self.queue_items:
            needs_change = any(item.mode != selected for item in self.queue_items)
            if needs_change:
                def dialog_handler(apply):
                    self.close_dialog(self.dlg_mode)
                    if apply:
                        for item in self.queue_items:
                            item.change_mode(selected)

                self.dlg_mode = ft.AlertDialog(
                    title=ft.Text(value="Смена режима"),
                    content=ft.Text(value=f"Перевести все видео в очереди в режим '{selected}'?"),
                    actions=[
                        ft.TextButton(content=ft.Text(value="Нет"), on_click=lambda e: dialog_handler(False)),
                        ft.TextButton(content=ft.Text(value="Да, применить"), on_click=lambda e: dialog_handler(True)),
                    ],
                )
                self.open_dialog(self.dlg_mode)
        else:
            self.page.update()

    def open_settings(self, e):
        switch_trans = ft.Switch(label="Авто-перевод Яндекса", value=self.settings["add_translation"], active_color="#E040FB")
        slider_vol_orig = ft.Slider(min=0, max=100, value=self.settings["vol_original"], divisions=100, label="{value}%")
        slider_vol_trans = ft.Slider(min=0, max=100, value=self.settings["vol_translate"], divisions=100, label="{value}%")
        path_input = ft.TextField(value=self.settings["save_path"], expand=True, read_only=True, height=40)

        def save_and_close(e):
            self.settings["add_translation"] = switch_trans.value
            self.settings["vol_original"] = int(slider_vol_orig.value)
            self.settings["vol_translate"] = int(slider_vol_trans.value)
            self.settings["save_path"] = path_input.value
            SettingsManager.save(self.settings)
            
            for item in self.queue_items:
                item.update_yandex_visibility(self.settings["add_translation"])
            
            self.close_dialog(self.dlg_settings)

        def pick_dir(e):
            def run_tkinter():
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(title="Выберите папку для сохранения")
                root.destroy()
                if folder:
                    path_input.value = folder
                    path_input.update()
            
            threading.Thread(target=run_tkinter, daemon=True).start()

        btn_folder = ft.Container(
            content=ft.Icon("folder_open"),
            on_click=pick_dir,
            padding=10, ink=True, border_radius=8
        )

        content = ft.Column([
            switch_trans,
            ft.Text(value="Громкость оригинала:"), slider_vol_orig,
            ft.Text(value="Громкость перевода:"), slider_vol_trans,
            ft.Text(value="Папка для сохранения:"),
            ft.Row([path_input, btn_folder])
        ], width=400, height=350, spacing=5)

        self.dlg_settings = ft.AlertDialog(
            title=ft.Text(value="Настройки", size=20, weight="bold"),
            content=content,
            actions=[ft.ElevatedButton(content=ft.Text(value="Сохранить"), on_click=save_and_close)]
        )
        self.open_dialog(self.dlg_settings)

    def check_dependencies(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        headers = {'User-Agent': 'Mozilla/5.0'}

        dependencies = [
            (self.ytdlp_path, self.ytdlp_url, "yt-dlp"),
            (self.vot_path, self.vot_url, "vot-cli"),
            (self.ffmpeg_path, None, "FFmpeg")
        ]

        for path, url, name in dependencies:
            if not os.path.exists(path):
                self.update_status(f"Установка ядра {name}...", "#FFC107")
                try:
                    if name == "FFmpeg":
                        dl_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" if self.os_name == "Windows" else "https://evermeet.cx/ffmpeg/getrelease/zip"
                        temp_path = path + ".zip"
                        req = urllib.request.Request(dl_url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx) as response, open(temp_path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                            for file_info in zip_ref.infolist():
                                if file_info.filename.endswith(self.ffmpeg_exe_name):
                                    with zip_ref.open(file_info) as source, open(self.ffmpeg_path, "wb") as target:
                                        target.write(source.read())
                                    break
                        if os.path.exists(temp_path): os.remove(temp_path)
                    elif name == "vot-cli":
                        temp_path = path + ".tmp"
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx) as response, open(temp_path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                        try:
                            with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                                for file_info in zip_ref.infolist():
                                    if not file_info.filename.endswith('/') and "vot" in file_info.filename.lower():
                                        with zip_ref.open(file_info) as source, open(path, "wb") as target:
                                            target.write(source.read())
                                        break
                        except zipfile.BadZipFile:
                            shutil.copyfile(temp_path, path)
                        if os.path.exists(temp_path): os.remove(temp_path)
                    else:
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx) as response, open(path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                    
                    if self.os_name != "Windows": os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
                except Exception as e:
                    self.update_status(f"Ошибка загрузки {name}", "#F44336")
                    return

        self.update_status("Проверка обновлений ядер...", "#FFC107")
        try:
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            subprocess.run([self.ytdlp_path, "-U"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        except: pass

        self.update_status("✅ Готов к работе", "#4CAF50")

    def request_format_fetch(self, item):
        self.format_fetch_queue.put(item)

    def format_fetch_worker(self):
        while True:
            try:
                item = self.format_fetch_queue.get()
                if item not in self.queue_items or item.mode != "Видео":
                    self.format_fetch_queue.task_done()
                    continue

                cmd = [self.ytdlp_path, '--dump-json', '--no-playlist', '--no-check-certificate', item.url]
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', **kwargs)
                
                max_val = 1080
                if res.returncode == 0:
                    info = json.loads(res.stdout.splitlines()[0]) 
                    max_h = max([max((f.get('width') or 0), (f.get('height') or 0)) for f in info.get('formats', [])] + [0])
                    
                    if max_h >= 2160: max_val = 2160
                    elif max_h >= 1080: max_val = 1080
                    elif max_h >= 720: max_val = 720
                    elif max_h >= 480: max_val = 480
                    else: max_val = 360
                
                all_res = [(2160, "4K (2160p)"), (1080, "1080p FullHD"), (720, "720p HD"), (480, "480p SD"), (360, "360p SD")]
                res_list = [name for h, name in all_res if h <= max_val] or ["360p SD"]
                
                item.set_available_resolutions(res_list, self.global_res_dropdown.value)
                self.format_fetch_queue.task_done()
            except Exception as e:
                logging.error(f"Ошибка в format_fetch_worker: {e}")
                self.format_fetch_queue.task_done()

    def fetch_and_add(self, e):
        url = self.url_input.value.strip()
        if len(url) < 10: return
        
        self.btn_add.disabled = True
        self.page.update()
        threading.Thread(target=self._analyze_url_thread, args=(url,), daemon=True).start()

    def _analyze_url_thread(self, url):
        try:
            cmd = [self.ytdlp_path, '--dump-json', '--ignore-errors', '--no-check-certificate', '--flat-playlist', url]
            kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='ignore', **kwargs)
            
            videos = []
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                try:
                    data = json.loads(line)
                    if data.get('id'):
                        videos.append(data)
                        self.update_status(f"Анализ... Найдено: {len(videos)}", "#FFFFFF")
                except: pass
                
            process.wait()
            if not videos: 
                raise Exception("Видео не найдено")

            if len(videos) > 1:
                self.show_playlist_dialog(videos)
            else:
                self.add_items_to_queue(videos)

        except Exception as e:
            logging.error(f"Ошибка анализа ссылки: {e}")
            self.show_snack(f"Ошибка: {e}", "#F44336")
            self.update_status("Ошибка анализа", "#F44336")
        finally:
            self.btn_add.disabled = False
            self.url_input.value = ""
            self.page.update()

    def show_playlist_dialog(self, videos):
        total = len(videos)
        lbl_count = ft.Text(value=f"Выбрано: {total} из {total}", color="#B3B3B3")
        
        checkboxes = []
        def update_count(e):
            selected = sum(1 for c, _ in checkboxes if c.value)
            lbl_count.value = f"Выбрано: {selected} из {total}"
            self.page.update()

        scroll_col = ft.Column(scroll="auto", height=300)
        for vid in videos:
            dur = vid.get('duration', 0)
            dur_str = f" ({int(dur)//60}:{int(dur)%60:02d})" if dur else ""
            title = (vid.get('title', 'Без названия')[:50] + "...") if len(vid.get('title', '')) > 50 else vid.get('title', 'Без названия')
            cb = ft.Checkbox(label=f"{title}{dur_str}", value=True, on_change=update_count)
            checkboxes.append((cb, vid))
            scroll_col.controls.append(cb)

        def confirm(e):
            selected_vids = [v for c, v in checkboxes if c.value]
            self.close_dialog(self.dlg_playlist)
            self.add_items_to_queue(selected_vids)

        self.dlg_playlist = ft.AlertDialog(
            title=ft.Text(value="Найден Плейлист", weight="bold"),
            content=ft.Container(
                content=ft.Column([lbl_count, ft.Divider(color="#2C2C2E"), scroll_col], tight=True),
                width=500
            ),
            actions=[
                ft.TextButton(content=ft.Text(value="Отмена"), on_click=lambda e: self.close_dialog(self.dlg_playlist)),
                ft.ElevatedButton(content=ft.Text(value="Добавить"), on_click=confirm, bgcolor="#43A047", color="#FFFFFF")
            ]
        )
        self.open_dialog(self.dlg_playlist)

    def add_items_to_queue(self, videos_list):
        mode = self.mode_dropdown.value
        global_res = self.global_res_dropdown.value
        
        existing_ids = set(item.video_id for item in self.queue_items)
        added = 0
        
        for vid in videos_list:
            vid_id = vid.get('id')
            if vid_id in existing_ids: continue 
                
            item = QueueItemWidget(self, vid, mode, global_res)
            self.queue_items.append(item)
            self.queue_list.controls.append(item)
            existing_ids.add(vid_id)
            added += 1
            
        if added == 0 and videos_list:
            self.show_snack("Видео уже в очереди", "#FBC02D")
        
        self.update_queue_status()

    def update_queue_status(self):
        total = len(self.queue_items)
        self.update_status(f"В очереди: {total} элементов", "#B3B3B3")

    def clear_queue(self, e=None):
        to_remove = [item for item in self.queue_items if item.status not in ["downloading", "processing"]]
        for item in to_remove:
            self.queue_list.controls.remove(item)
            self.queue_items.remove(item)
        self.update_queue_status()

    def start_queue(self, e):
        if not self.queue_items:
            self.show_snack("Очередь пуста!", "#FBC02D")
            return
            
        if not self.settings["save_path"]:
            def run_tkinter_start():
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(title="Выберите папку для сохранения")
                root.destroy()
                if folder:
                    self.settings["save_path"] = folder
                    SettingsManager.save(self.settings)
                    self.start_queue(None)
            
            threading.Thread(target=run_tkinter_start, daemon=True).start()
            return

        if self.is_downloading:
            self.stop_requested = True
            self.btn_start.disabled = True
            self.update_status("Остановка...", "#FF9800")
            return

        self.stop_requested = False
        self.is_downloading = True
        
        self.btn_start.content = ft.Row([ft.Icon("stop_rounded"), ft.Text(value="ОСТАНОВИТЬ")], alignment="center", spacing=5)
        self.btn_start.style.bgcolor = "#D32F2F"
        self.toggle_ui(True)
        
        threading.Thread(target=self._process_queue_thread, daemon=True).start()

    def _process_queue_thread(self):
        try:
            for item in self.queue_items:
                if self.stop_requested: break
                
                while item.status == "fetching_formats" and not self.stop_requested:
                    time.sleep(0.5)
                    
                if item.status == "waiting" or item.status == "error":
                    self.download_item(item)
                    
        except Exception as e:
            logging.error(f"Глобальная ошибка очереди: {e}")
        finally:
            self.is_downloading = False
            self.btn_start.content = ft.Row([ft.Icon("play_arrow_rounded"), ft.Text(value="ЗАПУСТИТЬ ОЧЕРЕДЬ")], alignment="center", spacing=5)
            self.btn_start.style.bgcolor = "#43A047"
            self.btn_start.disabled = False
            self.toggle_ui(False)
            self.update_queue_status()

    def download_item(self, item):
        process = None
        try:
            actual_translation_path = None
            if item.mode == "Видео" and item.use_yandex:
                item.set_status("Яндекс переводит...", "#E040FB")
                
                translate_temp = os.path.join(self.settings["save_path"], f"{item.video_id}.mp3")
                cmd_vot = [self.vot_path, item.url, f'--outdir={self.settings["save_path"]}']
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                
                subprocess.run(cmd_vot, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
                
                if self.stop_requested: raise Exception("Остановлено")
                
                if os.path.exists(translate_temp):
                    actual_translation_path = translate_temp
                else:
                    item.set_status("⚠️ Перевод не удался", "#FF9800")
                    time.sleep(1.5)

            item.set_status("Скачивание...", "#42A5F5")
            
            safe_title = "".join([c for c in item.title_text if c.isalnum() or c in (' ', '.', '_', '-', '!')]).strip().rstrip('.')
            is_audio = (item.mode == "Только Аудио (MP3)")
            
            res_raw = item.combo_res.value
            res_num = 2160 if "4K" in res_raw else (int(res_raw.split("p")[0]) if "p" in res_raw else 1080)
            
            base_name = f"{safe_title}.mp3" if is_audio else f"{safe_title} {res_num}p.mp4"
            final_name = base_name if is_audio else (f"{safe_title} {res_num}p (Яндекс).mp4" if actual_translation_path else base_name)
                
            base_path = os.path.join(self.settings["save_path"], base_name)
            final_path = os.path.join(self.settings["save_path"], final_name)

            if os.path.exists(final_path):
                item.set_progress(100)
                item.set_status("✅ Готово", "#4CAF50")
                return

            temp_template = os.path.join(self.settings["save_path"], "temp_v.%(ext)s")
            temp_video = os.path.join(self.settings["save_path"], "temp_v.mp4")
            temp_mp3 = os.path.join(self.settings["save_path"], "temp_v.mp3")
            
            if not (not is_audio and actual_translation_path and os.path.exists(base_path)): 
                if is_audio:
                    cmd = [
                        self.ytdlp_path, '-f', 'bestaudio', '--extract-audio', '--audio-format', 'mp3',
                        '--audio-quality', '0', '-o', temp_template, '--newline', '--no-playlist', 
                        '--no-check-certificate', '--ffmpeg-location', self.ffmpeg_path, item.url
                    ]
                else:
                    MAX_DIMS = {4320: 7680, 2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640, 240: 426}
                    max_dim = MAX_DIMS.get(res_num, 1920)
                    cmd = [
                        self.ytdlp_path, '-f', f'bestvideo[width<={max_dim}][height<={max_dim}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                        '-o', temp_video, '--newline', '--no-playlist',
                        '--no-check-certificate', '--ffmpeg-location', self.ffmpeg_path, item.url
                    ]
                
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', **kwargs)
                
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
                            item.set_progress(percent)
                            
                process.wait()
                if process.returncode != 0 and not self.stop_requested:
                    raise Exception("Ошибка загрузки")

                actual_temp = temp_mp3 if is_audio else temp_video
                if os.path.exists(actual_temp):
                    if os.path.exists(base_path): os.remove(base_path)
                    os.rename(actual_temp, base_path)

            if getattr(self, 'stop_requested', False): raise Exception("Остановлено")

            if not is_audio and actual_translation_path:
                item.set_status("Склейка...", "#FF9800")
                
                v1, v2 = self.settings["vol_original"]/100, self.settings["vol_translate"]/100
                cmd_ffmpeg = [self.ffmpeg_path, '-y', '-i', base_path, '-i', actual_translation_path,
                       '-filter_complex', f'[0:a]volume={v1}[a1];[1:a]volume={v2}[a2];[a1][a2]amix=inputs=2[aout]',
                       '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', final_path]
                       
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                subprocess.run(cmd_ffmpeg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

            item.set_progress(100)
            item.set_status("✅ Готово", "#4CAF50")
            
        except Exception as e:
            if process and process.poll() is None: process.terminate() 
            item.set_status("❌ Ошибка" if "Остановлено" not in str(e) else "⏹ Остановлено", "#F44336")
        finally:
            if actual_translation_path and os.path.exists(actual_translation_path):
                try: os.remove(actual_translation_path)
                except: pass
            
            save_dir = self.settings.get("save_path", "")
            if save_dir and os.path.exists(save_dir):
                for f_name in os.listdir(save_dir):
                    if f_name.startswith("temp_v") or f_name.startswith("temp_trans_"):
                        try: os.remove(os.path.join(save_dir, f_name))
                        except: pass

class QueueItemWidget(ft.Container):
    def __init__(self, app: VideoMixerApp, video_info, mode, global_res_str):
        super().__init__()
        self.app = app
        self.video_id = video_info.get('id', '')
        self.url = video_info.get('url') or f"https://www.youtube.com/watch?v={self.video_id}"
        self.title_text = video_info.get('title', 'Видео')
        self.mode = mode
        self.status = "waiting" 
        self.use_yandex = app.settings.get("add_translation")

        self.bgcolor = "#1C1C1E"
        self.border_radius = 12
        self.padding = 15

        display_title = (self.title_text[:60] + '...') if len(self.title_text) > 60 else self.title_text
        self.lbl_title = ft.Text(value=display_title, weight="bold", size=14, color="#FFFFFF")
        
        self.btn_remove = ft.Container(
            content=ft.Icon("close", color="#EF5350", size=20),
            on_click=self.remove_self,
            width=35, height=35,
            alignment=ft.alignment.center,
            ink=True, border_radius=8
        )
        
        self.combo_res = ft.Dropdown(
            options=[ft.dropdown.Option(key="4K (2160p)", text="4K (2160p)")], 
            value="4K (2160p)", 
            width=140, height=40,
            text_size=12,
            content_padding=10,
            border_color="transparent", bgcolor="#2C2C2E"
        )
        self.lbl_mp3 = ft.Text(value="🎵 Формат: MP3", color="#8A8A8A", size=13)
        
        self.btn_yandex = ft.Switch(
            label="Яндекс.Перевод", 
            value=self.use_yandex, 
            active_color="#E040FB",
            on_change=self.toggle_yandex
        )

        self.lbl_status = ft.Text(value="В очереди", color="#8A8A8A", size=12)
        self.progress_bar = ft.ProgressBar(value=0, color="#2196F3", bgcolor="#2C2C2E", expand=True)
        self.lbl_percent = ft.Text(value="0%", size=12, color="#B3B3B3", width=40, text_align="right")

        self.controls_row = ft.Row(spacing=15)
        self.setup_mode_ui(global_res_str)

        self.content = ft.Column([
            ft.Row([self.lbl_title, self.btn_remove], alignment="spaceBetween"),
            ft.Row([self.controls_row, self.lbl_status], alignment="spaceBetween"),
            ft.Row([self.progress_bar, self.lbl_percent])
        ], spacing=8)

    def setup_mode_ui(self, target_res=""):
        self.controls_row.controls.clear()
        
        if self.mode == "Видео":
            self.controls_row.controls.append(self.combo_res)
            if self.app.settings.get("add_translation"):
                self.btn_yandex.visible = True
                self.controls_row.controls.append(self.btn_yandex)
            else:
                self.btn_yandex.visible = False
                
            if len(self.combo_res.options) == 1 and self.status == "waiting":
                self.status = "fetching_formats"
                self.combo_res.disabled = True
                self.app.request_format_fetch(self)
        else:
            self.controls_row.controls.append(self.lbl_mp3)
            if self.status == "fetching_formats":
                self.status = "waiting"
        
        if target_res and self.page:
            self.page.update()

    def change_mode(self, new_mode):
        if self.mode == new_mode: return
        self.mode = new_mode
        self.setup_mode_ui()
        if self.page: self.page.update()

    def set_available_resolutions(self, res_list, global_res_str):
        self.combo_res.options = [ft.dropdown.Option(key=r, text=r) for r in res_list]
        self.combo_res.disabled = False
        
        global_val = 2160 if "4K" in global_res_str else (int(global_res_str.split("p")[0]) if "p" in global_res_str else 1080)
        selected = res_list[0] 
        for r in res_list:
            val = 2160 if "4K" in r else (int(r.split("p")[0]) if "p" in r else 0)
            if val <= global_val:
                selected = r
                break 
                
        self.combo_res.value = selected
        if self.status == "fetching_formats":
            self.status = "waiting"
        
        if self.page: self.page.update()

    def update_yandex_visibility(self, global_trans):
        if self.mode == "Видео":
            if global_trans:
                if not self.btn_yandex.visible:
                    self.btn_yandex.visible = True
                    self.btn_yandex.value = True
                    self.use_yandex = True
                    if self.btn_yandex not in self.controls_row.controls:
                        self.controls_row.controls.append(self.btn_yandex)
            else:
                self.btn_yandex.visible = False
                self.use_yandex = False
                if self.btn_yandex in self.controls_row.controls:
                    self.controls_row.controls.remove(self.btn_yandex)
            if self.page: self.page.update()

    def toggle_yandex(self, e):
        self.use_yandex = self.btn_yandex.value

    def set_progress(self, percent):
        self.progress_bar.value = percent / 100.0
        self.lbl_percent.value = f"{int(percent)}%"
        if self.page: self.page.update()

    def set_status(self, text, color):
        if text == "❌ Ошибка" or text == "✅ Готово" or text == "⏹ Остановлено":
            self.status = "error" if "Ошибка" in text or "Остановлено" in text else "done"
        self.lbl_status.value = text
        self.lbl_status.color = color
        if self.page: self.page.update()

    def set_disabled(self, disabled):
        self.btn_remove.disabled = disabled
        if disabled:
            self.combo_res.disabled = True
            self.btn_yandex.disabled = True
        else:
            if self.mode == "Видео":
                self.combo_res.disabled = False
                self.btn_yandex.disabled = False
        if self.page: self.page.update()

    def remove_self(self, e):
        if self.status in ["downloading", "processing"]:
            self.app.show_snack("Дождитесь окончания или остановите очередь", "#FBC02D")
            return
        self.app.queue_list.controls.remove(self)
        self.app.queue_items.remove(self)
        self.app.update_queue_status()
        self.page.update()

def main(page: ft.Page):
    try:
        VideoMixerApp(page)
    except Exception as e:
        logging.critical(f"Сбой при отрисовке UI: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        ft.app(target=main)
    except Exception as e:
        logging.critical(f"Критическая ошибка ядра Flet: {e}", exc_info=True)
