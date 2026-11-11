r"""Klikz — minimal auto clicker for Windows 11.

Run from project root:
    .\.venv\Scripts\python.exe .\src\main.py

NOTE: While running, this program clicks at the CURRENT mouse cursor location.
Use only when it is safe to click there. The global F6 hotkey toggles clicking.
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import pyautogui
import pystray
from PIL import Image
from pynput import keyboard

APP_NAME = "Klikz"
VERSION = "1.0.0"
APP_ID = "Klikz.Desktop.AutoClicker.1"
GREEN = "#10C948"
DARK_GREEN = "#089A32"
DARK = "#161A18"
MUTED = "#737D77"
CARD_BG = "#F5F7F5"
INTERVALS = {"10 seconds": 10, "30 seconds": 30, "60 seconds": 60,
             "2 minutes": 120, "5 minutes": 300}


def resource_path(*parts: str) -> Path:
    """Locate bundled assets both in source mode and a PyInstaller EXE."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)


def configure_logging() -> None:
    """Write errors to a user-writable directory, not to the project folder."""
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
    try:
        base.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(base / "klikz.log"),
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            encoding="utf-8",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def configure_windows_app_id() -> None:
    """Help Windows use our own taskbar identity instead of the Python icon."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            logging.exception("Could not set Windows AppUserModelID")


class KlikzApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("light")
        super().__init__()
        self.title(APP_NAME)
        self.geometry("392x560")
        self.resizable(False, False)
        self.configure(fg_color="#FFFFFF")
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.bind("<Unmap>", self._on_unmap)
        self.bind("<Control-q>", lambda _event: self.exit_app())

        self._messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._running = threading.Event()
        self._shutdown = threading.Event()
        self._wake_worker = threading.Event()
        self._interval_lock = threading.Lock()
        self._interval_seconds = 60
        self._exiting = False
        self._tray_available = True
        self._f6_pressed = False
        self._about_window: ctk.CTkToplevel | None = None

        # PyAutoGUI failsafe: moving the pointer into a screen corner can stop it.
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

        image_path = resource_path("assets", "klikz.png")
        icon_path = resource_path("assets", "klikz.ico")
        self._logo_image = Image.open(image_path).convert("RGBA")
        self._logo = ctk.CTkImage(
            light_image=self._logo_image,
            dark_image=self._logo_image,
            size=(45, 45),
        )
        if sys.platform == "win32" and icon_path.is_file():
            self.iconbitmap(str(icon_path))

        self._build_ui()

        self._worker = threading.Thread(
            target=self._click_worker,
            name="KlikzClickWorker",
            daemon=True,
        )
        self._worker.start()

        # pystray on Windows supports running its event loop in another thread.
        self._tray = pystray.Icon(
            APP_NAME,
            self._logo_image.copy().resize((64, 64), Image.Resampling.LANCZOS),
            f"{APP_NAME} — Stopped",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Open Klikz", lambda _icon, _item: self._send("open"), default=True
                ),
                pystray.MenuItem(
                    lambda _item: "Stop Clicking" if self._running.is_set() else "Start Clicking",
                    lambda _icon, _item: self._send("toggle"),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", lambda _icon, _item: self._send("exit")),
            ),
        )
        threading.Thread(
            target=self._run_tray,
            name="KlikzSystemTray",
            daemon=True,
        ).start()

        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.daemon = True
        self._listener.start()
        self.after(100, self._process_messages)
        logging.info("Klikz started")

    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=24, pady=18)

        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", pady=(0, 17))
        ctk.CTkLabel(header, image=self._logo, text="", width=48).pack(side="left")
        name_group = ctk.CTkFrame(header, fg_color="transparent")
        name_group.pack(side="left", padx=11)
        ctk.CTkLabel(
            name_group, text=APP_NAME, font=("Segoe UI", 22, "bold"),
            text_color=DARK, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            name_group, text="Simple Auto Clicker", font=("Segoe UI", 12),
            text_color=MUTED, anchor="w",
        ).pack(anchor="w")

        status_card = ctk.CTkFrame(outer, fg_color=CARD_BG, corner_radius=14)
        status_card.pack(fill="x", pady=(0, 19))
        self.status_title = ctk.CTkLabel(
            status_card, text="Ready to Click", font=("Segoe UI", 19, "bold"),
            text_color=DARK,
        )
        self.status_title.pack(pady=(24, 4))
        self.status_text = ctk.CTkLabel(
            status_card, text="●  Not Running", font=("Segoe UI", 12),
            text_color=MUTED,
        )
        self.status_text.pack(pady=(0, 24))

        ctk.CTkLabel(
            outer, text="Click Interval", font=("Segoe UI", 13, "bold"),
            text_color=DARK, anchor="w",
        ).pack(fill="x", pady=(0, 6))
        self.interval_menu = ctk.CTkOptionMenu(
            outer, values=list(INTERVALS.keys()),
            command=self._change_interval,
            fg_color="#FFFFFF", button_color=GREEN,
            button_hover_color=DARK_GREEN, text_color=DARK,
            dropdown_fg_color="#FFFFFF", dropdown_text_color=DARK,
            font=("Segoe UI", 13), height=39, corner_radius=8,
        )
        self.interval_menu.set("60 seconds")
        self.interval_menu.pack(fill="x")
        ctk.CTkLabel(
            outer, text="Clicks every selected interval", font=("Segoe UI", 11),
            text_color=MUTED, anchor="w",
        ).pack(fill="x", pady=(4, 14))

        ctk.CTkLabel(
            outer, text="Click Type", font=("Segoe UI", 13, "bold"),
            text_color=DARK, anchor="w",
        ).pack(fill="x", pady=(0, 6))
        click_type = ctk.CTkFrame(outer, fg_color=CARD_BG, corner_radius=8, height=38)
        click_type.pack(fill="x", pady=(0, 21))
        click_type.pack_propagate(False)
        ctk.CTkLabel(
            click_type, text="Left Click", font=("Segoe UI", 12),
            text_color=DARK,
        ).pack(side="left", padx=13)
        ctk.CTkLabel(
            click_type, text="✓", font=("Segoe UI", 17, "bold"),
            text_color=DARK_GREEN,
        ).pack(side="right", padx=13)

        self.start_button = ctk.CTkButton(
            outer, text="▶  Start Clicking", command=self.toggle_clicking,
            fg_color=GREEN, hover_color=DARK_GREEN, text_color="#0C1A10",
            font=("Segoe UI", 14, "bold"), height=46, corner_radius=10,
        )
        self.start_button.pack(fill="x")

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(side="bottom", fill="x", pady=(13, 0))
        ctk.CTkLabel(
            footer, text="F6 — Start / Stop", font=("Segoe UI", 11),
            text_color=MUTED,
        ).pack(side="left")
        ctk.CTkButton(
            footer, text="ⓘ  About", command=self.show_about,
            fg_color="transparent", hover_color=CARD_BG,
            text_color=DARK_GREEN, width=75, height=30,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="right")

    def _change_interval(self, value: str) -> None:
        seconds = INTERVALS.get(value)
        if seconds is None:
            return
        with self._interval_lock:
            self._interval_seconds = seconds
        self._wake_worker.set()  # Restart the waiting interval.
        logging.info("Click interval changed to %s seconds", seconds)

    def toggle_clicking(self) -> None:
        if self._running.is_set():
            self._running.clear()
            logging.info("Auto click stopped")
        else:
            self._running.set()
            logging.info("Auto click started")
        self._wake_worker.set()
        self._update_status()

    def _update_status(self) -> None:
        active = self._running.is_set()
        self.status_title.configure(text="Auto Click Active" if active else "Ready to Click")
        self.status_text.configure(
            text="●  Running" if active else "●  Not Running",
            text_color=DARK_GREEN if active else MUTED,
        )
        self.start_button.configure(
            text="■  Stop Clicking" if active else "▶  Start Clicking",
            fg_color="#E7ECE8" if active else GREEN,
            hover_color="#D9E0DB" if active else DARK_GREEN,
        )
        try:
            self._tray.title = f"{APP_NAME} — {'Running' if active else 'Stopped'}"
            self._tray.update_menu()
        except Exception:
            logging.exception("Could not update tray menu")  # GUI and hotkey still work.

    def _click_worker(self) -> None:
        while not self._shutdown.is_set():
            if not self._running.wait(timeout=0.2):
                continue

            with self._interval_lock:
                interval = self._interval_seconds

            # Wait before the first click. Setting/clearing the wake event
            # interrupts the delay immediately when Start/Stop changes.
            interrupted = self._wake_worker.wait(timeout=interval)
            if interrupted:
                self._wake_worker.clear()
                continue
            if self._shutdown.is_set() or not self._running.is_set():
                continue

            try:
                pyautogui.click(button="left")
            except pyautogui.FailSafeException:
                self._running.clear()
                self._wake_worker.set()
                self._send("error", "Emergency stop: mouse reached a screen corner.")
            except Exception as exc:
                logging.exception("Auto click failed")
                self._running.clear()
                self._wake_worker.set()
                self._send("error", f"Auto click failed: {exc}")

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key == keyboard.Key.f6 and not self._f6_pressed:
            self._f6_pressed = True
            self._send("toggle")

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key == keyboard.Key.f6:
            self._f6_pressed = False

    def _send(self, action: str, detail: str | None = None) -> None:
        self._messages.put((action, detail))

    def _process_messages(self) -> None:
        if self._exiting:
            return
        try:
            while True:
                action, detail = self._messages.get_nowait()
                if action == "toggle":
                    self.toggle_clicking()
                elif action == "open":
                    self.show_window()
                elif action == "exit":
                    self.exit_app()
                    return
                elif action == "tray_failed":
                    self._tray_available = False
                    logging.error("System Tray unavailable: %s", detail)
                elif action == "error":
                    self._update_status()
                    self.show_window()
                    messagebox.showwarning(APP_NAME, detail or "Clicking was stopped.")
        except queue.Empty:
            pass
        self.after(100, self._process_messages)

    def _run_tray(self) -> None:
        try:
            self._tray.run()
        except Exception as exc:
            logging.exception("System Tray failed")
            self._send("tray_failed", str(exc))

    def _on_unmap(self, event: object) -> None:
        if getattr(event, "widget", None) is self and not self._exiting:
            self.after(100, self._hide_if_minimized)

    def _hide_if_minimized(self) -> None:
        if not self._exiting and self.state() == "iconic" and self._tray_available:
            self.withdraw()

    def hide_to_tray(self) -> None:
        if self._tray_available:
            self.withdraw()
        else:
            # Avoid an inaccessible application if the tray is unavailable.
            self.iconify()

    def show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def show_about(self) -> None:
        """Show a compact, Lightshot-inspired About window."""
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.deiconify()
            self._about_window.lift()
            self._about_window.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        self._about_window = dialog
        dialog.title("About")
        dialog.geometry("420x225")
        dialog.resizable(False, False)
        dialog.configure(fg_color="#FFFFFF")
        dialog.transient(self)

        # Center the About window over the Klikz main window.
        self.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - 420) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - 225) // 2)
        dialog.geometry(f"420x225+{x}+{y}")

        icon_file = resource_path("assets", "klikz.ico")
        if sys.platform == "win32" and icon_file.is_file():
            def set_about_icon() -> None:
                if dialog.winfo_exists():
                    try:
                        dialog.iconbitmap(str(icon_file))
                    except Exception:
                        logging.exception("Could not set About window icon")
            dialog.after(100, set_about_icon)

        # Copyright footer — intentionally kept as one line, like the reference.
        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=16, pady=(0, 11))
        ctk.CTkLabel(
            footer,
            text="© 2026 Faqih Fadillah. All rights reserved.",
            font=("Segoe UI", 11),
            text_color=DARK,
            anchor="w",
        ).pack(side="left")

        content = ctk.CTkFrame(dialog, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=22, pady=(16, 4))

        details = ctk.CTkFrame(content, fg_color="transparent")
        details.pack(side="left", fill="y")
        ctk.CTkLabel(
            details,
            text=APP_NAME,
            font=("Segoe UI", 25),
            text_color=DARK,
            anchor="w",
        ).pack(anchor="w", pady=(20, 0))
        ctk.CTkLabel(
            details,
            text=VERSION,
            font=("Segoe UI", 12),
            text_color=DARK,
            anchor="w",
        ).pack(anchor="w", pady=(0, 0))

        # Use the same selected green/black K logo as the main app and tray.
        about_logo = ctk.CTkImage(
            light_image=self._logo_image,
            dark_image=self._logo_image,
            size=(124, 124),
        )
        ctk.CTkLabel(
            content, image=about_logo, text="", width=130, height=130,
        ).pack(side="right", padx=(8, 0))
        dialog._about_logo_ref = about_logo  # Keep the image reference alive.

        dialog.grab_set()
        dialog.focus_force()

    def exit_app(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        self._running.clear()
        self._shutdown.set()
        self._wake_worker.set()
        try:
            self._listener.stop()
        except Exception:
            logging.exception("Could not stop hotkey listener")
        try:
            self._tray.stop()
        except Exception:
            logging.exception("Could not stop tray")
        logging.info("Klikz exited")
        self.destroy()


def main() -> None:
    configure_logging()
    configure_windows_app_id()
    try:
        app = KlikzApp()
        app.mainloop()
    except Exception:
        logging.exception("Fatal error")
        raise


if __name__ == "__main__":
    main()
