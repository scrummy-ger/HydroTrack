import customtkinter as ctk
import json
import os
import sys
import threading
import time
from datetime import date, timedelta, datetime
import pystray
from PIL import Image, ImageDraw
import winreg
from winotify import Notification, audio
import tkinter as tk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ✅ CONSTANTS
DEFAULT_GOAL = 3000
STEP_SMALL = 250
STEP_BIG = 500

app = None

# --------------------------
def format_date(d):
    return d.strftime("%d.%m.%Y")

# --------------------------
def parse_date(date_string):
    try:
        return datetime.strptime(date_string, "%d.%m.%Y").date()
    except Exception:
        try:
            return date.fromisoformat(date_string)
        except Exception:
            return date.today()

# --------------------------
def format_weekday(d):
    weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return weekdays[d.weekday()]

# --------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --------------------------
def show_toast(title, message):
    def worker():
        try:
            toast = Notification(
                app_id="HydroTrack",
                title=title,
                msg=message,
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            print("Toast Fehler:", e)

    threading.Thread(target=worker, daemon=True).start()

# --------------------------
DATA_FILE = os.path.join(
    os.getenv("APPDATA"),
    "HydroTrack",
    "hydrotrack.json"
)

os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

# --------------------------
def create_tray_icon(progress):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 10

    draw.rectangle(
        [margin, margin, size - margin, size - margin],
        outline="white",
        width=3
    )

    fill_height = int((size - 2 * margin) * progress)

    draw.rectangle(
        [margin + 2, size - margin - fill_height, size - margin - 2, size - margin],
        fill=(0, 150, 255, 200)
    )

    return img

# --------------------------
class HydroTrack(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.data = self.load_data()

        mode = self.data.get("settings", {}).get("mode", "dark")
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme("dark-blue")

        self.title("💧 HydroTrack")
        self.geometry("420x750")

        self.current_graph_days = None
        self.canvas = None

        try:
            icon_path = resource_path("HydroTrack.ico")
            self.iconbitmap(icon_path)
        except Exception as e:
            print("Icon Fehler:", e)

        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.goal_notified = False

        # --------------------------
        # UI
        # --------------------------
        self.label = ctk.CTkLabel(self, text="", font=("Segoe UI", 22))
        self.label.pack(pady=10)

        self.progress = ctk.CTkProgressBar(self, width=300, height=10)
        self.progress.pack(pady=10, padx=20)

        self.progress_label = ctk.CTkLabel(self, text="")
        self.progress_label.pack()

        self.add_button = ctk.CTkButton(
            self,
            text=f"+{STEP_SMALL} ml",
            command=self.add_water
        )
        self.add_button.pack(pady=5)

        self.goal_entry = ctk.CTkEntry(self, placeholder_text="Ziel (ml)")
        self.goal_entry.pack(pady=5)

        self.set_goal_btn = ctk.CTkButton(
            self,
            text="Ziel setzen",
            command=self.set_goal
        )
        self.set_goal_btn.pack(pady=5)

        self.graph7_btn = ctk.CTkButton(
            self,
            text="📊 7 Tage Graph",
            command=lambda: self.show_graph(7)
        )
        self.graph7_btn.pack(pady=5)

        self.graph30_btn = ctk.CTkButton(
            self,
            text="📈 30 Tage Graph",
            command=lambda: self.show_graph(30)
        )
        self.graph30_btn.pack(pady=5)

        self.mode_btn = ctk.CTkButton(self, command=self.toggle_mode)
        self.mode_btn.pack(pady=10)

        self.graph_frame = ctk.CTkFrame(self)
        self.graph_frame.pack(pady=10, fill="both", expand=True)

        self.stats_label = ctk.CTkLabel(self, text="", justify="left")
        self.stats_label.pack(pady=10)

        self.autostart_btn = ctk.CTkButton(
            self,
            text="Autostart aktivieren",
            command=self.toggle_autostart
        )
        self.autostart_btn.pack(pady=10)

        self.reset_button = ctk.CTkButton(
            self,
            text="Reset",
            command=self.reset
        )
        self.reset_button.pack(pady=5)

        self.update_mode_button()
        self.update_ui()

        threading.Thread(target=self.test_notification, daemon=True).start()
        threading.Thread(target=self.reminder_loop, daemon=True).start()

    # --------------------------
    # ✅ FIXED GRAPH
    # --------------------------
    def show_graph(self, days):
        self.current_graph_days = days

        data = self.get_last_days(days)

        date_strings = [d for d, _ in data]
        values = [v for _, v in data]

        parsed_dates = [parse_date(d) for d in date_strings]
        weekday_labels = [format_weekday(d) for d in parsed_dates]

        if self.canvas:
            try:
                widget = self.canvas.get_tk_widget()
                widget.pack_forget()
                widget.destroy()
            except Exception:
                pass
            self.canvas = None

        fig, ax = plt.subplots(figsize=(5, 3), dpi=100)

        mode = self.data.get("settings", {}).get("mode", "dark")

        if mode == "dark":
            fig.patch.set_facecolor("#2b2b2b")
            ax.set_facecolor("#2b2b2b")
            text_color = "white"
            bar_color = "#4c8cff"
            edge_color = "white"
            goal_color = "#00ffaa"
            grid_color = "#555555"
        else:
            fig.patch.set_facecolor("#f0f0f0")
            ax.set_facecolor("#f0f0f0")
            text_color = "black"
            bar_color = "#1f77b4"
            edge_color = "#0b3d91"
            goal_color = "green"
            grid_color = "#cccccc"

        positions = list(range(len(values)))

        ax.bar(
            positions,
            values,
            color=bar_color,
            edgecolor=edge_color,
            linewidth=0.8
        )

        today_goal = self.get_today_data().get("goal", DEFAULT_GOAL)

        ax.axhline(
            y=today_goal,
            color=goal_color,
            linestyle="--",
            linewidth=1.2,
            label=f"Ziel: {today_goal} ml"
        )

        ax.set_title(f"{days} Tage Statistik", color=text_color)
        ax.set_ylabel("ml", color=text_color)
        ax.set_xlabel("Wochentag", color=text_color)

        ax.set_xticks(positions)
        ax.set_xticklabels(
            weekday_labels,
            rotation=45,
            ha="right",
            color=text_color
        )

        ax.tick_params(axis="y", colors=text_color)
        ax.tick_params(axis="x", colors=text_color)

        for spine in ax.spines.values():
            spine.set_color(text_color)

        ax.grid(axis="y", linestyle=":", linewidth=0.6, color=grid_color)

        max_value = max(values) if values else 0
        max_y = max(max_value, today_goal, 10)
        ax.set_ylim(0, max_y * 1.25)

        for i, val in enumerate(values):
            if val > 0:
                ax.text(
                    i,
                    val + max_y * 0.03,
                    f"{val}",
                    ha="center",
                    va="bottom",
                    color=text_color,
                    fontsize=8
                )
            else:
                ax.text(
                    i,
                    max_y * 0.02,
                    "0",
                    ha="center",
                    va="bottom",
                    color=text_color,
                    fontsize=8
                )

        legend = ax.legend()
        legend.get_frame().set_facecolor("#2b2b2b" if mode == "dark" else "#f0f0f0")
        legend.get_frame().set_edgecolor(text_color)

        for text in legend.get_texts():
            text.set_color(text_color)

        fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(fig, master=self.graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        plt.close(fig)

    # --------------------------
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    loaded_data = json.load(f)
            except Exception as e:
                print("Load Fehler:", e)
                loaded_data = {}
        else:
            loaded_data = {}

        data = {}

        for key, value in loaded_data.items():
            if key == "settings":
                data[key] = value
                continue

            try:
                parsed_date = date.fromisoformat(key)
                new_key = format_date(parsed_date)
            except Exception:
                new_key = key

            data[new_key] = value

        today = format_date(date.today())

        if today not in data:
            data[today] = {
                "amount": 0,
                "goal": DEFAULT_GOAL
            }

        if "settings" not in data:
            data["settings"] = {
                "mode": "dark"
            }

        return data

    # --------------------------
    def save_data(self):
        try:
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(self.data, f, indent=4)

            os.replace(temp_file, DATA_FILE)
        except Exception as e:
            print("Save Fehler:", e)

    # --------------------------
    def update_mode_button(self):
        mode = self.data.get("settings", {}).get("mode", "dark")

        self.mode_btn.configure(
            text="☀️ Light Mode" if mode == "dark" else "🌙 Dark Mode"
        )

    # --------------------------
    def toggle_mode(self):
        current = self.data.get("settings", {}).get("mode", "dark")
        new_mode = "light" if current == "dark" else "dark"

        ctk.set_appearance_mode(new_mode)

        if "settings" not in self.data:
            self.data["settings"] = {}

        self.data["settings"]["mode"] = new_mode

        self.save_data()
        self.update_mode_button()

        if self.current_graph_days:
            self.show_graph(self.current_graph_days)

    # --------------------------
    def get_today(self):
        return format_date(date.today())

    # --------------------------
    def get_today_data(self):
        today = self.get_today()

        if today not in self.data:
            self.data[today] = {
                "amount": 0,
                "goal": DEFAULT_GOAL
            }

        if "amount" not in self.data[today]:
            self.data[today]["amount"] = 0

        if "goal" not in self.data[today]:
            self.data[today]["goal"] = DEFAULT_GOAL

        return self.data[today]

    # --------------------------
    def hide_window(self):
        self.withdraw()

    # --------------------------
    def test_notification(self):
        time.sleep(3)
        self.after(
            0,
            lambda: show_toast(
                "💧 HydroTrack",
                "Testmeldung funktioniert ✅"
            )
        )

    # --------------------------
    def add_water(self):
        today = self.get_today_data()
        today["amount"] += STEP_SMALL

        self.save_data()
        self.update_ui()

        if self.current_graph_days:
            self.show_graph(self.current_graph_days)

    # --------------------------
    def reset(self):
        today = self.get_today_data()
        today["amount"] = 0

        self.save_data()
        self.update_ui()

        if self.current_graph_days:
            self.show_graph(self.current_graph_days)

    # --------------------------
    def set_goal(self):
        try:
            value = self.goal_entry.get().strip()

            if not value:
                return

            goal = int(value)

            if goal <= 0:
                return

            today = self.get_today_data()
            today["goal"] = goal

            self.save_data()
            self.update_ui()

            if self.current_graph_days:
                self.show_graph(self.current_graph_days)

        except Exception as e:
            print("Goal Fehler:", e)

    # --------------------------
    def reminder_loop(self):
        while True:
            time.sleep(self.smart_interval())
            self.after(0, self.reminder_check)

    # --------------------------
    def reminder_check(self):
        today = self.get_today_data()

        if today["amount"] < today["goal"]:
            remaining = today["goal"] - today["amount"]

            show_toast(
                "💧 Trink-Erinnerung",
                f"Noch {remaining} ml bis zum Ziel 💪"
            )

    # --------------------------
    def smart_interval(self):
        today = self.get_today_data()

        goal = today.get("goal", DEFAULT_GOAL)
        amount = today.get("amount", 0)

        progress = amount / goal if goal > 0 else 0

        if progress < 0.3:
            return 3600
        elif progress < 0.7:
            return 5400

        return 7200

    # --------------------------
    def update_ui(self):
        today = self.get_today_data()

        amount = today.get("amount", 0)
        goal = today.get("goal", DEFAULT_GOAL)

        progress_value = min(amount / goal, 1.0) if goal > 0 else 0

        self.label.configure(text=f"{amount} / {goal} ml")
        self.progress.set(progress_value)

        remaining = max(goal - amount, 0)

        self.progress_label.configure(
            text=f"{int(progress_value * 100)}% erreicht\nNoch {remaining} ml"
        )

        stats_text = "📊 Letzte 7 Tage:\n"

        for d, val in self.get_last_days(7):
            parsed = parse_date(d)
            weekday = format_weekday(parsed)
            stats_text += f"{weekday}: {val} ml\n"

        self.stats_label.configure(text=stats_text)

        if amount >= goal and not self.goal_notified:
            self.goal_notified = True

            show_toast(
                "💧 Ziel erreicht!",
                "Glückwunsch! 🎉"
            )

        elif amount < goal:
            self.goal_notified = False

    # --------------------------
    def get_last_days(self, days=7):
        result = []

        for i in range(days):
            d = format_date(date.today() - timedelta(days=i))
            val = self.data.get(d, {}).get("amount", 0)
            result.append((d, val))

        return list(reversed(result))

    # --------------------------
    def toggle_autostart(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_ALL_ACCESS
            )

            exe_path = sys.executable

            try:
                winreg.QueryValueEx(key, "HydroTrack")
                winreg.DeleteValue(key, "HydroTrack")

                self.autostart_btn.configure(
                    text="Autostart aktivieren"
                )

            except FileNotFoundError:
                winreg.SetValueEx(
                    key,
                    "HydroTrack",
                    0,
                    winreg.REG_SZ,
                    exe_path
                )

                self.autostart_btn.configure(
                    text="Autostart deaktivieren"
                )

            winreg.CloseKey(key)

        except Exception as e:
            print("Autostart Fehler:", e)

# --------------------------
def run_tray():
    global app

    time.sleep(1)

    def quit_app(icon, item):
        try:
            icon.stop()
        except Exception:
            pass

        try:
            app.destroy()
        except Exception:
            pass

        os._exit(0)

    def add_big():
        today = app.get_today_data()
        today["amount"] += STEP_BIG

        app.save_data()
        app.update_ui()

        if app.current_graph_days:
            app.show_graph(app.current_graph_days)

    def create_menu():
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: f"💧 {app.get_today_data()['amount']} ml",
                None,
                enabled=False
            ),

            pystray.Menu.SEPARATOR,

            pystray.MenuItem(
                f"+{STEP_SMALL} ml",
                lambda icon, item: app.after(0, app.add_water)
            ),

            pystray.MenuItem(
                f"+{STEP_BIG} ml",
                lambda icon, item: app.after(0, add_big)
            ),

            pystray.Menu.SEPARATOR,

            pystray.MenuItem(
                "Öffnen",
                lambda icon, item: app.after(0, app.deiconify)
            ),

            pystray.MenuItem(
                "Beenden",
                quit_app
            )
        )

    icon = pystray.Icon(
        "HydroTrack",
        create_tray_icon(0),
        "HydroTrack",
        create_menu()
    )

    def update_tray():
        while True:
            try:
                today = app.get_today_data()

                amount = today.get("amount", 0)
                goal = today.get("goal", DEFAULT_GOAL)

                progress = min(amount / goal, 1.0) if goal > 0 else 0

                icon.icon = create_tray_icon(progress)
                icon.menu = create_menu()

            except Exception as e:
                print("Tray Fehler:", e)

            time.sleep(5)

    threading.Thread(target=update_tray, daemon=True).start()

    icon.run()

# --------------------------
if __name__ == "__main__":
    app = HydroTrack()

    threading.Thread(target=run_tray, daemon=True).start()

    app.mainloop()
