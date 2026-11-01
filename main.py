"""
UGC 〆 NINJA - iOS Professional Suite v1.0
USB-connected iPhone diagnostics + official Apple activation-support guidance.

This application reads basic device information from a trusted, USB-connected
iPhone. It does NOT remove Activation Lock, bypass iCloud, alter device state,
or access protected account data.
"""
from __future__ import annotations

import sys
import traceback
from typing import Any, Dict, Optional

from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTabWidget, QFrame, QMessageBox, QProgressBar,
    QSizePolicy
)

APP_TITLE = "UGC 〆 NINJA - iOS Professional Suite v1.0"
APPLE_SUPPORT_URL = "https://al-support.apple.com"


def _first_value(data: Dict[str, Any], *keys: str) -> Optional[str]:
    """Return the first non-empty value for any candidate key."""
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def read_iphone_info() -> Dict[str, str]:
    """
    Read basic lockdown values from a paired/trusted USB device.

    pymobiledevice2 has changed import locations across releases, so support
    the current LockdownClient import and a compatible fallback. All I/O runs
    inside the worker thread, never on the GUI thread.
    """
    try:
        from pymobiledevice2.lockdown import create_using_usbmux
    except ImportError:
        try:
            from pymobiledevice2.lockdown import LockdownClient
            client = LockdownClient.create()
        except Exception as exc:
            raise RuntimeError(
                "Could not import or initialize pymobiledevice2. "
                "Install the requirements and check the package version."
            ) from exc
    else:
        client = create_using_usbmux()

    # Some versions expose .all_values; others provide .get_value().
    values: Dict[str, Any] = {}
    try:
        all_values = getattr(client, "all_values", None)
        if callable(all_values):
            all_values = all_values()
        if isinstance(all_values, dict):
            values.update(all_values)
    except Exception:
        pass

    def get_value(domain: Optional[str], key: str) -> Any:
        getter = getattr(client, "get_value", None)
        if callable(getter):
            try:
                return getter(domain=domain, key=key)
            except TypeError:
                try:
                    return getter(key)
                except Exception:
                    return None
            except Exception:
                return None
        return None

    # Device name is commonly under DeviceName; product/build values are
    # supplied by the com.apple.mobile.* lockdown domains.
    candidates = {
        "device_name": _first_value(values, "DeviceName", "device_name"),
        "serial": _first_value(values, "SerialNumber", "serial_number"),
        "model": _first_value(values, "ProductType", "ModelNumber", "product_type"),
        "ios": _first_value(values, "ProductVersion", "product_version"),
    }

    for field, key in (
        ("device_name", "DeviceName"),
        ("serial", "SerialNumber"),
        ("model", "ProductType"),
        ("ios", "ProductVersion"),
    ):
        if not candidates[field]:
            candidates[field] = get_value(None, key)

    # Battery is exposed by the mobile.battery domain on supported iOS versions.
    battery = get_value("com.apple.mobile.battery", "BatteryCurrentCapacity")
    if battery is None:
        battery = get_value(None, "BatteryCurrentCapacity")

    # A few client versions expose domain values as a nested dictionary.
    if battery is None:
        for container_key in ("Battery", "battery", "com.apple.mobile.battery"):
            nested = values.get(container_key)
            if isinstance(nested, dict):
                battery = nested.get("BatteryCurrentCapacity") or nested.get("CurrentCapacity")
                if battery is not None:
                    break

    result = {
        "Device Name": str(candidates["device_name"] or "Not reported"),
        "Serial Number": str(candidates["serial"] or "Not reported"),
        "Model Identifier": str(candidates["model"] or "Not reported"),
        "iOS Version": str(candidates["ios"] or "Not reported"),
        "Battery Capacity": f"{battery}%" if battery is not None else "Not reported",
    }
    return result


class DeviceWorker(QObject):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.succeeded.emit(read_iphone_info())
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            self.failed.emit(detail)
        finally:
            self.finished.emit()


