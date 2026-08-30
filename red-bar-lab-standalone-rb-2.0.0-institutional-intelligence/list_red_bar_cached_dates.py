from pathlib import Path

from red_bar_lab.config import RedBarSettings
from red_bar_lab.storage.artifacts import ArtifactLayout


settings = RedBarSettings.from_env()
layout = ArtifactLayout(settings)
layout.ensure()

root = settings.historical_root / "upstox"

print("Historical cache root:", root.resolve())
print()

if not root.exists():
    raise SystemExit("Historical cache folder does not exist.")

for instrument_folder in sorted(path for path in root.iterdir() if path.is_dir()):
    one_minute = instrument_folder / "1"
    if not one_minute.exists():
        continue

    dates = sorted(path.stem for path in one_minute.glob("*.csv"))
    if not dates:
        continue

    print(instrument_folder.name)
    print("  Dates:", ", ".join(dates))
    print("  Count:", len(dates))
    print()
