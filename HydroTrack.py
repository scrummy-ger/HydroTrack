import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import json
import os
import sys
import threading
from datetime import date, timedelta
import pystray
from PIL import Image, ImageDraw
import winreg
from winotify import Notification, audio

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ============================================================
# GLOBALS
# ============================================================

app = None
tray_icon = None

APP_NAME = "HydroTrack"
APP_AUTHOR = "HydroTrack"
DEFAULT_GOAL = 3000
DEFAULT_STEP_SMALL = 250
DEFAULT_STEP_BIG = 500

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ============================================================
# PATHS
# ============================================================

def resource_path(relative_path):
    """
    Unterstützt normale Python-Ausführung und PyInstaller.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_appdata_dir():
    path = os.path.join(os.getenv("APPDATA"), APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = get_appdata_dir()
DATA_FILE = os.path.join(DATA_DIR, "hydrotrack_data.json")

# ✅ FIX: Assets sauber aus assets/ laden
ICON_FILE = resource_path("assets/HydroTrack.ico")
SMALL_IMAGE = resource_path("assets/HydroTrack_Small.bmp")



# ============================================================
# WINDOW HELPERS
# ============================================================

def center_window(window, width, height, parent=None):
    """
    Zentriert ein Fenster entweder auf dem Parent-Fenster oder auf dem Bildschirm.
    """
    window.update_idletasks()

    if parent is not None:
        parent.update_idletasks()

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()

        x = parent_x + (parent_w // 2) - (width // 2)
        y = parent_y + (parent_h // 2) - (height // 2)
    else:
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()

        x = (screen_w // 2) - (width // 2)
        y = (screen_h // 2) - (height // 2)

    window.geometry(f"{width}x{height}+{x}+{y}")


# ============================================================
# DATA
# ============================================================

def today_key():
    return date.today().isoformat()


def safe_load_json(path):
    """Safely load JSON file with error recovery."""
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # JSON is corrupted, backup and return None
        backup = path + ".broken"
        try:
            os.replace(path, backup)
        except Exception:
            pass
        return None
    except Exception:
        return None


def default_data():
    return {
        "goal": DEFAULT_GOAL,
        "theme": "Dark",
        "history": {},
        "last_notification_goal": None
    }


def normalize_data(data):
    """Ensure data has all required fields with correct types."""
    if not isinstance(data, dict):
        data = default_data()

    # Ensure all required keys exist with defaults
    data.setdefault("goal", DEFAULT_GOAL)
    data.setdefault("theme", "Dark")
    data.setdefault("history", {})
    data.setdefault("last_notification_goal", None)

    # Validate data types and values
    try:
        data["goal"] = max(1, int(data["goal"]))  # Ensure goal is at least 1
    except (ValueError, TypeError):
        data["goal"] = DEFAULT_GOAL

    if not isinstance(data["history"], dict):
        data["history"] = {}
    else:
        # Clean up history: ensure all values are non-negative integers
        clean_history = {}
        for k, v in data["history"].items():
            try:
                clean_history[k] = max(0, int(v))
            except (ValueError, TypeError):
                clean_history[k] = 0
        data["history"] = clean_history

    return data


def load_data():
    data = safe_load_json(DATA_FILE)
    if data is None:
        data = default_data()
        save_data(data)
    return normalize_data(data)


def save_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


# ============================================================
# WINDOWS AUTOSTART
# ============================================================

def get_executable_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def is_autostart_enabled():
    """Check if autostart is enabled in Windows registry."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ
        )
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enabled):
    """Enable or disable autostart in Windows registry."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )

        try:
            if enabled:
                exe_path = get_executable_path()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        
        return True
    except Exception as e:
        messagebox.showerror("Autostart Fehler", str(e))
        return False


# ============================================================
# ICON
# ============================================================

def load_tray_image():
    if os.path.exists(ICON_FILE):
        try:
            return Image.open(ICON_FILE)
        except Exception:
            pass

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((14, 8, 50, 58), fill=(56, 189, 248, 255))
    draw.ellipse((24, 16, 34, 28), fill=(255, 255, 255, 180))
    return image


# ============================================================
# NOTIFICATIONS
# ============================================================

def notify_goal_reached():
    """Send a notification when daily goal is reached."""
    try:
        icon_param = ICON_FILE if os.path.exists(ICON_FILE) else ""
        toast = Notification(
            app_id=APP_NAME,
            title="Ziel erreicht 🎉",
            msg="Du hast dein Trinkziel für heute erreicht!",
            icon=icon_param
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception as e:
        # Silently fail - notifications are non-critical
        pass


# ============================================================
# MAIN APP
# ============================================================

class HydroTrack(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.data = load_data()
        ctk.set_appearance_mode(self.data.get("theme", "Dark"))

        self.title(APP_NAME)
        self.geometry("520x720")
        self.minsize(480, 650)

        self.apply_window_icon(self)

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self.bg_dark = "#0F172A"
        self.card_dark = "#1E293B"
        self.card_dark_2 = "#243449"
        self.text_dark = "#F8FAFC"
        self.muted_dark = "#94A3B8"

        self.bg_light = "#F8FAFC"
        self.card_light = "#FFFFFF"
        self.card_light_2 = "#E2E8F0"
        self.text_light = "#0F172A"
        self.muted_light = "#64748B"

        self.primary = "#38BDF8"
        self.primary_hover = "#0EA5E9"
        self.success = "#22C55E"
        self.danger = "#EF4444"
        self.warning = "#F59E0B"

        self.chart_canvas = None

        self.build_ui()
        self.refresh_ui()

    # --------------------------------------------------------
    # WINDOW ICON
    # --------------------------------------------------------

    def apply_window_icon(self, window):
        """Applies the window icon to any Tkinter window (root or toplevel)."""
        if not os.path.exists(ICON_FILE):
            return
        
        try:
            # Use iconbitmap for main window, schedule it to ensure proper initialization
            if window == self:
                window.iconbitmap(ICON_FILE)
            else:
                # For Toplevel windows, use a longer deferred call to ensure window initialization
                window.after(200, lambda: self._set_window_icon_toplevel(window))
        except Exception:
            pass
    
    def _set_window_icon_toplevel(self, window):
        """Helper method to set icon on Toplevel windows."""
        try:
            window.update_idletasks()
            window.iconbitmap(ICON_FILE)
        except Exception:
            try:
                # Fallback: Use parent window's icon
                if self.tk.call('winfo', 'exists', window):
                    window.tk.call('wm', 'iconbitmap', window, ICON_FILE)
            except Exception:
                pass

    # --------------------------------------------------------
    # THEME HELPERS
    # --------------------------------------------------------

    def is_dark(self):
        return ctk.get_appearance_mode().lower() == "dark"

    def colors(self):
        if self.is_dark():
            return {
                "bg": self.bg_dark,
                "card": self.card_dark,
                "card2": self.card_dark_2,
                "text": self.text_dark,
                "muted": self.muted_dark
            }
        return {
            "bg": self.bg_light,
            "card": self.card_light,
            "card2": self.card_light_2,
            "text": self.text_light,
            "muted": self.muted_light
        }

    # --------------------------------------------------------
    # DATA HELPERS
    # --------------------------------------------------------

    def get_today_amount(self):
        return int(self.data["history"].get(today_key(), 0))

    def set_today_amount(self, amount):
        amount = max(0, int(amount))
        self.data["history"][today_key()] = amount

        if amount < self.data["goal"]:
            self.data["last_notification_goal"] = None

        if amount >= self.data["goal"]:
            if self.data.get("last_notification_goal") != today_key():
                self.data["last_notification_goal"] = today_key()
                notify_goal_reached()

        save_data(self.data)
        self.refresh_ui()

    def add_water(self, amount):
        self.set_today_amount(self.get_today_amount() + amount)

    def subtract_water(self, amount):
        self.set_today_amount(self.get_today_amount() - amount)

    # --------------------------------------------------------
    # UI BUILD
    # --------------------------------------------------------

    def build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.main = ctk.CTkFrame(self, corner_radius=0)
        self.main.grid(row=0, column=0, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        self.build_header()
        self.build_today_card()
        self.build_chart_card()
        self.build_footer()

    def build_header(self):
        self.header = ctk.CTkFrame(self.main, corner_radius=0, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        self.header.grid_columnconfigure(1, weight=1)

        self.logo_label = ctk.CTkLabel(
            self.header,
            text="💧",
            font=ctk.CTkFont(size=30)
        )
        self.logo_label.grid(row=0, column=0, padx=(0, 10))

        self.title_label = ctk.CTkLabel(
            self.header,
            text="HydroTrack",
            font=ctk.CTkFont(size=25, weight="bold", slant="roman")
        )
        self.title_label.grid(row=0, column=1, sticky="w")

        self.theme_button = ctk.CTkButton(
            self.header,
            text="Light",
            width=64,
            height=38,
            corner_radius=14,
            command=self.toggle_theme
        )
        self.theme_button.grid(row=0, column=2, padx=(8, 8))

        self.settings_button = ctk.CTkButton(
            self.header,
            text="⚙",
            width=42,
            height=38,
            corner_radius=14,
            command=self.open_settings
        )
        self.settings_button.grid(row=0, column=3)

    def build_today_card(self):
        self.today_card = ctk.CTkFrame(self.main, corner_radius=26)
        self.today_card.grid(row=1, column=0, sticky="ew", padx=24, pady=(6, 18))
        self.today_card.grid_columnconfigure((0, 1), weight=1)

        self.today_label = ctk.CTkLabel(
            self.today_card,
            text="Heute",
            font=ctk.CTkFont(size=17, weight="bold")
        )
        self.today_label.grid(row=0, column=0, columnspan=2, pady=(22, 2))

        self.amount_label = ctk.CTkLabel(
            self.today_card,
            text="0 ml",
            font=ctk.CTkFont(size=46, weight="bold")
        )
        self.amount_label.grid(row=1, column=0, columnspan=2, pady=(0, 0))

        self.goal_label = ctk.CTkLabel(
            self.today_card,
            text="von 3000 ml",
            font=ctk.CTkFont(size=15)
        )
        self.goal_label.grid(row=2, column=0, columnspan=2, pady=(0, 14))

        self.progress_bg = ctk.CTkFrame(
            self.today_card,
            height=16,
            corner_radius=100
        )
        self.progress_bg.grid(row=3, column=0, columnspan=2, sticky="ew", padx=52, pady=(0, 10))
        self.progress_bg.grid_columnconfigure(0, weight=1)

        self.progress_fill = ctk.CTkFrame(
            self.progress_bg,
            height=16,
            corner_radius=100
        )
        self.progress_fill.place(x=0, y=0, relheight=1, relwidth=0)

        self.percent_label = ctk.CTkLabel(
            self.today_card,
            text="0%",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.percent_label.grid(row=4, column=0, columnspan=2, pady=(0, 18))

        self.btn_add_250 = ctk.CTkButton(
            self.today_card,
            text="+250 ml",
            height=48,
            corner_radius=18,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=lambda: self.add_water(DEFAULT_STEP_SMALL)
        )
        self.btn_add_250.grid(row=5, column=0, sticky="ew", padx=(28, 8), pady=(0, 12))

        self.btn_add_500 = ctk.CTkButton(
            self.today_card,
            text="+500 ml",
            height=48,
            corner_radius=18,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=lambda: self.add_water(DEFAULT_STEP_BIG)
        )
        self.btn_add_500.grid(row=5, column=1, sticky="ew", padx=(8, 28), pady=(0, 12))

        self.btn_subtract = ctk.CTkButton(
            self.today_card,
            text="-250 ml",
            height=40,
            corner_radius=16,
            fg_color="transparent",
            border_width=1,
            command=lambda: self.subtract_water(DEFAULT_STEP_SMALL)
        )
        self.btn_subtract.grid(row=6, column=0, sticky="ew", padx=(28, 8), pady=(0, 22))

        self.btn_set_value = ctk.CTkButton(
            self.today_card,
            text="Wert setzen",
            height=40,
            corner_radius=16,
            fg_color="transparent",
            border_width=1,
            command=self.open_set_value_dialog
        )
        self.btn_set_value.grid(row=6, column=1, sticky="ew", padx=(8, 28), pady=(0, 22))

    def build_chart_card(self):
        self.chart_card = ctk.CTkFrame(self.main, corner_radius=26)
        self.chart_card.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 18))
        self.chart_card.grid_columnconfigure(0, weight=1)
        self.chart_card.grid_rowconfigure(1, weight=1)

        self.chart_title = ctk.CTkLabel(
            self.chart_card,
            text="Letzte 7 Tage",
            font=ctk.CTkFont(size=17, weight="bold")
        )
        self.chart_title.grid(row=0, column=0, sticky="w", padx=24, pady=(20, 0))

        self.chart_container = ctk.CTkFrame(self.chart_card, fg_color="transparent")
        self.chart_container.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 0))

        self.stats_frame = ctk.CTkFrame(self.chart_card, fg_color="transparent")
        self.stats_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 20))
        self.stats_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.avg_label = self.create_stat_label(self.stats_frame, "Ø Tag", "0 ml", 0)
        self.goal_days_label = self.create_stat_label(self.stats_frame, "Zieltage", "0/7", 1)
        self.best_label = self.create_stat_label(self.stats_frame, "Bester Tag", "0 ml", 2)

    def create_stat_label(self, parent, title, value, column):
        frame = ctk.CTkFrame(parent, corner_radius=18)
        frame.grid(row=0, column=column, sticky="ew", padx=5)
        frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=12)
        )
        title_label.grid(row=0, column=0, pady=(10, 0))

        value_label = ctk.CTkLabel(
            frame,
            text=value,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        value_label.grid(row=1, column=0, pady=(0, 10))

        return value_label

    def build_footer(self):
        self.footer = ctk.CTkFrame(self.main, corner_radius=0, fg_color="transparent")
        self.footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 20))
        self.footer.grid_columnconfigure((0, 1), weight=1)

        self.reset_button = ctk.CTkButton(
            self.footer,
            text="Heute zurücksetzen",
            height=38,
            corner_radius=15,
            fg_color=self.danger,
            hover_color="#DC2626",
            command=self.reset_today
        )
        self.reset_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.folder_button = ctk.CTkButton(
            self.footer,
            text="Datenordner öffnen",
            height=38,
            corner_radius=15,
            fg_color="transparent",
            border_width=1,
            command=self.open_data_folder
        )
        self.folder_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    # --------------------------------------------------------
    # UI REFRESH
    # --------------------------------------------------------

    def refresh_ui(self):
        c = self.colors()

        self.configure(fg_color=c["bg"])
        self.main.configure(fg_color=c["bg"])

        self.today_card.configure(fg_color=c["card"])
        self.chart_card.configure(fg_color=c["card"])

        self.progress_bg.configure(fg_color=c["card2"])

        amount = self.get_today_amount()
        goal = max(1, int(self.data.get("goal", DEFAULT_GOAL)))
        progress = min(1, amount / goal)
        percent = int(progress * 100)

        if amount >= goal:
            progress_color = self.success
        elif progress >= 0.5:
            progress_color = self.primary
        else:
            progress_color = self.warning

        self.amount_label.configure(text=f"{amount} ml", text_color=c["text"])
        self.goal_label.configure(text=f"von {goal} ml", text_color=c["muted"])
        self.percent_label.configure(text=f"{percent}%", text_color=progress_color)
        self.today_label.configure(text_color=c["text"])
        self.title_label.configure(text_color=c["text"])
        self.chart_title.configure(text_color=c["text"])

        self.progress_fill.configure(fg_color=progress_color)
        self.progress_fill.place_configure(relwidth=progress)

        self.theme_button.configure(text="Light" if self.is_dark() else "Dark")

        self.btn_add_250.configure(fg_color=self.primary, hover_color=self.primary_hover)
        self.btn_add_500.configure(fg_color=self.primary, hover_color=self.primary_hover)

        self.btn_subtract.configure(
            text_color=c["text"],
            border_color=c["card2"],
            hover_color=c["card2"]
        )

        self.btn_set_value.configure(
            text_color=c["text"],
            border_color=c["card2"],
            hover_color=c["card2"]
        )

        self.folder_button.configure(
            text_color=c["text"],
            border_color=c["card2"],
            hover_color=c["card2"]
        )

        self.draw_chart()

    def get_last_7_days(self):
        """Get the last 7 days with labels and values."""
        days = []
        day_replacements = {
            "Mon": "Mo", "Tue": "Di", "Wed": "Mi",
            "Thu": "Do", "Fri": "Fr", "Sat": "Sa", "Sun": "So"
        }
        
        for i in range(6, -1, -1):
            d = date.today() - timedelta(days=i)
            key = d.isoformat()
            label = d.strftime("%a")
            
            # Replace day abbreviations
            for en, de in day_replacements.items():
                label = label.replace(en, de)
            
            value = int(self.data["history"].get(key, 0))
            days.append((label, value))
        
        return days

    def draw_chart(self):
        """Draw the 7-day history chart."""
        c = self.colors()

        # Clear previous chart
        for widget in self.chart_container.winfo_children():
            widget.destroy()

        days = self.get_last_7_days()
        labels = [d[0] for d in days]
        values = [d[1] for d in days]
        goal = int(self.data.get("goal", DEFAULT_GOAL))

        # Calculate statistics
        avg = int(sum(values) / len(values)) if values else 0
        goal_days = sum(1 for v in values if v >= goal)
        best = max(values) if values else 0

        # Update statistics labels
        self.avg_label.configure(text=f"{avg} ml")
        self.goal_days_label.configure(text=f"{goal_days}/7")
        self.best_label.configure(text=f"{best} ml")

        # Create matplotlib figure
        fig, ax = plt.subplots(figsize=(4.8, 2.25), dpi=100)
        fig.patch.set_facecolor(c["card"])
        ax.set_facecolor(c["card"])

        # Determine bar colors based on goal achievement
        bar_colors = [
            self.success if v >= goal else (self.primary if v >= goal * 0.5 else self.warning)
            for v in values
        ]

        # Draw bars and goal line
        ax.bar(labels, values, color=bar_colors, width=0.55)
        ax.axhline(goal, color=self.success, linestyle="--", linewidth=1, alpha=0.7)

        # Set y-axis limits
        max_y = max(goal, max(values) if values else 0, 1000)
        ax.set_ylim(0, max_y * 1.2)

        # Style axes
        ax.set_xticklabels(labels, color=c["muted"], fontsize=9)
        ax.tick_params(axis="x", colors=c["muted"], labelsize=9)
        ax.tick_params(axis="y", colors=c["muted"], labelsize=8)

        for spine in ax.spines.values():
            spine.set_visible(False)

        ax.grid(axis="y", linestyle="-", alpha=0.12)
        ax.set_axisbelow(True)
        ax.set_ylabel("ml", color=c["muted"], fontsize=8)

        plt.tight_layout(pad=1)

        # Embed in Tkinter canvas
        canvas = FigureCanvasTkAgg(fig, master=self.chart_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        plt.close(fig)

    # --------------------------------------------------------
    # DIALOGS
    # --------------------------------------------------------

    def open_set_value_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Wert setzen")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        self.apply_window_icon(dialog)
        center_window(dialog, 340, 240, self)

        c = self.colors()
        dialog.configure(fg_color=c["bg"])

        frame = ctk.CTkFrame(dialog, corner_radius=22, fg_color=c["card"])
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        label = ctk.CTkLabel(
            frame,
            text="Heutigen Wert setzen",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=c["text"]
        )
        label.pack(pady=(22, 10))

        entry = ctk.CTkEntry(frame, placeholder_text="ml", justify="center", height=40)
        entry.pack(fill="x", padx=28, pady=(0, 16))
        entry.insert(0, str(self.get_today_amount()))
        entry.focus()

        def save_value():
            try:
                value = int(entry.get())
                self.set_today_amount(value)
                dialog.destroy()
            except Exception:
                messagebox.showerror("Ungültiger Wert", "Bitte gib eine gültige Zahl ein.")

        button = ctk.CTkButton(
            frame,
            text="Speichern",
            height=42,
            corner_radius=15,
            command=save_value
        )
        button.pack(fill="x", padx=28)

        dialog.bind("<Return>", lambda e: save_value())

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Einstellungen")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        self.apply_window_icon(dialog)
        center_window(dialog, 440, 580, self)

        c = self.colors()
        dialog.configure(fg_color=c["bg"])

        frame = ctk.CTkFrame(dialog, corner_radius=24, fg_color=c["card"])
        frame.pack(fill="both", expand=True, padx=22, pady=22)
        frame.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            frame,
            text="Einstellungen",
            font=ctk.CTkFont(size=22, weight="bold", slant="roman"),
            text_color=c["text"]
        )
        title.grid(row=0, column=0, sticky="w", padx=26, pady=(26, 24))

        goal_label = ctk.CTkLabel(
            frame,
            text="Tagesziel",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c["text"]
        )
        goal_label.grid(row=1, column=0, sticky="w", padx=26, pady=(0, 8))

        goal_hint = ctk.CTkLabel(
            frame,
            text="Wie viel ml möchtest du pro Tag trinken?",
            font=ctk.CTkFont(size=12),
            text_color=c["muted"]
        )
        goal_hint.grid(row=2, column=0, sticky="w", padx=26, pady=(0, 10))

        goal_entry = ctk.CTkEntry(
            frame,
            height=44,
            corner_radius=14,
            font=ctk.CTkFont(size=14),
            placeholder_text="z. B. 3000"
        )
        goal_entry.grid(row=3, column=0, sticky="ew", padx=26, pady=(0, 22))
        goal_entry.insert(0, str(self.data.get("goal", DEFAULT_GOAL)))

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())

        autostart_box = ctk.CTkFrame(frame, corner_radius=18, fg_color=c["card2"])
        autostart_box.grid(row=4, column=0, sticky="ew", padx=26, pady=(0, 20))
        autostart_box.grid_columnconfigure(0, weight=1)
        autostart_box.grid_columnconfigure(1, weight=0)

        autostart_label = ctk.CTkLabel(
            autostart_box,
            text="Mit Windows starten",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c["text"]
        )
        autostart_label.grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(16, 2))

        autostart_hint = ctk.CTkLabel(
            autostart_box,
            text="HydroTrack automatisch beim Systemstart öffnen",
            font=ctk.CTkFont(size=12),
            text_color=c["muted"],
            wraplength=245,
            justify="left"
        )
        autostart_hint.grid(row=1, column=0, sticky="w", padx=(18, 8), pady=(0, 16))

        autostart_switch = ctk.CTkSwitch(
            autostart_box,
            text="",
            variable=autostart_var,
            width=44
        )
        autostart_switch.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 18), pady=18)

        theme_info = "Aktuelles Design: Dark Mode" if self.is_dark() else "Aktuelles Design: Light Mode"

        theme_label = ctk.CTkLabel(
            frame,
            text=theme_info,
            font=ctk.CTkFont(size=13),
            text_color=c["muted"]
        )
        theme_label.grid(row=5, column=0, sticky="w", padx=26, pady=(0, 16))

        folder_btn = ctk.CTkButton(
            frame,
            text="Datenordner öffnen",
            height=44,
            corner_radius=15,
            fg_color="transparent",
            border_width=1,
            text_color=c["text"],
            border_color=c["card2"],
            hover_color=c["card2"],
            command=self.open_data_folder
        )
        folder_btn.grid(row=6, column=0, sticky="ew", padx=26, pady=(0, 22))

        def save_settings():
            try:
                new_goal = int(goal_entry.get())
                if new_goal <= 0:
                    raise ValueError
            except Exception:
                messagebox.showerror("Ungültiges Ziel", "Bitte gib ein gültiges Tagesziel ein.")
                return

            self.data["goal"] = new_goal
            save_data(self.data)
            set_autostart(autostart_var.get())

            self.refresh_ui()
            dialog.destroy()

        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.grid(row=7, column=0, sticky="ew", padx=26, pady=(2, 26))
        button_frame.grid_columnconfigure((0, 1), weight=1)

        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Abbrechen",
            height=46,
            corner_radius=16,
            fg_color="transparent",
            border_width=1,
            text_color=c["text"],
            border_color=c["card2"],
            hover_color=c["card2"],
            command=dialog.destroy
        )
        cancel_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        save_btn = ctk.CTkButton(
            button_frame,
            text="Speichern",
            height=46,
            corner_radius=16,
            command=save_settings
        )
        save_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        goal_entry.focus()
        dialog.bind("<Return>", lambda e: save_settings())

    # --------------------------------------------------------
    # ACTIONS
    # --------------------------------------------------------

    def toggle_theme(self):
        new_theme = "Light" if self.is_dark() else "Dark"
        ctk.set_appearance_mode(new_theme)
        self.data["theme"] = new_theme
        save_data(self.data)
        self.refresh_ui()

    def reset_today(self):
        result = messagebox.askyesno(
            "Heute zurücksetzen",
            "Möchtest du den heutigen Wert wirklich auf 0 ml zurücksetzen?"
        )
        if result:
            self.set_today_amount(0)

    def open_data_folder(self):
        """Open the data folder in file explorer."""
        try:
            os.startfile(DATA_DIR)
        except FileNotFoundError:
            messagebox.showerror("Fehler", "Datenordner nicht gefunden.")
        except Exception as e:
            messagebox.showerror("Fehler", f"Fehler beim Öffnen des Ordners: {str(e)}")

    def hide_to_tray(self):
        self.withdraw()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_app(self):
        global tray_icon
        try:
            if tray_icon:
                tray_icon.stop()
        except Exception:
            pass
        self.destroy()


# ============================================================
# TRAY
# ============================================================

def tray_add_water(amount):
    global app
    if app:
        app.after(0, lambda: app.add_water(amount))


def tray_subtract_water(amount):
    global app
    if app:
        app.after(0, lambda: app.subtract_water(amount))


def tray_reset_today():
    global app
    if app:
        app.after(0, lambda: app.set_today_amount(0))


def tray_show():
    global app
    if app:
        app.after(0, app.show_window)


def tray_quit():
    global app
    if app:
        app.after(0, app.quit_app)


def run_tray():
    global tray_icon

    image = load_tray_image()

    menu = pystray.Menu(
        pystray.MenuItem("Öffnen", lambda: tray_show()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("+250 ml", lambda: tray_add_water(250)),
        pystray.MenuItem("+500 ml", lambda: tray_add_water(500)),
        pystray.MenuItem("-250 ml", lambda: tray_subtract_water(250)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Heute zurücksetzen", lambda: tray_reset_today()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", lambda: tray_quit())
    )

    tray_icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
    tray_icon.run()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    app = HydroTrack()
    threading.Thread(target=run_tray, daemon=True).start()
    app.mainloop()
