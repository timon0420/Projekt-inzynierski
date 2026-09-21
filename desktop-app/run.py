import sys

from PyQt6.QtWidgets import QApplication
from app.window import Window

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())