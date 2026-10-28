
import os
import sys
import json
import base64
import uuid
import hashlib
import logging
import subprocess
import shutil
import traceback
from pathlib import Path

import requests
import minecraft_launcher_lib

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QLineEdit, QSpinBox, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox, QProgressBar, QFrame, QFormLayout,
    QCheckBox, QFileDialog, QInputDialog
)

# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "Stealth."
CLIENT_ID = "kslauncher"

LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
APP_DIR = LOCAL_APPDATA / "Stealth"
INSTANCES_DIR = APP_DIR / "instances"
LOG_FILE = APP_DIR / "stealth.log"
CONFIG_FILE = APP_DIR / "settings.json"

APP_DIR.mkdir(parents=True, exist_ok=True)
INSTANCES_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)


def load_config():
    defaults = {
        "java_path": "",
        "min_ram": 1,
        "max_ram": 4,
        "java_args": "",
        "width": 1280,
        "height": 720,
        "fullscreen": False,
    }
    try:
        if CONFIG_FILE.exists():
            defaults.update(json.loads(CONFIG_FILE.read_text("utf-8")))
    except Exception:
        logging.exception("Unable to read settings")
    return defaults


def save_config(config):
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


def safe_name(name):
    cleaned = "".join(
        c for c in name if c.isalnum() or c in " _-."
    ).strip(" .")
    return cleaned[:60] or "My Instance"


