import cv2
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.camera import Camera
from app.websocket_sender import SessionWebSocketClient

JOINT_CAPTIONS = ("1 · Obrót", "2 · Ramię", "3 · Łokieć", "4 · Nadgarstek", "5 · Przechył chwytaka", "6 · Chwytak")
PREVIEW_PLACEHOLDER = "Kamera jest wyłączona\nWybierz źródło obrazu i uruchom kamerę."


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.cap = None
        self.camera = None
        self.session_client = None
        self.loading = False
        self.timer = QTimer(self)
        self.timer.setInterval(30)  # Set the interval to 30 milliseconds (approx. 33 FPS)
        self.timer.timeout.connect(self.update_frame)
        self.init_ui()
        self.init_style()
        self.set_status("Wpisz kod sesji lub uruchom kamerę lokalną, aby utworzyć nową sesję.")

    def init_ui(self):
        self.setObjectName("root")
        self.setWindowTitle("Sterowanie manipulatorem — aplikacja sterująca")
        self.resize(1180, 800)
        self.setMinimumSize(980, 720)

        master = QHBoxLayout(self)
        master.setContentsMargins(24, 24, 24, 24)
        master.setSpacing(20)

        master.addWidget(self._build_controls(), 34)
        master.addWidget(self._build_preview(), 66)

    def _build_controls(self):
        frame = QFrame(self)
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        eyebrow = QLabel("APLIKACJA STERUJĄCA")
        eyebrow.setObjectName("eyebrow")
        self._set_letter_spacing(eyebrow, 1.5)
        title = QLabel("Analiza gestów dłoni")
        title.setObjectName("title")
        subtitle = QLabel("Rozpoznaje położenie dłoni i przekazuje kąty przegubów do modelu manipulatora.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)

        layout.addWidget(eyebrow)
        layout.addSpacing(6)
        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        layout.addWidget(self._divider())
        layout.addSpacing(18)

        layout.addWidget(self._field_label("Kod sesji"))
        layout.addSpacing(6)
        self.code_input = QLineEdit()
        self.code_input.setObjectName("code_input")
        self.code_input.setPlaceholderText("np. 7K4M-P2QX")
        self.code_input.setMaxLength(9)
        self._set_letter_spacing(self.code_input, 2)
        self.code_input.textEdited.connect(lambda text: self.code_input.setText(text.upper()))
        layout.addWidget(self.code_input)
        layout.addSpacing(6)
        code_hint = QLabel("Przy kamerze lokalnej możesz zostawić puste — powstanie nowa sesja.")
        code_hint.setObjectName("hint")
        code_hint.setWordWrap(True)
        layout.addWidget(code_hint)
        layout.addSpacing(14)

        layout.addWidget(self._field_label("Źródło obrazu"))
        layout.addSpacing(6)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Kamera lokalna", "local_camera")
        self.source_combo.addItem("Kamera webowa (smartfon)", "remote_camera")
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        layout.addWidget(self.source_combo)
        layout.addSpacing(18)

        self.start_camera_button = QPushButton()
        self.start_camera_button.setObjectName("primary")
        self.start_camera_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_camera_button.clicked.connect(self.start_camera)
        self.close_camera_button = QPushButton("Zatrzymaj kamerę")
        self.close_camera_button.setObjectName("secondary")
        self.close_camera_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_camera_button.clicked.connect(self.close_camera)
        self.close_camera_button.setEnabled(False)
        self._source_changed()

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.start_camera_button, 3)
        buttons.addWidget(self.close_camera_button, 2)
        layout.addLayout(buttons)
        layout.addSpacing(14)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addSpacing(18)
        layout.addWidget(self._divider())
        layout.addSpacing(18)

        layout.addWidget(self._field_label("Pozycja dłoni"))
        layout.addSpacing(8)
        position_grid = QGridLayout()
        position_grid.setSpacing(8)
        self.position_values = []
        for column, axis in enumerate(("X", "Y", "Z")):
            cell, value = self._data_cell(axis)
            position_grid.addWidget(cell, 0, column)
            self.position_values.append(value)
        layout.addLayout(position_grid)
        layout.addSpacing(14)

        layout.addWidget(self._field_label("Kąty przegubów"))
        layout.addSpacing(8)
        angles_grid = QGridLayout()
        angles_grid.setSpacing(8)
        self.angle_values = []
        for index, caption in enumerate(JOINT_CAPTIONS):
            cell, value = self._data_cell(caption)
            angles_grid.addWidget(cell, index // 3, index % 3)
            self.angle_values.append(value)
        layout.addLayout(angles_grid)
        layout.addStretch()

        self._reset_tracking_data()
        return frame

    def _build_preview(self):
        frame = QFrame(self)
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(20, 14, 20, 14)
        preview_title = QLabel("Podgląd na żywo")
        preview_title.setObjectName("topbar_title")
        self.camera_state = QLabel()
        self.camera_state.setObjectName("camera_state")
        self._set_letter_spacing(self.camera_state, 1)
        topbar_layout.addWidget(preview_title)
        topbar_layout.addStretch()
        topbar_layout.addWidget(self.camera_state)

        self.image_label = QLabel(PREVIEW_PLACEHOLDER)
        self.image_label.setObjectName("image_label")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 450)

        layout.addWidget(topbar)
        layout.addWidget(self.image_label, 1)
        self._set_camera_state(False)
        return frame

    @staticmethod
    def _set_letter_spacing(widget, spacing):
        font = widget.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        widget.setFont(font)

    @staticmethod
    def _field_label(text):
        label = QLabel(text)
        label.setObjectName("field_label")
        return label

    @staticmethod
    def _divider():
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _data_cell(caption):
        cell = QFrame()
        cell.setObjectName("data_cell")
        cell.setMinimumHeight(52)
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(10, 8, 10, 8)
        cell_layout.setSpacing(2)
        caption_label = QLabel(caption)
        caption_label.setObjectName("data_caption")
        value = QLabel("—")
        value.setObjectName("data_value")
        cell_layout.addWidget(caption_label)
        cell_layout.addWidget(value)
        return cell, value

    def init_style(self):
        # Paleta zgodna z aplikacją webową (web-cam/frontend/src/styles/global.css).
        self.setStyleSheet("""
            QWidget {
                color: #f1f4f8;
                font-family: "Inter", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QWidget#root {
                background: #0e141f;
            }

            QFrame#panel {
                background: #141c2a;
                border: 1px solid #263244;
                border-radius: 14px;
            }
            QFrame#divider {
                background: #263244;
                border: 0;
            }

            QLabel#eyebrow {
                color: #8ab4f0;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#title {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#muted {
                color: #94a1b4;
            }
            QLabel#field_label {
                color: #94a1b4;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#hint {
                color: #6b778a;
                font-size: 11px;
            }

            QLineEdit, QComboBox {
                min-height: 22px;
                padding: 8px 12px;
                border: 1px solid #36455c;
                border-radius: 8px;
                background: #0e141f;
                selection-background-color: #3a6fcf;
            }
            QLineEdit#code_input {
                font-size: 16px;
                font-weight: 700;
                color: #8ab4f0;
            }
            QLineEdit:focus, QComboBox:focus, QComboBox:on {
                border-color: #8ab4f0;
            }
            QLineEdit[readOnly="true"] {
                background: #1a2434;
            }
            QComboBox::drop-down {
                border: 0;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                padding: 4px;
                border: 1px solid #36455c;
                background: #1a2434;
                color: #f1f4f8;
                selection-background-color: rgba(138, 180, 240, 0.18);
                outline: 0;
            }

            QPushButton {
                min-height: 22px;
                padding: 10px 14px;
                border: 1px solid transparent;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton#primary {
                background: #3a6fcf;
                color: white;
            }
            QPushButton#primary:hover {
                background: #315fb3;
            }
            QPushButton#secondary {
                background: #1a2434;
                border-color: #36455c;
                color: #f1f4f8;
            }
            QPushButton#secondary:hover {
                background: #1f2a3c;
            }
            QPushButton:disabled, QPushButton#primary:disabled, QPushButton#secondary:disabled,
            QComboBox:disabled {
                background: #1f2938;
                border-color: #1f2938;
                color: #6b778a;
            }

            QLabel#status {
                padding: 10px 12px;
                border: 1px solid #263244;
                border-left: 3px solid #36455c;
                border-radius: 8px;
                background: rgba(31, 42, 60, 0.45);
                color: #b6c2d3;
                font-size: 12px;
            }
            QLabel#status[kind="loading"] {
                border-left-color: #f59e0b;
                color: #f3d9a8;
            }
            QLabel#status[kind="ready"] {
                border-left-color: #4fc49a;
                color: #b8ead6;
            }
            QLabel#status[kind="error"] {
                border-color: rgba(220, 76, 76, 0.35);
                border-left-color: #dc4c4c;
                background: rgba(127, 29, 29, 0.2);
                color: #fecaca;
            }

            QFrame#data_cell {
                border: 1px solid #263244;
                border-radius: 8px;
                background: rgba(31, 42, 60, 0.45);
            }
            QLabel#data_caption {
                color: #6b778a;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#data_value {
                color: #8ab4f0;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 14px;
                font-weight: 600;
            }

            QFrame#topbar {
                border: 0;
                border-bottom: 1px solid #263244;
                border-radius: 0;
                background: transparent;
            }
            QLabel#topbar_title {
                color: #cbd5e1;
                font-weight: 600;
            }
            QLabel#camera_state {
                color: #94a1b4;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#camera_state[active="true"] {
                color: #4fc49a;
            }
            QLabel#image_label {
                background: #0b111b;
                border-bottom-left-radius: 14px;
                border-bottom-right-radius: 14px;
                color: #94a1b4;
                font-size: 14px;
            }
        """)

    @staticmethod
    def _repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _source_changed(self):
        is_local = self.source_combo.currentData() == "local_camera"
        self.start_camera_button.setText("Uruchom kamerę lokalną" if is_local else "Odbieraj obraz z telefonu")

    def set_status(self, text, kind="neutral"):
        kind = kind.lower()
        if self.status.text() == text and self.status.property("kind") == kind:
            return
        self.status.setText(text)
        self.status.setProperty("kind", kind)
        self._repolish(self.status)

    def _set_camera_state(self, active):
        self.camera_state.setText("AKTYWNA" if active else "NIEAKTYWNA")
        self.camera_state.setProperty("active", active)
        self._repolish(self.camera_state)

    def start_camera(self):
        if self.loading or self.timer.isActive():
            return
        code = self.code_input.text().strip()
        source = self.source_combo.currentData()
        if not code and source == "remote_camera":
            self.set_status("Wpisz kod sesji wyświetlony na stronie transmisji wideo.", "error")
            return
        self.loading = True
        self._set_controls_enabled(False)
        self.set_status("Łączenie z serwerem…", "loading")
        QTimer.singleShot(0, self._initialize_source)

    def _initialize_source(self):
        source = self.source_combo.currentData()
        try:
            if self.session_client is None:
                self.session_client = SessionWebSocketClient()
            self.session_client.start(self.code_input.text().strip(), source)

            if source == "local_camera":
                camera_index = 0  # Default camera index
                cap = cv2.VideoCapture(camera_index)
                if not cap.isOpened():
                    raise Exception("Nie udało się otworzyć kamery lokalnej.")
                self.cap = cap
                self.camera = Camera(QImage, cap)
            else:
                self.camera = Camera(QImage, None)  # For remote camera, we don't use cv2.VideoCapture

            self.close_camera_button.setEnabled(True)
            self.timer.start()
        except Exception as e:
            self._release_resources(stop_client=True)
            self.loading = False
            self._set_controls_enabled(True)
            self.set_status(f"Błąd: {e}", "error")

    def update_frame(self):
        try:
            if self.session_client and getattr(self.session_client, "session_code", None) and not self.code_input.text():
                self.code_input.setText(self.session_client.session_code)

            is_connected = bool(self.session_client and getattr(self.session_client, "connected", False))
            last_error = getattr(self.session_client, "last_error", None) if self.session_client else None

            if self.source_combo.currentData() == "local_camera":
                qimage, tracking_data = self.camera.run_camera()
                if qimage is None:
                    raise RuntimeError("Nie udało się odczytać klatki z kamery lokalnej.")
            else:
                if not self.session_client:
                    self.set_status("Brak połączenia z serwerem sesji.", "error")
                    return

                jpeg = self.session_client.get_latest_frame()
                if jpeg is None:
                    if last_error and not is_connected:
                        self.set_status(last_error, "error")
                    elif is_connected:
                        self.set_status("Połączono. Oczekiwanie na obraz z aplikacji webowej…", "ready")
                    else:
                        self.set_status("Łączenie z serwerem…", "loading")
                    return

                qimage, tracking_data = self.camera.process_jpeg(jpeg)
                if qimage is None:
                    return

            self.loading = False
            self._set_camera_state(True)
            if is_connected:
                self.set_status("Kamera aktywna — sesja połączona.", "ready")
            elif last_error:
                self.set_status(f"Kamera aktywna, brak połączenia z sesją: {last_error}", "error")
            else:
                self.set_status("Kamera aktywna — łączenie z sesją…", "loading")

            pixmap = QPixmap.fromImage(qimage)
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

            self._update_tracking_data(tracking_data, is_connected)

        except Exception as error:
            self.close_camera(status_text=str(error), error=True)

    def _reset_tracking_data(self):
        for label in (*self.position_values, *self.angle_values):
            label.setText("—")

    def _update_tracking_data(self, tracking_data, is_connected):
        if tracking_data is None:
            self._reset_tracking_data()
            return

        x, y, z = tracking_data["position"].center_pixels
        angles = tracking_data["angles"]

        for label, value in zip(self.position_values, (f"{x:.0f} px", f"{y:.0f} px", f"{z:.2f}")):
            label.setText(value)
        for label, angle in zip(self.angle_values, angles):
            label.setText(f"{angle:.1f}°")

        if is_connected:
            try:
                self.session_client.send_angles(angles)
            except Exception as error:
                self.set_status(f"Kąty obliczone, ale nie udało się ich wysłać: {error}", "error")

    def close_camera(self, checked=False, status_text=None, error=False):
        del checked
        self._release_resources(stop_client=True)
        self.loading = False
        self._set_controls_enabled(True)
        self.close_camera_button.setEnabled(False)

        self.image_label.clear()
        self.image_label.setText(PREVIEW_PLACEHOLDER)
        self._set_camera_state(False)
        self._reset_tracking_data()

        self.set_status(
            status_text or "Kamera zatrzymana.",
            "error" if error else "neutral",
        )

    def _set_controls_enabled(self, enabled):
        self.start_camera_button.setEnabled(enabled)
        # Pole kodu pozostaje tylko do odczytu, aby można było skopiować kod sesji.
        self.code_input.setReadOnly(not enabled)
        self._repolish(self.code_input)
        self.source_combo.setEnabled(enabled)

    def _release_resources(self, stop_client=False):
        self.timer.stop()
        if self.camera is not None:
            self.camera.close()
            self.camera = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if stop_client and self.session_client is not None:
            self.session_client.stop()
            self.session_client = None

    def closeEvent(self, event):
        self._release_resources(stop_client=True)
        super().closeEvent(event)
