import sys
import os
import requests
import asyncio
import aiohttp
import subprocess
from pathlib import Path
from packaging import version
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QFileDialog, QRadioButton, QCheckBox, QDialog, QDialogButtonBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings, QTimer, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QCursor, QPainter, QPainterPath, QDesktopServices
from getMetadata import get_profile_data
from gallery_dl import job, config

class ImageDownloader(QThread):
    finished = pyqtSignal(bytes)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    async def download_image(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as response:
                if response.status == 200:
                    return await response.read()
        return None
        
    def run(self):
        image_data = asyncio.run(self.download_image())
        if image_data:
            self.finished.emit(image_data)

class MetadataFetcher(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, username):
        super().__init__()
        self.username = username
        
    def run(self):
        try:
            username = self.username.strip()
            if "instagram.com/" in username:
                username = username.split("/")[-2]
            
            result = get_profile_data(username)
            
            if "error" in result:
                raise ValueError(result["error"])
                
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))

class MediaDownloader(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, username, output_dir, config_filename, total_posts, cookie):
        super().__init__()
        self.username = username
        self.output_dir = output_dir
        self.config_filename = config_filename
        self.total_posts = total_posts
        self.cookie = cookie
        self.download_count = 0
        self.output_path = os.path.join(output_dir, username)
        self.error_message = None

    class OutputRedirector:
        def __init__(self, callback, output_path, error_callback):
            self.callback = callback
            self.output_path = output_path
            self.error_callback = error_callback
            self.buffer = ""

        def write(self, text):
            if text.strip():
                if "HttpError" in text or "error" in text.lower() or "failed" in text.lower():
                    self.error_callback(text.strip())
                    return

                if os.path.exists(self.output_path):
                    try:
                        current_total = len([f for f in os.listdir(self.output_path) 
                                        if os.path.isfile(os.path.join(self.output_path, f))])
                        self.callback(f"Downloaded {current_total} files... {text.strip()}")
                    except:
                        self.callback(text.strip())
                else:
                    self.callback(text.strip())

        def flush(self):
            pass

    def count_downloaded_files(self):
        if os.path.exists(self.output_path):
            files = [f for f in os.listdir(self.output_path) if os.path.isfile(os.path.join(self.output_path, f))]
            return len(files)
        return 0

    def capture_error(self, error_text):
        self.error_message = error_text
        self.error.emit(error_text)

    def run(self):
        try:
            config.set((), "directory", ["{username}"])
            config.set((), "base-directory", self.output_dir)
            config.set((), "filename", self.config_filename)
            
            if self.cookie:
                config.set(("extractor", "instagram"), "cookies", {
                    "sessionid": self.cookie
                })
            
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            
            redirector = self.OutputRedirector(
                lambda text: self.status_update.emit(text.strip()),
                self.output_path,
                self.capture_error
            )
            
            sys.stdout = redirector
            sys.stderr = redirector
            
            try:
                url = f"https://www.instagram.com/{self.username}/posts"
                result = job.DownloadJob(url).run()
                
                if result == 0:
                    final_count = self.count_downloaded_files()
                    self.finished.emit(f"Downloaded {final_count} files successfully")
                elif self.error_message:
                    self.error.emit(self.error_message)
                else:
                    self.error.emit(f"Download failed with unknown error")
                    
            except Exception as e:
                error_msg = str(e)
                if not self.error_message:
                    self.error.emit(error_msg)
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr
                
        except Exception as e:
            if not self.error_message:
                self.error.emit(str(e))

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
        
class InstagramMediaDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_version = "1.6" 
        self.setWindowTitle("Instagram Media Batch Downloader")
        
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setFixedWidth(600)
        self.setFixedHeight(180)
        
        self.default_pictures_dir = str(Path.home() / "Pictures")
        os.makedirs(self.default_pictures_dir, exist_ok=True)
        
        self.media_info = None
        self.settings = QSettings('InstagramMediaDownloader', 'Settings')
        self.check_for_updates = self.settings.value('check_for_updates', True, type=bool)
        
        self.init_ui()
        self.load_settings()
        self.setup_auto_save()
        
        if self.check_for_updates:
            QTimer.singleShot(0, self.check_updates)

    def check_updates(self):
        try:
            response = requests.get("https://raw.githubusercontent.com/afkarxyz/Instagram-Media-Batch-Downloader/refs/heads/main/version.json")
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

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        content_area = QWidget()
        content_area.setFixedHeight(120)
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.input_widget = QWidget()
        input_layout = QVBoxLayout(self.input_widget)
        input_layout.setSpacing(10)
        input_layout.setContentsMargins(0, 0, 0, 0)

        url_layout = QHBoxLayout()
        url_label = QLabel("Username/URL:")
        url_label.setFixedWidth(100)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("e.g. takomayuyi or https://instagram.com/takomayuyi/")
        self.url_input.setClearButtonEnabled(True)
        
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.fetch_button.setFixedWidth(100)
        self.fetch_button.clicked.connect(self.fetch_metadata)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.fetch_button)
        input_layout.addLayout(url_layout)

        dir_layout = QHBoxLayout()
        dir_label = QLabel("Output Directory:")
        dir_label.setFixedWidth(100)
        
        self.dir_input = QLineEdit(self.default_pictures_dir)
        
        self.dir_button = QPushButton("Browse")
        self.dir_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.dir_button.setFixedWidth(100)
        self.dir_button.clicked.connect(self.select_directory)
        
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_button)
        input_layout.addLayout(dir_layout)
        
        cookie_layout = QHBoxLayout()
        cookie_label = QLabel("Cookie:")
        cookie_label.setFixedWidth(100)
        
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("Enter your Instagram SessionID if the download fails")
        self.cookie_input.setClearButtonEnabled(True)
        
        cookie_layout.addWidget(cookie_label)
        cookie_layout.addWidget(self.cookie_input)
        input_layout.addLayout(cookie_layout)

        format_layout = QHBoxLayout()
        format_label = QLabel("Filename Format:")
        format_label.setFixedWidth(100)
        
        self.format_username = QRadioButton("Username - Date")
        self.format_date = QRadioButton("Date - Username")
        self.format_username.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.format_date.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        format_layout.addWidget(format_label)
        format_layout.addWidget(self.format_username)
        format_layout.addWidget(self.format_date)
        format_layout.addStretch()
        input_layout.addLayout(format_layout)

        content_layout.addWidget(self.input_widget)

        self.profile_widget = QWidget()
        self.profile_widget.hide()
        profile_layout = QHBoxLayout(self.profile_widget)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(10)

        profile_container = QWidget()
        profile_image_layout = QVBoxLayout(profile_container)
        profile_image_layout.setContentsMargins(0, 0, 0, 0)
        profile_image_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.profile_image_label = QLabel()
        self.profile_image_label.setFixedSize(100, 100)
        self.profile_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_image_layout.addWidget(self.profile_image_label)
        profile_layout.addWidget(profile_container)

        profile_details_container = QWidget()
        profile_details_layout = QVBoxLayout(profile_details_container)
        profile_details_layout.setContentsMargins(0, 0, 0, 0)
        profile_details_layout.setSpacing(2)
        profile_details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-size: 14px;")
        self.name_label.setWordWrap(True)
        self.name_label.setMinimumWidth(400)
        
        self.privacy_status_label = QLabel()
        self.privacy_status_label.setStyleSheet("font-size: 12px;")
        self.privacy_status_label.setWordWrap(True)
        self.privacy_status_label.setMinimumWidth(400)
        
        self.followers_label = QLabel()
        self.followers_label.setStyleSheet("font-size: 12px;")
        self.followers_label.setWordWrap(True)
        self.followers_label.setMinimumWidth(400)

        self.following_label = QLabel()
        self.following_label.setStyleSheet("font-size: 12px;")
        self.following_label.setWordWrap(True)
        self.following_label.setMinimumWidth(400)

        self.posts_label = QLabel()
        self.posts_label.setStyleSheet("font-size: 12px;")
        self.posts_label.setWordWrap(True)
        self.posts_label.setMinimumWidth(400)

        profile_details_layout.addWidget(self.name_label)
        profile_details_layout.addWidget(self.privacy_status_label)
        profile_details_layout.addWidget(self.followers_label)
        profile_details_layout.addWidget(self.following_label)
        profile_details_layout.addWidget(self.posts_label)
        profile_layout.addWidget(profile_details_container, stretch=1)
        profile_layout.addStretch()

        content_layout.addWidget(self.profile_widget)
        
        self.main_layout.addWidget(content_area)

        self.main_layout.addStretch()

        button_widget = QWidget()
        button_widget.setFixedHeight(30)
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        self.download_button = QPushButton("Download")
        self.download_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.download_button.setFixedWidth(100)
        self.download_button.clicked.connect(self.start_download)
        self.download_button.hide()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self.cancel_clicked)
        self.cancel_button.hide()

        self.open_button = QPushButton("Open")
        self.open_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.open_button.setFixedWidth(100)
        self.open_button.clicked.connect(self.open_output_directory)
        self.open_button.hide()

        button_layout.addStretch()
        button_layout.addWidget(self.open_button)
        button_layout.addWidget(self.download_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()

        self.main_layout.addWidget(button_widget)

        status_widget = QWidget()
        status_widget.setFixedHeight(20)
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.version_label = QLabel(f"v1.6 (gallery-dl v1.29.6)")
        status_layout.addWidget(self.version_label)
        
        self.status_label = QLabel("")
        status_layout.addWidget(self.status_label, stretch=1)
        
        self.update_button = QPushButton()
        icon_path = os.path.join(os.path.dirname(__file__), "update.svg")
        if os.path.exists(icon_path):
            self.update_button.setIcon(QIcon(icon_path))
        self.update_button.setFixedSize(16, 16)
        self.update_button.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background: transparent;
            }
        """)
        self.update_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.update_button.setToolTip("Check for Updates")
        self.update_button.clicked.connect(self.open_update_page)
        status_layout.addWidget(self.update_button)

        self.main_layout.addWidget(status_widget)

    def open_update_page(self):
        import webbrowser
        webbrowser.open('https://github.com/afkarxyz/Instagram-Media-Batch-Downloader/releases')
        
    def setup_auto_save(self):
        self.url_input.textChanged.connect(self.auto_save_settings)
        self.dir_input.textChanged.connect(self.auto_save_settings)
        self.cookie_input.textChanged.connect(self.auto_save_settings)
        self.format_username.toggled.connect(self.auto_save_settings)
    
    def auto_save_settings(self):
        self.settings.setValue('url_input', self.url_input.text())
        self.settings.setValue('output_dir', self.dir_input.text())
        self.settings.setValue('cookie_input', self.cookie_input.text())
        self.settings.setValue('filename_format',
                             'username_date' if self.format_username.isChecked() else 'date_username')
        self.settings.sync()

    def load_settings(self):
        self.url_input.setText(self.settings.value('url_input', '', str))
        self.dir_input.setText(self.settings.value('output_dir', self.default_pictures_dir, str))
        self.cookie_input.setText(self.settings.value('cookie_input', '', str))
        
        format_setting = self.settings.value('filename_format', 'username_date')
        self.format_username.setChecked(format_setting == 'username_date')
        self.format_date.setChecked(format_setting == 'date_username')

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            os.makedirs(directory, exist_ok=True)
            self.dir_input.setText(directory)

    def open_output_directory(self):
        output_dir = self.dir_input.text().strip() or self.default_pictures_dir
        if os.path.exists(output_dir):
            if sys.platform == 'win32':
                os.startfile(output_dir)
            elif sys.platform == 'darwin':
                subprocess.run(['open', output_dir])
            else:
                subprocess.run(['xdg-open', output_dir])

    def set_status_text(self, text):
        """Set status text and hide/show version label accordingly"""
        self.status_label.setText(text)
        if text:
            self.version_label.hide()
        else:
            self.version_label.show()

    def fetch_metadata(self):
        username = self.url_input.text().strip()
        if not username:
            self.set_status_text("Please enter a username or URL")
            return

        if "instagram.com/" in username:
            if not username.endswith('/'):
                username += '/'
            self.url_input.setText(username)

        self.fetch_button.setEnabled(False)
        self.set_status_text("Fetching profile information...")
        
        self.fetcher = MetadataFetcher(username)
        self.fetcher.finished.connect(self.handle_profile_info)
        self.fetcher.error.connect(self.handle_fetch_error)
        self.fetcher.start()

    def handle_profile_info(self, info):
        self.media_info = info
        self.fetch_button.setEnabled(True)
        
        name = info['name']
        nick = info['nick']
        is_private = info.get('is_private', False)
        privacy_status = "Private" if is_private else "Public"
        followers = info['followers_count']
        following = info['friends_count']
        posts = info['statuses_count']
        
        self.name_label.setText(f"<b>{name}</b> ({nick})")
        self.privacy_status_label.setText(f"<b>Account Status:</b> {privacy_status}")
        self.followers_label.setText(f"<b>Followers:</b> {followers:,}")
        self.following_label.setText(f"<b>Following:</b> {following:,}")
        self.posts_label.setText(f"<b>Posts:</b> {posts:,}")

        self.set_status_text("Successfully fetched profile info")

        profile_image_url = info['profile_image']
        self.image_downloader = ImageDownloader(profile_image_url)
        self.image_downloader.finished.connect(self.update_profile_image)
        self.image_downloader.start()

        self.input_widget.hide()
        self.profile_widget.show()
        self.download_button.show()
        self.cancel_button.show()
        self.update_button.hide()

    def update_profile_image(self, image_data):
        original_pixmap = QPixmap()
        original_pixmap.loadFromData(image_data)
        
        scaled_pixmap = original_pixmap.scaled(100, 100, 
                                             Qt.AspectRatioMode.KeepAspectRatio, 
                                             Qt.TransformationMode.SmoothTransformation)
        
        rounded_pixmap = QPixmap(scaled_pixmap.size())
        rounded_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(rounded_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, scaled_pixmap.width(), scaled_pixmap.height(), 10, 10)
        
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, scaled_pixmap)
        painter.end()
        
        self.profile_image_label.setPixmap(rounded_pixmap)

    def handle_fetch_error(self, error):
        self.fetch_button.setEnabled(True)
        self.set_status_text(f"Error fetching profile info: {error}")

    def start_download(self):
        if not self.media_info:
            self.set_status_text("Please fetch profile information first")
            return

        self.download_button.hide()
        self.cancel_button.hide()
        self.set_status_text("Starting download...")

        username = self.url_input.text().strip()
        if "instagram.com/" in username:
            username = username.split("/")[-2]
            
        output_dir = self.dir_input.text().strip() or self.default_pictures_dir
        cookie = self.cookie_input.text().strip()
        
        filename_format = "username_date" if self.format_username.isChecked() else "date_username"
        if filename_format == "username_date":
            config_filename = "{username}_{date}_{num}.{extension}"
        else:
            config_filename = "{date}_{username}_{num}.{extension}"

        total_posts = self.media_info['statuses_count']
        self.worker = MediaDownloader(username, output_dir, config_filename, total_posts, cookie)
        self.worker.finished.connect(self.download_finished)
        self.worker.error.connect(self.download_error)
        self.worker.status_update.connect(self.set_status_text)
        self.worker.start()

    def download_finished(self, message):
        self.set_status_text(message)
        self.open_button.show()
        self.download_button.setText("Clear")
        self.download_button.clicked.disconnect()
        self.download_button.clicked.connect(self.clear_form)
        self.download_button.show()
        self.cancel_button.hide()

    def clear_form(self):
        self.url_input.clear()
        self.profile_widget.hide()
        self.input_widget.show()
        self.download_button.hide()
        self.cancel_button.hide()
        self.open_button.hide()
        self.set_status_text("")
        self.media_info = None
        self.update_button.show()
        self.fetch_button.setEnabled(True)
        self.download_button.setText("Download")
        self.download_button.clicked.disconnect()
        self.download_button.clicked.connect(self.start_download)

    def download_error(self, error_message):
        self.set_status_text(f"Download error: {error_message}")
        self.download_button.setText("Retry")
        self.download_button.show()
        self.cancel_button.show()

    def cancel_clicked(self):
        self.profile_widget.hide()
        self.input_widget.show()
        self.download_button.hide()
        self.cancel_button.hide()
        self.open_button.hide()
        self.set_status_text("")
        self.media_info = None
        self.update_button.show()
        self.fetch_button.setEnabled(True)

def main():
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    
    app = QApplication(sys.argv)
    window = InstagramMediaDownloaderGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()