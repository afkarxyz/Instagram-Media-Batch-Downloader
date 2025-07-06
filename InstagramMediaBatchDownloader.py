import sys
import os
import asyncio
import requests
import json
import tempfile
from pathlib import Path
from packaging import version
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QFileDialog, QListWidget, QTextEdit, QTabWidget, QAbstractItemView, QSpacerItem, QSizePolicy, QProgressBar, QCheckBox, QDialog,
    QDialogButtonBox, QComboBox, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer, QTime, QSettings, QSize
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtGui import QIcon, QTextCursor, QDesktopServices, QPixmap, QPainter, QPainterPath
from getMetadata import InstagramFetcher
from getMedia import InstagramMediaDownloader

@dataclass
class Account:
    username: str
    nick: str
    followers: int
    following: int
    posts: int
    media_type: str
    profile_image: str = None
    
    reels: int = 0
    tagged: int = 0
    stories: int = 0
    highlights: int = 0

class MetadataFetchWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, username, fetch_posts=True, fetch_reels=False, fetch_tagged=False, 
                 fetch_stories=False, fetch_highlights=False):
        super().__init__()
        self.username = username
        self.fetch_posts = fetch_posts
        self.fetch_reels = fetch_reels
        self.fetch_tagged = fetch_tagged
        self.fetch_stories = fetch_stories
        self.fetch_highlights = fetch_highlights
        self.session_id = None
        
    def run(self):
        try:
            normalized = extract_username_from_url(self.username)
            
            cookies = {}
            if self.session_id:
                cookies = {"sessionid": self.session_id}
            
            self.progress.emit(f"Fetching metadata for {normalized}...")
            
            def progress_callback(message):
                self.progress.emit(message)
            
            fetcher = InstagramFetcher(normalized, cookies=cookies, progress_callback=progress_callback)
            
            results = fetcher.fetch_selective_media(
                fetch_posts=self.fetch_posts,
                fetch_reels=self.fetch_reels,
                fetch_tagged=self.fetch_tagged,
                fetch_stories=self.fetch_stories,
                fetch_highlights=self.fetch_highlights
            )
            
            data = {
                'username': normalized,
                'user_info': results.get('user_info', {}),
                'posts': results.get('posts', []),
                'reels': results.get('reels', []),
                'tagged_posts': results.get('tagged_posts', []),
                'stories': results.get('stories', []),
                'highlights': results.get('highlights', [])
            }
            
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))

class DownloadWorker(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str, int)
    
    def __init__(self, accounts, outpath, session_id, max_concurrent=25):
        super().__init__()
        self.accounts = accounts
        self.outpath = outpath
        self.session_id = session_id
        self.max_concurrent = max_concurrent
        self.is_paused = False
        self.is_stopped = False

    def run(self):
        try:
            total_accounts = len(self.accounts)
            
            for i, account in enumerate(self.accounts):
                if self.is_stopped:
                    break
                    
                while self.is_paused:
                    if self.is_stopped:
                        return
                    self.msleep(100)
                
                self.progress.emit(f"Processing account: {account.username} ({i+1}/{total_accounts})", 
                                int((i) / total_accounts * 100))
                
                user_output_dir = os.path.join(self.outpath, account.username)
                
                asyncio.run(self.download_account_media(account, user_output_dir))
                
                self.progress.emit(f"Completed: {account.username}", 
                                int((i + 1) / total_accounts * 100))

            if not self.is_stopped:
                self.finished.emit(True, "Download completed successfully!")
                
        except Exception as e:
            self.finished.emit(False, f"Download failed: {str(e)}")

    async def download_account_media(self, account, output_dir):
        try:
            temp_dir = os.path.join(tempfile.gettempdir(), "instagrammediabatchdownloader")
            
            def progress_callback(message, percentage):
                self.progress.emit(message, percentage)
            
            async with InstagramMediaDownloader(
                output_dir=output_dir,
                max_concurrent=self.max_concurrent,
                progress_callback=progress_callback
            ) as downloader:
                await downloader.download_all_media(
                    data_dir=temp_dir,
                    username=account.username
                )
                
        except Exception as e:
            self.progress.emit(f"Error downloading {account.username}: {str(e)}", 0)

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self): 
        self.is_stopped = True
        self.is_paused = False

