import os

import cv2
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QImage, QPixmap
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

    def init_ui(self):
        self.setWindowTitle("")
        self.resize(1120, 740)
        self.setMinimumSize(900, 620)

        master = QHBoxLayout(self)
        master.setContentsMargins(24, 24, 24, 24)
        master.setSpacing(24)

        controls_frame = QFrame(self)
        controls_frame.setObjectName("controls_frame")
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(24, 24, 24, 24)
        controls_layout.setSpacing(24)

        title = QLabel("Hand Gesture Recognition")
        title.setObjectName("title")
        subtitle = QLabel("Real-time hand gesture recognition")
        subtitle.setObjectName("subtitle")

        code_label = QLabel("Session Code:")
        code_label.setObjectName("code_label")
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("7K4M-P2QX")
        self.code_input.setMaxLength(9)

        source_label = QLabel("Video Source:")
        source_label.setObjectName("source_label")
        self.source_combo = QComboBox()
        self.source_combo.addItem("Local Camera", "local_camera")
        self.source_combo.addItem("Remote Camera", "remote_camera")
        self.source_combo.currentIndexChanged.connect(self._source_changed)

        self.start_camera_button = QPushButton("Start Camera")
        self.start_camera_button.setObjectName("start_camera_button")
        self.start_camera_button.clicked.connect(self.start_camera)
        self.close_camera_button = QPushButton("Close Camera")
        self.close_camera_button.setObjectName("close_camera_button")
        self.close_camera_button.clicked.connect(self.close_camera)
        self.close_camera_button.setEnabled(False)

        self.status = QLabel("Waiting for session code...")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)

        data_title = QLabel("Data:")
        data_title.setObjectName("data_title")
        self.position_label = QLabel("X: -, Y: -, Z: -")
        self.position_label.setObjectName("position_label")
        self.angles_label = QLabel("Angles: -, -, -, -, -, -")
        self.angles_label.setObjectName("angles_label")
        self.angles_label.setWordWrap(True)

        for widget in (
            title,
            subtitle,
            code_label,
            self.code_input,
            source_label,
            self.source_combo,
            self.start_camera_button,
            self.close_camera_button,
            self.status,
            data_title,
            self.position_label,
            self.angles_label,
        ):
            controls_layout.addWidget(widget)
        controls_layout.addStretch()

        preview_frame = QFrame(self)
        preview_frame.setObjectName("preview_frame")
        preview_layout = QGridLayout(preview_frame)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self.image_label = QLabel("Camera Preview")
        self.image_label.setObjectName("image_label")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 450)
        preview_layout.addWidget(self.image_label, 0, 0)

        master.addWidget(controls_frame, 34)
        master.addWidget(preview_frame, 66)

    def init_style(self):
        self.setStyleSheet("""
            QWidget { 
                color: #e2e8f0; 
                font-family: "Segoe UI", sans-serif; 
            }
            
            /* Panele boczne */
            QFrame#controls_frame, QFrame#preview_frame {
                background: #172033; 
                border: 1px solid #26344d; 
                border-radius: 14px;
            }
            
            /* Nagłówki i podtytuły */
            QLabel#title { 
                font-size: 24px; 
                font-weight: 700; 
                color: #f8fafc; 
            }
            QLabel#subtitle { 
                font-size: 13px; 
                color: #94a3b8; 
                margin-bottom: 4px; 
            }
            
            /* Etykiety pól i sekcji */
            QLabel#code_label, QLabel#source_label, QLabel#data_title { 
                font-size: 13px; 
                font-weight: 600; 
                color: #cbd5e1;
            }
            QLabel#data_title {
                font-size: 15px;
                color: #f8fafc;
                margin-top: 8px;
            }

            /* Pola tekstowe i listy rozwijane */
            QLineEdit, QComboBox {
                border: 1px solid #334155; 
                border-radius: 7px;
                padding: 8px 12px; 
                font-size: 13px; 
                color: #f8fafc;
                selection-background-color: #2563eb;
            }
            QLineEdit:focus, QComboBox:focus { 
                border-color: #60a5fa; 
            }
            QComboBox QAbstractItemView { 
                background: #172033; 
                selection-background-color: #2563eb; 
                color: #f8fafc;
                border: 1px solid #334155;
            }

            /* Przyciski */
            QPushButton {
                border: 0; 
                border-radius: 7px; 
                padding: 10px 16px;
                font-size: 13px; 
                font-weight: 600;
            }
            QPushButton#start_camera_button { 
                background: #2563eb; 
                color: white; 
            }
            QPushButton#start_camera_button:hover { 
                background: #1d4ed8; 
            }
            QPushButton#close_camera_button { 
                background: #334155; 
                color: #e2e8f0; 
            }
            QPushButton#close_camera_button:hover { 
                background: #475569; 
            }
            QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {
                background: #1e293b; 
                color: #64748b;
                border-color: #1e293b;
            }

            /* Pole ze stanem (Status) */
            QLabel#status {
                border: 1px solid #26344d;
                border-radius: 7px; 
                padding: 10px; 
                font-size: 12px;
                color: #94a3b8;
            }

            /* Wyświetlanie danych pozycji i kątów */
            QLabel#position_label, QLabel#angles_label {
                border: 1px solid #26344d;
                border-radius: 7px; 
                padding: 4px 4px; 
                color: #38bdf8;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 8px;
            }

            /* Podgląd kamery */
            QLabel#image_label { 
                color: #64748b; 
                font-size: 16px; 
                font-weight: 500;
                border-radius: 8px;
            }
        """)

    def _source_changed(self):
        is_local = self.source_combo.currentData() == "local_camera"
        self.start_camera_button.setText("Start Local Camera" if is_local else "Start Remote Camera")

    def set_status(self, text, kind="Neutral"):
        self.status.setText(text)
        self.status.setObjectName(f"status_{kind.lower()}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def start_camera(self):
        if self.loading or self.timer.isActive():
            return
        code = self.code_input.text().strip()
        source = self.source_combo.currentData()
        if not code and source == "remote_camera":
            self.set_status("Session code is required for remote camera.", "Error")
            return
        self.loading = True
        self.set_status("Connecting...", "Loading")
        self._set_controls_enabled(False)
        self.set_status(
            "Connected. Starting camera..." if source == "local_camera" else "Connected. Starting video...",
            "Loading",
        )
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
                    raise Exception("Failed to open camera.")
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
            self.set_status(f"Error: {str(e)}", "Error")

    def update_frame(self):
        try:
            if self.session_client and getattr(self.session_client, "session_code", None) and not self.code_input.text():
                self.code_input.setText(self.session_client.session_code)

            if self.session_client and getattr(self.session_client, "last_error", None) and not getattr(self.session_client, "connected", False):
                self.set_status(self.session_client.last_error, "Error")

            if self.source_combo.currentData() == "local_camera":
                qimage, tracking_data = self.camera.run_camera()
                if qimage is None:
                    raise RuntimeError("Failed to read frame from local camera.")
            else:
                if not self.session_client:
                    self.set_status("No session client connection.", "Error")
                    return

                jpeg = self.session_client.get_latest_frame()
                if jpeg is None:
                    is_connected = getattr(self.session_client, "connected", False)
                    self.set_status(
                        "Connected. Waiting for video stream from web application..."
                        if is_connected else "Connecting to server...",
                        "Ready" if is_connected else "Loading",
                    )
                    return

                qimage, tracking_data = self.camera.process_jpeg(jpeg)
                if qimage is None:
                    return

            if self.loading or self.status.property("status_kind") != "ready":
                self.loading = False
                self.set_status("Camera active — session connected", "Ready")

            pixmap = QPixmap.fromImage(qimage)
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

            self._update_tracking_data(tracking_data)

        except Exception as error:
            self.close_camera(status_text=str(error), error=True)

    def _update_tracking_data(self, tracking_data):
        if tracking_data is None:
            self.position_label.setText("X: —    Y: —    Z: —")
            self.angles_label.setText("Angles: —")
            return

        x, y, z = tracking_data["position"].center_pixels
        angles = tracking_data["angles"]

        self.position_label.setText(f"X: {x:.1f}px   Y: {y:.1f}px   Z: {z:.1f} rel.")
        self.angles_label.setText("Angles:\n" + "  ·  ".join(f"{angle:.1f}°" for angle in angles))

        if self.session_client and getattr(self.session_client, "connected", False):
            try:
                self.session_client.send_angles(angles)
            except Exception as error:
                self.set_status(f"Angles calculated; send error: {error}", "Error")

    def close_camera(self, checked=False, status_text=None, error=False):
        del checked
        self._release_resources(stop_client=True)
        self.loading = False
        self._set_controls_enabled(True)
        self.close_camera_button.setEnabled(False)

        self.image_label.clear()
        self.image_label.setText("Camera Preview")
        self.position_label.setText("X: —    Y: —    Z: —")
        self.angles_label.setText("Angles: —")

        self.set_status(
            status_text or "Camera stopped",
            "Error" if error else "Neutral"
        )

    def _set_controls_enabled(self, enabled):
        self.start_camera_button.setEnabled(enabled)
        self.code_input.setEnabled(enabled)
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