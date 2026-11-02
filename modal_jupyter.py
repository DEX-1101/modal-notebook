"""
Colab-style JupyterLab on Modal  (replacement for the removed Modal Notebooks).

You get a normal JupyterLab: create or upload ANY notebook, write code in cells,
use "!" shell commands, open a terminal, install packages with "!pip install ...".
Everything you save in your DRIVE folder is kept between sessions (it is a permanent Modal Volume).

Usage:
    modal run modal_jupyter.py                      # stops itself after IDLE_MINUTES without activity
    modal run modal_jupyter.py --idle-minutes 90    # change that for this run (0 = never stop by itself)
    modal run modal_jupyter.py --reset         # overwrite the default notebook with your local copy

Keep this terminal open and open the printed link in your browser.
Stop billing: press Ctrl+C here (or use the Stop button in the app).
If it is still running: `modal app list`, then `modal app stop <App ID>`.

Download files from your storage:
    modal volume get modal-root notebooks ./notebooks_from_modal
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import modal

# =============================================================================
# SETTINGS - change things here
# =============================================================================

# ---- GPU --------------------------------------------------------------------
# Pick ONE. Bigger GPU = faster + more VRAM, but costs more per hour.
#   "T4"          16 GB   cheapest, slow (small models only)
#   "L4"          24 GB   cheap, decent
#   "A10G"        24 GB   cheap, decent
#   "L40S"        48 GB   best value for SDXL / Anima  <- default
#   "A100-40GB"   40 GB   fast
#   "A100-80GB"   80 GB   fast, lots of VRAM (use if you run out of memory)
#   "H100"        80 GB   fastest common option
#   "H200"       141 GB   very large jobs
#   "B200"       180 GB   newest / most expensive
#   None                  no GPU (CPU only, for testing the setup)
# You can also give a fallback list, e.g. ["L40S", "A100-80GB"]
GPU = "L4"

# ---- Session ------------------------------------------------------------------
# There is no fixed time limit: the session runs until you stop it. To avoid paying for a forgotten
# session it stops by itself after this many minutes WITHOUT ACTIVITY (no code running, nothing typed,
# no terminal use). 0 = never stop by itself. (Modal itself ends any session after 24 hours.)
IDLE_MINUTES = 180
CPU_CORES = None       # None = Modal default, or a number like 4
MEMORY_MB = None       # None = Modal default, or e.g. 32768 for 32 GB RAM
PYTHON_VERSION = "3.11"  # "3.10", "3.11", "3.12"  (3.11 matches your notebook)

# ---- Notebooks ----------------------------------------------------------------
# Your notebooks live in the "notebooks" folder of your drive (see below).
NOTEBOOK_FILE = "lora-trainer-backend-2.ipynb"   # copied there on the first run ("" = skip)
LOCAL_NOTEBOOK_DIR = "_notebook"                 # folder next to this script that holds your notebooks
RESET_NOTEBOOK = False   # True = overwrite that notebook with your local file every run
                         # (same as running with --reset)
SCRATCH_NOTEBOOK = True  # create an empty "scratch.ipynb" (Colab-style) if it is missing

# ---- Your drive: a permanent folder ---------------------------------------------
# (Advanced settings: the desktop app no longer shows them. Browse, edit and delete everything in your
#  drive from the app's Volume page.)
# One folder inside /root that is kept between sessions. Everything you save in it is still there
# next time, and your notebooks live in it too. JupyterLab opens inside it, like your own drive.
# Use any name you like (letters, numbers, - . _).
DRIVE_FOLDER = "drive"
# Optional shortcuts, for notebooks that use fixed paths such as /root/models: each name listed here
# becomes a shortcut in /root that points into your drive, so that folder is kept too (and it is
# created in your drive). Empty = nothing extra is created.   Example: SHORTCUTS = ["models", "outputs"]
SHORTCUTS = []
# Keep downloaded models and caches (Hugging Face, torch, pip) in your drive, in a ".cache" folder,
# so they are not downloaded again every session. Off = no ".cache" folder is created.
KEEP_CACHES = False
STORAGE_VOLUME = "modal-root"   # name of the permanent Volume behind your drive
VOLUME_VERSION = 1              # 1 = stable (max ~500k files), 2 = beta (no file limit).
                                # Cannot be changed for an existing volume: use a new name.
COMMIT_EVERY_SECONDS = 60       # how often changes are saved while running

# ---- Tokens (Modal secrets) ---------------------------------------------------
# Names of the Modal secrets that your notebooks receive. Every key inside a secret becomes an
# environment variable (for example HF_TOKEN -> os.environ["HF_TOKEN"]).
# Manage them in the desktop app (Tokens page) or by hand:
#   modal secret create huggingface HF_TOKEN=hf_xxx
#   modal secret create civitai CIVITAI_API_KEY=xxx
# Then list the names here:  SECRETS = ["huggingface", "civitai"]
# Each name must exist on your Modal account, otherwise the session cannot start.
SECRETS = []

# ---- Installed software ----------------------------------------------------------
# System packages (apt)
APT_PACKAGES = [
    "git", "curl", "wget", "aria2", "unzip", "p7zip-full",
    "build-essential", "libgl1", "libglib2.0-0",
]
# Python packages for the Jupyter kernel (the trainer makes its own venv).
# Add more here (e.g. "torch") to have them ready in every notebook, or just
# run  !pip install ...  inside a notebook.
PIP_PACKAGES = [
    "jupyterlab", "ipywidgets", "tomlkit", "huggingface_hub",
    "pillow", "psutil", "numpy", "matplotlib",
]

# ---- Jupyter ------------------------------------------------------------------
# Theme of JupyterLab. Pick ONE:
#   "JupyterLab Dark"                 <- default
#   "JupyterLab Light"
#   "JupyterLab Dark High Contrast"
#   None                              leave JupyterLab's own default (light)
THEME = "JupyterLab Dark"
# JupyterLab saves your notebooks by itself every N seconds (0 = JupyterLab's own default, 120).
# The desktop app copies them to your PC automatically while a session runs.
AUTOSAVE_SECONDS = 30
JUPYTER_PORT = 8888
APP_NAME = "modal-jupyter"

# =============================================================================
# END OF SETTINGS
# =============================================================================

if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(DRIVE_FOLDER)):
    raise SystemExit(f'DRIVE_FOLDER "{DRIVE_FOLDER}" is not a valid folder name (use letters, numbers, - . _).')
DRIVE_PATH = f"/root/{DRIVE_FOLDER}"
NOTEBOOK_DIR = f"{DRIVE_PATH}/notebooks"

app = modal.App(APP_NAME)

_volume_kwargs = {"version": 2} if VOLUME_VERSION == 2 else {}
volume = modal.Volume.from_name(STORAGE_VOLUME, create_if_missing=True, **_volume_kwargs)

SEED_DIR = "/opt/seed"

image = (
    modal.Image.debian_slim(python_version=PYTHON_VERSION)
    .apt_install(*APT_PACKAGES)
    .pip_install(*PIP_PACKAGES)
)
_local_nb = None
if NOTEBOOK_FILE:
    for _cand in (Path(__file__).parent / LOCAL_NOTEBOOK_DIR / NOTEBOOK_FILE, Path(__file__).parent / NOTEBOOK_FILE):
        if _cand.exists():
            _local_nb = _cand
            break
if _local_nb is not None:
    image = image.add_local_file(_local_nb, f"{SEED_DIR}/{NOTEBOOK_FILE}")

function_options = dict(
    image=image,
    gpu=GPU,
    timeout=24 * 3600,                # Modal's own maximum for one session
    volumes={DRIVE_PATH: volume},
    secrets=[modal.Secret.from_name(n) for n in SECRETS],
    max_containers=1,
)
if CPU_CORES:
    function_options["cpu"] = CPU_CORES
if MEMORY_MB:
    function_options["memory"] = MEMORY_MB


# -----------------------------------------------------------------------------
# Storage helpers (run inside the container)
# -----------------------------------------------------------------------------
def _copy_missing(src: Path, dst: Path) -> None:
    """Copy files from src to dst without overwriting anything that already exists."""
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            s, d = Path(root) / name, dst / rel / name
            if not d.exists() and not d.is_symlink():
                try:
                    shutil.copy2(s, d, follow_symlinks=False)
                except OSError:
                    pass


def link_shortcuts() -> list:
    """Makes /root/<name> point to <drive>/<name> for every name in SHORTCUTS."""
    made = []
    drive = Path(DRIVE_PATH)
    for raw in SHORTCUTS:
        name = str(raw).strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name == DRIVE_FOLDER:
            continue
        target, link = drive / name, Path("/root") / name
        if link.is_symlink():
            made.append(name)
            continue
        if target.exists() and not target.is_dir():
            continue
        target.mkdir(exist_ok=True)
        if link.exists():
            if not link.is_dir():
                continue
            _copy_missing(link, target)
            shutil.rmtree(link, ignore_errors=True)
        link.symlink_to(target, target_is_directory=True)
        made.append(name)
    return made


def prepare_drive() -> dict:
    """Gets your drive ready and returns extra environment variables for JupyterLab."""
    Path(NOTEBOOK_DIR).mkdir(parents=True, exist_ok=True)
    shortcuts = link_shortcuts()
    env = {}
    if KEEP_CACHES:
        cache = Path(DRIVE_PATH) / ".cache"
        (cache / "huggingface").mkdir(parents=True, exist_ok=True)
        env = {"XDG_CACHE_HOME": str(cache), "HF_HOME": str(cache / "huggingface"),
               "TORCH_HOME": str(cache / "torch")}
    print(f"Your drive: {DRIVE_PATH}  (everything in it is kept between sessions)", flush=True)
    if shortcuts:
        print("Shortcuts into your drive: " + ", ".join("/root/" + n for n in shortcuts), flush=True)
    return env


def seed_notebooks(reset: bool) -> None:
    nb_dir = Path(NOTEBOOK_DIR)
    nb_dir.mkdir(parents=True, exist_ok=True)
    if NOTEBOOK_FILE:
        src, dst = Path(SEED_DIR) / NOTEBOOK_FILE, nb_dir / NOTEBOOK_FILE
        if src.exists() and (reset or not dst.exists()):
            shutil.copy(src, dst)
            print(f"Notebook copied: {dst}", flush=True)
    scratch = nb_dir / "scratch.ipynb"
    if SCRATCH_NOTEBOOK and not scratch.exists():
        nb = {
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": [
                    "# Scratch notebook\n",
                    "Write code in a cell and press Shift+Enter. Use `!command` for shell commands.\n",
                    f"Everything you save in `{DRIVE_PATH}` is kept between sessions."]},
                {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                 "source": ["!nvidia-smi\n", f"!df -h {DRIVE_PATH}"]},
            ],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
            "nbformat": 4, "nbformat_minor": 5,
        }
        scratch.write_text(json.dumps(nb, indent=1))


def configure_jupyter() -> str:
    """Theme + autosave. Written to an explicit settings folder (set through
    JUPYTERLAB_SETTINGS_DIR) AND as admin defaults, so it works no matter which
    config folder this Jupyter version prefers."""
    settings_dir = Path.home() / ".jupyter" / "lab" / "user-settings"
    values = {}
    if THEME:
        values["@jupyterlab/apputils-extension:themes"] = {"theme": THEME}
    if AUTOSAVE_SECONDS:
        values["@jupyterlab/docmanager-extension:plugin"] = {
            "autosave": True, "autosaveInterval": int(AUTOSAVE_SECONDS)}
    for plugin, conf in values.items():
        package, name = plugin.split(":")
        f = settings_dir / package / f"{name}.jupyterlab-settings"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(conf, indent=2))
    if values:
        ov = Path(sys.prefix) / "share" / "jupyter" / "lab" / "settings"
        ov.mkdir(parents=True, exist_ok=True)
        (ov / "overrides.json").write_text(json.dumps(values, indent=2))
    return str(settings_dir)


def _jupyter_api(path: str, token: str):
    req = urllib.request.Request(f"http://127.0.0.1:{JUPYTER_PORT}{path}", headers={"Authorization": f"token {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def idle_seconds(token: str):
    """Seconds since anything happened in JupyterLab (0 while code is running).
    None when it cannot be told: that always counts as "active", so a session is never cut by mistake."""
    try:
        if any(k.get("execution_state") == "busy" for k in _jupyter_api("/api/kernels", token)):
            return 0.0
        last = _jupyter_api("/api/status", token).get("last_activity")
        if not last:
            return None
        when = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - when).total_seconds())
    except Exception:  # noqa: BLE001
        return None


@app.function(**function_options)
def run_jupyter(idle_minutes: int, reset: bool):
    cache_env = prepare_drive()
    seed_notebooks(reset)
    settings_dir = configure_jupyter()

    # Databases and sockets do not work well on a Volume: keep them local.
    env = {
        **os.environ,
        "SHELL": "/bin/bash",
        "JUPYTERLAB_SETTINGS_DIR": settings_dir,
        "JUPYTER_RUNTIME_DIR": "/tmp/jupyter-runtime",
        "JUPYTER_DATA_DIR": "/tmp/jupyter-data",
        "IPYTHONDIR": "/tmp/ipython",
        **cache_env,
    }
    token = secrets.token_urlsafe(16)
    env["JUPYTER_TOKEN"] = token
    with modal.forward(JUPYTER_PORT) as tunnel:
        proc = subprocess.Popen(
            [
                "jupyter", "lab",
                "--no-browser", "--allow-root",
                "--ip=0.0.0.0", f"--port={JUPYTER_PORT}",
                "--ServerApp.allow_origin=*",
                "--ServerApp.allow_remote_access=True",
                f"--ServerApp.root_dir={DRIVE_PATH}",
                f"--ServerApp.preferred_dir={NOTEBOOK_DIR}",
            ],
            env=env,
            cwd=DRIVE_PATH,
        )
        print(f"\n>>> Open JupyterLab: {tunnel.url}/?token={token}\n", flush=True)
        if idle_minutes > 0:
            print(f"Stops by itself after {idle_minutes} minutes without activity.", flush=True)

        started = last_commit = last_check = time.time()
        try:
            while proc.poll() is None:
                time.sleep(5)
                now = time.time()
                if now - last_commit >= COMMIT_EVERY_SECONDS:
                    volume.commit()
                    last_commit = now
                if idle_minutes > 0 and now - started > 120 and now - last_check >= 30:
                    last_check = now
                    idle = idle_seconds(token)
                    if idle is not None and idle >= idle_minutes * 60:
                        print(f"Stopping: no activity for {idle_minutes} minutes.", flush=True)
                        break
        finally:
            proc.terminate()
            volume.commit()


@app.local_entrypoint()
def main(idle_minutes: int = IDLE_MINUTES, reset: bool = RESET_NOTEBOOK):
    run_jupyter.remote(idle_minutes, reset)
