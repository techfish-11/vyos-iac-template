import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vyos_iac.config import quote


class FilterModule:
    def filters(self):
        return {"vyos_quote": quote}
