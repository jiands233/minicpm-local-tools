#!/usr/bin/env python3
"""Create a synthetic Chrome history database for local comparison."""
import argparse
from pathlib import Path

from minicpm_tools.reading_demo import create_history

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("database", type=Path, help="New SQLite path; existing files are refused")
args = parser.parse_args()
db = create_history(args.database)
db.close()
print(args.database)
