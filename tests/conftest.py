import sys
from pathlib import Path

# Os scripts se importam como módulos irmãos (python3 scripts/build.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
