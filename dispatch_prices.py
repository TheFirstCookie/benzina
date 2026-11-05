"""Windows scheduled-task entry point for the ANRE relay."""
import os
from pathlib import Path
from fuelbot.relay import cli

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    raise SystemExit(cli())
