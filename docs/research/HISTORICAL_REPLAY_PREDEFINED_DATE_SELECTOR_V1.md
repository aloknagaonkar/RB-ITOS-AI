# Historical Replay Predefined Date Selector V1

Adds two date controls to Historical Replay:

- **Quick date** — a predefined dropdown containing the previous 45 weekdays,
  plus any already-known replay session dates.
- **Custom date** — the existing unrestricted calendar/date input.

Selecting a quick date immediately updates the replay/readiness date. The
readiness system remains authoritative: a preset date can still be PARTIAL,
DOWNLOADABLE, or NOT READY.

The dropdown intentionally does not claim every weekday is a trading day.
Holiday/non-recorded dates are allowed to be selected and will be rejected by
readiness when required data is unavailable.