class UpdateDialog(QDialog):
    def __init__(self, current_version, new_version, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setFixedWidth(400)
        self.setModal(True)

        layout = QVBoxLayout()

        message = QLabel(f"A new version of Instagram Media Batch Downloader is available!\n\n"
                        f"Current version: v{current_version}\n"
                        f"New version: v{new_version}")
        message.setWordWrap(True)
        layout.addWidget(message)

        self.disable_check = QCheckBox("Turn off update checking")
        self.disable_check.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.disable_check)

        button_box = QDialogButtonBox()
        self.update_button = QPushButton("Update")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        
        button_box.addButton(self.update_button, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        
        layout.addWidget(button_box)

        self.setLayout(layout)

        self.update_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
class InstagramMediaDownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.current_version = "1.7"
        self.accounts = []
        self.temp_dir = os.path.join(tempfile.gettempdir(), "instagrammediabatchdownloader")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.reset_state()
        
        self.settings = QSettings('InstagramMediaDownloader', 'Settings')
        self.last_output_path = self.settings.value('output_path', str(Path.home() / "Pictures"))
        self.last_url = self.settings.value('instagram_url', 'lyq01777')
        self.last_session_id = self.settings.value('session_id', '')
        self.max_concurrent = self.settings.value('max_concurrent', 25, type=int)
        
        self.fetch_posts = self.settings.value('fetch_posts', True, type=bool)
        self.fetch_reels = self.settings.value('fetch_reels', False, type=bool)
        self.fetch_tagged = self.settings.value('fetch_tagged', False, type=bool)
        self.fetch_stories = self.settings.value('fetch_stories', False, type=bool)
        self.fetch_highlights = self.settings.value('fetch_highlights', False, type=bool)
        self.check_for_updates = self.settings.value('check_for_updates', True, type=bool)
        
        self.profile_image_cache = {}
        self.pending_downloads = {}
        self.network_manager = QNetworkAccessManager()
        
        self.elapsed_time = QTime(0, 0, 0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.initUI()
        self.load_all_cached_accounts()
        
        if self.check_for_updates:
            QTimer.singleShot(0, self.check_updates)

    def check_updates(self):
        try:
            response = requests.get("https://raw.githubusercontent.com/afkarxyz/Instagram-Media-Batch-Downloader/main/version.json")
            if response.status_code == 200:
                data = response.json()
                new_version = data.get("version")
                if new_version and version.parse(new_version) > version.parse(self.current_version):
                    dialog = UpdateDialog(self.current_version, new_version, self)
                    result = dialog.exec()
                    
                    if dialog.disable_check.isChecked():
                        self.settings.setValue('check_for_updates', False)
                        self.check_for_updates = False
                    
                    if result == QDialog.DialogCode.Accepted:
                        QDesktopServices.openUrl(QUrl("https://github.com/afkarxyz/Instagram-Media-Batch-Downloader/releases"))
                        
        except Exception as e:
            print(f"Error checking for updates: {e}")

    def reset_state(self):
        self.accounts.clear()

    def reset_ui(self):
        self.account_list.clear()
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self.stop_btn.hide()
        self.pause_resume_btn.hide()
        self.pause_resume_btn.setText('Pause')
        self.hide_account_buttons()
        
    def reset_process_ui(self):
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self.stop_btn.hide()
        self.pause_resume_btn.hide()
        self.pause_resume_btn.setText('Pause')

    def initUI(self):
        self.setWindowTitle('Instagram Media Batch Downloader')
        self.setFixedWidth(650)
        self.setFixedHeight(350)
        
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.main_layout = QVBoxLayout()
        
        self.setup_instagram_section()
        self.setup_tabs()
        
        self.setLayout(self.main_layout)
        
    def setup_instagram_section(self):
        instagram_layout = QHBoxLayout()
        instagram_label = QLabel('Username/URL:')
        instagram_label.setFixedWidth(100)
        
        self.instagram_url = QLineEdit()
        self.instagram_url.setPlaceholderText("e.g. lyq01777 or https://www.instagram.com/lyq01777")
        self.instagram_url.setClearButtonEnabled(True)
        self.instagram_url.setText(self.last_url)
        self.instagram_url.textChanged.connect(self.save_url)        
        self.fetch_btn = QPushButton('Fetch')
        self.fetch_btn.setFixedWidth(100)
        self.fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_btn.clicked.connect(self.fetch_account)
        
        instagram_layout.addWidget(instagram_label)
        instagram_layout.addWidget(self.instagram_url)
        instagram_layout.addWidget(self.fetch_btn)
        self.main_layout.addLayout(instagram_layout)

    def setup_tabs(self):
        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)

        self.setup_dashboard_tab()
        self.setup_process_tab()
        self.setup_settings_tab()
        self.setup_about_tab()

    def setup_dashboard_tab(self):
        dashboard_tab = QWidget()
        dashboard_layout = QVBoxLayout()

        self.account_list = QListWidget()
        self.account_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.account_list.itemSelectionChanged.connect(self.update_button_states)
        self.account_list.setIconSize(QSize(36, 36))
        self.account_list.setStyleSheet("""
            QListWidget {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 0px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 12px;
                margin: 2px 0px;
                border: none;
                border-radius: 4px;
                outline: none;
            }
            QListWidget::item:selected {
                background-color: palette(highlight);
                border: none;
                outline: none;
            }
            QListWidget::item:focus {
                border: none;
                outline: none;
            }
            QListWidget::item:hover {
                background-color: palette(midlight);
            }
        """)
        
        dashboard_layout.addWidget(self.account_list)
        
        self.setup_account_buttons()
        dashboard_layout.addLayout(self.btn_layout)
        dashboard_tab.setLayout(dashboard_layout)
        self.tab_widget.addTab(dashboard_tab, "Dashboard")

        self.hide_account_buttons()
            
    def setup_account_buttons(self):
        self.btn_layout = QHBoxLayout()
        self.download_selected_btn = QPushButton('Download Selected')
        self.download_all_btn = QPushButton('Download All')
        self.remove_btn = QPushButton('Remove Selected')
        self.clear_btn = QPushButton('Clear')
        
        for btn in [self.download_selected_btn, self.download_all_btn, self.remove_btn, self.clear_btn]:
            btn.setFixedWidth(150)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
        self.download_selected_btn.clicked.connect(self.download_selected)
        self.download_all_btn.clicked.connect(self.download_all)
        self.remove_btn.clicked.connect(self.remove_selected_accounts)
        self.clear_btn.clicked.connect(self.clear_accounts)
        
        self.btn_layout.addStretch()
        for btn in [self.download_selected_btn, self.download_all_btn, self.remove_btn, self.clear_btn]:
            self.btn_layout.addWidget(btn)
        self.btn_layout.addStretch()

    def setup_process_tab(self):
        self.process_tab = QWidget()
        process_layout = QVBoxLayout()
        process_layout.setSpacing(5)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        process_layout.addWidget(self.log_output)
        
        progress_time_layout = QVBoxLayout()
        progress_time_layout.setSpacing(2)
        
        self.progress_bar = QProgressBar()
        progress_time_layout.addWidget(self.progress_bar)
        
        self.time_label = QLabel("00:00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_time_layout.addWidget(self.time_label)
        
        process_layout.addLayout(progress_time_layout)
        
        control_layout = QHBoxLayout()
        self.stop_btn = QPushButton('Stop')
        self.pause_resume_btn = QPushButton('Pause')
        
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.stop_btn.clicked.connect(self.stop_download)
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.pause_resume_btn)
        process_layout.addLayout(control_layout)
        
        self.process_tab.setLayout(process_layout)
        
        self.tab_widget.addTab(self.process_tab, "Process")
        
        self.progress_bar.hide()
        self.time_label.hide()
        self.stop_btn.hide()
        self.pause_resume_btn.hide()

    def setup_settings_tab(self):
        settings_tab = QWidget()
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(0)
        settings_layout.setContentsMargins(9, 9, 9, 9)

        output_group = QWidget()
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(5)
        
        output_label = QLabel('Output Directory')
        output_label.setStyleSheet("font-weight: bold;")
        output_layout.addWidget(output_label)
        
        output_dir_layout = QHBoxLayout()
        self.output_dir = QLineEdit()
        self.output_dir.setText(self.last_output_path)
        self.output_dir.textChanged.connect(self.save_settings)
        self.output_browse = QPushButton('Browse')
        self.output_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.output_browse.clicked.connect(self.browse_output)
        
        output_dir_layout.addWidget(self.output_dir)
        output_dir_layout.addWidget(self.output_browse)
        output_layout.addLayout(output_dir_layout)
        
        settings_layout.addWidget(output_group)

        auth_group = QWidget()
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setSpacing(5)
        
        auth_label = QLabel('Cookies')
        auth_label.setStyleSheet("font-weight: bold;")
        auth_layout.addWidget(auth_label)
        
        session_id_layout = QHBoxLayout()
        session_id_label = QLabel('Session ID:')
        
        self.session_id_input = QLineEdit()
        self.session_id_input.setPlaceholderText("Enter your Instagram sessionid")
        self.session_id_input.setText(self.last_session_id)
        self.session_id_input.textChanged.connect(self.save_settings)
        self.session_id_input.setClearButtonEnabled(True)
        
        session_id_layout.addWidget(session_id_label)
        session_id_layout.addWidget(self.session_id_input)
        auth_layout.addLayout(session_id_layout)
        
        settings_layout.addWidget(auth_group)

        gallery_dl_group = QWidget()
        gallery_dl_layout = QVBoxLayout(gallery_dl_group)
        gallery_dl_layout.setSpacing(5)
        
        gallery_dl_label = QLabel('gallery-dl Settings')
        gallery_dl_label.setStyleSheet("font-weight: bold;")
        gallery_dl_layout.addWidget(gallery_dl_label)
        
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setSpacing(10)

        self.posts_checkbox = QCheckBox("Posts")
        self.posts_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.posts_checkbox.setChecked(self.fetch_posts)
        self.posts_checkbox.stateChanged.connect(self.save_settings)
        checkboxes_layout.addWidget(self.posts_checkbox)
        
        self.reels_checkbox = QCheckBox("Reels")
        self.reels_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reels_checkbox.setChecked(self.fetch_reels)
        self.reels_checkbox.stateChanged.connect(self.save_settings)
        checkboxes_layout.addWidget(self.reels_checkbox)
        
        self.tagged_checkbox = QCheckBox("Tagged")
        self.tagged_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tagged_checkbox.setChecked(self.fetch_tagged)
        self.tagged_checkbox.stateChanged.connect(self.save_settings)
        checkboxes_layout.addWidget(self.tagged_checkbox)
        
        self.stories_checkbox = QCheckBox("Stories")
        self.stories_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stories_checkbox.setChecked(self.fetch_stories)
        self.stories_checkbox.stateChanged.connect(self.save_settings)
        checkboxes_layout.addWidget(self.stories_checkbox)
        
        self.highlights_checkbox = QCheckBox("Highlights")
        self.highlights_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.highlights_checkbox.setChecked(self.fetch_highlights)
        self.highlights_checkbox.stateChanged.connect(self.save_settings)
        checkboxes_layout.addWidget(self.highlights_checkbox)
        
        checkboxes_layout.addStretch()
        gallery_dl_layout.addLayout(checkboxes_layout)
        
        settings_layout.addWidget(gallery_dl_group)

        download_group = QWidget()
        download_layout = QVBoxLayout(download_group)
        download_layout.setSpacing(5)
        
        download_label = QLabel('Download Settings')
        download_label.setStyleSheet("font-weight: bold;")
        download_layout.addWidget(download_label)
        
        batch_layout = QHBoxLayout()
        batch_label = QLabel('Batch Size:')
        
        self.max_concurrent_combo = QComboBox()
        self.max_concurrent_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_concurrent_combo.setFixedWidth(80)
        for size in range(5, 101, 5):
            self.max_concurrent_combo.addItem(str(size))
        self.max_concurrent_combo.setCurrentText(str(self.max_concurrent))
        self.max_concurrent_combo.currentTextChanged.connect(self.save_settings)
        
        batch_layout.addWidget(batch_label)
        batch_layout.addWidget(self.max_concurrent_combo)
        batch_layout.addStretch()
        download_layout.addLayout(batch_layout)
        
        settings_layout.addWidget(download_group)
        settings_layout.addStretch()
        
        settings_tab.setLayout(settings_layout)
        self.tab_widget.addTab(settings_tab, "Settings")
        
    def setup_about_tab(self):
        about_tab = QWidget()
        about_layout = QVBoxLayout()
        about_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.setSpacing(3)

        sections = [
            ("Check for Updates", "https://github.com/afkarxyz/Instagram-Media-Batch-Downloader/releases"),
            ("Report an Issue", "https://github.com/afkarxyz/Instagram-Media-Batch-Downloader/issues"),
            ("gallery-dl Repository", "https://github.com/mikf/gallery-dl")
        ]

        for title, url in sections:
            section_widget = QWidget()
            section_layout = QVBoxLayout(section_widget)
            section_layout.setSpacing(10)
            section_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(title)
            label.setStyleSheet("color: palette(text); font-weight: bold;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            section_layout.addWidget(label)

            button = QPushButton("Click Here!")
            button.setFixedWidth(150)
            button.setStyleSheet("""
                QPushButton {
                    background-color: palette(button);
                    color: palette(button-text);
                    border: 1px solid palette(mid);
                    padding: 6px;
                    border-radius: 15px;
                }
                QPushButton:hover {
                    background-color: palette(light);
                }
                QPushButton:pressed {
                    background-color: palette(midlight);
                }            
                """)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _, url=url: QDesktopServices.openUrl(QUrl(url if url.startswith(('http://', 'https://')) else f'https://{url}')))
            section_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)            
            about_layout.addWidget(section_widget)
            if sections.index((title, url)) < len(sections) - 1:
                spacer = QSpacerItem(20, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                about_layout.addItem(spacer)

        footer_label = QLabel("v1.7 | gallery-dl v1.30.0 | July 2025")
        footer_label.setStyleSheet("font-size: 12px; margin-top: 10px;")
        about_layout.addWidget(footer_label, alignment=Qt.AlignmentFlag.AlignCenter)
        about_tab.setLayout(about_layout)
        self.tab_widget.addTab(about_tab, "About")

    def save_url(self):
        self.settings.setValue('instagram_url', self.instagram_url.text().strip())
        self.settings.sync()
        
    def save_settings(self):
        self.settings.setValue('output_path', self.output_dir.text().strip())
        self.settings.setValue('session_id', self.session_id_input.text().strip())
        self.settings.setValue('max_concurrent', int(self.max_concurrent_combo.currentText()))
        
        self.settings.setValue('fetch_posts', self.posts_checkbox.isChecked())
        self.settings.setValue('fetch_reels', self.reels_checkbox.isChecked())
        self.settings.setValue('fetch_tagged', self.tagged_checkbox.isChecked())
        self.settings.setValue('fetch_stories', self.stories_checkbox.isChecked())
        self.settings.setValue('fetch_highlights', self.highlights_checkbox.isChecked())
        
        self.fetch_posts = self.posts_checkbox.isChecked()
        self.fetch_reels = self.reels_checkbox.isChecked()
        self.fetch_tagged = self.tagged_checkbox.isChecked()
        self.fetch_stories = self.stories_checkbox.isChecked()
        self.fetch_highlights = self.highlights_checkbox.isChecked()
        self.settings.sync()

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Output Directory')
        if folder:
            self.output_dir.setText(folder)
            self.save_settings()

    def get_cache_file_path(self, username):
        return os.path.join(self.temp_dir, f"{username}_user_info.json")

    def load_cached_data(self, username):
        cache_path = self.get_cache_file_path(username)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return None

    def save_cached_data(self, username, data):
        cache_path = self.get_cache_file_path(username)
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass

    def load_all_cached_accounts(self):
        try:
            if not os.path.exists(self.temp_dir):
                return
                
            cache_files = [f for f in os.listdir(self.temp_dir) if f.endswith('_user_info.json')]
            
            if not cache_files:
                return
            
            for cache_file in cache_files:
                try:
                    username = cache_file.replace('_user_info.json', '')
                    
                    cached_data = self.load_cached_data(username)
                    if cached_data:
                        followers = cached_data.get('followers_count', 0)
                        following = cached_data.get('following_count', 0)
                        posts_total = cached_data.get('posts_count', 0)
                        full_name = cached_data.get('full_name', '')
                        profile_pic_url = cached_data.get('profile_pic_url', '')
                        
                        posts_count = 0
                        reels_count = 0
                        tagged_count = 0
                        stories_count = 0
                        highlights_count = 0
                        
                        posts_file = os.path.join(self.temp_dir, f"{username}_posts.json")
                        if os.path.exists(posts_file):
                            try:
                                with open(posts_file, 'r', encoding='utf-8') as f:
                                    posts_data = json.load(f)
                                    posts_count = len(posts_data) if isinstance(posts_data, list) else 0
                            except:
                                pass
                        
                        reels_file = os.path.join(self.temp_dir, f"{username}_reels.json")
                        if os.path.exists(reels_file):
                            try:
                                with open(reels_file, 'r', encoding='utf-8') as f:
                                    reels_data = json.load(f)
                                    reels_count = len(reels_data) if isinstance(reels_data, list) else 0
                            except:
                                pass
                        
                        tagged_file = os.path.join(self.temp_dir, f"{username}_tagged.json")
                        if os.path.exists(tagged_file):
                            try:
                                with open(tagged_file, 'r', encoding='utf-8') as f:
                                    tagged_data = json.load(f)
                                    tagged_count = len(tagged_data.get('tagged_posts', [])) if isinstance(tagged_data, dict) else 0
                            except:
                                pass
                        
                        stories_file = os.path.join(self.temp_dir, f"{username}_stories.json")
                        if os.path.exists(stories_file):
                            try:
                                with open(stories_file, 'r', encoding='utf-8') as f:
                                    stories_data = json.load(f)
                                    stories_count = len(stories_data) if isinstance(stories_data, list) else 0
                            except:
                                pass
                        
                        highlights_file = os.path.join(self.temp_dir, f"{username}_highlights.json")
                        if os.path.exists(highlights_file):
                            try:
                                with open(highlights_file, 'r', encoding='utf-8') as f:
                                    highlights_data = json.load(f)
                                    highlights_count = len(highlights_data) if isinstance(highlights_data, list) else 0
                            except:
                                pass
                        
                        media_types = []
                        if posts_count > 0:
                            media_types.append(f"Posts: {posts_count}")
                        if reels_count > 0:
                            media_types.append(f"Reels: {reels_count}")
                        if tagged_count > 0:
                            media_types.append(f"Tagged: {tagged_count}")
                        if stories_count > 0:
                            media_types.append(f"Stories: {stories_count}")
                        if highlights_count > 0:
                            media_types.append(f"Highlights: {highlights_count}")
                        
                        media_type_str = " - ".join(media_types) if media_types else "No Media"
                        
                        account = Account(
                            username=username,
                            nick=full_name,
                            followers=followers,
                            following=following,
                            posts=posts_total,
                            media_type=media_type_str,
                            profile_image=profile_pic_url,
                            reels=reels_count,
                            tagged=tagged_count,
                            stories=stories_count,
                            highlights=highlights_count
                        )
                        
                        self.accounts.append(account)
                except Exception as e:
                    continue
                    
            if self.accounts:
                self.update_account_list()
                
        except Exception as e:
            pass    
    def fetch_account(self):
        url = self.instagram_url.text().strip()
        
        if not url:
            self.log_output.append('Warning: Please enter an Instagram username/URL.')
            return

        username = extract_username_from_url(url)

        for account in self.accounts:
            if account.username == username:
                self.log_output.append(f'Account {username} already in list.')
                return

        cached_data = self.load_cached_data(username)
        if cached_data:
            try:
                followers = cached_data.get('followers_count', 0)
                following = cached_data.get('following_count', 0)
                posts_total = cached_data.get('posts_count', 0)
                full_name = cached_data.get('full_name', '')
                profile_pic_url = cached_data.get('profile_pic_url', '')
                
                posts_count = 0
                reels_count = 0
                
                posts_file = os.path.join(self.temp_dir, f"{username}_posts.json")
                if os.path.exists(posts_file):
                    try:
                        with open(posts_file, 'r', encoding='utf-8') as f:
                            posts_data = json.load(f)
                            posts_count = len(posts_data) if isinstance(posts_data, list) else 0
                    except:
                        pass
                
                reels_file = os.path.join(self.temp_dir, f"{username}_reels.json")
                if os.path.exists(reels_file):
                    try:
                        with open(reels_file, 'r', encoding='utf-8') as f:
                            reels_data = json.load(f)
                            reels_count = len(reels_data) if isinstance(reels_data, list) else 0
                    except:
                        pass
                
                media_types = []
                if posts_count > 0:
                    media_types.append(f"Posts: {posts_count}")
                if reels_count > 0:
                    media_types.append(f"Reels: {reels_count}")
                
                media_type_str = " - ".join(media_types) if media_types else "All"
                
                account = Account(
                    username=username,
                    nick=full_name,
                    followers=followers,
                    following=following,
                    posts=posts_total,
                    media_type=media_type_str,
                    profile_image=profile_pic_url,
                    reels=reels_count
                )
                self.accounts.append(account)
                self.update_account_list()
                self.log_output.append(f'Loaded from cache: {username} - Followers: {followers:,} - Posts: {posts_total:,}')
                self.instagram_url.clear()
                return
            except:
                pass        
        try:
            self.reset_process_ui()
            
            self.tab_widget.setCurrentWidget(self.process_tab)
            
            self.metadata_worker = MetadataFetchWorker(
                username,
                fetch_posts=self.fetch_posts,
                fetch_reels=self.fetch_reels,
                fetch_tagged=self.fetch_tagged,
                fetch_stories=self.fetch_stories,
                fetch_highlights=self.fetch_highlights
            )
            self.metadata_worker.session_id = self.session_id_input.text().strip()
            self.metadata_worker.progress.connect(self.handle_metadata_progress)
            self.metadata_worker.finished.connect(lambda data: self.on_metadata_fetched(data, username))
            self.metadata_worker.error.connect(self.on_metadata_error)
            self.metadata_worker.start()
            
        except Exception as e:
            self.log_output.append(f'Error: Failed to start metadata fetch: {str(e)}')
            self.update_account_list()
            
    def handle_metadata_progress(self, message):
        if message.startswith("PROGRESS_UPDATE:"):
            progress_msg = message[16:]
            
            cursor = self.log_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            current_text = cursor.selectedText()
            
            fetch_indicators = ["Fetching posts:", "Fetching reels:", "Fetching tagged:", "Fetching stories:", "Fetching highlights:"]
            should_replace = any(indicator in current_text for indicator in fetch_indicators)
            
            if should_replace:
                cursor.removeSelectedText()
                cursor.deletePreviousChar()
                self.log_output.append(progress_msg)
            else:
                self.log_output.append(progress_msg)
        elif message == "PROGRESS_CLEAR":
            cursor = self.log_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            current_text = cursor.selectedText()
            
            fetch_indicators = ["Fetching posts:", "Fetching reels:", "Fetching tagged:", "Fetching stories:", "Fetching highlights:"]
            should_clear = any(indicator in current_text for indicator in fetch_indicators)
            
            if should_clear:
                cursor.removeSelectedText()
                cursor.deletePreviousChar()
        else:
            self.log_output.append(message)
        
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)

    def on_metadata_fetched(self, data, username):
        try:
            if 'error' in data:
                self.log_output.append(f'Error: {data["error"]}')
                self.update_account_list()
                return
            user_info_data = self.load_cached_data(username)
            posts = data.get('posts', [])
            reels = data.get('reels', [])
            tagged_posts = data.get('tagged_posts', [])
            stories = data.get('stories', [])
            highlights = data.get('highlights', [])
            
            if not user_info_data:
                self.log_output.append('Error: User info not found')
                self.update_account_list()
                return
            
            followers = user_info_data.get('followers_count', 0)
            following = user_info_data.get('following_count', 0)
            posts_total = user_info_data.get('posts_count', 0)
            full_name = user_info_data.get('full_name', '')
            profile_pic_url = user_info_data.get('profile_pic_url', '')
            
            media_types = []
            if len(posts) > 0:
                media_types.append(f"Posts: {len(posts)}")
            if len(reels) > 0:
                media_types.append(f"Reels: {len(reels)}")
            if len(tagged_posts) > 0:
                media_types.append(f"Tagged: {len(tagged_posts)}")
            if len(stories) > 0:
                media_types.append(f"Stories: {len(stories)}")
            if len(highlights) > 0:
                media_types.append(f"Highlights: {len(highlights)}")
            
            media_type_str = " - ".join(media_types) if media_types else "No Media"
            
            account = Account(
                username=username,
                nick=full_name,
                followers=followers,
                following=following,
                posts=posts_total,
                media_type=media_type_str,
                profile_image=profile_pic_url,
                reels=len(reels),
                tagged=len(tagged_posts),
                stories=len(stories),
                highlights=len(highlights)
            )
            
            self.accounts.append(account)
            
            fetched_items = []
            if len(posts) > 0:
                fetched_items.append(f"{len(posts)} posts")
            if len(reels) > 0:
                fetched_items.append(f"{len(reels)} reels")
            if len(tagged_posts) > 0:
                fetched_items.append(f"{len(tagged_posts)} tagged")
            if len(stories) > 0:
                fetched_items.append(f"{len(stories)} stories")
            if len(highlights) > 0:
                fetched_items.append(f"{len(highlights)} highlights")
            
            fetched_str = ", ".join(fetched_items) if fetched_items else "no media"
            self.log_output.append(f'Successfully fetched: {username} - Followers: {followers:,} - {fetched_str}')
            
            self.update_account_list()
            self.instagram_url.clear()
            self.tab_widget.setCurrentIndex(0)
        except Exception as e:
            self.log_output.append(f'Error: {str(e)}')
            self.update_account_list()
            
    def on_metadata_error(self, error_message):
        self.log_output.append(f'Error: {error_message}')
        self.update_account_list()

    def update_account_list(self):
        self.account_list.clear()
        for i, account in enumerate(self.accounts, 1):
            line1 = f"{i}. {account.username} ({account.nick})"
            line2 = f"Followers: {account.followers:,} • Following: {account.following:,} • Posts: {account.posts:,} • {account.media_type}"
            display_text = f"{line1}\n{line2}"
            item = QListWidgetItem()
            item.setText(display_text)
            item.setSizeHint(QSize(0, 52))
            
            if account.profile_image:
                if account.profile_image in self.profile_image_cache:
                    item.setIcon(QIcon(self.profile_image_cache[account.profile_image]))
                else:
                    self.download_profile_image(account.profile_image)
                    placeholder = self.create_placeholder_icon(52)
                    if placeholder:
                        item.setIcon(QIcon(placeholder))
            else:
                placeholder = self.create_placeholder_icon(52)
                if placeholder:
                    item.setIcon(QIcon(placeholder))
            
            self.account_list.addItem(item)
        
        self.update_button_states()

    def create_placeholder_icon(self, size=36):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setBrush(Qt.GlobalColor.gray)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 8, 8)
        
        painter.setPen(Qt.GlobalColor.white)
        font_size = int(size * 0.4)
        painter.setFont(painter.font())
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "👤")
        
        painter.end()
        return pixmap

    def create_square_pixmap(self, original_pixmap, size=36):
        if original_pixmap.isNull():
            return self.create_placeholder_icon(size)
        
        square_pixmap = QPixmap(size, size)
        square_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(square_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, 8, 8)
        painter.setClipPath(path)
        
        scaled_pixmap = original_pixmap.scaled(
            size, size, 
            Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
            Qt.TransformationMode.SmoothTransformation
        )
        
        x = (size - scaled_pixmap.width()) // 2
        y = (size - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)
        
        painter.end()
        return square_pixmap

    def download_profile_image(self, url):
        if not url or url in self.profile_image_cache or url in self.pending_downloads:
            return
        
        try:
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, 
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            reply = self.network_manager.get(request)
            self.pending_downloads[url] = reply
            reply.finished.connect(lambda: self.on_profile_image_downloaded(reply, url))
        except Exception as e:
            print(f"Error downloading profile image: {e}")

    def on_profile_image_downloaded(self, reply, image_url):
        try:
            if reply.error() == reply.NetworkError.NoError:
                data = reply.readAll()
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    square_pixmap = self.create_square_pixmap(pixmap, 52)
                    self.profile_image_cache[image_url] = square_pixmap
                    
                    self.update_account_list()
            
            if image_url in self.pending_downloads:
                del self.pending_downloads[image_url]
                
        except Exception as e:
            print(f"Error processing profile image: {e}")
        finally:
            reply.deleteLater()

    def update_button_states(self):
        has_accounts = len(self.accounts) > 0
        
        self.download_selected_btn.setEnabled(has_accounts)
        self.download_all_btn.setEnabled(has_accounts)
        self.remove_btn.setEnabled(has_accounts)
        self.clear_btn.setEnabled(has_accounts)
        
        if has_accounts:
            self.download_selected_btn.show()
            self.download_all_btn.show()
            self.remove_btn.show()
            self.clear_btn.show()
        else:            
            self.hide_account_buttons()
    
    def hide_account_buttons(self):
        buttons = [
            self.download_selected_btn,
            self.download_all_btn,
            self.remove_btn,
            self.clear_btn
        ]
        for btn in buttons:
            btn.hide()

    def download_selected(self):
        selected_items = self.account_list.selectedItems()
        if not selected_items:
            self.log_output.append('Warning: Please select accounts to download.')
            return
        self.download_accounts([self.account_list.row(item) for item in selected_items])

    def download_all(self):
        self.download_accounts(range(len(self.accounts)))

    def download_accounts(self, indices):
        self.log_output.clear()
        outpath = self.output_dir.text()
        if not os.path.exists(outpath):
            self.log_output.append('Warning: Invalid output directory.')
            return

        accounts_to_download = [self.accounts[i] for i in indices]

        try:
            self.start_download_worker(accounts_to_download, outpath)
        except Exception as e:
            self.log_output.append(f"Error: An error occurred while starting the download: {str(e)}")

    def start_download_worker(self, accounts_to_download, outpath):
        self.worker = DownloadWorker(
            accounts_to_download, 
            outpath, 
            self.session_id_input.text().strip(),
            self.max_concurrent
        )
        self.worker.finished.connect(self.on_download_finished)
        self.worker.progress.connect(self.update_progress)
        self.worker.start()
        self.start_timer()
        self.update_ui_for_download_start(len(accounts_to_download))

    def update_ui_for_download_start(self, account_count):
        self.download_selected_btn.setEnabled(False)
        self.download_all_btn.setEnabled(False)
        self.stop_btn.show()
        self.pause_resume_btn.show()
        
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        self.tab_widget.setCurrentWidget(self.process_tab)
    
    def update_progress(self, message, percentage):
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        current_text = cursor.selectedText()
        
        category_indicators = ["posts:", "reels:", "tagged:", "stories:", "highlights:"]
        is_category_update = any(indicator in message for indicator in category_indicators)
        is_same_category = any(indicator in current_text and indicator in message for indicator in category_indicators)
        
        stats_indicators = ["Total time:", "Total files:", "Downloaded:", "Skipped:", "Failed:"]
        is_stats_message = any(indicator in message for indicator in stats_indicators)
        
        other_progress_indicators = ["Processing", "Completed"]
        is_other_progress = any(indicator in current_text and indicator in message for indicator in other_progress_indicators)
        
        should_replace = is_same_category or is_other_progress
        
        if should_replace and current_text.strip():
            cursor.removeSelectedText()
            cursor.deletePreviousChar()
        
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        
        if percentage >= 0:
            self.progress_bar.setValue(percentage)
            self.progress_bar.show()

    def stop_download(self):
        if hasattr(self, 'worker'):
            self.worker.stop()
        self.stop_timer()
        self.on_download_finished(True, "Download stopped by user.")
        
    def on_download_finished(self, success, message):
        self.progress_bar.hide()
        self.stop_btn.hide()
        self.pause_resume_btn.hide()
        self.pause_resume_btn.setText('Pause')
        self.stop_timer()
        
        self.download_selected_btn.setEnabled(True)
        self.download_all_btn.setEnabled(True)
        if success:
            self.log_output.append(f"\nStatus: {message}")
        else:
            self.log_output.append(f"Error: {message}")

        self.tab_widget.setCurrentWidget(self.process_tab)
    
    def toggle_pause_resume(self):
        if hasattr(self, 'worker'):
            if self.worker.is_paused:
                self.worker.resume()
                self.pause_resume_btn.setText('Pause')
                self.timer.start(1000)
            else:
                self.worker.pause()
                self.pause_resume_btn.setText('Resume')

    def remove_all_related_cache_files(self, username):
        cache_file_types = ['_user_info.json', '_posts.json', '_reels.json', '_tagged.json', '_stories.json', '_highlights.json']
        
        for file_type in cache_file_types:
            cache_file = os.path.join(self.temp_dir, f"{username}{file_type}")
            try:
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    self.log_output.append(f'Removed temp file: {os.path.basename(cache_file)}')
            except Exception as e:
                self.log_output.append(f'Warning: Could not remove temp file {os.path.basename(cache_file)}: {str(e)}')

    def remove_selected_accounts(self):
        selected_indices = sorted([self.account_list.row(item) for item in self.account_list.selectedItems()], reverse=True)
        
        if not selected_indices:
            return
        for index in selected_indices:
            account = self.accounts[index]
            username = account.username
            if username:
                self.remove_all_related_cache_files(username)
            
            self.accounts.pop(index)
        self.update_account_list()
        self.update_button_states()

    def clear_accounts(self):
        for account in self.accounts:
            username = account.username
            if username:
                self.remove_all_related_cache_files(username)
        
        self.reset_state()
        self.reset_ui()
        self.tab_widget.setCurrentIndex(0)

    def update_timer(self):
        self.elapsed_time = self.elapsed_time.addSecs(1)
        self.time_label.setText(self.elapsed_time.toString("hh:mm:ss"))
    
    def start_timer(self):
        self.elapsed_time = QTime(0, 0, 0)
        self.time_label.setText("00:00:00")
        self.time_label.show()
        self.timer.start(1000)
    def stop_timer(self):
        self.timer.stop()
        self.time_label.hide()

def extract_username_from_url(url_or_username):
    if not url_or_username:
        return ""
    
    url_or_username = url_or_username.strip()
    
    if "instagram.com" not in url_or_username.lower():
        return url_or_username
    
    try:
        clean_url = url_or_username.split('?')[0].split('#')[0]
        
        if 'instagram.com/' in clean_url:
            parts = clean_url.split('instagram.com/')
            if len(parts) > 1:
                after_domain = parts[1]
                if after_domain:
                    username = after_domain.split('/')[0]
                    if username:
                        return username
                        
    except Exception as e:
        pass
        
    return url_or_username

def main():
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    app = QApplication(sys.argv)
    window = InstagramMediaDownloaderGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
