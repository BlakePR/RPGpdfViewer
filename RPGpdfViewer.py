# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "PyMuPDF",
#     "PySide6"]
# ///

# RPG Character Sheet PDF Viewer with Rulebook Integration
# Developed by: Blake Romrell
# With Gemini AI Assistance
# 3/14/2026

import sys
import os
import re
import json  
import fitz  # PyMuPDF
from PySide6.QtWidgets import (QApplication, QMainWindow, QScrollArea, 
                               QLabel, QWidget, QTextEdit, QPushButton, 
                               QMessageBox, QToolBar, QFileDialog, 
                               QVBoxLayout, QHBoxLayout)
from PySide6.QtGui import (QPixmap, QImage, QTextCursor, 
                           QAction)
from PySide6.QtCore import Qt, Signal

# --- 1. Custom UI Elements ---
class SmartField(QTextEdit):
    link_activated = Signal(str)

    def __init__(self, text="", font_size=14, parent=None):
        super().__init__(parent)
        self.font_size = font_size
        self.setPlainText(text)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.apply_style()
        self.pattern = re.compile(r"(?:pg\.?|p\.?)\s*(\d+)", re.IGNORECASE)

    def apply_style(self):
        self.setStyleSheet(f"background: transparent; border: none; font-size: {self.font_size}px;")

    def set_font_size(self, new_size):
        self.font_size = new_size
        self.apply_style()

    def check_for_link(self, pos):
        """Helper to check if the mouse is hovering over a page number."""
        cursor = self.cursorForPosition(pos)
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        text_block = cursor.block().text()
        for match in self.pattern.finditer(text_block):
            click_idx = cursor.positionInBlock()
            if match.start() <= click_idx <= match.end():
                self.link_activated.emit(match.group(1))
                return True
        return False

    def mousePressEvent(self, event):
        # Handle Ctrl + Left Click
        if event.button() == Qt.MouseButton.LeftButton and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if self.check_for_link(event.pos()):
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        # Handle Right Click (intercepts the copy/paste menu)
        if self.check_for_link(event.pos()):
            event.accept() # We found a link, block the copy/paste menu
        else:
            super().contextMenuEvent(event) # No link found, show normal copy/paste menu

    def mouseMoveEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(event)

class SkillDot(QPushButton):
    def __init__(self, field, doc, render_doc, render_callback, parent=None):
        super().__init__(parent)
        self.field = field
        self.doc = doc
        self.render_doc = render_doc
        self.render_callback = render_callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.toggle)
        self.setStyleSheet("background: transparent; border: none;")

    def _get_on_value(self):
        try:
            states = self.field.button_states()
            if isinstance(states, dict):
                for key in ("normal", "down"):
                    for value in (states.get(key) or []):
                        if value != "Off":
                            return value
            elif isinstance(states, (list, tuple)):
                for value in states:
                    if value != "Off":
                         return value
        except Exception:
            pass
        return "Yes" 

    def _is_checked(self):
        as_val = self.doc.xref_get_key(self.field.xref, "AS")
        if as_val[0] == "name":
            return as_val[1] != "/Off"
        return False

    def toggle(self):
        is_checked = self._is_checked()
        new_state = "Off" if is_checked else self._get_on_value()
        
        self.doc.xref_set_key(self.field.xref, "V", f"/{new_state}")
        self.doc.xref_set_key(self.field.xref, "AS", f"/{new_state}")
        
        self.render_doc.xref_set_key(self.field.xref, "V", f"/{new_state}")
        self.render_doc.xref_set_key(self.field.xref, "AS", f"/{new_state}")
        
        self.render_callback()

class InvisibleLink(QPushButton):
    """A bulletproof invisible button that accepts both left and right clicks."""
    def __init__(self, target_page, callback, parent=None):
        super().__init__(parent)
        self.target_page = target_page
        self.callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def mousePressEvent(self, event):
        # Fire the rulebook on Left OR Right click
        if event.button() in [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton]:
            self.callback(self.target_page)
            event.accept()
        else:
            super().mousePressEvent(event)

# --- 2. The Viewers ---
class RulebookViewer(QMainWindow):
    def __init__(self, pdf_path, target_page="1"):
        super().__init__()
        self.setWindowTitle(f"Rulebook - {os.path.basename(pdf_path)}")
        self.resize(800, 900)
        
        try:
            self.doc = fitz.open(pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "File Error", f"Could not load rulebook at {pdf_path}\n{e}")
            self.close()
            return
            
        self.scroll_area = QScrollArea()
        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.lbl_image)
        self.setCentralWidget(self.scroll_area)
        
        self.zoom = 1.5
        self.jump_to_page(target_page)

    def jump_to_page(self, page_str):
        try:
            target_index = int(page_str) - 1
            self.current_page_num = max(0, min(target_index, self.doc.page_count - 1))
        except ValueError:
            self.current_page_num = 0
            
        self.render_page()

    def render_page(self):
        page = self.doc[self.current_page_num]
        
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        
        q_img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.lbl_image.setPixmap(QPixmap.fromImage(q_img))
        self.lbl_image.adjustSize()

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0: self.zoom += 0.1
            else: self.zoom -= 0.1
            self.zoom = max(0.5, min(self.zoom, 4.0)) 
            self.render_page()
        else:
            super().wheelEvent(event)

