"""PySide6 desktop shell and launcher controller."""

from __future__ import annotations

import ctypes
import signal
import sys
import threading
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QUrlQuery,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_USER_MODEL_ID, WINDOW_TITLE
from .config import (
    BRAND_ICON,
    BRAND_SPLASH,
    LOG_DIR,
    LaunchConfig,
    LaunchError,
    validate_environment,
)
from .services import ServiceManager, patron_state, ui_theme, wait_for_services

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "app": "#0B0D0F",
        "surface": "#15191D",
        "surface2": "#1B2025",
        "border": "#292F35",
        "text": "#E8EAED",
        "muted": "#A0A8B1",
        "accent": "#4D9AFF",
        "accent_ink": "#06101F",
        "track": "#22282E",
        "error": "#E46B70",
    },
    "light": {
        "app": "#F4F6F8",
        "surface": "#FFFFFF",
        "surface2": "#F8FAFC",
        "border": "#E2E7ED",
        "text": "#171B20",
        "muted": "#59636F",
        "accent": "#2F6FDB",
        "accent_ink": "#FFFFFF",
        "track": "#E7ECF2",
        "error": "#D64550",
    },
}

SETTINGS_ORG = "KBMTI"
SETTINGS_APP = "KBMTI"
THEME_KEY = "theme"


def normalize_theme(value: object) -> str:
    return "light" if value == "light" else "dark"


def theme_colors(theme: str) -> dict[str, str]:
    return THEMES[normalize_theme(theme)]


def set_windows_app_user_model_id() -> None:
    """Give the process a stable taskbar identity before any window exists."""

    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        # A missing shell API must not prevent the application from starting.
        pass


def brand_icon() -> QIcon:
    icon = QIcon()
    if BRAND_ICON.is_file():
        icon.addFile(str(BRAND_ICON))
    if BRAND_SPLASH.is_file():
        icon.addFile(str(BRAND_SPLASH))
    return icon


