# Canonical 90 Nine-Leg Option Coverage V1

This expands the strike study to four ITM legs and four OTM legs around ATM.

Per signal:

BULLISH (CE):
- ITM4 = ATM-4
- ITM3 = ATM-3
- ITM2 = ATM-2
- ITM1 = ATM-1
- ATM
- OTM1 = ATM+1
- OTM2 = ATM+2
- OTM3 = ATM+3
- OTM4 = ATM+4

BEARISH (PE):
- ITM4 = ATM+4
- ITM3 = ATM+3
- ITM2 = ATM+2
- ITM1 = ATM+1
- ATM
- OTM1 = ATM-1
- OTM2 = ATM-2
- OTM3 = ATM-3
- OTM4 = ATM-4

For 370 TRADE_ELIGIBLE signals:
- expected exact legs = 370 x 9 = 3,330.

This stage is coverage only:
- exact C2 timestamp;
- exact strike offset;
- exact instrument;
- exact next-minute OPEN;
- exact 15-minute path;
- no nearest-strike or nearest-time fallback;
- session-end censoring remains explicit.

After coverage passes, replay all READY legs with the unchanged frozen
`SL5_BE5_TRAIL3_AFTER10_TIME15` engine and compare the nine legs on the same
complete-signal population.
