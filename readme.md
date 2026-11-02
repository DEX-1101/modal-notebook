# Modal Notebook (GUI & CLI)

A lightweight, modern application to launch, manage, and sync JupyterLab notebook environments on [Modal](https://modal.com) cloud GPUs.

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
