from pathlib import Path
import shutil
import sys

TARGET = Path("red_bar_lab/ui/_shared.py")

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found.")
    print("Run this script from the red-bar-lab-standalone-rb-2.0.0-institutional-intelligence root.")
    sys.exit(1)

text = TARGET.read_text(encoding="utf-8")
original = text

backup = TARGET.with_suffix(".py.before_ema10_ui")
shutil.copy2(TARGET, backup)

replacements = []

# 1) Live Paper Exit Engine caption.
old = '''    st.caption(
        "Operational exit authority: premium protection, Target 1, EOD, "
        "NIFTY thesis, opposite Red Bar and option technical health. "
        "PCR/OI/Greeks remain SHADOW EXIT evidence only."
    )
'''
new = '''    st.caption(
        "Operational exit authority: premium protection, completed NIFTY "
        "5-minute EMA10 trend exit, EOD, NIFTY thesis, opposite Red Bar "
        "and option technical health. Fixed profit targets are informational "
        "only and have no exit authority. PCR/OI/Greeks remain SHADOW EXIT "
        "evidence only."
    )
'''
replacements.append(("live exit caption", old, new))

# 2) Live panel: remove operational Target 1/2 presentation and show EMA10 trend.
old = '''        target1_near = bool(
            exit_health.target1 is not None
            and current < exit_health.target1
            and exit_health.target1 > 0
            and (exit_health.target1 - current)
            / exit_health.target1
            <= 0.05
        )
        target1_state = (
            "HIT"
            if (
                exit_health.target1 is not None
                and current >= exit_health.target1
            )
            else "NEAR"
            if target1_near
            else "ACTIVE"
        )
        target1_tone = (
            "pass"
            if target1_state == "HIT"
            else "warning"
            if target1_state == "NEAR"
            else "info"
        )

        _protection_row(
            "Target 1",
            (
                f"₹{exit_health.target1:.2f}"
                if exit_health.target1 is not None
                else "—"
            ),
            target1_state,
            target1_tone,
        )

        _protection_row(
            "Target 2",
            (
                f"₹{exit_health.target2:.2f}"
                if exit_health.target2 is not None
                else "—"
            ),
            "INFO",
            "info",
        )
'''
new = '''        ema10_value = (
            (
                f"5m Close {exit_health.underlying_5m_close:.2f} · "
                f"EMA10 {exit_health.underlying_ema10:.2f}"
            )
            if (
                exit_health.underlying_5m_close is not None
                and exit_health.underlying_ema10 is not None
            )
            else "Awaiting completed 5m EMA10 data"
        )
        ema10_state = str(exit_health.ema10_trend or "UNKNOWN").upper()
        ema10_tone = (
            "fail"
            if ema10_state == "LOST"
            else "pass"
            if ema10_state == "VALID"
            else "info"
        )
        _protection_row(
            "NIFTY 5m EMA10",
            ema10_value,
            ema10_state,
            ema10_tone,
        )
'''
replacements.append(("live target rows -> EMA10", old, new))

# 3) Live health panel: show EMA10 as operational evidence.
old = '''        _health_row(
            "NIFTY Thesis",
            exit_health.nifty_thesis,
            "OPERATIONAL",
        )
        _health_row(
            "Opposite Red Bar",
'''
new = '''        _health_row(
            "NIFTY Thesis",
            exit_health.nifty_thesis,
            "OPERATIONAL",
        )
        _health_row(
            "5m EMA10 Trend",
            exit_health.ema10_trend,
            "OPERATIONAL",
        )
        _health_row(
            "Opposite Red Bar",
'''
replacements.append(("live EMA10 health row", old, new))

# 4) Idle protection rules: remove fixed targets; show EMA10 continuation/exit.
old = '''            {
                "Protection": "Trailing Distance",
                "Trigger": "10% below peak",
                "State": "READY",
            },
            {
                "Protection": "Target 1",
                "Trigger": "+25% premium",
                "State": "READY",
            },
            {
                "Protection": "Target 2",
                "Trigger": "+40% premium",
                "State": "INFO",
            },
'''
new = '''            {
                "Protection": "Trailing Distance",
                "Trigger": "10% below peak",
                "State": "READY",
            },
            {
                "Protection": "5m EMA10 Trend Exit",
                "Trigger": "Bullish: close < EMA10 · Bearish: close > EMA10",
                "State": "READY",
            },
'''
replacements.append(("idle protection rules", old, new))

# 5) Idle exit authority: Target 1 -> EMA10.
old = '''            {
                "Condition": "Target 1",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
'''
new = '''            {
                "Condition": "5m EMA10 Trend Exit",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
'''
replacements.append(("idle exit authority", old, new))

# Apply with strict safety checks.
for label, old, new in replacements:
    count = text.count(old)
    if count != 1:
        print(f"ERROR: Expected exactly 1 match for '{label}', found {count}.")
        print(f"Backup is available at: {backup}")
        sys.exit(2)
    text = text.replace(old, new, 1)
    print(f"OK: {label}")

if text == original:
    print("ERROR: No changes made.")
    sys.exit(3)

TARGET.write_text(text, encoding="utf-8")

print()
print("SUCCESS")
print(f"Updated: {TARGET}")
print(f"Backup : {backup}")
print()
print("Expected UI:")
print("  - Target 1 / Target 2 removed from Paper Exit Engine protection UI")
print("  - 5m EMA10 Trend Exit shown as OPERATIONAL")
print("  - Bullish: completed NIFTY 5m close < EMA10 => exit CE")
print("  - Bearish: completed NIFTY 5m close > EMA10 => exit PE")
print("  - Fixed targets have no operational exit authority")