class RPGSheetViewer(QMainWindow):
    def __init__(self, pdf_path, rulebook_path=""):
        super().__init__()
        self.pdf_path = pdf_path
        self.rulebook_path = rulebook_path
        self.current_page_num = 0
        self.font_size = 14 
        
        self.setWindowTitle(f"Character Sheet - {os.path.basename(self.pdf_path)}")
        
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
            
        self.doc = fitz.open("pdf", pdf_bytes)
        self.render_doc = fitz.open("pdf", pdf_bytes)
        
        for p_num in range(self.render_doc.page_count):
            p = self.render_doc[p_num]
            for w in p.widgets():
                if w.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                    p.delete_widget(w)

        self.current_page = self.doc[self.current_page_num]
        self.zoom = 800.0 / self.current_page.rect.height
        
        self.scroll_area = QScrollArea()
        self.container = QWidget()
        self.lbl_image = QLabel(self.container)
        self.scroll_area.setWidget(self.container)
        self.setCentralWidget(self.scroll_area)
        self.resize(850, 850)
        
        self.setup_menus_and_toolbars()
        self.render_page()

    def setup_menus_and_toolbars(self):
        menubar = self.menuBar()
        
        # --- File Menu ---
        file_menu = menubar.addMenu("File")
        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_pdf)
        file_menu.addAction(save_action)

        # --- View Menu (Font Adjustments) ---
        view_menu = menubar.addMenu("View")
        
        inc_font_action = QAction("Increase Font Size", self)
        inc_font_action.setShortcut("Ctrl+=") # Ctrl and +
        inc_font_action.triggered.connect(self.increase_font)
        view_menu.addAction(inc_font_action)
        
        dec_font_action = QAction("Decrease Font Size", self)
        dec_font_action.setShortcut("Ctrl+-") # Ctrl and -
        dec_font_action.triggered.connect(self.decrease_font)
        view_menu.addAction(dec_font_action)

        # --- Toolbar ---
        toolbar = QToolBar("Navigation")
        self.addToolBar(toolbar)
        
        self.btn_prev = QAction("◀ Previous Page", self)
        self.btn_prev.triggered.connect(self.prev_page)
        toolbar.addAction(self.btn_prev)
        
        self.lbl_page_counter = QLabel()
        self.lbl_page_counter.setStyleSheet("margin: 0px 10px;")
        toolbar.addWidget(self.lbl_page_counter)
        
        self.btn_next = QAction("Next Page ▶", self)
        self.btn_next.triggered.connect(self.next_page)
        toolbar.addAction(self.btn_next)

    def increase_font(self):
        self.font_size += 1
        self.apply_font_size()

    def decrease_font(self):
        self.font_size = max(6, self.font_size - 1) # Prevent shrinking below 6px
        self.apply_font_size()

    def apply_font_size(self):
        for child in self.container.children():
            if isinstance(child, SmartField):
                child.set_font_size(self.font_size)

    def prev_page(self):
        if self.current_page_num > 0:
            self.current_page_num -= 1
            self.render_page()

    def next_page(self):
        if self.current_page_num < self.doc.page_count - 1:
            self.current_page_num += 1
            self.render_page()

    def render_page(self):
        self.current_page = self.doc[self.current_page_num]
        self.lbl_page_counter.setText(f" Page {self.current_page_num + 1} of {self.doc.page_count} ")

        for child in self.container.children():
            if isinstance(child, (SmartField, QPushButton, SkillDot)):
                child.deleteLater()

        render_page = self.render_doc[self.current_page_num]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = render_page.get_pixmap(matrix=mat)
        
        q_img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.lbl_image.setPixmap(QPixmap.fromImage(q_img))
        self.lbl_image.adjustSize()
        self.container.resize(self.lbl_image.size())
        
        self.spawn_static_hotspots(self.current_page)  
        self.spawn_smart_fields(self.current_page)
        
    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0:
                self.zoom += 0.1
            else:
                self.zoom -= 0.1
            self.zoom = max(0.5, min(self.zoom, 4.0)) 
            self.render_page()
        else:
            super().wheelEvent(event)

    def save_pdf(self):
        try:
            self.doc.save(self.pdf_path, incremental=False, encryption=fitz.PDF_ENCRYPT_KEEP)
            print("Saved successfully!")
        except Exception as e:
            print(f"Error saving: {e}")
            QMessageBox.critical(self, "Save Error", f"Could not save PDF:\n{e}")

    def spawn_static_hotspots(self, page):
        text_instances = page.search_for("pg. ") 
        for rect in text_instances:
            self.create_invisible_button(rect, "162") 

    def create_invisible_button(self, rect, target_page):
        # Use our new custom class that handles both click types
        btn = InvisibleLink(target_page, self.open_rulebook, parent=self.container)
        btn.setGeometry(
            int(rect.x0 * self.zoom), int(rect.y0 * self.zoom),
            int(rect.width * self.zoom), int(rect.height * self.zoom)
        )
        btn.show()

    def spawn_smart_fields(self, page):
        for field in page.widgets():
            x = int(field.rect.x0 * self.zoom)
            y = int(field.rect.y0 * self.zoom)
            w = int(field.rect.width * self.zoom)
            h = int(field.rect.height * self.zoom)

            if field.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                editor = SmartField(text=field.field_value or "", font_size=self.font_size, parent=self.container)
                editor.link_activated.connect(self.open_rulebook)
                editor.textChanged.connect(lambda f=field, e=editor: self.update_text_field(f, e))
                editor.setGeometry(x, y, w, h)
                editor.show()
                
            elif field.field_type in [fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON]:
                dot = SkillDot(field, self.doc, self.render_doc, self.render_page, parent=self.container)
                dot.setGeometry(x, y, w, h)
                dot.show()

    def update_text_field(self, field, editor):
        field.field_value = editor.toPlainText()
        field.update()

    def open_rulebook(self, page_num):
        if not self.rulebook_path or not os.path.exists(self.rulebook_path):
            QMessageBox.warning(self, "No Rulebook", "You didn't select a Rulebook PDF at launch!")
            return

        if not hasattr(self, 'rulebook_window') or self.rulebook_window is None or not self.rulebook_window.isVisible():
            self.rulebook_window = RulebookViewer(self.rulebook_path, page_num)
            self.rulebook_window.show()
        else:
            self.rulebook_window.jump_to_page(page_num)
            self.rulebook_window.raise_()
            self.rulebook_window.activateWindow()

