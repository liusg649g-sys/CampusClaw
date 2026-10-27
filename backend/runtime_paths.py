"""Optional isolated data root; native Windows defaults remain backend/ unchanged."""
import os
from pathlib import Path

DATA_DIR=Path(os.environ.get('CAMPUSCLAW_DATA_DIR') or Path(__file__).resolve().parent)
