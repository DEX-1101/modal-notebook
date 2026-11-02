# Modal Notebook (GUI & CLI)

A lightweight, modern application to launch, manage, and sync JupyterLab notebook environments on [Modal](https://modal.com) cloud GPUs.

## ✨ Features

* ⚡ **One-Click JupyterLab Launch**: Spin up JupyterLab on cloud GPUs (T4, L4, A100, H100, B200) or CPU in seconds.
* 🖥️ **Dual Modes**: Launch via the PySide6 Desktop GUI or an interactive Windows CLI batch menu.
* 🔄 **Notebook Auto-Sync**: Keep your local `_notebook` folder and remote Modal drive automatically synchronized.
* 🔒 **Token Vault**: Store API keys (Hugging Face, Civitai, W&B, OpenAI) securely using Windows DPAPI and sync them across Modal accounts.
* 📁 **Remote Volume Browser**: Upload, download, browse, and edit persistent files on your Modal Volume.
* ⏱️ **Auto-Idle Guard**: Auto-stops instances after a set period of inactivity to prevent unexpected charges.
* 📊 **Usage & Cost Tracking**: Monitor monthly credit usage and account status.

## ⚡ Quick Start (Windows)

### Prerequisites
Install [Python 3.10+](https://www.python.org/) and make sure to check **"Add python.exe to PATH"** during installation.

### Option 1: Desktop GUI (Recommended)
Double-click `start_gui.bat`. It will automatically check for and install missing dependencies (like `PySide6`), then launch the desktop interface.

### Option 2: Interactive CLI Menu
Double-click `start_menu.bat` for an interactive command-line interface with options to setup Modal, start sessions, download files, or stop running apps.

### Option 3: Manual Execution
If you prefer running commands directly in your terminal:

```bash
# 1. Install dependencies
pip install PySide6 modal

# 2. Login to Modal (first-time setup)
modal setup

# 3. Launch GUI
python modal_gui.py
```

## 📁 Repository Structure

```
├── modal_gui.py            # PySide6 Desktop GUI application
├── modal_jupyter.py        # Backend script executed on Modal containers
├── start_gui.bat           # One-click Windows GUI launcher (auto-installs PySide6)
├── start_menu.bat          # Interactive Windows batch CLI menu
└── _notebook/              # Local folder for synced .ipynb files
```

## ⚙️ Configuration & Customization

* **GPU & Hardware**: Select your target GPU directly from the GUI Home tab or CLI setup menu.
* **Persistent Storage**: All files inside `/root/drive` on Modal persist between session resets.
* **Default Notebook**: Place your `.ipynb` files into the `_notebook/` directory to have them loaded automatically.