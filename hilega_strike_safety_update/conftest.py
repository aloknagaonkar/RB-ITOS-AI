"""VM-only staged import overlay. Never runs order or service entry points."""
import sys
from pathlib import Path
FILES=Path(__file__).resolve().parent/'files'
sys.path.insert(0,str(FILES))
sys.path.insert(0,str(Path.cwd()/'backend'))
import market_lab
market_lab.__path__=[str(FILES/'backend/market_lab')]+list(market_lab.__path__)
import scripts
scripts.__path__=[str(FILES/'scripts')]+list(scripts.__path__)
