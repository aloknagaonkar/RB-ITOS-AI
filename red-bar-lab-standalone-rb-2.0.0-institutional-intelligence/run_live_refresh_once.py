import traceback

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.services.upstox_service import (
    RedBarUpstoxService,
    resolve_access_token,
)
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.live_service import RedBarLiveService
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase

settings = RedBarSettings.from_env()
layout = ArtifactLayout(settings)
layout.ensure()

database = RedBarDatabase(settings.database_path)
database.initialize()

try:
    token = resolve_access_token("")
    print("Access token resolved: YES")

    provider = RedBarUpstoxService(token)
    historical = RedBarHistoricalService(provider, layout)
    service = RedBarLiveService(historical, layout, database)

    instrument_key = UNDERLYINGS["NIFTY 50"]
    print("Refreshing:", instrument_key)

    result = service.refresh(instrument_key)

    print("Connected:", result.connected)
    print("Message:", result.message)
    print("Trading date:", result.trading_date)
    print("Source rows:", result.source_rows)
    print("Levels stored:", result.levels_stored)
    print("Completed 5-minute candles:", result.completed_five_minute_rows)

except Exception:
    print("LIVE REFRESH FAILED")
    traceback.print_exc()