def open_folder(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ============================================================
# INSTALL WORKER
# ============================================================

class InstallWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, name, mc_version, loader, instance_dir, java):
        super().__init__()
        self.name = name
        self.mc_version = mc_version
        self.loader = loader
        self.instance_dir = Path(instance_dir)
        self.java = java.strip() or None

    def run(self):
        try:
            def set_status(message):
                self.progress.emit(0, str(message))

            def set_progress(value):
                self.progress.emit(
                    max(0, min(100, int(value))),
                    f"Installing {self.loader}..."
                )

            callback = {
                "setStatus": set_status,
                "setProgress": set_progress,
                "setMax": lambda maximum: None,
            }

            # Resolve Java explicitly for mod-loader installers. Fabric's installer
            # launches Java as a subprocess; a missing executable otherwise raises
            # an unhelpful WinError 2.
            java_executable = self.java
            if java_executable:
                java_executable = str(Path(java_executable).expanduser())
                if not Path(java_executable).is_file():
                    raise RuntimeError(
                        "The Java executable selected in Stealth does not exist.\n\n"
                        "Open Settings and select the actual java.exe file, or clear the Java path "
                        "to let Stealth search PATH."
                    )
            else:
                java_executable = shutil.which("java")


            if self.loader != "Vanilla" and not java_executable:
                raise RuntimeError(
                    "Stealth could not find java.exe, which the mod-loader installer needs.\n\n"
                    "Install a compatible Java JDK, restart Stealth, then try again. "
                    "Or open Stealth Settings and browse directly to java.exe.\n\n"
                    "Java 8 is commonly needed for Minecraft 1.16.5 and older; "
                    "Java 17 for 1.17–1.20.4; Java 21 for 1.20.5 and newer."
                )

            self.instance_dir.mkdir(parents=True, exist_ok=True)
            game_dir = self.instance_dir / "game"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "mods").mkdir(exist_ok=True)

            if self.loader == "Vanilla":
                installed_id = minecraft_launcher_lib.install.install_minecraft_version(
                    self.mc_version,
                    str(self.instance_dir),
                    callback=callback,
                )
            else:
                # The unified mod_loader API was introduced in minecraft-launcher-lib 8.
                loader_ids = {
                    "Fabric": "fabric",
                    "Forge": "forge",
                    "NeoForge": "neoforge",
                    "Quilt": "quilt",
                }
                loader_id = loader_ids.get(self.loader)
                if not loader_id:
                    raise RuntimeError(f"Unknown mod loader: {self.loader}")

                mod_loader_module = getattr(minecraft_launcher_lib, "mod_loader", None)
                if mod_loader_module is None:
                    raise RuntimeError(
                        "Your minecraft-launcher-lib version is too old for mod loaders.\n\n"
                        "Close Stealth and run this in CMD:\n"
                        "py -m pip install --upgrade minecraft-launcher-lib\n\n"
                        "Then restart Stealth."
                    )

                try:
                    mod_loader = mod_loader_module.get_mod_loader(loader_id)
                except (AttributeError, ValueError) as exc:
                    raise RuntimeError(
                        "Stealth could not load the mod-loader API. Update the library with:\n"
                        "py -m pip install --upgrade minecraft-launcher-lib\n\n"
                        f"Details: {exc}"
                    ) from exc

                # Fail early with a clear message for unsupported MC/loader combinations.
                support_check = getattr(mod_loader, "is_minecraft_version_supported", None)
                if callable(support_check) and not support_check(self.mc_version):
                    raise RuntimeError(
                        f"{self.loader} does not currently support Minecraft {self.mc_version}.\n"
                        "Choose a supported Minecraft version for this loader, then try again."
                    )

                installed_id = mod_loader.install(
                    self.mc_version,
                    str(self.instance_dir),
                    callback=callback,
                    java=java_executable,
                )

            metadata = {
                "name": self.name,
                "minecraft_version": self.mc_version,
                "loader": self.loader,
                "installed_version": installed_id,
                "game_dir": str(game_dir),
            }
            (self.instance_dir / "stealth_instance.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )
            self.completed.emit(str(installed_id))

        except Exception as exc:
            error = str(exc)
            details = traceback.format_exc()
            logging.error("Instance installation failed: %s\n%s", error, details)
            self.failed.emit(f"{error}\n\nTechnical details:\n{details}")


# ============================================================
# MAIN WINDOW
# ============================================================

class StealthWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.account = None
        self.worker = None
        self.instances = {}

        self.setWindowTitle("Stealth. — Minecraft Launcher")
        self.resize(1120, 730)
        self.setMinimumSize(900, 620)

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #0d0f15;
                color: #edf0f8;
                font-family: "Segoe UI";
                font-size: 13px;
            }
            QWidget { selection-background-color: #7652df; }
            QFrame#sidebar {
                background: #141721;
                border: none;
            }
            QFrame#panel {
                background: #171b27;
                border: 1px solid #2a3042;
                border-radius: 14px;
            }
            /* Keep text and logo labels transparent so they do not look boxed. */
            QLabel {
                background: transparent;
                border: none;
            }
            QLabel#brand {
                font-size: 31px;
                font-weight: 900;
                color: #a78bfa;
            }
            QLabel#heading {
                font-size: 27px;
                font-weight: 800;
            }
            QLabel#muted {
                color: #969db1;
            }
            QLabel#section {
                color: #b6a4ff;
                font-weight: 700;
                font-size: 12px;
            }
            QLineEdit, QComboBox, QSpinBox {
                background: #202434;
                color: #f4f4fb;
                border: 1px solid #353b50;
                border-radius: 7px;
                padding: 10px 11px;
                min-height: 20px;
            }
            QComboBox QAbstractItemView {
                background: #202434;
                color: white;
                selection-background-color: #7045d5;
            }
            QPushButton {
                background: #222738;
                border: 1px solid #373e53;
                border-radius: 8px;
                padding: 11px 13px;
                text-align: left;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #30364a;
            }
            QPushButton#primary {
                background: #7547e8;
                border: none;
                color: white;
                font-weight: 800;
                padding: 14px;
            }
            QPushButton#primary:hover {
                background: #8963f3;
            }
            QPushButton#nav {
                background: transparent;
                border: none;
                padding: 13px 14px;
                border-radius: 9px;
                text-align: left;
            }
            QPushButton#nav:hover {
                background: #252a3b;
            }
            QProgressBar {
                background: #24293a;
                border: none;
                border-radius: 5px;
                height: 10px;
            }
            QProgressBar::chunk {
                background: #9b7aff;
                border-radius: 5px;
            }
            QCheckBox {
                spacing: 9px;
            }
        """)

        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 24, 14, 20)

        brand = QLabel("Stealth.")
        brand.setObjectName("brand")
        side.addWidget(brand)

        subtitle = QLabel("MINECRAFT CONTROL")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(26)

        self.pages = QStackedWidget()

        for label, index in [
            ("⌂   Home", 0),
            ("▦   Instances", 1),
            ("♙   Accounts", 2),
            ("⚙   Settings", 3),
        ]:
            button = QPushButton(label)
            button.setObjectName("nav")
            button.clicked.connect(
                lambda checked=False, i=index: self.pages.setCurrentIndex(i)
            )
            side.addWidget(button)

        side.addStretch()

        footer = QLabel("STEALTH. / JAVA EDITION")
        footer.setObjectName("muted")
        side.addWidget(footer)

        main.addWidget(sidebar)
        main.addWidget(self.pages, 1)

        self.pages.addWidget(self.make_home())
        self.pages.addWidget(self.make_instances())
        self.pages.addWidget(self.make_accounts())
        self.pages.addWidget(self.make_settings())

        self.refresh_instances()
        self.refresh_versions()
        self.load_offline_profiles()
        self.statusBar().showMessage("Ready")

    def panel(self):
        frame = QFrame()
        frame.setObjectName("panel")
        return frame

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    def make_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 25)
        layout.setSpacing(15)

        heading = QLabel("Welcome back.")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        desc = QLabel("Your game. Your instances. Your rules.")
        desc.setObjectName("muted")
        layout.addWidget(desc)

        box = self.panel()
        form = QVBoxLayout(box)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(13)

        label = QLabel("CREATE A NEW INSTANCE")
        label.setObjectName("section")
        form.addWidget(label)

        self.instance_name = QLineEdit()
        self.instance_name.setPlaceholderText("Instance name (e.g. Survival)")
        form.addWidget(self.instance_name)

        row = QHBoxLayout()

        version_column = QVBoxLayout()
        version_column.addWidget(QLabel("Minecraft version"))
        self.version = QComboBox()
        self.version.setEditable(True)
        self.version.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        version_column.addWidget(self.version)
        version_refresh = QPushButton("Refresh versions")
        version_refresh.clicked.connect(self.refresh_versions)
        version_column.addWidget(version_refresh)
        row.addLayout(version_column, 2)

        loader_column = QVBoxLayout()
        loader_column.addWidget(QLabel("Mod loader"))
        self.loader = QComboBox()
        self.loader.addItems([
            "Vanilla", "Fabric", "Forge", "NeoForge", "Quilt"
        ])
        loader_column.addWidget(self.loader)
        row.addLayout(loader_column, 1)

        form.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        form.addWidget(self.progress)

        self.install_status = QLabel(
            "Choose a version and loader, then install."
        )
        self.install_status.setWordWrap(True)
        self.install_status.setObjectName("muted")
        form.addWidget(self.install_status)

        install = QPushButton("↓   Install instance")
        install.setObjectName("primary")
        install.clicked.connect(self.install_instance)
        form.addWidget(install)

        layout.addWidget(box)

        account_box = self.panel()
        account_layout = QVBoxLayout(account_box)
        account_layout.setContentsMargins(20, 15, 20, 15)

        self.home_account = QLabel("Account: Not signed in")
        self.home_account.setObjectName("muted")
        account_layout.addWidget(self.home_account)

        layout.addWidget(account_box)

        layout.addWidget(QLabel("QUICK ACCESS"))

        quick = QHBoxLayout()
        for label, action in [
            ("Open instances", lambda: open_folder(INSTANCES_DIR)),
            ("Open app data", lambda: open_folder(APP_DIR)),
            ("Manage instances", lambda: self.pages.setCurrentIndex(1)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(action)
            quick.addWidget(button)

        layout.addLayout(quick)
        layout.addStretch()
        return page

    # --------------------------------------------------------
    # INSTANCES
    # --------------------------------------------------------

    def make_instances(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 25)
        layout.setSpacing(15)

        heading = QLabel("Your instances")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        desc = QLabel("Each instance has its own game directory and mods.")
        desc.setObjectName("muted")
        layout.addWidget(desc)

        self.instance_list = QComboBox()
        self.instance_list.currentTextChanged.connect(self.instance_changed)
        layout.addWidget(self.instance_list)

        self.instance_details = QLabel("Create an instance to get started.")
        self.instance_details.setWordWrap(True)
        layout.addWidget(self.instance_details)

        row = QHBoxLayout()

        open_instance = QPushButton("Open instance folder")
        open_instance.clicked.connect(self.open_selected_instance)
        row.addWidget(open_instance)

        open_mods = QPushButton("Open mods folder")
        open_mods.clicked.connect(self.open_selected_mods)
        row.addWidget(open_mods)

        shortcut = QPushButton("Create desktop shortcut")
        shortcut.setObjectName("primary")
        shortcut.clicked.connect(self.create_selected_shortcut)
        row.addWidget(shortcut)

        uninstall = QPushButton("Uninstall instance")
        uninstall.clicked.connect(self.uninstall_selected_instance)
        row.addWidget(uninstall)

        layout.addLayout(row)

        launch = QPushButton("▶   Launch selected instance")
        launch.setObjectName("primary")
        launch.clicked.connect(self.launch_selected_instance)
        layout.addWidget(launch)

        refresh = QPushButton("Refresh instances")
        refresh.clicked.connect(self.refresh_instances)
        layout.addWidget(refresh)

        layout.addStretch()
        return page

    def refresh_versions(self):
        """Fetch the current version manifest instead of relying on a short hard-coded list."""
        current = self.version.currentText().strip() if hasattr(self, "version") else ""
        try:
            versions = minecraft_launcher_lib.utils.get_version_list()
            ids = [v.get("id", "") for v in versions if v.get("id")]
            if not ids:
                raise RuntimeError("The Minecraft version manifest returned no versions.")
            self.version.blockSignals(True)
            self.version.clear()
            self.version.addItems(ids)
            if current and current in ids:
                self.version.setCurrentText(current)
            elif current:
                self.version.setEditText(current)
            self.version.blockSignals(False)
            self.statusBar().showMessage(f"Loaded {len(ids)} Minecraft versions", 5000)
        except Exception as exc:
            logging.exception("Could not refresh Minecraft versions")
            if self.version.count() == 0:
                self.version.addItems(["1.21.8", "1.21.5", "1.21.4", "1.21.1", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9"])
            QMessageBox.warning(self, "Version list unavailable", f"Could not fetch the full Minecraft version list. Check your internet connection and press Refresh versions to try again.\n\n{exc}")

    def uninstall_selected_instance(self):
        item = self.selected_instance()
        if not item:
            QMessageBox.warning(self, "No instance", "Select an instance first.")
            return
        path = Path(item["path"]).resolve()
        root = INSTANCES_DIR.resolve()
        if path.parent != root:
            QMessageBox.critical(self, "Safety check failed", "This instance folder is outside Stealth's instances directory, so it was not deleted.")
            return
        answer = QMessageBox.question(
            self, "Uninstall instance?",
            f"Delete instance '{item['name']}' and all its files, including saves/worlds, mods, and settings?\n\nThis cannot be undone.\n\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            import shutil
            shutil.rmtree(path)
            logging.info("Uninstalled instance %s", item["name"])
            self.refresh_instances()
            self.statusBar().showMessage(f"Uninstalled {item['name']}", 5000)
        except Exception as exc:
            logging.exception("Instance uninstall failed")
            QMessageBox.critical(self, "Uninstall failed", f"Could not remove the instance. Close Minecraft if it is running, then try again.\n\n{exc}")

    def refresh_instances(self):
        if not hasattr(self, "instance_list"):
            return

        previous = self.instance_list.currentText()

        self.instances = {}
        for folder in INSTANCES_DIR.iterdir():
            metadata_file = folder / "stealth_instance.json"
            if not folder.is_dir() or not metadata_file.exists():
                continue
            try:
                data = json.loads(metadata_file.read_text("utf-8"))
                self.instances[data["name"]] = {
                    **data,
                    "path": folder,
                }
            except Exception:
                logging.exception("Invalid instance metadata: %s", folder)

        self.instance_list.blockSignals(True)
        self.instance_list.clear()
        self.instance_list.addItems(sorted(self.instances.keys()))
        if previous in self.instances:
            self.instance_list.setCurrentText(previous)
        self.instance_list.blockSignals(False)

        self.instance_changed(self.instance_list.currentText())

    def selected_instance(self):
        return self.instances.get(self.instance_list.currentText())

    def instance_changed(self, name):
        if not hasattr(self, "instance_details"):
            return

        item = self.instances.get(name)
        if not item:
            self.instance_details.setText("No instance selected.")
            return

        self.instance_details.setText(
            f"Name: {item['name']}\n"
            f"Minecraft: {item['minecraft_version']}\n"
            f"Loader: {item['loader']}\n"
            f"Installed profile: {item['installed_version']}\n\n"
            f"Folder: {item['path']}\n"
            f"Mods: {item['path'] / 'game' / 'mods'}"
        )

    def open_selected_instance(self):
        item = self.selected_instance()
        if item:
            open_folder(item["path"])

    def open_selected_mods(self):
        item = self.selected_instance()
        if item:
            open_folder(item["path"] / "game" / "mods")

    def create_selected_shortcut(self):
        item = self.selected_instance()
        if not item:
            QMessageBox.warning(self, "No instance", "Select an instance first.")
            return
        if sys.platform != "win32":
            QMessageBox.warning(self, "Windows only", "Desktop shortcuts are currently supported on Windows.")
            return

        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        shortcut_path = desktop / f"Stealth. - {safe_name(item['name'])}.lnk"

        # Use the packaged executable when frozen; otherwise point to Python + this script.
        if getattr(sys, "frozen", False):
            target = Path(sys.executable)
            arguments = f'--launch-instance "{item["name"]}"'
            working_dir = Path(sys.executable).parent
        else:
            target = Path(sys.executable)
            script_path = Path(__file__).resolve()
            arguments = f'"{script_path}" --launch-instance "{item["name"]}"'
            working_dir = script_path.parent
            # Prefer pythonw.exe so a shortcut does not open a console window.
            pythonw = target.with_name("pythonw.exe")
            if pythonw.exists():
                target = pythonw

        # Create a Minecraft-style grass-block icon in AppData for this shortcut.
        icon_path = APP_DIR / "minecraft_instance.ico"
        if not icon_path.exists():
            icon_path.write_bytes(base64.b64decode("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"))

        # PowerShell single-quoted strings preserve Windows backslashes safely.
        def ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        ps_script = f'''$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut({ps_quote(shortcut_path)})
$Shortcut.TargetPath = {ps_quote(target)}
$Shortcut.Arguments = {ps_quote(arguments)}
$Shortcut.WorkingDirectory = {ps_quote(working_dir)}
$Shortcut.IconLocation = {ps_quote(str(icon_path) + ",0")}
$Shortcut.Description = {ps_quote('Launch the ' + item['name'] + ' instance in Stealth.')}
$Shortcut.Save()'''
        encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                check=True, capture_output=True, text=True, timeout=15,
            )
            QMessageBox.information(
                self, "Shortcut created",
                f'Desktop shortcut created:\n{shortcut_path.name}\n\n'
                'It opens Stealth. with this instance selected. Sign in if needed, then click Launch.',
            )
            logging.info("Created desktop shortcut for instance %s at %s", item["name"], shortcut_path)
        except Exception as exc:
            logging.exception("Could not create desktop shortcut")
            QMessageBox.critical(self, "Shortcut failed", f"Could not create the shortcut.\n\n{exc}")

    # --------------------------------------------------------
    # INSTALL
    # --------------------------------------------------------

    def install_instance(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Please wait", "An installation is already running."
            )
            return

        name = safe_name(self.instance_name.text())
        version = self.version.currentText().strip()
        loader = self.loader.currentText()

        if not version:
            QMessageBox.warning(
                self, "Version required", "Enter a Minecraft version."
            )
            return

        target = INSTANCES_DIR / name
        if target.exists() and (target / "stealth_instance.json").exists():
            answer = QMessageBox.question(
                self,
                "Instance exists",
                f'"{name}" already exists. Reinstalling may replace files. '
                "Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.progress.setValue(0)
        self.install_status.setText(
            f"Preparing {name} — Minecraft {version} ({loader})..."
        )

        self.worker = InstallWorker(
            name,
            version,
            loader,
            target,
            self.config.get("java_path", ""),
        )
        self.worker.progress.connect(self.on_install_progress)
        self.worker.completed.connect(self.on_install_completed)
        self.worker.failed.connect(self.on_install_failed)
        self.worker.start()

    def on_install_progress(self, value, message):
        self.install_status.setText(message)
        if value > 0:
            self.progress.setValue(value)

    def on_install_completed(self, installed_id):
        self.progress.setValue(100)
        self.install_status.setText(
            f"Installed successfully: {installed_id}"
        )
        self.statusBar().showMessage("Instance installed")
        self.refresh_instances()
        self.pages.setCurrentIndex(1)

        item = self.selected_instance()
        if item:
            open_mods = QMessageBox.question(
                self,
                "Installation complete",
                "Your instance is ready.\n\n"
                "Would you like to open its mods folder now?",
            )
            if open_mods == QMessageBox.StandardButton.Yes:
                self.open_selected_mods()

    def on_install_failed(self, error):
        self.install_status.setText("Installation failed. Check the log.")
        logging.error("Installation error:\n%s", error)
        QMessageBox.critical(
            self, "Installation failed",
            f"{error}\n\nDiagnostic log:\n{LOG_FILE}"
        )

    # --------------------------------------------------------
    # ACCOUNTS
    # --------------------------------------------------------

    def make_accounts(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 25)

        heading = QLabel("Accounts")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        layout.addWidget(QLabel("Ely.by account"))

        form = QFormLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText("Username or e-mail")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Username", self.email)
        form.addRow("Password", self.password)
        layout.addLayout(form)

        login = QPushButton("Sign in with Ely.by")
        login.setObjectName("primary")
        login.clicked.connect(self.login_elyby)
        layout.addWidget(login)

        self.login_status = QLabel(
            "Passwords are not saved by this application."
        )
        self.login_status.setWordWrap(True)
        self.login_status.setObjectName("muted")
        layout.addWidget(self.login_status)

        layout.addWidget(QLabel("OFFLINE ACCOUNTS"))
        self.offline_accounts = QComboBox()
        self.offline_accounts.setMinimumWidth(260)
        layout.addWidget(self.offline_accounts)

        offline_row = QHBoxLayout()
        add_offline = QPushButton("Add offline account")
        add_offline.setObjectName("primary")
        add_offline.clicked.connect(self.add_offline_account)
        offline_row.addWidget(add_offline)
        use_offline = QPushButton("Use selected account")
        use_offline.clicked.connect(self.use_offline_account)
        offline_row.addWidget(use_offline)
        remove_offline = QPushButton("Remove saved offline account")
        remove_offline.clicked.connect(self.remove_offline_account)
        offline_row.addWidget(remove_offline)
        layout.addLayout(offline_row)

        offline_note = QLabel("Offline accounts do not authenticate with Microsoft or Mojang. They generally work only in single-player or on servers that allow offline-mode accounts.")
        offline_note.setWordWrap(True)
        offline_note.setObjectName("muted")
        layout.addWidget(offline_note)

        layout.addStretch()
        return page

    def login_elyby(self):
        username = self.email.text().strip()
        password = self.password.text()

        if not username or not password:
            QMessageBox.warning(
                self, "Missing details", "Enter your login details."
            )
            return

        self.login_status.setText("Connecting to Ely.by...")
        QApplication.processEvents()

        try:
            response = requests.post(
                "https://authserver.ely.by/auth/authenticate",
                json={
                    "username": username,
                    "password": password,
                    "clientToken": str(uuid.uuid4()),
                    "requestUser": True,
                },
                timeout=30,
            )
            data = response.json()

            if not response.ok:
                raise RuntimeError(
                    data.get("errorMessage")
                    or data.get("error")
                    or f"HTTP {response.status_code}"
                )

            profile = data.get("selectedProfile")
            token = data.get("accessToken")
            if not profile or not token:
                raise RuntimeError("No usable profile/token was returned.")

            self.account = {
                "username": profile["name"],
                "uuid": profile["id"],
                "token": token,
                "type": "ely.by",
            }
            self.password.clear()

            self.home_account.setText(
                f"Account: {profile['name']} (Ely.by)"
            )
            self.login_status.setText(
                "Authentication succeeded. Game-session compatibility "
                "may require Ely.by's authlib-injector integration."
            )
            logging.info("Ely.by login succeeded: %s", profile["name"])

            QMessageBox.information(
                self, "Signed in", f"Signed in as {profile['name']}."
            )

        except Exception as exc:
            self.password.clear()
            logging.exception("Ely.by login failed")
            QMessageBox.critical(
                self, "Sign-in failed",
                f"{exc}\n\nSee {LOG_FILE}"
            )

    def offline_profiles_file(self):
        return APP_DIR / "offline_profiles.json"

    def load_offline_profiles(self):
        if not hasattr(self, "offline_accounts"):
            return
        try:
            profiles = json.loads(self.offline_profiles_file().read_text("utf-8")) if self.offline_profiles_file().exists() else []
            if not isinstance(profiles, list):
                profiles = []
        except Exception:
            logging.exception("Could not load offline profiles")
            profiles = []
        self.offline_accounts.clear()
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("username"):
                self.offline_accounts.addItem(profile["username"], profile)

    def add_offline_account(self):
        username, ok = QInputDialog.getText(self, "Add offline account", "Username (3–16 letters, numbers, or underscores):")
        username = username.strip()
        if not ok:
            return
        if not (3 <= len(username) <= 16) or not all(c.isascii() and (c.isalnum() or c == "_") for c in username):
            QMessageBox.warning(self, "Invalid username", "Use 3–16 ASCII letters, numbers, or underscores.")
            return
        self.load_offline_profiles()
        profiles = [self.offline_accounts.itemData(i) for i in range(self.offline_accounts.count())]
        if any(p.get("username", "").lower() == username.lower() for p in profiles):
            QMessageBox.information(self, "Already saved", "That offline username is already saved.")
            return
        raw = bytearray(hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest())
        raw[6] = (raw[6] & 0x0F) | 0x30
        raw[8] = (raw[8] & 0x3F) | 0x80
        profile = {"username": username, "uuid": str(uuid.UUID(bytes=bytes(raw))), "type": "offline"}
        profiles.append(profile)
        self.offline_profiles_file().write_text(json.dumps(profiles, indent=2), encoding="utf-8")
        self.load_offline_profiles()
        index = self.offline_accounts.findText(username)
        if index >= 0:
            self.offline_accounts.setCurrentIndex(index)
        self.account = {**profile, "token": "0"}
        self.home_account.setText(f"Account: {username} (Offline)")
        self.login_status.setText(f"Offline profile {username} added and selected. This is not a paid/authenticated account.")
        QMessageBox.information(self, "Offline account added", f"Added and selected offline profile '{username}'.")

    def use_offline_account(self):
        profile = self.offline_accounts.currentData()
        if not profile:
            QMessageBox.warning(self, "No offline account", "Add an offline account first.")
            return
        self.account = {**profile, "token": "0", "type": "offline"}
        self.home_account.setText(f"Account: {profile['username']} (Offline)")
        self.login_status.setText(f"Using offline profile: {profile['username']}")
        self.statusBar().showMessage(f"Selected offline account {profile['username']}", 5000)

    def remove_offline_account(self):
        profile = self.offline_accounts.currentData()
        if not profile:
            QMessageBox.warning(self, "No offline account", "Select a saved offline account first.")
            return
        answer = QMessageBox.question(self, "Remove offline account", f"Remove saved profile '{profile['username']}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        profiles = [self.offline_accounts.itemData(i) for i in range(self.offline_accounts.count()) if self.offline_accounts.itemData(i).get("username") != profile.get("username")]
        self.offline_profiles_file().write_text(json.dumps(profiles, indent=2), encoding="utf-8")
        if self.account and self.account.get("type") == "offline" and self.account.get("username") == profile.get("username"):
            self.account = None
            self.home_account.setText("Account: Not signed in")
        self.load_offline_profiles()

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    def make_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 25)
        layout.setSpacing(12)

        heading = QLabel("Java & game settings")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        layout.addWidget(QLabel("JAVA RUNTIME"))

        java_row = QHBoxLayout()
        self.java_path = QLineEdit(self.config.get("java_path", ""))
        self.java_path.setPlaceholderText(
            "Leave blank to use the launcher-managed Java runtime"
        )
        java_row.addWidget(self.java_path, 1)

        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_java)
        java_row.addWidget(browse)
        layout.addLayout(java_row)

        form = QFormLayout()

        self.min_ram = QSpinBox()
        self.min_ram.setRange(1, 31)
        self.min_ram.setSuffix(" GB")
        self.min_ram.setValue(int(self.config.get("min_ram", 1)))
        form.addRow("Minimum RAM (-Xms)", self.min_ram)

        self.max_ram = QSpinBox()
        self.max_ram.setRange(2, 64)
        self.max_ram.setSuffix(" GB")
        self.max_ram.setValue(int(self.config.get("max_ram", 4)))
        form.addRow("Maximum RAM (-Xmx)", self.max_ram)

        self.width = QSpinBox()
        self.width.setRange(640, 7680)
        self.width.setValue(int(self.config.get("width", 1280)))
        form.addRow("Window width", self.width)

        self.height = QSpinBox()
        self.height.setRange(480, 4320)
        self.height.setValue(int(self.config.get("height", 720)))
        form.addRow("Window height", self.height)

        layout.addLayout(form)

        self.fullscreen = QCheckBox("Start Minecraft in fullscreen")
        self.fullscreen.setChecked(
            bool(self.config.get("fullscreen", False))
        )
        layout.addWidget(self.fullscreen)

        layout.addWidget(QLabel("EXTRA JAVA ARGUMENTS"))
        self.java_args = QLineEdit(self.config.get("java_args", ""))
        self.java_args.setPlaceholderText(
            "Optional: -XX:+UseG1GC"
        )
        layout.addWidget(self.java_args)

        note = QLabel(
            "Use a Java version compatible with the selected Minecraft "
            "release. Extra JVM arguments can cause crashes if invalid."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)

        open_data = QPushButton("Open Stealth. AppData folder")
        open_data.clicked.connect(lambda: open_folder(APP_DIR))
        layout.addWidget(open_data)

        layout.addStretch()
        return page

    def browse_java(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Java executable",
            str(Path.home()),
            "Java executable (java.exe);;All files (*.*)",
        )
        if path:
            self.java_path.setText(path)

    def save_settings(self):
        if self.min_ram.value() >= self.max_ram.value():
            QMessageBox.warning(
                self, "Invalid RAM settings",
                "Maximum RAM must be greater than minimum RAM."
            )
            return

        self.config = {
            "java_path": self.java_path.text().strip(),
            "min_ram": self.min_ram.value(),
            "max_ram": self.max_ram.value(),
            "java_args": self.java_args.text().strip(),
            "width": self.width.value(),
            "height": self.height.value(),
            "fullscreen": self.fullscreen.isChecked(),
        }

        save_config(self.config)
        QMessageBox.information(
            self, "Settings saved", "Your settings have been saved."
        )

    # --------------------------------------------------------
    # LAUNCH
    # --------------------------------------------------------

    def launch_selected_instance(self):
        item = self.selected_instance()
        if not item:
            QMessageBox.warning(
                self, "No instance", "Create or select an instance first."
            )
            return

        if not self.account:
            QMessageBox.warning(
                self, "Account required",
                "Add/select an offline profile or sign in with Ely.by first."
            )
            self.pages.setCurrentIndex(2)
            return

        try:
            options = {
                "username": self.account["username"],
                "uuid": self.account["uuid"],
                "token": self.account.get("token", "0"),
                "userType": "legacy" if self.account.get("type") == "offline" else "msa",
                "gameDirectory": str(item["path"] / "game"),
                "jvmArguments": [
                    f"-Xms{self.config['min_ram']}G",
                    f"-Xmx{self.config['max_ram']}G",
                ],
                "customResolution": True,
                "resolutionWidth": str(self.config["width"]),
                "resolutionHeight": str(self.config["height"]),
            }

            java_path = self.config.get("java_path", "").strip()
            if java_path:
                options["executablePath"] = java_path

            extra_args = self.config.get("java_args", "").strip()
            if extra_args:
                import shlex
                options["jvmArguments"].extend(
                    shlex.split(extra_args, posix=False)
                )

            if self.config.get("fullscreen"):
                options["fullscreen"] = True

            command = minecraft_launcher_lib.command.get_minecraft_command(
                item["installed_version"],
                str(item["path"]),
                options,
            )

            subprocess.Popen(
                command,
                cwd=str(item["path"]),
            )
            self.statusBar().showMessage("Minecraft launch requested")
            logging.info("Launching instance %s", item["name"])

        except Exception as exc:
            logging.exception("Minecraft launch failed")
            QMessageBox.critical(
                self, "Launch failed",
                f"{exc}\n\nSee diagnostic log:\n{LOG_FILE}"
            )


# ============================================================
# STARTUP
# ============================================================

def main():
    try:
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        window = StealthWindow()
        window.show()
        if "--launch-instance" in sys.argv:
            try:
                index = sys.argv.index("--launch-instance")
                requested_name = sys.argv[index + 1]
                if requested_name in window.instances:
                    window.instance_list.setCurrentText(requested_name)
                    window.pages.setCurrentIndex(1)
                    window.statusBar().showMessage(f"Selected instance: {requested_name}")
                else:
                    QMessageBox.warning(
                        window, "Instance not found",
                        f'The shortcut refers to "{requested_name}", but that instance was not found. Refresh your instances list.',
                    )
            except (ValueError, IndexError):
                logging.exception("Invalid launch-instance command line")
        sys.exit(app.exec())
    except Exception:
        logging.exception("Fatal startup error")
        raise


if __name__ == "__main__":
    main()