def apply_palette(app: QApplication, theme: str) -> None:
    colors = theme_colors(theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["app"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["surface2"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["accent_ink"]))
    app.setPalette(palette)


class LaunchController(QObject):
    """Owns the child services and reports readiness to the window."""

    status = Signal(str)
    ready = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, config: LaunchConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.manager: ServiceManager | None = None
        self._thread: threading.Thread | None = None
        self._closing = False

    @property
    def logs(self) -> Path:
        return LOG_DIR

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="kbmti-launch", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.status.emit("Checking application configuration…")
            validate_environment(self.config)
            self.status.emit("Starting backend services…")
            self.manager = ServiceManager(self.config)
            self.manager.start()
            self.status.emit("Starting frontend server…")
            wait_for_services(self.manager, on_status=self.status.emit)
            if self._closing:
                return
            self.status.emit("Connecting to market data…")
            state = patron_state(self.config)
            if state:
                label = str(state.get("state", "unknown")).lower()
                model = state.get("model_id", "PATRON")
                self.status.emit(f"{model} {label} · preparing workspace")
            else:
                self.status.emit("Market services ready · preparing workspace")
            theme = ui_theme(self.config)
            self.ready.emit(self.config.frontend_url, theme)
        except LaunchError as exc:
            if not self._closing:
                self.failed.emit(str(exc), self._log_tail())
        except Exception as exc:  # noqa: BLE001 - startup must surface real failures
            if not self._closing:
                self.failed.emit(f"Unexpected launcher error: {exc}", self._log_tail())

    def _log_tail(self) -> str:
        if not self.manager:
            return ""
        parts: list[str] = []
        for service in self.manager.services():
            try:
                text = service.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            tail = "\n".join(text.splitlines()[-60:])
            if tail:
                parts.append(f"--- {service.name} · {service.log_path} ---\n{tail}")
        return "\n\n".join(parts)

    def stop(self) -> None:
        self._closing = True
        if self.manager:
            self.manager.stop()


class LocalPage(QWebEnginePage):
    """Allow navigation only inside the local frontend origin."""

    def __init__(self, profile: QWebEngineProfile, origin: QUrl, parent=None) -> None:
        super().__init__(profile, parent)
        self._origin = origin

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if url.scheme() in {"about", "data", "blob"}:
            return True
        if url.scheme() not in {"http", "https"}:
            return False
        return (
            url.host() == self._origin.host()
            and url.port(defaultPort=-1) == self._origin.port(defaultPort=-1)
        )


class LoadingPage(QWidget):
    """Branded startup surface driven by the launcher's real stage signals."""

    def __init__(self, theme: str = "dark", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("loadingPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = normalize_theme(theme)
        self._animated = False
        self._build()
        self.set_theme(self._theme)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(0)
        layout.addStretch(1)

        brand = QWidget(self)
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)

        self._icon_label = QLabel(brand)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = self._brand_pixmap()
        if not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        brand_layout.addWidget(self._icon_label)
        brand_layout.addSpacing(22)

        self._wordmark = QLabel(APP_NAME, brand)
        self._wordmark.setObjectName("wordmark")
        self._wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wordmark_font = QFont("Segoe UI", 25)
        wordmark_font.setWeight(QFont.Weight.DemiBold)
        wordmark_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 8)
        self._wordmark.setFont(wordmark_font)
        brand_layout.addWidget(self._wordmark)
        brand_layout.addSpacing(7)

        self._tagline = QLabel("AI-Powered Market Intelligence", brand)
        self._tagline.setObjectName("tagline")
        self._tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline_font = QFont("Segoe UI", 10)
        tagline_font.setWeight(QFont.Weight.Medium)
        tagline_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
        self._tagline.setFont(tagline_font)
        brand_layout.addWidget(self._tagline)

        layout.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(38)

        self._status = QLabel("Initializing KBMTI…")
        self._status.setObjectName("status")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setAccessibleName("Initializing KBMTI")
        layout.addWidget(self._status)
        layout.addSpacing(13)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(220, 3)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self._progress)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(18)

        self._hint = QLabel("LOCAL WORKSTATION · READ-ONLY MARKET INTELLIGENCE")
        self._hint.setObjectName("hint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_font = QFont("Segoe UI", 8)
        hint_font.setWeight(QFont.Weight.Medium)
        hint_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        self._hint.setFont(hint_font)
        layout.addWidget(self._hint)
        layout.addStretch(2)

        self._effect = QGraphicsOpacityEffect(brand)
        brand.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(520)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _brand_pixmap(self) -> QPixmap:
        path = BRAND_SPLASH if BRAND_SPLASH.is_file() else BRAND_ICON
        if not path.is_file():
            return QPixmap()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            88,
            88,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._animated:
            self._animated = True
            QTimer.singleShot(0, self._fade.start)

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setAccessibleName(text)

    def set_theme(self, theme: str) -> None:
        self._theme = normalize_theme(theme)
        colors = theme_colors(self._theme)
        self.setStyleSheet(
            f"QWidget#loadingPage {{ background: {colors['app']}; }}"
            f"QLabel#wordmark {{ color: {colors['text']}; }}"
            f"QLabel#tagline {{ color: {colors['muted']}; }}"
            f"QLabel#status {{ color: {colors['muted']}; font-family: 'Segoe UI'; font-size: 11px; }}"
            f"QLabel#hint {{ color: {colors['muted']}; }}"
            f"QProgressBar {{ background: {colors['track']}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 1px; }}"
        )


class ErrorPage(QWidget):
    def __init__(self, theme: str = "dark", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("errorPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = normalize_theme(theme)
        self._on_retry = None
        self._on_quit = None
        self._build()
        self.set_theme(self._theme)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(10)

        self._title = QLabel("KBMTI could not start", self)
        self._title.setObjectName("errorTitle")
        layout.addWidget(self._title)

        self._message = QLabel(self)
        self._message.setObjectName("errorMessage")
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        self._hint = QLabel(
            "The failing service is identified below. Fix the cause, then retry. "
            "Logs stay on this machine.",
            self,
        )
        self._hint.setObjectName("errorHint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self.detail = QTextEdit(self)
        self.detail.setObjectName("errorDetail")
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail, 1)

        row = QHBoxLayout()
        logs = QPushButton("Open logs", self)
        logs.clicked.connect(self._open_logs)
        retry = QPushButton("Retry", self)
        retry.setObjectName("retryButton")
        retry.clicked.connect(lambda: self._on_retry and self._on_retry())
        quit_button = QPushButton("Quit", self)
        quit_button.clicked.connect(lambda: self._on_quit and self._on_quit())
        for button in (logs, retry, quit_button):
            row.addWidget(button)
        row.insertStretch(0, 1)
        layout.addLayout(row)

    def set_theme(self, theme: str) -> None:
        self._theme = normalize_theme(theme)
        colors = theme_colors(self._theme)
        self.setStyleSheet(
            f"QWidget#errorPage {{ background: {colors['app']}; }}"
            f"QLabel#errorTitle {{ color: {colors['error']}; font-size: 18px; font-weight: 600; }}"
            f"QLabel#errorMessage {{ color: {colors['text']}; font-size: 11px; }}"
            f"QLabel#errorHint {{ color: {colors['muted']}; font-size: 10px; }}"
            "QTextEdit#errorDetail {"
            f"background: {colors['surface']}; color: {colors['muted']};"
            f"border: 1px solid {colors['border']}; border-radius: 6px;"
            "font-family: Consolas, monospace; font-size: 10px; padding: 8px;"
            "}"
            "QPushButton {"
            f"background: {colors['surface']}; color: {colors['text']};"
            f"border: 1px solid {colors['border']}; border-radius: 5px;"
            "padding: 6px 15px; font-size: 11px;"
            "}"
            f"QPushButton:hover {{ border-color: {colors['accent']}; }}"
            "QPushButton#retryButton {"
            f"background: {colors['accent']}; color: {colors['accent_ink']};"
            f"border: 1px solid {colors['accent']};"
            "}"
        )

    def show_error(self, message: str, detail: str, retry, quit_callback) -> None:
        self._message.setText(message)
        self.detail.setPlainText(detail or "No log output was produced.")
        self._on_retry = retry
        self._on_quit = quit_callback

    def _open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))


class MainWindow(QMainWindow):
    def __init__(self, config: LaunchConfig, controller: LaunchController) -> None:
        super().__init__()
        self.config = config
        self.controller = controller
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._theme = normalize_theme(self._settings.value(THEME_KEY, "dark"))
        self._awaiting_app = False
        self._screenshot_path = config.screenshot

        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(brand_icon())
        if config.window_size:
            width, height = config.window_size
        else:
            screen = QApplication.primaryScreen()
            available = screen.availableGeometry() if screen else None
            width = min(1600, (available.width() - 80) if available else 1600)
            height = min(960, (available.height() - 80) if available else 960)
        self.resize(max(1100, width), max(680, height))
        self.setMinimumSize(QSize(1100, 680))

        self.stack = QStackedWidget()
        self.loading = LoadingPage(self._theme)
        self.error_page = ErrorPage(self._theme)
        self.web = QWebEngineView()
        self._configure_web()
        self.stack.addWidget(self.loading)
        self.stack.addWidget(self.web)
        self.stack.addWidget(self.error_page)
        self.setCentralWidget(self.stack)

        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(1500)
        self._theme_timer.timeout.connect(self._sync_theme)

        self.controller.status.connect(self.loading.set_status)
        self.controller.ready.connect(self._show_app)
        self.controller.failed.connect(self._show_error)
        self.web.loadFinished.connect(self._load_finished)
        self._apply_theme(self._theme, persist=False)

        for sequence, slot in (
            ("Ctrl+Q", QApplication.quit),
            ("F5", self.web.reload),
            ("Ctrl+R", self.web.reload),
        ):
            QShortcut(QKeySequence(sequence), self).activated.connect(slot)
        if config.devtools:
            QShortcut(QKeySequence("F12"), self).activated.connect(self._toggle_devtools)

    def _configure_web(self) -> None:
        profile = QWebEngineProfile("kbmti-desktop", self.web)
        profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        page = LocalPage(profile, QUrl(self.config.frontend_url), self.web)
        page.setBackgroundColor(QColor(theme_colors(self._theme)["app"]))
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, False)
        self.web.setPage(page)
        self.web.setAcceptDrops(False)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def _apply_theme(self, theme: str, persist: bool = True) -> None:
        self._theme = normalize_theme(theme)
        colors = theme_colors(self._theme)
        self.loading.set_theme(self._theme)
        self.error_page.set_theme(self._theme)
        page = self.web.page()
        if page is not None:
            page.setBackgroundColor(QColor(colors["app"]))
        self.setStyleSheet(f"QMainWindow {{ background: {colors['app']}; }}")
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_palette(app, self._theme)
        if persist:
            self._settings.setValue(THEME_KEY, self._theme)
            self._settings.sync()

    def _show_app(self, url: str, theme: str) -> None:
        self._apply_theme(theme, persist=True)
        self.loading.set_status("Preparing dashboard…")
        target = QUrl(url)
        query = QUrlQuery()
        query.addQueryItem("theme", self._theme)
        target.setQuery(query)
        self._awaiting_app = True
        # Keep the branded surface visible until the first paint completes so
        # neither a white nor a black frame flashes behind the dashboard.
        self.web.load(target)

    def _load_finished(self, ok: bool) -> None:
        if not self._awaiting_app:
            return
        self._awaiting_app = False
        if ok:
            self.stack.setCurrentWidget(self.web)
            if not self._theme_timer.isActive():
                self._theme_timer.start()
            if self._screenshot_path:
                QTimer.singleShot(800, self._wait_for_ui)
            return
        self._show_error(
            "The dashboard did not finish loading.",
            "Check the frontend log for a Vite or React startup failure, then retry.",
            self._retry,
            QApplication.quit,
        )

    def _sync_theme(self) -> None:
        self.web.page().runJavaScript(
            "window.localStorage.getItem('kbmti.theme') || ''",
            self._theme_from_web,
        )

    def _theme_from_web(self, value: object) -> None:
        if not isinstance(value, str) or not value:
            return
        theme = normalize_theme(value)
        if theme != self._theme:
            self._apply_theme(theme, persist=True)

    def _show_error(self, message: str, detail: str) -> None:
        self._theme_timer.stop()
        self._awaiting_app = False
        self.error_page.show_error(message, detail, self._retry, QApplication.quit)
        self.stack.setCurrentWidget(self.error_page)

    def _retry(self) -> None:
        self._theme_timer.stop()
        self._awaiting_app = False
        self.controller.stop()
        self.loading.set_status("Restarting local services…")
        self.stack.setCurrentWidget(self.loading)
        QTimer.singleShot(300, self.controller.start)

    def _wait_for_ui(self, attempt: int = 0) -> None:
        def inspect(text: str) -> None:
            ready = (
                bool(text)
                and "Connecting to the local backend" not in text
                and "PATRON LOADING" not in text
                and "MODEL NOT READY" not in text
            )
            if ready or attempt >= 60:
                QTimer.singleShot(800, self._capture_screenshot)
            else:
                QTimer.singleShot(500, lambda: self._wait_for_ui(attempt + 1))

        self.web.page().runJavaScript("document.body.innerText", inspect)

    def _capture_screenshot(self) -> None:
        path = Path(self._screenshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.grab().save(str(path))
        print(f"Screenshot saved to {path}")
        QApplication.quit()

    def _toggle_devtools(self) -> None:
        view = getattr(self, "_devtools_view", None)
        if view is None:
            self._devtools_view = QWebEngineView()
            self._devtools_view.setWindowTitle("KBMTI DevTools")
            self._devtools_view.setWindowIcon(brand_icon())
            self._devtools_view.resize(1100, 760)
            self.web.page().setDevToolsPage(self._devtools_view.page())
            view = self._devtools_view
        view.show()
        view.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._theme_timer.stop()
        self.controller.stop()
        event.accept()


def run_desktop(config: LaunchConfig) -> int:
    # The AppUserModelID must be set before QApplication and the first window
    # so Windows groups the process under the KBMTI taskbar icon.
    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    signal.signal(signal.SIGINT, lambda *_: QApplication.quit())
    # Qt owns the event loop, so poll Python signals to make Ctrl+C responsive.
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(400)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(SETTINGS_ORG)
    app.setWindowIcon(brand_icon())

    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    theme = normalize_theme(settings.value(THEME_KEY, "dark"))
    apply_palette(app, theme)

    controller = LaunchController(config)
    window = MainWindow(config, controller)
    app.aboutToQuit.connect(controller.stop)
    window.show()
    controller.start()
    return int(app.exec())
