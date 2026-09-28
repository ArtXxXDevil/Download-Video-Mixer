import flet as ft
import subprocess
import threading
import os
import sys
import json
import platform
import urllib.request
import urllib.parse
import urllib.error
import zipfile
import tarfile
import stat
import shutil
import ssl
import re
import queue
import time
import traceback
from datetime import datetime

# --- РАЗДЕЛЕНИЕ ПУТЕЙ ---

# 1. Каталог приложения (только для чтения)
if getattr(sys, 'frozen', False):
    if platform.system() == "Darwin":
        APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))))
    else:
        APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Пользовательский каталог данных (Чтение/Запись)
def get_app_data_dir():
    system = platform.system()
    if system == "Darwin":
        path = os.path.join(os.path.expanduser("~/Library/Application Support"), "Download Video Mixer")
    elif system == "Windows":
        path = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Download Video Mixer")
    else:
        path = os.path.join(os.path.expanduser("~/.local/share"), "Download Video Mixer")
    return path

APP_DATA_DIR = get_app_data_dir()
RUNTIME_DIR = os.path.join(APP_DATA_DIR, "runtime")
BIN_DIR = os.path.join(RUNTIME_DIR, "bin")
NODE_DIR = os.path.join(RUNTIME_DIR, "node")
NODE_MODULES_DIR = os.path.join(RUNTIME_DIR, "node_modules")
TEMP_DIR = os.path.join(RUNTIME_DIR, "temp")

SETTINGS_FILE = os.path.join(APP_DATA_DIR, "settings.json")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "error.log")

for d in [RUNTIME_DIR, BIN_DIR, NODE_DIR, TEMP_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)


def log_error(video_id, error_msg, exception=None, vot_log=None):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(f"Video ID: {video_id}\n")
            f.write(f"Ошибка: {error_msg}\n")
            if vot_log:
                f.write(f"Консоль VOT: {vot_log}\n")
            if exception and "urllib.error.URLError" not in str(type(exception)):
                f.write(traceback.format_exc())
    except:
        pass


