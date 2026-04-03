"""
Nereid Install Script
Checks requirements, installs dependencies, and sets up your .env file.

Usage:
    python install.py
"""

import sys
import os
import subprocess
import shutil


# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"{GREEN}✓{RESET}  {msg}")
def info(msg):  print(f"{CYAN}ℹ{RESET}  {msg}")
def warn(msg):  print(f"{YELLOW}⚠{RESET}  {msg}")
def error(msg): print(f"{RED}✗{RESET}  {msg}")
def header(msg):print(f"\n{BOLD}{msg}{RESET}")


def check_python():
    header("Checking Python version...")
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 10):
        error(f"Python 3.10+ is required. You have {major}.{minor}.")
        error("Download the latest Python from https://python.org")
        sys.exit(1)
    ok(f"Python {major}.{minor} detected.")


def check_pip():
    header("Checking pip...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"],
                       check=True, capture_output=True)
        ok("pip is available.")
    except subprocess.CalledProcessError:
        error("pip is not available. Please install pip first.")
        sys.exit(1)


def install_nereid():
    header("Installing Nereid and dependencies...")
    info("Running: pip install -e .")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        capture_output=False,
    )
    if result.returncode != 0:
        error("Installation failed. See output above for details.")
        sys.exit(1)
    ok("Nereid installed successfully.")


def setup_env():
    header("Setting up .env file...")
    env_path = ".env"
    example_path = ".env.example"

    if os.path.exists(env_path):
        warn(".env already exists — skipping. Edit it manually if needed.")
        return

    if not os.path.exists(example_path):
        error(".env.example not found. Make sure you are running this from the Nereid root folder.")
        sys.exit(1)

    shutil.copy(example_path, env_path)
    ok(".env created from .env.example.")
    print()
    warn("You must edit .env before using Nereid. Open it and fill in:")
    print(f"    {CYAN}NEREID_DB_URL{RESET}       — your PostgreSQL connection string")
    print(f"    {CYAN}NEREID_FILE_PATH{RESET}    — path to your XLSX file or folder")
    print(f"    {CYAN}NEREID_PK_COLUMN{RESET}    — your primary key column name (default: id)")


def verify_cli():
    header("Verifying CLI...")
    result = subprocess.run(
        ["nereid", "--version"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Try via python -m as fallback
        result = subprocess.run(
            [sys.executable, "-m", "nereid", "--version"],
            capture_output=True, text=True
        )

    if result.returncode == 0:
        ok(f"CLI is working: {result.stdout.strip()}")
    else:
        warn("CLI not found in PATH. You may need to restart your terminal.")
        info("You can still run Nereid with: python -m nereid")


def print_next_steps():
    print(f"\n{BOLD}{'─' * 50}{RESET}")
    print(f"{BOLD}{GREEN}Nereid is installed!{RESET}")
    print(f"{BOLD}{'─' * 50}{RESET}\n")
    print("Next steps:\n")
    print(f"  1. Edit {CYAN}.env{RESET} with your database connection and file path")
    print(f"  2. Export your database to a spreadsheet:")
    print(f"     {CYAN}nereid export --mode single --output data.xlsx{RESET}")
    print(f"  3. Share the file via Google Drive / Dropbox / OneDrive")
    print(f"  4. Start watching for changes:")
    print(f"     {CYAN}nereid watch --mode single --path data.xlsx{RESET}")
    print(f"  5. Review staged changes before promoting to production:")
    print(f"     {CYAN}nereid review --interactive{RESET}")
    print(f"\nFull documentation: https://github.com/JonLindholm11/Nereid\n")


if __name__ == "__main__":
    print(f"\n{BOLD}Nereid Installer{RESET} — a Lunar Systems open source tool\n")
    check_python()
    check_pip()
    install_nereid()
    setup_env()
    verify_cli()
    print_next_steps()