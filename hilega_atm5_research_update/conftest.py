"""VM staged research imports only; runtime backend remains the installed one."""
import sys
from pathlib import Path
FILES=Path(__file__).resolve().parent/'files'
sys.path.insert(0,str(FILES))
import scripts
scripts.__path__=[str(FILES/'scripts')]+list(scripts.__path__)