class InfoCard(QFrame):
    def __init__(self, caption: str, value: str = "—", accent: str = "#00f3ff"):
        super().__init__()
        self.setObjectName("InfoCard")
        self.setMinimumHeight(88)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        self.caption = QLabel(caption.upper())
        self.caption.setObjectName("CardCaption")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.value.setStyleSheet(f"color: {accent};")

        layout.addWidget(self.caption)
        layout.addWidget(self.value, 1)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class DeviceTab(QWidget):
    def __init__(self):
        super().__init__()
        self.thread: Optional[QThread] = None
        self.worker: Optional[DeviceWorker] = None
        self.cards: Dict[str, InfoCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(15)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("DEVICE INTELLIGENCE")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("USBMUXD TELEMETRY  /  TRUSTED DEVICE SESSION")
        subtitle.setObjectName("SectionSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()
        self.status = QLabel("● STANDBY")
        self.status.setObjectName("StatusPill")
        header.addWidget(self.status, alignment=Qt.AlignTop)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        fields = [
            ("Device Name", "#00f3ff"),
            ("Serial Number", "#00ff66"),
            ("Model Identifier", "#00f3ff"),
            ("iOS Version", "#00ff66"),
            ("Battery Capacity", "#00f3ff"),
        ]
        for index, (name, accent) in enumerate(fields):
            card = InfoCard(name, accent=accent)
            self.cards[name] = card
            grid.addWidget(card, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        self.progress = QProgressBar()
        self.progress.setObjectName("ScanProgress")
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)

        self.scan_button = QPushButton("⚡  Scan & Read iPhone Info")
        self.scan_button.setObjectName("PrimaryButton")
        self.scan_button.setCursor(Qt.PointingHandCursor)
        self.scan_button.setMinimumHeight(46)
        self.scan_button.clicked.connect(self.start_scan)
        root.addWidget(self.scan_button)

        foot = QLabel("Connect iPhone by USB, unlock it, then tap “Trust This Computer”.")
        foot.setObjectName("Hint")
        foot.setAlignment(Qt.AlignCenter)
        root.addWidget(foot)

    def start_scan(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            return

        self.scan_button.setEnabled(False)
        self.scan_button.setText("◌  SCANNING DEVICE…")
        self.progress.show()
        self.status.setText("● CONNECTING")
        self.status.setProperty("state", "working")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        self.thread = QThread(self)
        self.worker = DeviceWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.on_thread_finished)
        self.thread.start()

    @pyqtSlot(dict)
    def on_success(self, data: Dict[str, str]) -> None:
        for key, value in data.items():
            if key in self.cards:
                self.cards[key].set_value(value)
        self.status.setText("● DEVICE READ")
        self.status.setProperty("state", "success")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @pyqtSlot(str)
    def on_failure(self, error: str) -> None:
        self.status.setText("● DEVICE NOT FOUND")
        self.status.setProperty("state", "error")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        QMessageBox.warning(
            self,
            "Device Scan Failed",
            "The iPhone could not be read.\n\n"
            f"Details: {error}\n\n"
            "Check that Apple device drivers are installed, the phone is "
            "connected by a data-capable USB cable, the phone is unlocked, "
            "and “Trust This Computer” has been accepted."
        )

    @pyqtSlot()
    def on_thread_finished(self) -> None:
        self.progress.hide()
        self.scan_button.setEnabled(True)
        self.scan_button.setText("⚡  Scan & Read iPhone Info")
        self.thread = None
        self.worker = None


class LockedTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(25, 25, 25, 25)
        root.addStretch(1)

        panel = QFrame()
        panel.setObjectName("LockedPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 26, 24, 26)
        panel_layout.setSpacing(16)

        lock_icon = QLabel("▣")
        lock_icon.setObjectName("LockIcon")
        lock_icon.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(lock_icon)

        heading = QLabel("🔒  iCloud Bypass X to 18 (Module Locked)")
        heading.setObjectName("LockedHeading")
        heading.setAlignment(Qt.AlignCenter)
        heading.setWordWrap(True)
        panel_layout.addWidget(heading)

        warning = QLabel(
            "This module is intentionally locked. Activation Lock is an "
            "anti-theft security feature; this suite does not bypass or "
            "remove it. If this is your device, use Apple's official "
            "ownership and account-recovery process."
        )
        warning.setObjectName("LockedDescription")
        warning.setAlignment(Qt.AlignCenter)
        warning.setWordWrap(True)
        panel_layout.addWidget(warning)

        self.activation_button = QPushButton("⬡  GET ACTIVATION")
        self.activation_button.setObjectName("SecureButton")
        self.activation_button.setMinimumHeight(46)
        self.activation_button.setCursor(Qt.PointingHandCursor)
        self.activation_button.clicked.connect(self.show_activation_info)
        panel_layout.addWidget(self.activation_button)

        link = QLabel(f'<a href="{APPLE_SUPPORT_URL}">{APPLE_SUPPORT_URL}</a>')
        link.setObjectName("SupportLink")
        link.setAlignment(Qt.AlignCenter)
        link.setOpenExternalLinks(True)
        panel_layout.addWidget(link)

        root.addWidget(panel)
        root.addStretch(1)

    def show_activation_info(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Official Activation Support")
        box.setIcon(QMessageBox.Information)
        box.setText("Use Apple's official Activation Lock support channel.")
        box.setInformativeText(
            "Prepare proof of purchase and the device serial number or IMEI "
            "if requested. Submit information only through Apple's official "
            "support page. Never share your Apple Account password or "
            "verification codes with third parties."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.setStyleSheet(DIALOG_STYLE)
        box.exec_()
        # Open the official support page after the user acknowledges the notice.
        import webbrowser
        webbrowser.open(APPLE_SUPPORT_URL)


DIALOG_STYLE = """
QMessageBox { background: #10151b; color: #eafcff; }
QLabel { color: #d7e8ed; min-width: 340px; }
QPushButton {
  background: #00f3ff; color: #071014; border: 0; border-radius: 7px;
  padding: 8px 22px; font-weight: 800; min-width: 90px;
}
"""


APP_STYLE = """
* { font-family: "Segoe UI"; }
QMainWindow, QWidget {
    background: #090d12;
    color: #e8f7fa;
}
QTabWidget::pane {
    border: 1px solid #1b333c;
    border-radius: 10px;
    background: #0d131a;
    top: -1px;
}
QTabBar::tab {
    background: #0b1117;
    color: #78939d;
    border: 1px solid #1a3038;
    border-bottom: 3px solid transparent;
    padding: 12px 22px;
    min-width: 190px;
    font-size: 10pt;
    font-weight: 800;
}
QTabBar::tab:selected {
    color: #00f3ff;
    background: #101b22;
    border-bottom: 3px solid #00f3ff;
}
QTabBar::tab:hover:!selected { color: #00ff66; }
QLabel#Brand {
    color: #f2feff;
    font-size: 17pt;
    font-weight: 900;
    letter-spacing: 1px;
}
QLabel#Version {
    color: #00ff66;
    font-size: 8pt;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#SectionTitle {
    color: #eaffff;
    font-size: 15pt;
    font-weight: 900;
    letter-spacing: 1px;
}
QLabel#SectionSubtitle, QLabel#Hint {
    color: #68838d;
    font-size: 8pt;
    letter-spacing: 1px;
}
QLabel#StatusPill {
    color: #00f3ff;
    background: #10242a;
    border: 1px solid #12616a;
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 8pt;
    font-weight: 800;
}
QLabel#StatusPill[state="success"] {
    color: #00ff66; background: #10251a; border-color: #17663a;
}
QLabel#StatusPill[state="error"] {
    color: #ff5b69; background: #29151a; border-color: #80313c;
}
QLabel#StatusPill[state="working"] { color: #00f3ff; }
QFrame#InfoCard {
    background: #111a22;
    border: 1px solid #203640;
    border-radius: 10px;
}
QFrame#InfoCard:hover { border: 1px solid #00aab5; }
QLabel#CardCaption {
    color: #718d98;
    font-size: 8pt;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#CardValue {
    color: #00f3ff;
    font-size: 11pt;
    font-weight: 800;
}
QPushButton#PrimaryButton {
    color: #061115;
    background: #00e6f2;
    border: 1px solid #55f8ff;
    border-radius: 9px;
    font-size: 10pt;
    font-weight: 900;
    letter-spacing: 1px;
}
QPushButton#PrimaryButton:hover {
    background: #72fbff;
    border: 1px solid #ffffff;
}
QPushButton#PrimaryButton:pressed {
    background: #00aeb8;
    padding-top: 3px;
}
QPushButton#PrimaryButton:disabled {
    color: #59747b; background: #1a2b31; border-color: #28434a;
}
QProgressBar#ScanProgress {
    border: 1px solid #1c424b; border-radius: 3px;
    background: #0b1116; height: 5px; text-align: center;
}
QProgressBar#ScanProgress::chunk { background: #00f3ff; }
QFrame#LockedPanel {
    background: #10151c;
    border: 1px solid #a33a49;
    border-top: 3px solid #00ff66;
    border-bottom: 3px solid #ff4259;
    border-radius: 14px;
}
QLabel#LockIcon { color: #ff5267; font-size: 38pt; font-weight: 900; }
QLabel#LockedHeading {
    color: #ff6374; font-size: 13pt; font-weight: 900;
}
QLabel#LockedDescription {
    color: #9bb0b8; font-size: 9pt; line-height: 1.4;
}
QPushButton#SecureButton {
    color: #f4ffff; background: #14251e;
    border: 1px solid #00ff66; border-radius: 9px;
    font-size: 10pt; font-weight: 900; letter-spacing: 2px;
}
QPushButton#SecureButton:hover {
    color: #07120c; background: #00ff66;
}
QPushButton#SecureButton:pressed { background: #00b84a; }
QLabel#SupportLink { color: #00f3ff; }
QLabel#SupportLink a { color: #00f3ff; text-decoration: none; }
"""


class NinjaWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setFixedSize(700, 550)
        self.setStyleSheet(APP_STYLE)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 15, 18, 15)
        root.setSpacing(14)

        top = QHBoxLayout()
        brand_col = QVBoxLayout()
        brand = QLabel("UGC 〆 NINJA")
        brand.setObjectName("Brand")
        version = QLabel("iOS PROFESSIONAL SUITE  /  v1.0")
        version.setObjectName("Version")
        brand_col.addWidget(brand)
        brand_col.addWidget(version)
        top.addLayout(brand_col)
        top.addStretch()
        badge = QLabel("● SYSTEM ONLINE")
        badge.setStyleSheet(
            "color:#00ff66; border:1px solid #17663a; background:#10251a;"
            "border-radius:8px; padding:7px 10px; font-size:8pt; font-weight:800;"
        )
        top.addWidget(badge, alignment=Qt.AlignVCenter)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.device_tab = DeviceTab()
        self.locked_tab = LockedTab()
        self.tabs.addTab(self.device_tab, "01  DEVICE DIAGNOSTICS")
        self.tabs.addTab(self.locked_tab, "02  iCLOUD MODULE")
        root.addWidget(self.tabs, 1)

        footer = QLabel("UGC NINJA  •  LOCAL DEVICE DIAGNOSTICS  •  NO ACTIVATION-LOCK BYPASS")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color:#405761; font-size:7pt; letter-spacing:1px;")
        root.addWidget(footer)
        self.setCentralWidget(central)


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setFont(QFont("Segoe UI", 9))
    window = NinjaWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
