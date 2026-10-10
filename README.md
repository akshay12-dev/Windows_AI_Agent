# Windows AI Agent

A local, extensible Windows AI agent that turns natural-language commands into safe, structured actions on your PC.

```
LLM = brain/planner
Python tools = hands
Windows = environment
```

The LLM never runs arbitrary code — it can only call tools from a fixed registry (`agent/router.py`).

## ✨ Interactive & Advanced Features

### 1. Interactive Command HUD (`gui.py`)
- **Quick Action Chips**: 1-click interactive pills:
  - 📝 **Note in Notepad**
  - 📊 **Excel Table**
  - 💻 **PC Stats**
  - 📸 **Screenshot**
  - 🔍 **Find Files**
  - 🌐 **Search Web**
  - 🔊 **Mute Audio**
  - 📋 **Read Clipboard**
  - 📂 **Downloads Folder**
- **Interactive Plan Preview Card**: Inspect the step-by-step plan before execution with step numbers, tool names, arguments, and live status badges (`⏳ Pending` ➔ `⚡ Running...` ➔ `✅ Done` / `❌ Failed`).
- **Interactive Run & Abort Controls**:
  - `▶ Execute Plan`: Run the generated steps.
  - `⏹ Stop / Abort`: Interrupt and cancel any running plan mid-flight immediately.
- **Up/Down Arrow History**: Cycle through previously typed commands like a modern terminal or Spotlight search. History is saved to `command_history.json` and restored on the next launch.
- **Collapsible Tabbed Drawer**:
  - **⚡ Plan & Steps**: Live visual step tracking and status badges.
  - **📜 Logs**: Output stream with one-click "Clear Logs".
  - **🖥️ System Monitor**: Real-time PC telemetry (RAM usage, C: drive disk space, battery charging status, active window).
- **Settings Dialog (Gear Icon)**:
  - Switch backends: **Ollama**, **LM Studio**, **llama.cpp**, or **OpenAI / Cloud APIs**.
  - Configure Host URL, Model name, and optional API key.
  - **Test Connection** button: Pings your backend with live health status (`🟢 Connected` / `🔴 Error`).
  - Toggle Voice feedback (TTS) and Fast-path execution.
  - Settings are saved to `settings.json` and restored on the next launch.
- **Voice Feedback (TTS)**: Audible completion and status announcements via Windows SAPI.

### 2. Fast-Path Instant Execution
High-frequency single-action commands execute in **<0.01 seconds** without waiting for local LLM planning:
- "system stats", "pc status", "battery level"
- "take screenshot", "screen grab"
- "mute", "unmute", "volume up", "volume down"
- "play pause", "next track", "previous track"
- "show desktop", "minimize all", "lock screen"
- "read clipboard", "open downloads folder", "open documents"
- "open calculator", "open notepad", "open chrome", "open paint"
- "create 10 new folders", "create new folder named Reports"
- "close all open files", "close all explorer tabs", "close all file explorer windows"

### 3. Expanded Windows Tools
- **System Monitoring** (`tools/system.py`): Live RAM, CPU core count, disk usage, battery status, screen dimensions, active foreground window.
- **System Control** (`tools/system.py`): Volume up/down/mute, media playback controls, show desktop (Win+D), workstation lock.
- **Browser Navigation** (`tools/system.py`): Direct URL launching (`open_url`).
- **Clipboard Management** (`tools/clipboard.py`): Read current clipboard text or copy text/summaries to clipboard.
- **Safe File Access** (`tools/file_ops.py`): Open folders in File Explorer (`open_folder`), create one or many folders — including in the folder currently open in File Explorer (`create_folder`), and preview file contents safely (`read_file`).
- **Window Management** (`tools/windows.py`): Open/close/focus/maximize/minimize windows, read window text, capture screenshots. Supported apps include Notepad, Excel, Word, Chrome, Edge, Calculator, Paint, CMD, PowerShell, Terminal, VS Code, and Explorer.
- **Spreadsheet Generation** (`tools/excel.py`): Generate structured tables and open in Excel.
- **Web & File Search** (`tools/web_search.py`, `tools/file_search.py`): DuckDuckGo search, local file crawler.

## Requirements

- **Windows 10/11**
- Python 3.10+
- A local or cloud LLM backend (Ollama, LM Studio, llama.cpp, or OpenAI-compatible endpoint)

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
python main.py            # Launch interactive GUI (auto-falls-back to CLI on failure)
python main.py --cli      # Force terminal interface
python gui.py             # Launch GUI standalone
pythonw main.py           # Launch GUI cleanly without console window
```

## Safety

The agent runs every planned step immediately — there are no confirmation
prompts, so the AI has full access to the registered tools. Execution is still
constrained to the fixed tool registry: the LLM cannot execute arbitrary shell
code or call anything outside `agent/router.py`. Steps that touch the system in
risky ways are flagged with a `⚠` badge in the plan preview for visibility.
`close_app` / `close_windows` verify that a window actually closed before
reporting success.
