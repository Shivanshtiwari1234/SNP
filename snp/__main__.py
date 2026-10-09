#!/usr/bin/env python3
"""Module entrypoint for the SNP CLI."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "snp.py"

spec = spec_from_file_location("snp_cli_entry", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load CLI module from {MODULE_PATH}")

module = module_from_spec(spec)
sys.modules["snp_cli_entry"] = module
spec.loader.exec_module(module)

raise SystemExit(module.main())