# --- The Startup Launcher ---
class LauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RPG Tool - Setup")
        self.resize(500, 200)
        
        self.sheet_path = ""
        self.rulebook_path = ""
        
        self.config_file = "rpg_config.json"
        self.config_data = self.load_config()
        
        layout = QVBoxLayout()
        
        sheet_layout = QHBoxLayout()
        self.lbl_sheet = QLabel("Character Sheet: Not Selected")
        btn_sheet = QPushButton("Browse...")
        btn_sheet.clicked.connect(self.select_sheet)
        sheet_layout.addWidget(self.lbl_sheet)
        sheet_layout.addWidget(btn_sheet)
        layout.addLayout(sheet_layout)
        
        rb_layout = QHBoxLayout()
        self.lbl_rb = QLabel("Rulebook: Not Selected (Optional)")
        btn_rb = QPushButton("Browse...")
        btn_rb.clicked.connect(self.select_rulebook)
        rb_layout.addWidget(self.lbl_rb)
        rb_layout.addWidget(btn_rb)
        layout.addLayout(rb_layout)
        
        self.btn_launch = QPushButton("Launch Application")
        self.btn_launch.setEnabled(False) 
        self.btn_launch.clicked.connect(self.launch)
        layout.addWidget(self.btn_launch)
        
        self.setLayout(layout)
        
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config_data, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def select_sheet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Character Sheet", "", "PDF Files (*.pdf)")
        if path:
            self.sheet_path = path
            self.lbl_sheet.setText(f"Character Sheet: {os.path.basename(path)}")
            self.btn_launch.setEnabled(True) 
            
            if self.sheet_path in self.config_data:
                saved_rb = self.config_data[self.sheet_path]
                if os.path.exists(saved_rb):
                    self.rulebook_path = saved_rb
                    self.lbl_rb.setText(f"Rulebook: {os.path.basename(saved_rb)} (Auto-loaded)")
            
    def select_rulebook(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Rulebook", "", "PDF Files (*.pdf)")
        if path:
            self.rulebook_path = path
            self.lbl_rb.setText(f"Rulebook: {os.path.basename(path)}")
            
    def launch(self):
        if self.sheet_path and self.rulebook_path:
            self.config_data[self.sheet_path] = self.rulebook_path
            self.save_config()

        self.viewer = RPGSheetViewer(self.sheet_path, self.rulebook_path)
        self.viewer.show()
        self.close() 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    launcher = LauncherWindow()
    launcher.show()
    sys.exit(app.exec())