class DependencyManager:
    """ Управляет загрузкой, проверкой и предоставлением путей ко всем внешним Runtime зависимостям """
    def __init__(self, update_status_cb):
        self.update_status = update_status_cb
        self.os_name = platform.system()
        self.node_version = "v20.18.0"

        if self.os_name == "Windows":
            self.node_exe = os.path.join(NODE_DIR, f"node-{self.node_version}-win-x64", "node.exe")
            self.npm_cmd = os.path.join(NODE_DIR, f"node-{self.node_version}-win-x64", "npm.cmd")
            self.node_url = f"https://nodejs.org/dist/{self.node_version}/node-{self.node_version}-win-x64.zip"

            self.ffmpeg_exe_name = "ffmpeg.exe"
            self.ytdlp_exe_name = "yt-dlp.exe"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        else:
            self.node_exe = os.path.join(NODE_DIR, f"node-{self.node_version}-darwin-x64", "bin", "node")
            self.npm_cmd = os.path.join(NODE_DIR, f"node-{self.node_version}-darwin-x64", "bin", "npm")
            self.node_url = f"https://nodejs.org/dist/{self.node_version}/node-{self.node_version}-darwin-x64.tar.gz"

            self.ffmpeg_exe_name = "ffmpeg"
            self.ytdlp_exe_name = "yt-dlp"
            self.ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"

        self.ffmpeg_path = os.path.join(BIN_DIR, self.ffmpeg_exe_name)
        self.ytdlp_path = os.path.join(BIN_DIR, self.ytdlp_exe_name)
        self.vot_path = None

    def ensure_dependencies(self, startupinfo):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        headers = {'User-Agent': 'Mozilla/5.0'}

        # 1. Node.js
        if not os.path.exists(self.node_exe):
            self.update_status("Скачивание автономного Node.js (≈30MB)...", "orange")
            try:
                archive_path = os.path.join(TEMP_DIR, "node_temp.zip" if self.os_name == "Windows" else "node_temp.tar.gz")
                req = urllib.request.Request(self.node_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx) as response, open(archive_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                    
                self.update_status("Распаковка Node.js...", "orange")
                if self.os_name == "Windows":
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extractall(NODE_DIR)
                else:
                    with tarfile.open(archive_path, 'r:gz') as tar_ref:
                        tar_ref.extractall(NODE_DIR)
                        
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                    
                if self.os_name != "Windows":
                    os.chmod(self.node_exe, os.stat(self.node_exe).st_mode | stat.S_IEXEC)
                    os.chmod(self.npm_cmd, os.stat(self.npm_cmd).st_mode | stat.S_IEXEC)
            except Exception as e:
                self.update_status("❌ Ошибка скачивания Node.js", "red")
                log_error("Система", "Ошибка скачивания Node.js", e)
                return False

        # 2. FFmpeg & yt-dlp
        dependencies = [
            (self.ytdlp_path, self.ytdlp_url, "yt-dlp", "≈30MB"),
            (self.ffmpeg_path, None, "FFmpeg", "≈40MB")
        ]

        for path, url, name, size in dependencies:
            if not os.path.exists(path):
                self.update_status(f"Скачивание {name} ({size})...", "orange")
                try:
                    if name == "FFmpeg":
                        dl_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" if self.os_name == "Windows" else "https://evermeet.cx/ffmpeg/getrelease/zip"
                        zip_path = os.path.join(TEMP_DIR, "ffmpeg_temp.zip")
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
                except Exception as e:
                    self.update_status(f"❌ Ошибка скачивания {name}", "red")
                    log_error("Система", f"Ошибка скачивания {name}", e)
                    return False

        # 3. vot-cli
        bin_dir = os.path.join(NODE_MODULES_DIR, ".bin")
        possible_bins = ["vot-cli-live.cmd", "vot-cli-live", "vot-cli.cmd", "vot-cli"]
        
        for b in possible_bins:
            p = os.path.join(bin_dir, b)
            if os.path.exists(p):
                self.vot_path = p
                break

        if not self.vot_path:
            self.update_status("Установка JS-версии vot-cli...", "orange")
            try:
                kwargs = {'startupinfo': startupinfo} if startupinfo else {}
                env = os.environ.copy()
                env["PATH"] = os.path.dirname(self.node_exe) + os.pathsep + env.get("PATH", "")
                
                subprocess.run([self.npm_cmd, "install", "github:fantomcheg/vot-cli-live", "--no-save", "--prefix", RUNTIME_DIR], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
                
                for b in possible_bins:
                    p = os.path.join(bin_dir, b)
                    if os.path.exists(p):
                        self.vot_path = p
                        break
                        
                if not self.vot_path:
                    raise Exception("Бинарный файл vot-cli не найден после npm install")
            except Exception as e:
                self.update_status("❌ Ошибка установки JS-модуля vot-cli", "red")
                log_error("Система", "Ошибка NPM Install", e)
                return False

        self.update_status("Проверка обновлений движка...", "orange")
        try:
            kwargs = {'startupinfo': startupinfo} if startupinfo else {}
            subprocess.run([self.ytdlp_path, "-U"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        except: pass

        self.update_status("Готов к работе", "green")
        return True


class SettingsManager:
    @staticmethod
    def load():
        default_save = os.path.join(os.path.expanduser("~"), "Downloads")
        defaults = {
            "add_translation": False,
            "show_manual_audio": False,
            "delete_original": False,
            "title_translator": "Не переводить", 
            "ai_base_url": "https://openrouter.ai/api/v1/chat/completions",
            "ai_model": "openrouter/free",
            "ai_token": "",
            "discovered_models": [],
            "blacklisted_models": [],
            "global_quality": "4K (2160p)",
            "vol_original": 15,
            "vol_translate": 100,
            "save_path": default_save
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    old_models = ["google/gemma-2-9b-it:free", "meta-llama/llama-3.1-8b-instruct:free", "microsoft/phi-3-mini-128k-instruct:free"]
                    if loaded.get("ai_model") in old_models:
                        loaded["ai_model"] = "openrouter/free"
                    return {**defaults, **loaded}
            except:
                return defaults
        return defaults

    @staticmethod
    def save(settings):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)


# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Цветовая палитра приложения
ACCENT       = "#A855F7"    # Фиолетовый акцент
ACCENT_HOVER = "#9333EA"
SURFACE      = "#18181B"    # Тёмный фон
SURFACE2     = "#27272A"    # Карточки
SURFACE3     = "#3F3F46"    # Бордер / hover
TEXT_PRIMARY = "#FAFAFA"
TEXT_MUTED   = "#A1A1AA"
SUCCESS      = "#22C55E"
ERROR_COLOR  = "#EF4444"
WARNING      = "#F59E0B"
INFO         = "#3B82F6"
PURPLE_DIM   = "#7C3AED"

def snack(page: ft.Page, msg: str, color: str = SURFACE2, icon=None):
    """Показывает SnackBar с сообщением."""
    content_row = ft.Row(
        [
            ft.Icon(icon, color=TEXT_PRIMARY, size=18) if icon else ft.Container(),
            ft.Text(msg, color=TEXT_PRIMARY, size=13),
        ],
        tight=True,
        spacing=8,
    )
    sb = ft.SnackBar(
        content=content_row,
        bgcolor=color,
        duration=3500,
    )
    page.overlay.append(sb)
    sb.open = True
    page.update()


def _card(content, padding=10, border_radius=10, bgcolor=SURFACE2):
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=border_radius,
        bgcolor=bgcolor,
        border=ft.border.all(1, SURFACE3),
    )


# ─────────────────────────────────────────────────────────────────────────────
# QueueItemWidget  — элемент очереди загрузок
# ─────────────────────────────────────────────────────────────────────────────

class QueueItemWidget:
    """Представляет один элемент в очереди. Строит ft.Container и управляет своим состоянием."""

    def __init__(self, app: "VideoApp", video_info: dict, mode: str, global_res_str: str):
        self.app = app
        self.page = app.page
        self.video_info = video_info
        self.video_id = video_info.get('id', '')
        self.url = video_info.get('url') or f"https://www.youtube.com/watch?v={self.video_id}"
        self.title_text = video_info.get('title', 'Видео')
        self.translated_title = None
        self.used_model = None
        self.used_translator = None
        self.force_free_model = False
        self.mode = mode
        self.status = "waiting"

        self.use_yandex_translation = self.app.settings.get("add_translation", False)
        self.manual_audio_path = None

        # ── Прогресс-бар ──
        self.progress_bar = ft.ProgressBar(
            value=0,
            color=ACCENT,
            bgcolor=SURFACE3,
            expand=True,
        )
        self.lbl_percent = ft.Text("0%", size=12, color=TEXT_MUTED, width=38, text_align=ft.TextAlign.RIGHT)

        # ── Статус ──
        self.lbl_status = ft.Text("В очереди", size=11, color=TEXT_MUTED)

        # ── Выбор разрешения ──
        self._res_values = [global_res_str]
        self.dropdown_res = ft.DropdownM2(
            options=[ft.dropdown.Option(global_res_str)],
            value=global_res_str,
            width=140,
            height=34,
            text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            on_change=None,
            bgcolor=SURFACE3,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
        )

        self.lbl_mp3 = ft.Text("[Аудио MP3]", size=11, color=TEXT_MUTED)

        # ── Кнопка перевода Яндекс ──
        self.btn_yandex = ft.FilledButton(
            content="Перевод ВКЛ",
            icon=ft.Icons.RECORD_VOICE_OVER,
            on_click=self._toggle_yandex,
            style=ft.ButtonStyle(
                bgcolor=PURPLE_DIM,
                color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            ),
            height=32,
            visible=False,
        )

        # ── Кнопка своего аудио ──
        self.btn_manual = ft.FilledButton(
            content="Свой аудио",
            icon=ft.Icons.AUDIO_FILE,
            on_click=self._select_manual_audio,
            style=ft.ButtonStyle(
                bgcolor=SURFACE3,
                color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            ),
            height=32,
            visible=False,
        )

        # ── Название ──
        display_title = (self.title_text[:68] + '…') if len(self.title_text) > 68 else self.title_text
        self.lbl_title = ft.Text(
            display_title,
            size=13,
            weight=ft.FontWeight.BOLD,
            color=TEXT_PRIMARY,
            expand=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        )
        self._title_gesture = ft.GestureDetector(
            content=self.lbl_title,
            mouse_cursor=ft.MouseCursor.BASIC,
            on_tap=None,
        )

        # ── Кнопки управления ──
        self.btn_restart = ft.IconButton(
            icon=ft.Icons.REFRESH,
            icon_color=INFO,
            icon_size=18,
            tooltip="Сбросить и повторить",
            on_click=self._restart_self,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )
        self.btn_remove = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE,
            icon_color=ERROR_COLOR,
            icon_size=18,
            tooltip="Удалить из очереди",
            on_click=self._remove_self,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )

        # ── Строим виджет ──
        self.container = self._build()

        # Настройка режима
        self._setup_mode_ui()
        self._update_title_binding()

    # ── Сборка контейнера ──────────────────────────────────────────────────

    def _build(self) -> ft.Container:
        top_row = ft.Row(
            [
                self._title_gesture,
                self.btn_restart,
                self.btn_remove,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._mid_row = ft.Row(
            [
                self.dropdown_res,
                self.lbl_mp3,
                self.btn_yandex,
                self.btn_manual,
                ft.Container(expand=True),
                self.lbl_status,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        )

        bottom_row = ft.Row(
            [self.progress_bar, self.lbl_percent],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        )

        body = ft.Column(
            [top_row, self._mid_row, bottom_row],
            spacing=6,
        )

        return ft.Container(
            content=body,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=10,
            bgcolor=SURFACE2,
            border=ft.border.all(1, SURFACE3),
            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        )

    # ── Внутренние методы ──────────────────────────────────────────────────

    def _update_title_binding(self):
        translator = self.app.settings.get("title_translator", "Не переводить")
        if translator == "Не переводить":
            self._title_gesture.mouse_cursor = ft.MouseCursor.BASIC
            self._title_gesture.on_tap = None
        else:
            self._title_gesture.mouse_cursor = ft.MouseCursor.CLICK
            self._title_gesture.on_tap = self._show_translation_dialog

    def _setup_mode_ui(self):
        if self.mode == "Видео":
            self.dropdown_res.visible = True
            self.lbl_mp3.visible = False
            self._update_yandex_visibility(is_refresh=True)
            if self._res_values == [self.dropdown_res.value] and self.status == "waiting":
                self.status = "fetching_formats"
                self.dropdown_res.value = "Загрузка..."
                self.dropdown_res.disabled = True
                self.app.request_format_fetch(self)
        else:
            self.dropdown_res.visible = False
            self.lbl_mp3.visible = True
            self.btn_yandex.visible = False
            self.btn_manual.visible = False
            if self.status == "fetching_formats":
                self.status = "waiting"

    def change_mode(self, new_mode):
        if self.mode == new_mode:
            return
        self.mode = new_mode
        self._setup_mode_ui()
        self.page.update()

    def set_available_resolutions(self, res_list: list, global_res_str: str):
        self._res_values = res_list
        self.dropdown_res.options = [ft.dropdown.Option(r) for r in res_list]
        self.dropdown_res.disabled = self.app.is_downloading

        global_val = 2160 if "4K" in global_res_str else (int(global_res_str.split("p")[0]) if "p" in global_res_str else 1080)
        selected = res_list[0]
        for r in res_list:
            val = 2160 if "4K" in r else (int(r.split("p")[0]) if "p" in r else 0)
            if val <= global_val:
                selected = r
                break
        self.dropdown_res.value = selected
        if self.status == "fetching_formats":
            self.status = "waiting"
        self.page.update()

    def _update_yandex_visibility(self, is_refresh=False):
        if self.mode != "Видео":
            self.btn_yandex.visible = False
            self.btn_manual.visible = False
            return

        global_trans = self.app.settings.get("add_translation", False)

        if global_trans:
            self.btn_yandex.visible = True
            if is_refresh:
                self.use_yandex_translation = True
                self.btn_yandex.content = "Перевод ВКЛ"
                self.btn_yandex.icon = ft.Icons.RECORD_VOICE_OVER
                self.btn_yandex.style.bgcolor = PURPLE_DIM
        else:
            self.btn_yandex.visible = False
            self.use_yandex_translation = False

        if self.app.settings.get("show_manual_audio", False):
            self.btn_manual.visible = True
        else:
            self.btn_manual.visible = False
            self.manual_audio_path = None
            self.btn_manual.content = "Свой аудио"
            self.btn_manual.style.bgcolor = SURFACE3

    def _toggle_yandex(self, e):
        if self.app.is_downloading:
            return
        self.use_yandex_translation = not self.use_yandex_translation
        if self.use_yandex_translation:
            self.btn_yandex.content = "Перевод ВКЛ"
            self.btn_yandex.style.bgcolor = PURPLE_DIM
            self.manual_audio_path = None
            self.btn_manual.content = "Свой аудио"
            self.btn_manual.style.bgcolor = SURFACE3
        else:
            self.btn_yandex.content = "Перевод ВЫКЛ"
            self.btn_yandex.style.bgcolor = SURFACE3
        self.page.update()

    def _select_manual_audio(self, e):
        if self.app.is_downloading:
            return
        if self.manual_audio_path:
            self.manual_audio_path = None
            self.btn_manual.content = "Свой аудио"
            self.btn_manual.style.bgcolor = SURFACE3
            self.page.update()
            return

        def on_result(result: ft.FilePickerResultEvent):
            if result.files:
                self.manual_audio_path = os.path.abspath(result.files[0].path)
                self.btn_manual.content = "Выбран (сбросить)"
                self.btn_manual.style.bgcolor = SUCCESS
                self.use_yandex_translation = False
                self.btn_yandex.content = "Перевод ВЫКЛ"
                self.btn_yandex.style.bgcolor = SURFACE3
                self.page.update()

        picker = ft.FilePicker(on_result=on_result)
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(
            dialog_title="Выберите аудио",
            allowed_extensions=["mp3", "m4a", "wav"],
        )

    def _remove_self(self, e):
        if self.status in ["downloading", "processing"]:
            snack(self.page, "Дождитесь окончания или остановите очередь.", WARNING, ft.Icons.WARNING_AMBER)
            return
        self.app.queue_items.remove(self)
        self.app.queue_column.controls.remove(self.container)
        self.app.update_queue_status()
        self.page.update()

    def _restart_self(self, e):
        if self.status in ["downloading", "processing"]:
            snack(self.page, "Дождитесь окончания или остановите очередь.", WARNING, ft.Icons.WARNING_AMBER)
            return
        self.status = "waiting"
        self.set_progress_mode("determinate")
        self.set_status("В очереди", TEXT_MUTED)
        self.update_progress(0)
        self.app.update_queue_status()
        self.page.update()

    def _show_translation_dialog(self, e):
        current_translator = self.app.settings.get("title_translator", "Не переводить")
        if current_translator == "Не переводить":
            return

        trans_text = ft.Text("Выполнение перевода…", size=13, color=TEXT_PRIMARY, selectable=True)
        orig_text  = ft.Text(self.title_text, size=13, color=TEXT_MUTED, selectable=True)
        lbl_model  = ft.Text("Модель: ожидание ответа…", size=11, color=TEXT_MUTED)
        copy_btn   = ft.FilledButton(
            content="Скопировать",
            icon=ft.Icons.CONTENT_COPY,
            disabled=True,
            style=ft.ButtonStyle(bgcolor=INFO, color=TEXT_PRIMARY, shape=ft.RoundedRectangleBorder(radius=8)),
        )
        another_btn: ft.ElevatedButton | None = None

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Название видео ({current_translator})", size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
            bgcolor=SURFACE2,
            content=ft.Column(
                [
                    ft.Text("Оригинал:", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                    ft.Container(
                        content=orig_text,
                        bgcolor=SURFACE,
                        border_radius=8,
                        padding=8,
                    ),
                    ft.Text("Перевод:", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                    ft.Container(
                        content=trans_text,
                        bgcolor=SURFACE,
                        border_radius=8,
                        padding=8,
                        min_height=40,
                    ),
                    lbl_model,
                ],
                spacing=6,
                width=440,
                tight=True,
            ),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def close_dlg(e=None):
            dlg.open = False
            self.page.update()

        def copy_to_clip(e):
            self._set_clipboard(trans_text.value)
            copy_btn.content = "✅ Скопировано"
            self.page.update()
            time.sleep(2)
            copy_btn.content = "Скопировать"
            self.page.update()

        copy_btn.on_click = copy_to_clip

        def use_another_model(e):
            global_model = self.app.settings.get("ai_model", "openrouter/free")
            if getattr(self, 'used_model', None) and "Ошибка" not in self.used_model and "Без перевода" not in self.used_model:
                if self.used_model != global_model and global_model != "openrouter/free":
                    self.force_free_model = False
                else:
                    if self.used_model != "openrouter/free":
                        bl = self.app.settings.get("blacklisted_models", [])
                        if self.used_model not in bl:
                            bl.append(self.used_model)
                            self.app.settings["blacklisted_models"] = bl
                            SettingsManager.save(self.app.settings)
                    self.force_free_model = True
            else:
                self.force_free_model = True

            self.translated_title = None
            self.used_model = None
            self.used_translator = None
            trans_text.value = "Выполнение перевода…"
            lbl_model.value = "Модель: ожидание ответа…"
            copy_btn.disabled = True
            if another_btn:
                another_btn.disabled = True
            self.page.update()
            threading.Thread(target=fetch_translation, daemon=True).start()

        if current_translator == "Нейросеть (OpenAI/OpenRouter)":
            another_btn = ft.FilledButton(
                content="Другая модель",
                icon=ft.Icons.SWAP_HORIZ,
                on_click=use_another_model,
                disabled=True,
                style=ft.ButtonStyle(bgcolor=PURPLE_DIM, color=TEXT_PRIMARY, shape=ft.RoundedRectangleBorder(radius=8)),
            )

        action_row = [copy_btn]
        if another_btn:
            action_row.insert(0, another_btn)
        action_row.append(ft.TextButton("Закрыть", on_click=close_dlg, style=ft.ButtonStyle(color=TEXT_MUTED)))
        dlg.actions = action_row

        def fetch_translation():
            blacklist = self.app.settings.get("blacklisted_models", [])
            needs_translation = False
            if not getattr(self, 'translated_title', None):
                needs_translation = True
            elif self.translated_title.startswith("[Ошибка") or self.translated_title.startswith("[Лимит"):
                needs_translation = True
            elif getattr(self, 'used_translator', None) != current_translator:
                needs_translation = True
            elif current_translator == "Нейросеть (OpenAI/OpenRouter)" and getattr(self, 'used_model', None) in blacklist:
                needs_translation = True

            if needs_translation:
                self.translated_title, self.used_model = self.translate_text(self.title_text)
                self.used_translator = current_translator

            trans_text.value = self.translated_title
            lbl_model.value = f"Модель: {self.used_model}" if self.used_model else ""
            copy_btn.disabled = False
            if another_btn:
                another_btn.disabled = False
            self.page.update()

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
        threading.Thread(target=fetch_translation, daemon=True).start()

    # ── Публичные методы для управления UI из потоков ─────────────────────

    def set_status(self, text: str, color: str = TEXT_MUTED):
        self.lbl_status.value = text
        self.lbl_status.color = color
        self.page.update()

    def set_progress_mode(self, mode: str = "determinate"):
        if mode == "indeterminate":
            self.progress_bar.value = None  # Flet: None = indeterminate
            self.lbl_percent.value = "~"
        else:
            self.progress_bar.value = 0
            self.lbl_percent.value = "0%"
        self.page.update()

    def update_progress(self, percent: float):
        self.progress_bar.value = percent / 100.0
        self.lbl_percent.value = f"{int(percent)}%"
        self.page.update()

    def set_ui_enabled(self, enabled: bool):
        self.btn_restart.disabled = not enabled
        self.btn_remove.disabled = not enabled
        if self.mode == "Видео":
            self.dropdown_res.disabled = not enabled
            self.btn_yandex.disabled = not enabled
            self.btn_manual.disabled = not enabled
        self.page.update()

    # ── Методы бизнес-логики (сохранены 100%) ─────────────────────────────

    def clean_ai_text(self, text):
        cleaned = text.strip()
        cleaned = re.sub(r'^["\']|["\']$', '', cleaned)
        if "->" in cleaned:
            cleaned = cleaned.split("->")[-1].strip()
        if "Перевод:" in cleaned:
            cleaned = cleaned.split("Перевод:")[-1].strip()
        return cleaned

    def translate_text(self, text):
        translator = self.app.settings.get("title_translator", "Google API")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        if translator == "Нейросеть (OpenAI/OpenRouter)":
            base_url = self.app.settings.get("ai_base_url", "https://openrouter.ai/api/v1/chat/completions")
            token = self.app.settings.get("ai_token", "").strip()
            
            if getattr(self, 'force_free_model', False):
                model = "openrouter/free"
            else:
                model = self.app.settings.get("ai_model", "openrouter/free")
            
            if not token:
                return "[Ошибка: Введите API Token нейросети в Настройках API]", "N/A"
                
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "HTTP-Referer": "https://github.com",
                "X-Title": "Download Video Mixer"
            }
            
            blacklist = self.app.settings.get("blacklisted_models", [])
            free_models_fallback = [
                "google/gemma-2-9b-it:free",
                "meta-llama/llama-3.1-8b-instruct:free",
                "qwen/qwen-2-7b-instruct:free",
                "mistralai/mistral-7b-instruct:free",
                "microsoft/phi-3-mini-128k-instruct:free",
                "nvidia/nemotron-3.5-lightning:free"
            ]
            
            request_model = model
            max_retries = 3
            
            for attempt in range(max_retries):
                data = {
                    "model": request_model,
                    "messages": [
                        {"role": "system", "content": "You are a raw text translator. Output ONLY the Russian translation. NEVER include the original text, prefixes, or explanations."},
                        {"role": "user", "content": f"Translate to Russian:\n{text}"}
                    ],
                    "temperature": 0.1
                }
                req = urllib.request.Request(base_url, headers=headers, data=json.dumps(data).encode('utf-8'))
                
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
                        resp_data = json.loads(response.read().decode('utf-8'))
                        raw_translation = resp_data['choices'][0]['message']['content']
                        
                        actual_model = resp_data.get('model', request_model)
                        
                        if actual_model in blacklist:
                            if attempt < max_retries - 1:
                                time.sleep(1)
                                continue
                        
                        if request_model == "openrouter/free" and actual_model != "openrouter/free":
                            self.app.settings["ai_model"] = actual_model
                            SettingsManager.save(self.app.settings)

                        disc = self.app.settings.get("discovered_models", [])
                        if actual_model not in disc and actual_model != "openrouter/free":
                            disc.append(actual_model)
                            self.app.settings["discovered_models"] = disc
                            SettingsManager.save(self.app.settings)
                            
                        return self.clean_ai_text(raw_translation), actual_model
                        
                except urllib.error.URLError as e:
                    if attempt == max_retries - 1:
                        log_error(self.video_id, f"Сетевая ошибка URLError (Нейросеть): {e.reason}")
                        return f"[Ошибка сети: ИИ недоступен (возможна блокировка)]", "Ошибка Сети"
                    time.sleep(1)
                except urllib.error.HTTPError as e:
                    if e.code in [404, 429, 502, 500] and request_model != "openrouter/free":
                        request_model = "openrouter/free"
                        time.sleep(1)
                        continue
                    elif e.code in [401, 403]:
                        return f"[Ошибка ИИ {e.code}: Проверьте настройки токена]", "Ошибка API"
                    else:
                        try: err_body = e.read().decode('utf-8')
                        except: err_body = str(e)
                        log_error(self.video_id, f"HTTP Ошибка {e.code} (Нейросеть):\n{err_body}")
                        time.sleep(1)
                except Exception as e:
                    if attempt == max_retries - 1:
                        log_error(self.video_id, f"Сетевая ошибка перевода (Нейросеть): {e}")
                        return f"[Ошибка сети: проверьте подключение к ИИ]", "Ошибка Сети"
                    time.sleep(1)
                    
                available = [m for m in free_models_fallback if m not in blacklist and m != request_model]
                if available:
                    request_model = available[attempt % len(available)]
                else:
                    request_model = "openrouter/free"
                time.sleep(1)
                    
            return f"[Ошибка подключения к ИИ или все модели недоступны]", "Ошибка API"

        if translator == "Google API":
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ru&dt=t&q={urllib.parse.quote(text)}"
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
                        data = json.loads(response.read().decode('utf-8'))
                        return "".join([sentence[0] for sentence in data[0]]), "Google Translate API"
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        log_error(self.video_id, "Ошибка перевода названия (API Google) HTTP 429: Too Many Requests")
                        return f"[Ошибка Google API: Лимит запросов. Смените переводчик]", "Ошибка API"
                    time.sleep(1)
                except Exception as e:
                    time.sleep(1)
                    if attempt == max_retries - 1:
                        log_error(self.video_id, f"Ошибка перевода названия (API Google, {max_retries} попыток)")
                        return f"[Ошибка Google API: Сбой подключения]", "Ошибка API"
                        
        return text, "Без перевода"


# ─────────────────────────────────────────────────────────────────────────────
# Основное приложение
# ─────────────────────────────────────────────────────────────────────────────

class VideoApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.os_name = platform.system()
        self.stop_requested = False
        self.is_downloading = False
        self.queue_items: list[QueueItemWidget] = []
        self.actual_downloads_occurred = False
        self.settings = SettingsManager.load()

        self.startupinfo = None
        if self.os_name == "Windows":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Настройка страницы Flet
        page.title = "DownloadZone"
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = SURFACE
        page.padding = 0
        page.window.width = 900
        page.window.height = 720
        page.window.min_width = 750
        page.window.min_height = 550
        page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.DEEP_PURPLE,
            use_material3=True,
        )
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event

        # Иконка приложения
        if self.os_name == "Windows":
            def resource_path(relative_path):
                try: base_path = sys._MEIPASS
                except: base_path = os.path.abspath(".")
                return os.path.join(base_path, relative_path)
            icon_path = resource_path("icon.ico")
            if os.path.exists(icon_path):
                page.window.icon = icon_path

        self._build_ui()

        self.deps = DependencyManager(self._update_status_cb)
        self.format_fetch_queue = queue.Queue()

        threading.Thread(target=self._run_dependency_check, daemon=True).start()
        threading.Thread(target=self._format_fetch_worker, daemon=True).start()

        # Загрузить ссылки из файла с задержкой
        threading.Thread(target=self._delayed_load_urls, daemon=True).start()

    # ── Вспомогательные методы ─────────────────────────────────────────────

    def _set_clipboard(self, text: str):
        """Безопасная запись текста в буфер обмена через сервис-контрол Flet."""
        try:
            cb = ft.Clipboard()
            self.page.overlay.append(cb)
            self.page.update()
            cb.set(text)
            self.page.overlay.remove(cb)
        except Exception:
            pass

    # ── Построение UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        p = self.page

        # ── Заголовок ──
        self._title_lbl = ft.Text(
            "DownloadZone",
            size=30,
            weight=ft.FontWeight.BOLD,
            color="#FF2A93",
        )

        # ── Тема ──
        self._theme_icon = ft.Icons.LIGHT_MODE
        self._theme_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE,
            icon_color=TEXT_MUTED,
            tooltip="Переключить тему",
            on_click=self._toggle_theme,
        )

        # ── Кнопка настроек ──
        self._settings_btn = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            icon_color=TEXT_MUTED,
            icon_size=22,
            tooltip="Настройки",
            on_click=self._open_settings,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )

        # ── Поле ввода URL ──
        self._url_entry = ft.TextField(
            hint_text="Вставьте ссылку на видео или плейлист…",
            expand=True,
            height=42,
            text_size=13,
            border_radius=10,
            bgcolor=SURFACE2,
            border_color=SURFACE3,
            focused_border_color=ACCENT,
            color=TEXT_PRIMARY,
            hint_style=ft.TextStyle(color=TEXT_MUTED),
            on_submit=lambda e: self._fetch_and_add(e),
        )

        # ── Кнопка добавить ──
        self._btn_add = ft.FilledButton(
            content="Добавить",
            icon=ft.Icons.ADD_LINK,
            on_click=self._fetch_and_add,
            style=ft.ButtonStyle(
                bgcolor=SURFACE2,
                color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=10),
                overlay_color=SURFACE3,
            ),
            height=42,
        )

        top_bar = ft.Row(
            [self._settings_btn, self._url_entry, self._btn_add, self._theme_btn],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── Режим и качество ──
        self._mode_seg = ft.SegmentedButton(
            selected=["Видео"],
            segments=[
                ft.Segment(value="Видео", label=ft.Text("Видео"), icon=ft.Icon(ft.Icons.VIDEO_FILE)),
                ft.Segment(value="Только Аудио (MP3)", label=ft.Text("Только Аудио (MP3)"), icon=ft.Icon(ft.Icons.AUDIO_FILE)),
            ],
            on_change=self._on_mode_change,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.SELECTED: ACCENT, ft.ControlState.DEFAULT: SURFACE2},
                color={ft.ControlState.SELECTED: TEXT_PRIMARY, ft.ControlState.DEFAULT: TEXT_MUTED},
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )

        self._res_dropdown = ft.DropdownM2(
            label="Глобальное качество",
            options=[
                ft.dropdown.Option("4K (2160p)"),
                ft.dropdown.Option("1080p FullHD"),
                ft.dropdown.Option("720p HD"),
                ft.dropdown.Option("480p SD"),
                ft.dropdown.Option("360p SD"),
            ],
            value=self.settings.get("global_quality", "4K (2160p)"),
            width=170,
            height=42,
            text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            bgcolor=SURFACE2,
            border_color=SURFACE3,
            focused_border_color=ACCENT,
            color=TEXT_PRIMARY,
            on_change=self._save_global_quality,
        )

        params_row = ft.Row(
            [self._mode_seg, ft.Container(expand=True), self._res_dropdown],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── Очередь ──
        self.queue_column = ft.Column(
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        queue_container = ft.Container(
            content=self.queue_column,
            expand=True,
            padding=ft.Padding.symmetric(vertical=4),
        )

        # ── Нижняя панель ──
        self._clear_btn = ft.OutlinedButton(
            content="Очистить",
            icon=ft.Icons.DELETE_SWEEP,
            on_click=self._clear_queue,
            style=ft.ButtonStyle(
                color=TEXT_MUTED,
                side=ft.BorderSide(1, SURFACE3),
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            height=44,
            width=130,
        )

        self._start_btn = ft.FilledButton(
            content="▶  Запустить очередь",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_queue,
            style=ft.ButtonStyle(
                bgcolor=ACCENT,
                color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=12),
                overlay_color=ACCENT_HOVER,
            ),
            height=44,
            width=220,
        )

        self._status_label = ft.Text("Ожидание ссылок…", color=TEXT_MUTED, size=12)

        bottom_bar = ft.Row(
            [self._clear_btn, self._start_btn, ft.Container(expand=True), self._status_label],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

        # ── Компоновка ──
        header = ft.Row(
            [self._title_lbl, ft.Container(expand=True)],
            alignment=ft.MainAxisAlignment.START,
        )

        layout = ft.Column(
            [
                header,
                top_bar,
                params_row,
                ft.Divider(height=1, color=SURFACE3),
                queue_container,
                ft.Divider(height=1, color=SURFACE3),
                bottom_bar,
            ],
            spacing=12,
            expand=True,
        )

        p.add(
            ft.Container(
                content=layout,
                padding=ft.Padding.symmetric(horizontal=24, vertical=16),
                expand=True,
            )
        )
        self._toggle_ui("disabled")  # Заблокировано до завершения загрузки зависимостей

    # ── Тема ──────────────────────────────────────────────────────────────

    def _toggle_theme(self, e):
        if self.page.theme_mode == ft.ThemeMode.DARK:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self._theme_btn.icon = ft.Icons.DARK_MODE
        else:
            self.page.theme_mode = ft.ThemeMode.DARK
            self._theme_btn.icon = ft.Icons.LIGHT_MODE
        self.page.update()

    # ── Обратные вызовы для зависимостей ──────────────────────────────────

    def _update_status_cb(self, text: str, color: str = "orange"):
        color_map = {
            "orange": WARNING,
            "red": ERROR_COLOR,
            "green": SUCCESS,
            "black": TEXT_PRIMARY,
            "blue": INFO,
        }
        mapped = color_map.get(color, TEXT_MUTED)
        self._status_label.value = text
        self._status_label.color = mapped
        self.page.update()

    def _run_dependency_check(self):
        success = self.deps.ensure_dependencies(self.startupinfo)
        if success:
            self._toggle_ui("normal")
            self.page.update()

    # ── Режим / качество ──────────────────────────────────────────────────

    def _save_global_quality(self, e):
        self.settings["global_quality"] = self._res_dropdown.value
        SettingsManager.save(self.settings)

    def _on_mode_change(self, e):
        selected = list(e.control.selected)[0] if e.control.selected else "Видео"
        if selected != "Видео":
            self._res_dropdown.disabled = True
        else:
            self._res_dropdown.disabled = False

        if self.queue_items:
            needs_change = any(item.mode != selected for item in self.queue_items)
            if needs_change:
                self._confirm_mode_change(selected)
        self.page.update()

    def _confirm_mode_change(self, new_mode: str):
        def confirm(e):
            for item in self.queue_items:
                item.change_mode(new_mode)
            dlg.open = False
            self.page.update()

        def cancel(e):
            dlg.open = False
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Изменение режима", color=TEXT_PRIMARY),
            bgcolor=SURFACE2,
            content=ft.Text(f"Перевести все элементы в очереди в формат «{new_mode}»?", color=TEXT_PRIMARY),
            actions=[
                ft.FilledButton("Да", on_click=confirm, style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT_PRIMARY)),
                ft.TextButton("Нет", on_click=cancel, style=ft.ButtonStyle(color=TEXT_MUTED)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    # ── Загрузка ссылок из файла ──────────────────────────────────────────

    def _delayed_load_urls(self):
        time.sleep(0.8)
        self.load_urls_from_file()

    def load_urls_from_file(self):
        txt_path = os.path.join(APP_DIR, "video.txt")
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                for url in urls:
                    threading.Thread(target=self._analyze_url_thread, args=(url,), daemon=True).start()
                    time.sleep(0.2)
            except Exception as e:
                print(f"Error reading video.txt: {e}")

    # ── Анализ URL ────────────────────────────────────────────────────────

    def _fetch_and_add(self, e):
        url = self._url_entry.value.strip() if self._url_entry.value else ""
        if len(url) < 10:
            return
        self._btn_add.disabled = True
        self._btn_add.content = "Анализ…"
        self.page.update()
        threading.Thread(target=self._analyze_url_thread, args=(url,), daemon=True).start()

    def _analyze_url_thread(self, url):
        try:
            cmd = [self.deps.ytdlp_path, '--dump-json', '--ignore-errors', '--no-check-certificate', '--flat-playlist', url]
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
                        self._status_label.value = f"Анализ… Найдено видео: {len(videos)}"
                        self._status_label.color = TEXT_PRIMARY
                        self.page.update()
                except: pass

            process.wait()
            if not videos:
                raise Exception("Видео не найдено или доступ закрыт.")

            if len(videos) > 1:
                self._show_playlist_dialog(videos)
            else:
                self.add_items_to_queue(videos)

        except Exception as e:
            snack(self.page, f"Не удалось проанализировать ссылку:\n{e}", ERROR_COLOR, ft.Icons.ERROR_OUTLINE)
            self._status_label.value = "Ошибка анализа"
            self._status_label.color = ERROR_COLOR
            self.page.update()
        finally:
            self._btn_add.disabled = False
            self._btn_add.content = "Добавить"
            self._url_entry.value = ""
            self.page.update()

    # ── Диалог плейлиста ──────────────────────────────────────────────────

    def _show_playlist_dialog(self, videos: list):
        checks = {}  # video_id -> ft.Checkbox
        count_text = ft.Text(f"Выбрано: {len(videos)} из {len(videos)}", size=13, color=TEXT_MUTED)

        def on_check(e):
            selected = sum(1 for cb in checks.values() if cb.value)
            count_text.value = f"Выбрано: {selected} из {len(videos)}"
            self.page.update()

        items = []
        for vid in videos:
            title = vid.get('title', 'Без названия')
            duration = vid.get('duration', 0)
            dur_str = f" ({int(duration)//60}:{int(duration)%60:02d})" if duration else ""
            cb = ft.Checkbox(
                label=f"{title}{dur_str}",
                value=True,
                on_change=on_check,
                active_color=ACCENT,
                label_style=ft.TextStyle(color=TEXT_PRIMARY, size=12),
            )
            checks[vid.get('id', '')] = cb
            items.append(cb)

        scroll_col = ft.Column(items, spacing=4, scroll=ft.ScrollMode.AUTO, height=320)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Плейлист обнаружен", weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
            bgcolor=SURFACE2,
            content=ft.Column(
                [
                    ft.Text("Выберите видео для загрузки:", size=13, color=TEXT_MUTED),
                    count_text,
                    ft.Container(
                        content=scroll_col,
                        bgcolor=SURFACE,
                        border_radius=8,
                        padding=8,
                        width=460,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
        )

        def confirm(e):
            selected_vids = [vid for vid in videos if checks.get(vid.get('id', ''), ft.Checkbox(value=False)).value]
            dlg.open = False
            self.page.update()
            self.add_items_to_queue(selected_vids)

        def cancel(e):
            dlg.open = False
            self.page.update()

        dlg.actions = [
            ft.FilledButton("Добавить выбранные", icon=ft.Icons.DOWNLOAD, on_click=confirm, style=ft.ButtonStyle(bgcolor=SUCCESS, color=TEXT_PRIMARY)),
            ft.TextButton("Отмена", on_click=cancel, style=ft.ButtonStyle(color=TEXT_MUTED)),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    # ── Управление очередью ───────────────────────────────────────────────

    def add_items_to_queue(self, videos_list: list):
        mode = list(self._mode_seg.selected)[0] if self._mode_seg.selected else "Видео"
        global_res_str = self._res_dropdown.value or "4K (2160p)"

        existing_ids = set(item.video_id for item in self.queue_items)
        added_count = 0

        for vid in videos_list:
            vid_id = vid.get('id')
            if vid_id in existing_ids:
                continue
            item = QueueItemWidget(self, vid, mode, global_res_str)
            self.queue_items.append(item)
            existing_ids.add(vid_id)
            self.queue_column.controls.append(item.container)
            added_count += 1

        if added_count == 0 and videos_list:
            self._status_label.value = "Выбранные видео уже есть в очереди."
            self._status_label.color = WARNING
        else:
            self.update_queue_status()
        self.page.update()

    def update_queue_status(self):
        total = len(self.queue_items)
        self._status_label.value = f"В очереди: {total} видео."
        self._status_label.color = TEXT_MUTED
        self.page.update()

    def _clear_queue(self, e):
        to_remove = [item for item in self.queue_items if item.status not in ["downloading", "processing"]]
        for item in to_remove:
            self.queue_column.controls.remove(item.container)
            self.queue_items.remove(item)
        self.update_queue_status()
        self.page.update()

    # ── Запуск/остановка очереди ──────────────────────────────────────────

    def _start_queue(self, e):
        if not self.queue_items:
            snack(self.page, "Добавьте видео в очередь перед запуском.", INFO, ft.Icons.INFO_OUTLINE)
            return

        if not self.settings.get("save_path"):
            def on_dir(result: ft.FilePickerResultEvent):
                if result.path:
                    self.settings["save_path"] = os.path.abspath(result.path)
                    SettingsManager.save(self.settings)
                    self._do_start_queue()

            picker = ft.FilePicker(on_result=on_dir)
            self.page.overlay.append(picker)
            self.page.update()
            picker.get_directory_path(dialog_title="Выберите папку для сохранения")
            return

        self._do_start_queue()

    def _do_start_queue(self):
        self.stop_requested = False
        self.is_downloading = True
        self.actual_downloads_occurred = False

        self._start_btn.content = "⏹  Остановить очередь"
        self._start_btn.icon = ft.Icons.STOP
        self._start_btn.on_click = self._stop_process
        self._start_btn.style.bgcolor = ERROR_COLOR
        self._toggle_ui("disabled")
        self.page.update()

        threading.Thread(target=self._process_queue_thread, daemon=True).start()

    def _stop_process(self, e):
        self.stop_requested = True
        self._status_label.value = "Остановка текущей загрузки…"
        self._status_label.color = WARNING
        self._start_btn.disabled = True
        self.page.update()

    def _process_queue_thread(self):
        for item in self.queue_items:
            if self.stop_requested:
                break
            while item.status == "fetching_formats" and not self.stop_requested:
                time.sleep(0.5)
            if item.status in ("waiting", "error"):
                self.download_item(item)
        self._restore_ui_state()

    # ── Форматы ───────────────────────────────────────────────────────────

    def request_format_fetch(self, item: QueueItemWidget):
        self.format_fetch_queue.put(item)

    def _format_fetch_worker(self):
        while True:
            item = self.format_fetch_queue.get()
            if item.mode != "Видео":
                self.format_fetch_queue.task_done()
                continue
            try:
                cmd = [self.deps.ytdlp_path, '--dump-json', '--no-playlist', '--no-check-certificate', item.url]
                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', **kwargs)

                if res.returncode == 0:
                    info = json.loads(res.stdout.splitlines()[0])
                    formats = info.get('formats', [])
                    max_dim = 0
                    for f in formats:
                        vcodec = f.get('vcodec')
                        if vcodec and vcodec != 'none':
                            w = f.get('width', 0) or 0
                            h = f.get('height', 0) or 0
                            if w > 0 and h > 0:
                                dim = min(w, h)
                                if dim > max_dim:
                                    max_dim = dim

                    if max_dim >= 2160: max_val = 2160
                    elif max_dim >= 1080: max_val = 1080
                    elif max_dim >= 720: max_val = 720
                    elif max_dim >= 480: max_val = 480
                    else: max_val = 360
                else:
                    max_val = 1080
            except:
                max_val = 1080

            all_res = [(2160, "4K (2160p)"), (1080, "1080p FullHD"), (720, "720p HD"), (480, "480p SD"), (360, "360p SD")]
            res_list = [name for h, name in all_res if h <= max_val] or ["360p SD"]

            cur_global = self._res_dropdown.value or "4K (2160p)"
            item.set_available_resolutions(res_list, cur_global)
            self.format_fetch_queue.task_done()

    # ── Настройки ─────────────────────────────────────────────────────────

    def refresh_settings(self):
        self.settings = SettingsManager.load()
        for item in self.queue_items:
            item._update_title_binding()
            item._update_yandex_visibility(is_refresh=True)
        self.page.update()

    def _open_settings(self, e):
        self._show_settings_dialog()

    def _show_settings_dialog(self):
        s = SettingsManager.load()

        # ── Слайдер громкости ──
        vol1_val = s.get("vol_original", 15)
        vol2_val = s.get("vol_translate", 100)

        lbl_vol1 = ft.Text(f"Громкость оригинала: {vol1_val}%", size=13, color=TEXT_PRIMARY)
        lbl_vol2 = ft.Text(f"Громкость перевода: {vol2_val}%", size=13, color=TEXT_PRIMARY)

        slider_vol1 = ft.Slider(
            min=0, max=100, value=vol1_val,
            active_color=ACCENT,
            thumb_color=ACCENT,
        )
        slider_vol2 = ft.Slider(
            min=0, max=100, value=vol2_val,
            active_color=ACCENT,
            thumb_color=ACCENT,
        )

        def upd_vol1(e):
            lbl_vol1.value = f"Громкость оригинала: {int(slider_vol1.value)}%"
            dlg.update()

        def upd_vol2(e):
            lbl_vol2.value = f"Громкость перевода: {int(slider_vol2.value)}%"
            dlg.update()

        slider_vol1.on_change = upd_vol1
        slider_vol2.on_change = upd_vol2

        # ── Переключатели ──
        chk_trans = ft.Switch(
            label="Авто-перевод Яндекса по умолчанию",
            value=s.get("add_translation", False),
            active_color=ACCENT,
            label_style=ft.TextStyle(color=TEXT_PRIMARY),
        )
        chk_manual = ft.Switch(
            label="Показывать кнопку ручного добавления аудио",
            value=s.get("show_manual_audio", False),
            active_color=ACCENT,
            label_style=ft.TextStyle(color=TEXT_PRIMARY),
        )
        chk_del = ft.Switch(
            label="Удалять оригинал после успешного перевода",
            value=s.get("delete_original", False),
            active_color=ACCENT,
            label_style=ft.TextStyle(color=TEXT_PRIMARY),
        )

        # ── Переводчик ──
        translators = ["Не переводить", "Google API", "Нейросеть (OpenAI/OpenRouter)"]
        dd_translator = ft.DropdownM2(
            options=[ft.dropdown.Option(t) for t in translators],
            value=s.get("title_translator", "Не переводить"),
            width=260,
            text_size=13,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
        )

        btn_ai = ft.FilledButton(
            content="Настройка API",
            icon=ft.Icons.PSYCHOLOGY,
            style=ft.ButtonStyle(bgcolor=PURPLE_DIM, color=TEXT_PRIMARY, shape=ft.RoundedRectangleBorder(radius=8)),
        )

        def on_translator_change(e):
            btn_ai.disabled = dd_translator.value != "Нейросеть (OpenAI/OpenRouter)"
            dlg.update()

        dd_translator.on_change = on_translator_change
        btn_ai.disabled = dd_translator.value != "Нейросеть (OpenAI/OpenRouter)"

        def open_ai_settings(e):
            dlg.open = False
            self.page.update()
            self._show_ai_settings_dialog(on_back=lambda: (setattr(dlg, 'open', True), self.page.update()))

        btn_ai.on_click = open_ai_settings

        # ── Путь сохранения ──
        path_field = ft.TextField(
            value=s.get("save_path", ""),
            expand=True,
            text_size=12,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
            height=40,
        )

        def browse_folder(e):
            def on_dir(result: ft.FilePickerResultEvent):
                if result.path:
                    path_field.value = os.path.abspath(result.path)
                    dlg.update()
            picker = ft.FilePicker(on_result=on_dir)
            self.page.overlay.append(picker)
            self.page.update()
            picker.get_directory_path(dialog_title="Выберите папку сохранения")

        btn_browse = ft.IconButton(icon=ft.Icons.FOLDER_OPEN, icon_color=TEXT_MUTED, on_click=browse_folder, tooltip="Обзор")

        # ── Кнопка сброса данных ──
        def wipe_data(e):
            def do_wipe(e2):
                confirm_dlg.open = False
                self.page.update()
                shutil.rmtree(APP_DATA_DIR, ignore_errors=True)
                os._exit(0)

            def cancel_wipe(e2):
                confirm_dlg.open = False
                self.page.update()

            confirm_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Сброс приложения", color=ERROR_COLOR, weight=ft.FontWeight.BOLD),
                bgcolor=SURFACE2,
                content=ft.Text(
                    "ВНИМАНИЕ!\nЭто удалит все настройки, логи и скачанные системные зависимости (Node.js, FFmpeg, yt-dlp). Приложение будет закрыто.\n\nПродолжить?",
                    color=TEXT_PRIMARY,
                ),
                actions=[
                    ft.FilledButton("Да, очистить", on_click=do_wipe, style=ft.ButtonStyle(bgcolor=ERROR_COLOR, color=TEXT_PRIMARY)),
                    ft.TextButton("Отмена", on_click=cancel_wipe, style=ft.ButtonStyle(color=TEXT_MUTED)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.page.overlay.append(confirm_dlg)
            confirm_dlg.open = True
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.SETTINGS, color=ACCENT), ft.Text("Настройки", color=TEXT_PRIMARY, weight=ft.FontWeight.BOLD)], spacing=8),
            bgcolor=SURFACE2,
            content=ft.Column(
                [
                    # Раздел: Озвучка
                    ft.Text("Озвучка видео (Yandex)", size=14, weight=ft.FontWeight.BOLD, color=ACCENT),
                    chk_trans,
                    chk_manual,
                    chk_del,

                    ft.Divider(color=SURFACE3, height=16),

                    # Раздел: Переводчик
                    ft.Text("Перевод названий (Текст)", size=14, weight=ft.FontWeight.BOLD, color=ACCENT),
                    ft.Row([dd_translator, btn_ai], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),

                    ft.Divider(color=SURFACE3, height=16),

                    # Раздел: Громкость
                    ft.Text("Параметры громкости", size=14, weight=ft.FontWeight.BOLD, color=ACCENT),
                    lbl_vol1,
                    slider_vol1,
                    lbl_vol2,
                    slider_vol2,

                    ft.Divider(color=SURFACE3, height=16),

                    # Раздел: Путь
                    ft.Text("Путь сохранения", size=14, weight=ft.FontWeight.BOLD, color=ACCENT),
                    ft.Row([path_field, btn_browse], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),

                    ft.Divider(color=SURFACE3, height=16),

                    # Опасная зона
                    ft.OutlinedButton(
                        content="Очистить данные и зависимости…",
                        icon=ft.Icons.DELETE_FOREVER,
                        on_click=wipe_data,
                        style=ft.ButtonStyle(
                            color=ERROR_COLOR,
                            side=ft.BorderSide(1, ERROR_COLOR),
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                    ),
                ],
                spacing=8,
                width=480,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def save_and_close(e):
            current_settings = SettingsManager.load()
            current_settings.update({
                "add_translation": chk_trans.value,
                "show_manual_audio": chk_manual.value,
                "delete_original": chk_del.value,
                "title_translator": dd_translator.value,
                "vol_original": int(slider_vol1.value),
                "vol_translate": int(slider_vol2.value),
                "save_path": path_field.value,
            })
            SettingsManager.save(current_settings)
            self.refresh_settings()
            dlg.open = False
            self.page.update()

        def close_settings(e):
            save_and_close(e)

        dlg.actions = [
            ft.FilledButton("Сохранить", icon=ft.Icons.SAVE, on_click=save_and_close, style=ft.ButtonStyle(bgcolor=SUCCESS, color=TEXT_PRIMARY, shape=ft.RoundedRectangleBorder(radius=8))),
            ft.TextButton("Закрыть", on_click=close_settings, style=ft.ButtonStyle(color=TEXT_MUTED)),
        ]

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _show_ai_settings_dialog(self, on_back=None):
        s = SettingsManager.load()
        blacklist = s.get("blacklisted_models", [])

        url_field = ft.TextField(
            label="Base URL",
            value=s.get("ai_base_url", "https://openrouter.ai/api/v1/chat/completions"),
            expand=True,
            text_size=12,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
        )

        free_models = ["openrouter/free"]
        saved_disc = s.get("discovered_models", [])
        for m in saved_disc:
            if m not in free_models and m not in blacklist:
                free_models.append(m)

        current_model = s.get("ai_model", "openrouter/free")
        if current_model in blacklist:
            current_model = "openrouter/free"

        model_dd = ft.DropdownM2(
            label="Модель (Model)",
            options=[ft.dropdown.Option(m) for m in free_models],
            value=current_model,
            width=360,
            text_size=12,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
        )

        # Возможность ввести кастомную модель
        model_custom = ft.TextField(
            label="Или введите модель вручную",
            hint_text="например: gpt-4o",
            text_size=12,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
            width=360,
        )

        token_field = ft.TextField(
            label="API Token",
            value=s.get("ai_token", ""),
            password=True,
            can_reveal_password=True,
            expand=True,
            text_size=12,
            bgcolor=SURFACE,
            border_color=SURFACE3,
            color=TEXT_PRIMARY,
        )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.PSYCHOLOGY, color=PURPLE_DIM), ft.Text("Настройка API нейросети", color=TEXT_PRIMARY, weight=ft.FontWeight.BOLD)], spacing=8),
            bgcolor=SURFACE2,
            content=ft.Column(
                [url_field, model_dd, model_custom, token_field],
                spacing=12,
                width=400,
                tight=True,
            ),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def save_ai(e):
            cs = SettingsManager.load()
            cs["ai_base_url"] = url_field.value.strip()
            chosen = model_custom.value.strip() if model_custom.value and model_custom.value.strip() else model_dd.value
            cs["ai_model"] = chosen
            cs["ai_token"] = token_field.value.strip()
            SettingsManager.save(cs)
            self.refresh_settings()
            dlg.open = False
            self.page.update()
            if on_back:
                on_back()

        def cancel_ai(e):
            dlg.open = False
            self.page.update()
            if on_back:
                on_back()

        dlg.actions = [
            ft.FilledButton("Сохранить", icon=ft.Icons.SAVE, on_click=save_ai, style=ft.ButtonStyle(bgcolor=SUCCESS, color=TEXT_PRIMARY, shape=ft.RoundedRectangleBorder(radius=8))),
            ft.TextButton("Отмена", on_click=cancel_ai, style=ft.ButtonStyle(color=TEXT_MUTED)),
        ]

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    # ── Управление доступностью UI ─────────────────────────────────────────

    def _toggle_ui(self, state: str):
        enabled = state == "normal"
        self._url_entry.disabled = not enabled
        self._settings_btn.disabled = not enabled
        self._btn_add.disabled = not enabled
        self._mode_seg.disabled = not enabled
        self._clear_btn.disabled = not enabled

        mode = list(self._mode_seg.selected)[0] if self._mode_seg.selected else "Видео"
        self._res_dropdown.disabled = not enabled or mode != "Видео"

        for item in self.queue_items:
            item.set_ui_enabled(enabled)
        self.page.update()

    # ── Загрузка видео (бизнес-логика без изменений) ──────────────────────

    def clean_temp_files(self):
        save_dir = self.settings.get("save_path", "")
        if save_dir and os.path.exists(save_dir):
            for file_name in os.listdir(save_dir):
                if file_name.startswith("temp_v") or file_name.startswith("temp_trans_"):
                    try: os.remove(os.path.join(save_dir, file_name))
                    except: pass

    def download_item(self, item: QueueItemWidget):
        process = None
        process_vot = None
        process_ff = None
        actual_translation_path = None
        vot_log_output = []

        self.clean_temp_files()

        try:
            safe_title = "".join([c for c in item.title_text if c.isalnum() or c in (' ', '.', '_', '-', '!')]).strip().rstrip('.')
            is_audio = (item.mode == "Только Аудио (MP3)")
            res_raw = item.dropdown_res.value or "1080p FullHD"
            res_num = 2160 if "4K" in res_raw else (int(res_raw.split("p")[0]) if "p" in res_raw else 1080)

            if is_audio:
                base_name = f"{safe_title}.mp3"
                final_name = base_name
            else:
                base_name = f"{safe_title} {res_num}p.mp4"
                if getattr(item, 'manual_audio_path', None) or getattr(item, 'use_yandex_translation', False):
                    final_name = f"{safe_title} {res_num}p (Яндекс).mp4"
                else:
                    final_name = base_name

            base_path = os.path.join(self.settings["save_path"], base_name)
            final_path = os.path.join(self.settings["save_path"], final_name)

            temp_template = os.path.join(self.settings["save_path"], "temp_v.%(ext)s")
            temp_video = os.path.join(self.settings["save_path"], "temp_v.mp4")
            temp_mp3 = os.path.join(self.settings["save_path"], "temp_v.mp3")

            if os.path.exists(final_path):
                item.status = "done"
                item.set_status("✅ Файл уже существует", SUCCESS)
                item.update_progress(100)
                return

            self.actual_downloads_occurred = True

            # 1. СКАЧИВАНИЕ ПЕРЕВОДА
            if item.mode == "Видео":
                if getattr(item, 'manual_audio_path', None) and os.path.exists(item.manual_audio_path):
                    actual_translation_path = item.manual_audio_path
                    item.set_status("Используется свой файл перевода…", PURPLE_DIM)

                elif getattr(item, 'use_yandex_translation', False) and self.deps.vot_path:
                    item.status = "processing"
                    item.set_progress_mode("indeterminate")

                    translate_temp = os.path.join(self.settings["save_path"], f"{item.video_id}.mp3")

                    cmd_vot = [
                        self.deps.vot_path,
                        f"--output={self.settings['save_path']}",
                        f"--output-file={item.video_id}.mp3",
                        "--voice-style=tts",
                        item.url
                    ]

                    kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                    env = os.environ.copy()
                    env["PATH"] = os.path.dirname(self.deps.node_exe) + os.pathsep + env.get("PATH", "")

                    max_attempts = 3
                    for attempt in range(1, max_attempts + 1):
                        if getattr(self, 'stop_requested', False):
                            raise Exception("Остановлено")

                        item.set_status(f"Перевод: запрос к серверу ({attempt}/{max_attempts})…", PURPLE_DIM)

                        process_vot = subprocess.Popen(cmd_vot, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='ignore', **kwargs)

                        for line in process_vot.stdout:
                            if getattr(self, 'stop_requested', False):
                                process_vot.terminate()
                                raise Exception("Остановлено")

                            clean_line = line.strip()
                            if clean_line:
                                vot_log_output.append(clean_line)

                            line_lower = line.lower()
                            if "performing" in line_lower or "waiting" in line_lower:
                                item.set_status("Яндекс генерирует аудио…", PURPLE_DIM)
                            elif "download" in line_lower or "загруз" in line_lower:
                                item.set_status("Скачивание аудио дорожки перевода…", PURPLE_DIM)

                        process_vot.wait()

                        if getattr(self, 'stop_requested', False):
                            raise Exception("Остановлено")

                        if os.path.exists(translate_temp):
                            actual_translation_path = translate_temp
                            break
                        else:
                            if attempt < max_attempts:
                                item.set_status("Яндекс просит подождать… Пауза 15 сек…", PURPLE_DIM)
                                for _ in range(15):
                                    if getattr(self, 'stop_requested', False):
                                        raise Exception("Остановлено")
                                    time.sleep(1)
                            else:
                                raise Exception("Сервер Яндекса не отдал файл перевода")

            # 2. СКАЧИВАНИЕ ОРИГИНАЛЬНОГО ВИДЕО/АУДИО (YT-DLP)
            item.status = "downloading"
            item.set_progress_mode("determinate")
            item.set_status("Скачивание оригинала (yt-dlp)…", INFO)

            if not (not is_audio and actual_translation_path and os.path.exists(base_path)):
                if is_audio:
                    cmd = [
                        self.deps.ytdlp_path, '--force-overwrites', '--socket-timeout', '15', '-f', 'bestaudio',
                        '--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0',
                        '-o', temp_template, '--newline', '--no-playlist',
                        '--retries', '10', '--fragment-retries', '10', '--no-check-certificate',
                        '--ffmpeg-location', self.deps.ffmpeg_path, item.url
                    ]
                else:
                    MAX_DIMS = {4320: 7680, 2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640, 240: 426}
                    max_dim = MAX_DIMS.get(res_num, 1920)
                    cmd = [
                        self.deps.ytdlp_path, '--force-overwrites', '--socket-timeout', '15',
                        '-f', f'bestvideo[width<={max_dim}][height<={max_dim}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                        '-o', temp_video, '--newline', '--no-playlist',
                        '--retries', '10', '--fragment-retries', '10', '--no-check-certificate',
                        '--ffmpeg-location', self.deps.ffmpeg_path, item.url
                    ]

                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)

                yt_stage = 1
                last_yt_percent = 0.0

                for line in process.stdout:
                    if self.stop_requested:
                        process.terminate()
                        raise Exception("Остановлено")

                    match = re.search(r'\[download\]\s+([\d\.]+)%', line)
                    if match:
                        percent = float(match.group(1))
                        if percent < 5.0 and last_yt_percent > 90.0:
                            yt_stage = 2
                        last_yt_percent = percent
                        if yt_stage == 1:
                            overall = percent * 0.5
                        else:
                            overall = 50.0 + (percent * 0.3)
                        item.update_progress(overall)

                process.wait()
                if process.returncode != 0 and not self.stop_requested:
                    raise Exception("Ошибка загрузки оригинального видео")

                if process.returncode == 0:
                    item.update_progress(80 if not is_audio else 100)

                actual_temp = temp_mp3 if is_audio else temp_video
                if os.path.exists(actual_temp):
                    if os.path.exists(base_path): os.remove(base_path)
                    os.rename(actual_temp, base_path)

            if getattr(self, 'stop_requested', False):
                raise Exception("Остановлено")

            # 3. ФИНАЛЬНАЯ СКЛЕЙКА (FFMPEG)
            if not is_audio and actual_translation_path:
                item.status = "processing"
                item.set_status("Склейка дорожек (FFmpeg)…", WARNING)

                duration = float(item.video_info.get('duration') or 0.0)
                if duration <= 0:
                    item.set_progress_mode("indeterminate")

                v1, v2 = self.settings["vol_original"] / 100, self.settings["vol_translate"] / 100
                cmd_ffmpeg = [
                    self.deps.ffmpeg_path, '-y', '-i', base_path, '-i', actual_translation_path,
                    '-filter_complex', f'[0:a]volume={v1}[a1];[1:a]volume={v2}[a2];[a1][a2]amix=inputs=2[aout]',
                    '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', final_path
                ]

                kwargs = {'startupinfo': self.startupinfo} if self.startupinfo else {}
                process_ff = subprocess.Popen(cmd_ffmpeg, stderr=subprocess.PIPE, text=True, errors='ignore', **kwargs)

                for line in process_ff.stderr:
                    if self.stop_requested:
                        process_ff.terminate()
                        raise Exception("Остановлено")

                    if duration > 0:
                        time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d+)', line)
                        if time_match:
                            h = float(time_match.group(1))
                            m = float(time_match.group(2))
                            sec = float(time_match.group(3))
                            current_sec = h * 3600 + m * 60 + sec
                            ff_percent = min((current_sec / duration) * 100.0, 100.0)
                            overall = 80.0 + (ff_percent * 0.2)
                            item.update_progress(overall)

                process_ff.wait()
                if duration <= 0:
                    item.set_progress_mode("determinate")

                if self.settings.get("delete_original", False):
                    try:
                        if os.path.exists(base_path) and os.path.exists(final_path):
                            os.remove(base_path)
                    except Exception as del_e:
                        log_error(item.video_id, "Ошибка удаления оригинального видео", del_e)

            item.status = "done"
            item.set_status("✅ Готово", SUCCESS)
            item.update_progress(100)

        except Exception as e:
            if process and process.poll() is None: process.terminate()
            if process_vot and process_vot.poll() is None: process_vot.terminate()
            if process_ff and process_ff.poll() is None: process_ff.terminate()

            item.status = "error"
            item.set_progress_mode("determinate")

            err_msg = str(e)

            if "Остановлено" in err_msg:
                status_msg = "⏹ Остановлено"
            elif "Ошибка перевода" in err_msg or "Сервер Яндекса" in err_msg:
                status_msg = "❌ Ошибка перевода (error.log)"
                log_error(item.video_id, err_msg, e, " | ".join(vot_log_output[-15:]))
            else:
                status_msg = "❌ Ошибка загрузки"
                log_error(item.video_id, err_msg, e)

            item.set_status(status_msg, ERROR_COLOR)

        finally:
            if actual_translation_path and os.path.exists(actual_translation_path):
                if getattr(item, 'manual_audio_path', None) != actual_translation_path:
                    try: os.remove(actual_translation_path)
                    except: pass
            self.clean_temp_files()

    # ── Восстановление UI после очереди ───────────────────────────────────

    def _restore_ui_state(self):
        self.is_downloading = False

        self._start_btn.content = "▶  Запустить очередь"
        self._start_btn.icon = ft.Icons.PLAY_ARROW
        self._start_btn.on_click = self._start_queue
        self._start_btn.style.bgcolor = ACCENT
        self._start_btn.disabled = False

        done = sum(1 for i in self.queue_items if i.status == "done")
        errors = sum(1 for i in self.queue_items if i.status == "error")
        total = len(self.queue_items)

        if self.stop_requested:
            self._status_label.value = f"Очередь остановлена. Завершено: {done}/{total}"
            self._status_label.color = WARNING
        elif errors > 0:
            self._status_label.value = f"Очередь завершена с ошибками. Успешно: {done}/{total}"
            self._status_label.color = ERROR_COLOR
        else:
            self._status_label.value = "🎉 Все загрузки успешно завершены!"
            self._status_label.color = SUCCESS
            if getattr(self, 'actual_downloads_occurred', False):
                self._open_save_folder()

        self._toggle_ui("normal")

    def _open_save_folder(self):
        save_path = self.settings.get("save_path", "")
        if os.path.exists(save_path):
            try:
                if self.os_name == "Windows":
                    os.startfile(save_path)
                elif self.os_name == "Darwin":
                    subprocess.Popen(["open", save_path])
                else:
                    subprocess.Popen(["xdg-open", save_path])
            except Exception as e:
                print(f"Failed to open folder: {e}")

    # ── Закрытие приложения ────────────────────────────────────────────────

    def _on_window_event(self, e: ft.WindowEvent):
        # WindowEventType.CLOSE is fired when user clicks X (requires prevent_close=True)
        try:
            is_close = (e.type == ft.WindowEventType.CLOSE)
        except AttributeError:
            is_close = (getattr(e, 'data', '') == 'close')
        if is_close:
            if self.is_downloading:
                self._confirm_close()
            else:
                self._perform_exit()

    def _confirm_close(self):
        def do_exit(e):
            confirm_dlg.open = False
            self.page.update()
            self.stop_requested = True
            time.sleep(1.5)
            self._perform_exit()

        def cancel_exit(e):
            confirm_dlg.open = False
            self.page.update()

        confirm_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Подтверждение", color=TEXT_PRIMARY, weight=ft.FontWeight.BOLD),
            bgcolor=SURFACE2,
            content=ft.Text("Очередь активна. Прервать и закрыть?", color=TEXT_PRIMARY),
            actions=[
                ft.FilledButton("Да, закрыть", on_click=do_exit, style=ft.ButtonStyle(bgcolor=ERROR_COLOR, color=TEXT_PRIMARY)),
                ft.TextButton("Нет", on_click=cancel_exit, style=ft.ButtonStyle(color=TEXT_MUTED)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(confirm_dlg)
        confirm_dlg.open = True
        self.page.update()

    def _perform_exit(self):
        self.settings["global_quality"] = self._res_dropdown.value or "4K (2160p)"
        SettingsManager.save(self.settings)
        self.clean_temp_files()
        try:
            self.page.window.close()
        except Exception:
            pass
        os._exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

def main(page: ft.Page):
    VideoApp(page)


if __name__ == "__main__":
    ft.run(main)
