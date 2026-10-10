"""
Windows AI Agent — Fully Interactive & Scrollable Command HUD.

Enhancements:
- Dedicated Top Drag/Title Bar with move cursor, window title, minimize and close buttons.
- Multi-widget root-coordinate window dragging (click and drag from header, background, or canvas).
- Clean, organized 2-row Quick Action grid: ALL 10 quick actions are completely visible and accessible.
- Scrollable Plan & Steps container with custom vertical scrollbar and MouseWheel support.
- Scrollable Console Logs with scrollbar and 1-click Clear.
- Scrollable System Monitor HUD with real-time hardware gauges.
- Drawer Toggle button ("▼ Expand / ▲ Collapse") directly on the command bar.
- Dedicated Stop / Abort button visible in real time while execution is active.
- Settings modal with live connection tester and model discovery.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import threading
import time
from typing import Any

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as exc:
    import sys
    print(
        f"Could not import tkinter ({exc}).\n"
        "Please ensure Tcl/Tk is installed with Python.\n"
        "Run 'python main.py --cli' to use the terminal interface.\n"
    )
    sys.exit(1)

from utils.bootstrap import ensure_dependencies

ensure_dependencies()

from agent.executor import execute_plan
from agent.llm import LLM, ping_backend
from agent.planner import PlanningError, plan, set_last_command
from config import Config
from tools.system import get_system_stats

# ---- Palette & Design --------------------------------------------------
BG = "#0d1117"
HEADER_BG = "#161b22"
PANEL = "#161b22"
PANEL_LIGHT = "#21262d"
BORDER = "#30363d"
BORDER_FOCUS = "#58a6ff"
FG = "#f0f6fc"
MUTED = "#8b949e"
ACCENT = "#238636"
ACCENT_BLUE = "#1f6feb"
DANGER = "#da3633"
WARNING = "#d29922"

STATE_COLORS = {
    "idle": "#8b949e",
    "thinking": "#d29922",
    "running": "#238636",
    "error": "#da3633",
    "aborted": "#f85149",
}

STATE_LABELS = {
    "idle": "Ready",
    "thinking": "Thinking...",
    "running": "Running...",
    "error": "Failed",
    "aborted": "Aborted",
}

# Tools that touch the system in risky ways. They run automatically (the agent
# has full access) — this set only adds a warning badge in the plan preview.
RISKY_TOOLS = {
    "delete_file",
    "delete_files",
    "overwrite_file",
    "install_software",
    "run_command",
    "send_message",
    "send_email",
    "change_system_setting",
    "shutdown_windows",
    "restart_windows",
    "close_windows",
    "close_app",
}

WIN_W = 820
HEADER_H = 32
BAR_H = 56
CHIPS_H = 68
DRAWER_H = 260


def _speak_text(text: str) -> None:
    if not Config.VOICE_FEEDBACK or platform.system() != "Windows":
        return

    def _worker():
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def _hide_console() -> None:
    if platform.system() != "Windows":
        return
    try:
        console = ctypes.windll.kernel32.GetConsoleWindow()
        if console:
            ctypes.windll.user32.ShowWindow(console, 0)  # SW_HIDE
    except Exception:
        pass


class CommandBar(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Windows AI Agent")
        self.overrideredirect(True)
        self.configure(bg=BG)

        self._base_h = HEADER_H + BAR_H + CHIPS_H + 20
        self._drawer_open = False

        # Center on screen, positioned nicely near top
        screen_w = self.winfo_screenwidth()
        start_x = max(10, (screen_w - WIN_W) // 2)
        self.geometry(f"{WIN_W}x{self._base_h}+{start_x}+70")
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.98)
        except tk.TclError:
            pass

        self.llm = LLM()
        self.state = "idle"
        self._pulse_job = None
        self._cancel_event = threading.Event()
        self._active_steps: list[dict] = []
        self._step_widgets: list[dict] = []
        self._command_history: list[str] = self._load_history()
        self._history_idx = -1
        if self._command_history:
            # Let "repeat last command" work even after a restart.
            set_last_command(self._command_history[-1])

        self._build_ui()
        self._enable_universal_dragging()
        self.update_idletasks()
        self._apply_taskbar_style()
        self.bind("<Map>", self._on_map)

        # Keyboard shortcuts
        self.bind("<Escape>", self._on_escape)
        self.bind("<Control-l>", lambda e: self._clear_log())

    # ------------------------------------------------------------- DRAGGING
    def _enable_universal_dragging(self) -> None:
        """Rock-solid root-coordinate dragging that works across child widgets."""
        self._drag_data = {"start_x": 0, "start_y": 0, "win_x": 0, "win_y": 0}

        def on_press(event):
            self._drag_data["start_x"] = event.x_root
            self._drag_data["start_y"] = event.y_root
            self._drag_data["win_x"] = self.winfo_x()
            self._drag_data["win_y"] = self.winfo_y()

        def on_drag(event):
            dx = event.x_root - self._drag_data["start_x"]
            dy = event.y_root - self._drag_data["start_y"]
            new_x = self._drag_data["win_x"] + dx
            new_y = self._drag_data["win_y"] + dy
            # Clamp to keep visible on screen
            new_y = max(0, min(self.winfo_screenheight() - 60, new_y))
            self.geometry(f"+{new_x}+{new_y}")

        # Bind to top header bar and its children
        for w in (self.header_bar, self.title_label, self.drag_hint_label):
            w.bind("<Button-1>", on_press)
            w.bind("<B1-Motion>", on_drag)

        # Also bind to root background
        self.bind("<Button-1>", on_press, add="+")
        self.bind("<B1-Motion>", on_drag, add="+")

    def _apply_taskbar_style(self) -> None:
        if platform.system() == "Windows":
            try:
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                if hwnd:
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

    def _toggle_minimize(self) -> None:
        try:
            self.update_idletasks()
            self.overrideredirect(False)
            self.iconify()
        except Exception:
            self.withdraw()

    def _on_map(self, event=None) -> None:
        try:
            win_state = self.wm_state()
            if win_state == "normal" and not self.overrideredirect():
                self.overrideredirect(True)
                self._apply_taskbar_style()
        except Exception:
            pass

    # ------------------------------------------------------------- UI BUILD
    def _build_ui(self) -> None:
        # 1. Top Header & Drag Bar
        self.header_bar = tk.Frame(self, bg=HEADER_BG, height=HEADER_H, cursor="fleur")
        self.header_bar.pack(fill="x", side="top")
        self.header_bar.pack_propagate(False)

        # Title & Drag Indicator
        title_box = tk.Frame(self.header_bar, bg=HEADER_BG, cursor="fleur")
        title_box.pack(side="left", padx=12)

        self.title_label = tk.Label(
            title_box,
            text="🤖 Windows AI Agent",
            bg=HEADER_BG,
            fg=FG,
            font=("Segoe UI", 9, "bold"),
            cursor="fleur",
        )
        self.title_label.pack(side="left")

        self.drag_hint_label = tk.Label(
            title_box,
            text="  (⋮⋮ Drag to move)",
            bg=HEADER_BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            cursor="fleur",
        )
        self.drag_hint_label.pack(side="left")

        # Window Controls (Minimize & Close)
        ctrls = tk.Frame(self.header_bar, bg=HEADER_BG)
        ctrls.pack(side="right", padx=8)

        min_btn = tk.Label(
            ctrls, text=" — ", bg=HEADER_BG, fg=MUTED, font=("Segoe UI", 9, "bold"), cursor="hand2"
        )
        min_btn.pack(side="left", padx=2)
        min_btn.bind("<Enter>", lambda e: min_btn.configure(fg=FG, bg=PANEL_LIGHT))
        min_btn.bind("<Leave>", lambda e: min_btn.configure(fg=MUTED, bg=HEADER_BG))
        min_btn.bind("<Button-1>", lambda e: self._toggle_minimize())

        close_btn = tk.Label(
            ctrls, text=" ✕ ", bg=HEADER_BG, fg=MUTED, font=("Segoe UI", 9), cursor="hand2"
        )
        close_btn.pack(side="left", padx=2)
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#ffffff", bg=DANGER))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=MUTED, bg=HEADER_BG))
        close_btn.bind("<Button-1>", lambda e: self.destroy())

        # 2. Main Command Bar Frame
        cmd_wrapper = tk.Frame(self, bg=BG)
        cmd_wrapper.pack(fill="x", padx=12, pady=(8, 4))

        self.bar_frame = tk.Frame(
            cmd_wrapper, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        self.bar_frame.pack(fill="x", ipady=4)

        # Settings Gear Button
        self.gear_btn = tk.Label(
            self.bar_frame,
            text=" ⚙️ ",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 12),
            cursor="hand2",
        )
        self.gear_btn.pack(side="left", padx=(10, 4))
        self.gear_btn.bind("<Button-1>", lambda e: self._open_settings())
        self.gear_btn.bind("<Enter>", lambda e: self.gear_btn.configure(fg=FG, bg=PANEL_LIGHT))
        self.gear_btn.bind("<Leave>", lambda e: self.gear_btn.configure(fg=MUTED, bg=PANEL))

        # Status Ring Canvas & Label
        status_box = tk.Frame(self.bar_frame, bg=PANEL)
        status_box.pack(side="left", padx=(4, 8))

        self.status_canvas = tk.Canvas(status_box, width=24, height=24, bg=PANEL, highlightthickness=0)
        self.status_canvas.pack(side="left")
        self._draw_status_dot()

        self.status_label = tk.Label(
            status_box, text="Ready", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)
        )
        self.status_label.pack(side="left", padx=2)

        # Entry Field
        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(
            self.bar_frame,
            textvariable=self.entry_var,
            font=("Segoe UI", 11),
            bg=PANEL_LIGHT,
            fg=FG,
            relief="flat",
            bd=0,
            insertbackground=FG,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.entry.pack(side="left", fill="both", expand=True, padx=8, ipady=6)

        self._set_placeholder("Type a command, or click any quick action below...")
        self.entry.bind("<Return>", lambda e: self._submit())
        self.entry.bind("<Up>", self._history_prev)
        self.entry.bind("<Down>", self._history_next)

        # Abort / Stop Button (Hidden when idle)
        self.stop_btn = tk.Label(
            self.bar_frame,
            text=" ⏹ Stop ",
            bg=DANGER,
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            padx=6,
            pady=4,
            cursor="hand2",
        )
        self.stop_btn.bind("<Button-1>", lambda e: self._abort_execution())

        # Submit / Run Button
        self.enter_btn = tk.Label(
            self.bar_frame,
            text="  ➔  ",
            bg=ACCENT_BLUE,
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self.enter_btn.pack(side="left", padx=(4, 6))
        self.enter_btn.bind("<Button-1>", lambda e: self._submit())
        self.enter_btn.bind("<Enter>", lambda e: self.enter_btn.configure(bg="#388bfd"))
        self.enter_btn.bind("<Leave>", lambda e: self.enter_btn.configure(bg=ACCENT_BLUE))

        # Drawer Toggle Button
        self.toggle_drawer_btn = tk.Label(
            self.bar_frame,
            text=" ▼ Details ",
            bg=PANEL_LIGHT,
            fg=MUTED,
            font=("Segoe UI", 8),
            padx=6,
            pady=5,
            cursor="hand2",
        )
        self.toggle_drawer_btn.pack(side="left", padx=(2, 10))
        self.toggle_drawer_btn.bind("<Button-1>", lambda e: self._toggle_drawer())
        self.toggle_drawer_btn.bind("<Enter>", lambda e: self.toggle_drawer_btn.configure(fg=FG))
        self.toggle_drawer_btn.bind("<Leave>", lambda e: self.toggle_drawer_btn.configure(fg=MUTED))

        # 3. Quick Action Chips Grid (Clean 2 Rows, Fully Visible!)
        self.chips_wrapper = tk.Frame(self, bg=BG)
        self.chips_wrapper.pack(fill="x", padx=12, pady=(4, 6))
        self._build_quick_chips_grid()

        # 4. Collapsible & Scrollable Drawer Frame
        self.drawer = tk.Frame(self, bg=BG)
        self._build_drawer_content()

    # ------------------------------------------------------------- CHIPS GRID
    def _build_quick_chips_grid(self) -> None:
        """Arranges all 10 quick action chips into 2 neat rows so nothing is cut off."""
        row1_chips = [
            ("📝 Note in Notepad", "Open Notepad and write a helpful summary on "),
            ("📊 Excel Table", "Create an Excel table with dummy data about "),
            ("📂 Downloads", "Open downloads folder"),
            ("🔍 Find Files", "Search files for "),
            ("🌐 Search Web", "Search the web for "),
        ]
        row2_chips = [
            ("💻 System Stats", "Show system stats"),
            ("📸 Screenshot", "Take a screenshot"),
            ("🔊 Mute Audio", "Mute volume"),
            ("📋 Read Clipboard", "Read clipboard"),
            ("🖥️ Show Desktop", "Show desktop"),
        ]

        # Row 1
        r1_frame = tk.Frame(self.chips_wrapper, bg=BG)
        r1_frame.pack(fill="x", pady=1)
        for label, prompt in row1_chips:
            self._create_chip_button(r1_frame, label, prompt)

        # Row 2
        r2_frame = tk.Frame(self.chips_wrapper, bg=BG)
        r2_frame.pack(fill="x", pady=2)
        for label, prompt in row2_chips:
            self._create_chip_button(r2_frame, label, prompt)

    def _create_chip_button(self, parent: tk.Frame, label: str, prompt: str) -> None:
        btn = tk.Label(
            parent,
            text=label,
            bg=PANEL,
            fg="#c9d1d9",
            font=("Segoe UI", 8),
            padx=8,
            pady=3,
            cursor="hand2",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        btn.pack(side="left", padx=3, expand=True, fill="x")

        def on_enter(e):
            btn.configure(bg=PANEL_LIGHT, fg=FG, highlightbackground=BORDER_FOCUS)
        def on_leave(e):
            btn.configure(bg=PANEL, fg="#c9d1d9", highlightbackground=BORDER)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", lambda e, p=prompt: self._on_chip_clicked(p))

    def _on_chip_clicked(self, prompt: str) -> None:
        self._clear_placeholder()
        self.entry_var.set(prompt)
        self.entry.focus_set()
        self.entry.icursor("end")
        # Direct execution for complete queries
        if prompt in (
            "Show system stats",
            "Take a screenshot",
            "Mute volume",
            "Read clipboard",
            "Open downloads folder",
            "Show desktop",
        ):
            self._submit()

    # -------------------------------------------------------- DRAWER CONTENT
    def _build_drawer_content(self) -> None:
        # Tab bar
        tab_bar = tk.Frame(self.drawer, bg=BG)
        tab_bar.pack(fill="x", padx=12, pady=(2, 4))

        self.tab_buttons: dict[str, tk.Label] = {}
        for tab_name in ("⚡ Plan & Steps", "📜 Logs", "🖥️ System Monitor"):
            btn = tk.Label(
                tab_bar,
                text=tab_name,
                bg=PANEL if tab_name.startswith("⚡") else BG,
                fg=FG if tab_name.startswith("⚡") else MUTED,
                font=("Segoe UI", 9, "bold" if tab_name.startswith("⚡") else "normal"),
                padx=12,
                pady=4,
                cursor="hand2",
                highlightbackground=BORDER,
                highlightthickness=1,
            )
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>", lambda e, t=tab_name: self._switch_tab(t))
            self.tab_buttons[tab_name] = btn

        close_drawer_btn = tk.Label(
            tab_bar, text="▲ Collapse", bg=BG, fg=MUTED, font=("Segoe UI", 8), cursor="hand2"
        )
        close_drawer_btn.pack(side="right", padx=4)
        close_drawer_btn.bind("<Button-1>", lambda e: self._close_drawer())

        # Main Container
        self.tab_container = tk.Frame(
            self.drawer, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        self.tab_container.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # ---------------- 1. Plan View (Fully Scrollable!) ----------------
        self.plan_frame = tk.Frame(self.tab_container, bg=PANEL)

        plan_top = tk.Frame(self.plan_frame, bg=PANEL, padx=10, pady=6)
        plan_top.pack(fill="x")
        self.plan_title = tk.Label(
            plan_top,
            text="Ready for instructions.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9, "italic"),
        )
        self.plan_title.pack(side="left")

        self.plan_actions_frame = tk.Frame(plan_top, bg=PANEL)
        self.run_plan_btn = tk.Button(
            self.plan_actions_frame,
            text="▶ Execute Plan",
            bg=ACCENT,
            fg="#ffffff",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=2,
            command=self._execute_active_plan,
        )
        self.run_plan_btn.pack(side="left", padx=(0, 6))

        self.cancel_plan_btn = tk.Button(
            self.plan_actions_frame,
            text="Cancel",
            bg=PANEL_LIGHT,
            fg=MUTED,
            font=("Segoe UI", 8),
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=2,
            command=self._cancel_active_plan,
        )
        self.cancel_plan_btn.pack(side="left")

        # Scrollable Canvas for Steps
        steps_scroll_frame = tk.Frame(self.plan_frame, bg=PANEL)
        steps_scroll_frame.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.steps_canvas = tk.Canvas(
            steps_scroll_frame, bg=PANEL, highlightthickness=0, bd=0
        )
        self.steps_scrollbar = ttk.Scrollbar(
            steps_scroll_frame, orient="vertical", command=self.steps_canvas.yview
        )
        self.steps_inner = tk.Frame(self.steps_canvas, bg=PANEL)

        self.steps_canvas.create_window((0, 0), window=self.steps_inner, anchor="nw")
        self.steps_canvas.configure(yscrollcommand=self.steps_scrollbar.set)

        self.steps_canvas.pack(side="left", fill="both", expand=True)
        self.steps_scrollbar.pack(side="right", fill="y")

        self.steps_inner.bind(
            "<Configure>",
            lambda e: self.steps_canvas.configure(scrollregion=self.steps_canvas.bbox("all")),
        )
        self._bind_mousewheel(self.steps_canvas)
        self._bind_mousewheel(self.steps_inner)

        # ---------------- 2. Logs View (Scrollable Text) ----------------
        self.logs_frame = tk.Frame(self.tab_container, bg=PANEL)
        log_header = tk.Frame(self.logs_frame, bg=PANEL, padx=8, pady=4)
        log_header.pack(fill="x")

        log_lbl = tk.Label(log_header, text="Execution & Diagnostic Logs", bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        log_lbl.pack(side="left")

        clear_btn = tk.Label(
            log_header, text="🧹 Clear Logs", bg=PANEL_LIGHT, fg=MUTED, font=("Segoe UI", 8), padx=6, pady=2, cursor="hand2"
        )
        clear_btn.pack(side="right")
        clear_btn.bind("<Button-1>", lambda e: self._clear_log())

        log_body = tk.Frame(self.logs_frame, bg=PANEL)
        log_body.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.log_text = tk.Text(
            log_body,
            height=8,
            bg="#0d1117",
            fg="#c9d1d9",
            bd=0,
            font=("Consolas", 9),
            state="disabled",
            padx=8,
            pady=6,
            wrap="word",
        )
        log_scroll = ttk.Scrollbar(log_body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # ---------------- 3. System Monitor (Scrollable) ----------------
        self.system_frame = tk.Frame(self.tab_container, bg=PANEL)
        sys_scroll_frame = tk.Frame(self.system_frame, bg=PANEL)
        sys_scroll_frame.pack(fill="both", expand=True, padx=10, pady=8)

        sys_canvas = tk.Canvas(sys_scroll_frame, bg=PANEL, highlightthickness=0, bd=0)
        sys_scrollbar = ttk.Scrollbar(sys_scroll_frame, orient="vertical", command=sys_canvas.yview)
        sys_inner = tk.Frame(sys_canvas, bg=PANEL)

        sys_canvas.create_window((0, 0), window=sys_inner, anchor="nw")
        sys_canvas.configure(yscrollcommand=sys_scrollbar.set)

        sys_canvas.pack(side="left", fill="both", expand=True)
        sys_scrollbar.pack(side="right", fill="y")

        sys_inner.bind("<Configure>", lambda e: sys_canvas.configure(scrollregion=sys_canvas.bbox("all")))
        self._bind_mousewheel(sys_canvas)
        self._bind_mousewheel(sys_inner)

        self.sys_info_label = tk.Label(
            sys_inner,
            text="Gathering system telemetry...",
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 9),
            justify="left",
        )
        self.sys_info_label.pack(anchor="w", pady=(0, 8))

        refresh_sys_btn = tk.Button(
            sys_inner,
            text="🔄 Refresh System Stats",
            bg=PANEL_LIGHT,
            fg=FG,
            font=("Segoe UI", 8),
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=3,
            command=self._refresh_system_hud,
        )
        refresh_sys_btn.pack(anchor="w")

        # Start with Plan frame
        self.current_tab = "⚡ Plan & Steps"
        self.plan_frame.pack(fill="both", expand=True)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        """Enables smooth mouse-wheel scrolling for canvas widgets."""
        def _on_mousewheel(event):
            # Windows delivers event.delta in multiples of 120
            widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        widget.bind("<MouseWheel>", _on_mousewheel)

    def _switch_tab(self, target_tab: str) -> None:
        self.current_tab = target_tab
        for name, btn in self.tab_buttons.items():
            if name == target_tab:
                btn.configure(bg=PANEL, fg=FG, font=("Segoe UI", 9, "bold"))
            else:
                btn.configure(bg=BG, fg=MUTED, font=("Segoe UI", 9, "normal"))

        self.plan_frame.pack_forget()
        self.logs_frame.pack_forget()
        self.system_frame.pack_forget()

        if target_tab.startswith("⚡"):
            self.plan_frame.pack(fill="both", expand=True)
        elif target_tab.startswith("📜"):
            self.logs_frame.pack(fill="both", expand=True)
        else:
            self.system_frame.pack(fill="both", expand=True)
            self._refresh_system_hud()

    def _toggle_drawer(self) -> None:
        if self._drawer_open:
            self._close_drawer()
        else:
            self._open_drawer()

    def _open_drawer(self) -> None:
        if not self._drawer_open:
            self._drawer_open = True
            self.drawer.pack(fill="both", expand=True)
            self.toggle_drawer_btn.configure(text=" ▲ Details ", fg=FG)
            self.geometry(f"{WIN_W}x{self._base_h + DRAWER_H}+{self.winfo_x()}+{self.winfo_y()}")

    def _close_drawer(self) -> None:
        if self._drawer_open:
            self._drawer_open = False
            self.drawer.pack_forget()
            self.toggle_drawer_btn.configure(text=" ▼ Details ", fg=MUTED)
            self.geometry(f"{WIN_W}x{self._base_h}+{self.winfo_x()}+{self.winfo_y()}")

    def _refresh_system_hud(self) -> None:
        res = get_system_stats()
        stats = res.get("stats", {})
        lines = [f"OS: {stats.get('os', 'Windows')} | CPU Cores: {stats.get('cpu_count', 1)}"]
        if "ram" in stats:
            r = stats["ram"]
            lines.append(f"RAM Usage: {r['used_gb']} GB / {r['total_gb']} GB ({r['percent']}%)")
        if "disk_c" in stats:
            d = stats["disk_c"]
            lines.append(f"Storage (C:): {d['free_gb']} GB Free / {d['total_gb']} GB Total ({d['used_percent']}% used)")
        if "battery" in stats:
            b = stats["battery"]
            lines.append(f"Battery: {b['percent']}% ({'Charging ⚡' if b['charging'] else 'On Battery'})")
        if "active_window" in stats:
            lines.append(f"Active Window: '{stats['active_window']}'")

        self.sys_info_label.configure(text="\n\n".join(lines))

    # -------------------------------------------------------- STATUS & ICONS
    def _draw_status_dot(self) -> None:
        self.status_canvas.delete("all")
        color = STATE_COLORS.get(self.state, STATE_COLORS["idle"])
        self.status_canvas.create_oval(4, 4, 20, 20, outline=color, width=2)
        if self.state in ("thinking", "running"):
            self.status_canvas.create_arc(4, 4, 20, 20, start=90, extent=120, style="arc", outline=color, width=2)
        else:
            self.status_canvas.create_oval(8, 8, 16, 16, fill=color, outline=color)

    def _animate_pulse(self) -> None:
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        if self.state not in ("thinking", "running"):
            return

        angle = {"deg": 0}

        def step():
            if self.state not in ("thinking", "running"):
                return
            self.status_canvas.delete("all")
            color = STATE_COLORS[self.state]
            self.status_canvas.create_oval(4, 4, 20, 20, outline="#30363d", width=2)
            self.status_canvas.create_arc(4, 4, 20, 20, start=angle["deg"], extent=90, style="arc", outline=color, width=2)
            angle["deg"] = (angle["deg"] + 25) % 360
            self._pulse_job = self.after(50, step)

        step()

    def _set_state(self, state: str) -> None:
        self.state = state
        self._draw_status_dot()
        self._animate_pulse()
        lbl_text = STATE_LABELS.get(state, state.title())
        self.status_label.configure(text=lbl_text, fg=STATE_COLORS.get(state, MUTED))

        # Show stop button while running
        if state == "running":
            self.stop_btn.pack(side="left", padx=4)
        else:
            self.stop_btn.pack_forget()
        self.update_idletasks()

    # ------------------------------------------------------------- PLACEHOLDER
    def _set_placeholder(self, text: str) -> None:
        self._placeholder_text = text
        self._is_placeholder = True
        self.entry.insert(0, text)
        self.entry.configure(fg=MUTED)

        def clear(e=None):
            if self._is_placeholder:
                self.entry.delete(0, "end")
                self.entry.configure(fg=FG)
                self._is_placeholder = False

        def restore(e=None):
            if not self.entry.get().strip():
                self.entry.insert(0, self._placeholder_text)
                self.entry.configure(fg=MUTED)
                self._is_placeholder = True

        self.entry.bind("<FocusIn>", clear, add="+")
        self.entry.bind("<FocusOut>", restore, add="+")

    def _clear_placeholder(self) -> None:
        if self._is_placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(fg=FG)
            self._is_placeholder = False

    # ------------------------------------------------------------- HISTORY
    def _load_history(self) -> list[str]:
        try:
            data = json.loads(Config.HISTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [str(c) for c in data if str(c).strip()][-200:]

    def _save_history(self) -> None:
        try:
            Config.HISTORY_PATH.write_text(
                json.dumps(self._command_history[-200:], indent=0), encoding="utf-8"
            )
        except OSError:
            pass

    def _history_prev(self, event=None) -> str:
        if not self._command_history:
            return "break"
        if self._history_idx < len(self._command_history) - 1:
            self._history_idx += 1
            cmd = self._command_history[-(self._history_idx + 1)]
            self._clear_placeholder()
            self.entry_var.set(cmd)
            self.entry.icursor("end")
        return "break"

    def _history_next(self, event=None) -> str:
        if not self._command_history:
            return "break"
        if self._history_idx > 0:
            self._history_idx -= 1
            cmd = self._command_history[-(self._history_idx + 1)]
            self._clear_placeholder()
            self.entry_var.set(cmd)
            self.entry.icursor("end")
        elif self._history_idx == 0:
            self._history_idx = -1
            self.entry_var.set("")
        return "break"

    # ------------------------------------------------------------- LOGGING
    def _log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _on_escape(self, event=None) -> None:
        if self.state in ("thinking", "running"):
            self._abort_execution()
        elif self._drawer_open:
            self._close_drawer()

    # ------------------------------------------------------------- SUBMIT & RUN
    def _submit(self) -> None:
        if self._is_placeholder:
            return
        cmd = self.entry_var.get().strip()
        if not cmd:
            return

        # Add to history (persisted so it survives restarts)
        if not self._command_history or self._command_history[-1] != cmd:
            self._command_history.append(cmd)
            self._save_history()
        self._history_idx = -1

        self.entry.delete(0, "end")
        self._is_placeholder = False
        self._cancel_event.clear()

        self._open_drawer()
        self._switch_tab("⚡ Plan & Steps")
        self._log(f"\nUser: {cmd}")

        threading.Thread(target=self._run_planning, args=(cmd,), daemon=True).start()

    def _run_planning(self, command: str) -> None:
        self._set_state("thinking")
        self._update_plan_display_loading(command)

        try:
            steps = plan(command, llm=self.llm)
        except PlanningError as exc:
            self._log(f"[ERROR] {exc}")
            self._set_state("error")
            self._render_plan_error(str(exc))
            return
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._set_state("error")
            self._render_plan_error(str(exc))
            return

        self._active_steps = steps
        self._render_plan_steps(steps)

        # Full access: execute immediately, no confirmation prompt.
        self._execute_active_plan()

    def _update_plan_display_loading(self, command: str) -> None:
        self.plan_title.configure(text=f"Planning: \"{command}\"...", fg=WARNING)
        for w in self.steps_inner.winfo_children():
            w.destroy()
        self.plan_actions_frame.pack_forget()

    def _render_plan_error(self, err_text: str) -> None:
        self.plan_title.configure(text="Planning Failed", fg=DANGER)
        for w in self.steps_inner.winfo_children():
            w.destroy()
        err_lbl = tk.Label(
            self.steps_inner,
            text=err_text,
            bg=PANEL,
            fg=DANGER,
            wraplength=WIN_W - 80,
            justify="left",
        )
        err_lbl.pack(anchor="w", pady=4)

    def _render_plan_steps(self, steps: list[dict]) -> None:
        self.plan_title.configure(text=f"Plan generated ({len(steps)} steps):", fg=FG)
        for w in self.steps_inner.winfo_children():
            w.destroy()
        self._step_widgets.clear()

        for i, step in enumerate(steps, start=1):
            row = tk.Frame(
                self.steps_inner, bg=PANEL_LIGHT, padx=8, pady=4, highlightbackground=BORDER, highlightthickness=1
            )
            row.pack(fill="x", pady=2, padx=2)

            num_lbl = tk.Label(
                row, text=f"{i}.", bg=PANEL_LIGHT, fg=MUTED, font=("Segoe UI", 9, "bold"), width=3
            )
            num_lbl.pack(side="left")

            tool_text = f"⚠ {step['tool']}" if step["tool"] in RISKY_TOOLS else step["tool"]
            tool_lbl = tk.Label(
                row, text=tool_text, bg=PANEL_LIGHT, fg=WARNING if step["tool"] in RISKY_TOOLS else BORDER_FOCUS, font=("Consolas", 9, "bold")
            )
            tool_lbl.pack(side="left", padx=4)

            args_str = ", ".join(f"{k}={v}" for k, v in step.get("arguments", {}).items())
            if len(args_str) > 65:
                args_str = args_str[:65] + "..."
            args_lbl = tk.Label(row, text=args_str, bg=PANEL_LIGHT, fg=MUTED, font=("Segoe UI", 8))
            args_lbl.pack(side="left", padx=4)

            status_lbl = tk.Label(
                row, text="⏳ Pending", bg=PANEL_LIGHT, fg=MUTED, font=("Segoe UI", 8), width=12, anchor="e"
            )
            status_lbl.pack(side="right")

            self._step_widgets.append({"row": row, "status_lbl": status_lbl})

        self.plan_actions_frame.pack(side="right")
        self.steps_canvas.update_idletasks()
        self.steps_canvas.configure(scrollregion=self.steps_canvas.bbox("all"))

    def _execute_active_plan(self) -> None:
        if not self._active_steps:
            return
        self.plan_actions_frame.pack_forget()
        self._set_state("running")
        self._cancel_event.clear()

        threading.Thread(target=self._run_execution_worker, daemon=True).start()

    def _run_execution_worker(self) -> None:
        def on_step_update(step_idx: int, total: int, tool_name: str, status: str, result: dict | None) -> None:
            if 0 < step_idx <= len(self._step_widgets):
                lbl = self._step_widgets[step_idx - 1]["status_lbl"]
                if status == "running":
                    self.after(0, lambda: lbl.configure(text="⚡ Running...", fg=WARNING))
                elif status == "ok":
                    self.after(0, lambda: lbl.configure(text="✅ Done", fg=ACCENT))
                elif status == "failed":
                    self.after(0, lambda: lbl.configure(text="❌ Failed", fg=DANGER))
                elif status == "cancelled":
                    self.after(0, lambda: lbl.configure(text="⏹️ Cancelled", fg=MUTED))

        success = execute_plan(
            self._active_steps,
            log_fn=self._log,
            on_step_update=on_step_update,
            cancel_event=self._cancel_event,
        )

        final_state = "idle" if success else ("aborted" if self._cancel_event.is_set() else "error")
        self._set_state(final_state)

        if success:
            _speak_text("Task completed successfully")
        elif self._cancel_event.is_set():
            _speak_text("Task aborted")

    def _cancel_active_plan(self) -> None:
        self._active_steps.clear()
        self.plan_actions_frame.pack_forget()
        self.plan_title.configure(text="Plan cancelled.", fg=MUTED)
        self._set_state("idle")

    def _abort_execution(self) -> None:
        self._cancel_event.set()
        self._set_state("aborted")
        self._log("[USER] Requested execution stop.")

    # ------------------------------------------------------------- SETTINGS MODAL
    def _open_settings(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Agent Settings")
        dlg.geometry("540x460")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        # Center on screen
        dlg.geometry(f"+{self.winfo_x() + 40}+{self.winfo_y() + 30}")

        title = tk.Label(dlg, text="⚙️ Agent Settings", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w", padx=20, pady=(16, 12))

        form = tk.Frame(dlg, bg=BG)
        form.pack(fill="both", expand=True, padx=20)

        # Backend Selector
        tk.Label(form, text="LLM Backend:", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        backend_var = tk.StringVar(value=Config.LLM_BACKEND)
        backend_combo = ttk.Combobox(form, textvariable=backend_var, values=["ollama", "lmstudio", "llamacpp", "openai"], state="readonly", width=32)
        backend_combo.grid(row=0, column=1, sticky="w", pady=4)

        # Host URL
        tk.Label(form, text="Host / Base URL:", bg=BG, fg=FG, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        host_var = tk.StringVar(value=Config.OLLAMA_HOST if Config.LLM_BACKEND == "ollama" else (Config.LMSTUDIO_HOST if Config.LLM_BACKEND == "lmstudio" else Config.OPENAI_BASE_URL))
        host_entry = tk.Entry(form, textvariable=host_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", highlightbackground=BORDER, highlightthickness=1, width=34)
        host_entry.grid(row=1, column=1, sticky="w", pady=4)

        # Model Name
        tk.Label(form, text="Model Name:", bg=BG, fg=FG, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        model_var = tk.StringVar(value=Config.OLLAMA_MODEL if Config.LLM_BACKEND == "ollama" else Config.OPENAI_MODEL)
        model_entry = tk.Entry(form, textvariable=model_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", highlightbackground=BORDER, highlightthickness=1, width=34)
        model_entry.grid(row=2, column=1, sticky="w", pady=4)

        # API Key (for OpenAI / Cloud)
        tk.Label(form, text="API Key (optional):", bg=BG, fg=FG, font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", pady=4)
        key_var = tk.StringVar(value=Config.OPENAI_API_KEY)
        key_entry = tk.Entry(form, textvariable=key_var, show="•", bg=PANEL, fg=FG, insertbackground=FG, relief="flat", highlightbackground=BORDER, highlightthickness=1, width=34)
        key_entry.grid(row=3, column=1, sticky="w", pady=4)

        # Test Connection button & status
        test_frame = tk.Frame(form, bg=BG)
        test_frame.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 12))

        test_status_lbl = tk.Label(test_frame, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))

        def run_test():
            test_status_lbl.configure(text="Pinging backend...", fg=WARNING)
            b = backend_var.get()
            h = host_var.get().strip()
            m = model_var.get().strip()
            k = key_var.get().strip()

            def _test():
                ok, msg = ping_backend(b, h, m, k)
                color = ACCENT if ok else DANGER
                icon = "🟢" if ok else "🔴"
                dlg.after(0, lambda: test_status_lbl.configure(text=f"{icon} {msg}", fg=color))

            threading.Thread(target=_test, daemon=True).start()

        test_btn = tk.Button(test_frame, text="🔍 Test Connection", bg=PANEL_LIGHT, fg=FG, font=("Segoe UI", 8), relief="flat", cursor="hand2", command=run_test)
        test_btn.pack(side="left", padx=(0, 10))
        test_status_lbl.pack(side="left")

        # Toggles
        voice_var = tk.BooleanVar(value=Config.VOICE_FEEDBACK)
        voice_chk = tk.Checkbutton(form, text="Enable Voice / Audio announcements (TTS)", variable=voice_var, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, font=("Segoe UI", 9))
        voice_chk.grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        fast_var = tk.BooleanVar(value=Config.FAST_PATH_ENABLED)
        fast_chk = tk.Checkbutton(form, text="Fast-path instant execution for common actions", variable=fast_var, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, font=("Segoe UI", 9))
        fast_chk.grid(row=6, column=0, columnspan=2, sticky="w", pady=2)

        # Save & Cancel Buttons
        btns = tk.Frame(dlg, bg=BG)
        btns.pack(fill="x", padx=20, pady=(12, 16))

        def save_and_close():
            Config.LLM_BACKEND = backend_var.get().strip()
            Config.VOICE_FEEDBACK = voice_var.get()
            Config.FAST_PATH_ENABLED = fast_var.get()

            if Config.LLM_BACKEND == "ollama":
                Config.OLLAMA_HOST = host_var.get().strip()
                Config.OLLAMA_MODEL = model_var.get().strip()
            elif Config.LLM_BACKEND == "lmstudio":
                Config.LMSTUDIO_HOST = host_var.get().strip()
            elif Config.LLM_BACKEND in ("openai", "custom", "cloud"):
                Config.OPENAI_BASE_URL = host_var.get().strip()
                Config.OPENAI_MODEL = model_var.get().strip()
            Config.OPENAI_API_KEY = key_var.get().strip()

            Config.save_settings()  # persist across restarts
            self.llm = LLM()
            dlg.destroy()

        save_btn = tk.Button(btns, text="Save Settings", bg=ACCENT, fg="#ffffff", font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2", padx=14, pady=4, command=save_and_close)
        save_btn.pack(side="right", padx=(8, 0))

        cancel_btn = tk.Button(btns, text="Cancel", bg=PANEL_LIGHT, fg=MUTED, font=("Segoe UI", 9), relief="flat", cursor="hand2", padx=10, pady=4, command=dlg.destroy)
        cancel_btn.pack(side="right")


if __name__ == "__main__":
    _hide_console()
    CommandBar().mainloop()
