from __future__ import annotations

from pathlib import Path
import shutil
import sys


TARGET = Path("red_bar_lab/execution/exit_engine.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(
            f"Could not apply {label}. The target file does not match the "
            "expected Sprint 4.3.5.1.3.2 baseline."
        )
    return text.replace(old, new, 1)


def apply(root: Path) -> Path:
    target = root / TARGET
    if not target.exists():
        raise FileNotFoundError(f"Missing target file: {target}")

    original = target.read_text(encoding="utf-8")
    updated = original

    updated = replace_once(
        updated,
        '    breakeven_price: float | None\n'
        '    breakeven_armed: bool\n'
        '    trailing_active: bool\n'
        '    trailing_stop: float | None\n',
        '    breakeven_price: float | None\n'
        '    breakeven_armed: bool\n'
        '    profit_lock_active: bool\n'
        '    profit_lock_price: float | None\n'
        '    trailing_active: bool\n'
        '    trailing_stop: float | None\n',
        "ExitHealth profit-lock fields",
    )

    updated = replace_once(
        updated,
        '        breakeven_trigger_pct: float = 15.0,\n'
        '        trailing_trigger_pct: float = 20.0,\n'
        '        trailing_distance_pct: float = 10.0,\n'
        '    ):\n'
        '        self.breakeven_trigger_pct = float(breakeven_trigger_pct)\n'
        '        self.trailing_trigger_pct = float(trailing_trigger_pct)\n'
        '        self.trailing_distance_pct = float(trailing_distance_pct)\n',
        '        breakeven_trigger_pct: float = 5.0,\n'
        '        profit_lock_trigger_pct: float = 8.0,\n'
        '        profit_lock_pct: float = 2.0,\n'
        '        trailing_trigger_pct: float = 12.0,\n'
        '        trailing_distance_pct: float = 5.0,\n'
        '    ):\n'
        '        self.breakeven_trigger_pct = float(breakeven_trigger_pct)\n'
        '        self.profit_lock_trigger_pct = float(profit_lock_trigger_pct)\n'
        '        self.profit_lock_pct = float(profit_lock_pct)\n'
        '        self.trailing_trigger_pct = float(trailing_trigger_pct)\n'
        '        self.trailing_distance_pct = float(trailing_distance_pct)\n'
        '\n'
        '        if not (\n'
        '            0.0 <= self.breakeven_trigger_pct\n'
        '            <= self.profit_lock_trigger_pct\n'
        '            <= self.trailing_trigger_pct\n'
        '        ):\n'
        '            raise ValueError(\n'
        '                "Protection triggers must satisfy breakeven <= "\n'
        '                "profit-lock <= trailing."\n'
        '            )\n'
        '        if self.profit_lock_pct < 0.0:\n'
        '            raise ValueError("profit_lock_pct cannot be negative.")\n'
        '        if self.trailing_distance_pct < 0.0:\n'
        '            raise ValueError("trailing_distance_pct cannot be negative.")\n',
        "profit-protection configuration",
    )

    updated = replace_once(
        updated,
        '        breakeven_armed = peak_pct >= self.breakeven_trigger_pct\n'
        '        breakeven_price = entry if breakeven_armed else None\n'
        '\n'
        '        trailing_active = peak_pct >= self.trailing_trigger_pct\n'
        '        trailing_stop = None\n'
        '        if trailing_active:\n'
        '            trailing_stop = peak_price * (\n'
        '                1.0 - self.trailing_distance_pct / 100.0\n'
        '            )\n'
        '\n'
        '        # Keep both the stop value and its source so the audit reason matches\n',
        '        breakeven_armed = peak_pct >= self.breakeven_trigger_pct\n'
        '        breakeven_price = entry if breakeven_armed else None\n'
        '\n'
        '        profit_lock_active = (\n'
        '            peak_pct >= self.profit_lock_trigger_pct\n'
        '        )\n'
        '        profit_lock_price = None\n'
        '        if profit_lock_active:\n'
        '            profit_lock_price = entry * (\n'
        '                1.0 + self.profit_lock_pct / 100.0\n'
        '            )\n'
        '\n'
        '        trailing_active = peak_pct >= self.trailing_trigger_pct\n'
        '        trailing_stop = None\n'
        '        if trailing_active:\n'
        '            trailing_stop = peak_price * (\n'
        '                1.0 - self.trailing_distance_pct / 100.0\n'
        '            )\n'
        '\n'
        '        previous_protected_stop = max(\n'
        '            0.0,\n'
        '            _num(position.get("protected_stop_price")),\n'
        '            _num(position.get("effective_stop")),\n'
        '        )\n'
        '\n'
        '        # Keep both the stop value and its source so the audit reason matches\n',
        "staged profit-protection calculation",
    )

    updated = replace_once(
        updated,
        '        if breakeven_price is not None and breakeven_price > 0:\n'
        '            stop_candidates.append(("BREAKEVEN_STOP", breakeven_price, 1))\n'
        '        if trailing_stop is not None and trailing_stop > 0:\n'
        '            stop_candidates.append(("TRAILING_STOP", trailing_stop, 2))\n',
        '        if breakeven_price is not None and breakeven_price > 0:\n'
        '            stop_candidates.append(("BREAKEVEN_STOP", breakeven_price, 1))\n'
        '        if profit_lock_price is not None and profit_lock_price > 0:\n'
        '            stop_candidates.append(\n'
        '                ("PROFIT_LOCK_STOP", profit_lock_price, 2)\n'
        '            )\n'
        '        if trailing_stop is not None and trailing_stop > 0:\n'
        '            stop_candidates.append(("TRAILING_STOP", trailing_stop, 3))\n'
        '        if previous_protected_stop > 0:\n'
        '            stop_candidates.append(\n'
        '                ("PROTECTED_STOP", previous_protected_stop, 4)\n'
        '            )\n',
        "monotonic protected-stop candidates",
    )

    updated = replace_once(
        updated,
        '        elif trailing_active:\n'
        '            action = "HOLD / TRAIL"\n'
        '            reasons.append("Trailing protection active.")\n'
        '        elif breakeven_armed:\n'
        '            action = "HOLD / PROTECT"\n'
        '            reasons.append("Breakeven protection armed.")\n',
        '        elif trailing_active:\n'
        '            action = "HOLD / TRAIL"\n'
        '            reasons.append("Trailing profit protection active.")\n'
        '        elif profit_lock_active:\n'
        '            action = "HOLD / LOCK PROFIT"\n'
        '            reasons.append(\n'
        '                f"Minimum profit lock armed at " f"₹{profit_lock_price:.2f}."\n'
        '            )\n'
        '        elif breakeven_armed:\n'
        '            action = "HOLD / PROTECT"\n'
        '            reasons.append("Breakeven protection armed.")\n',
        "profit-lock action",
    )

    updated = replace_once(
        updated,
        '            breakeven_price=round(breakeven_price, 2) if breakeven_price is not None else None,\n'
        '            breakeven_armed=breakeven_armed,\n'
        '            trailing_active=trailing_active,\n',
        '            breakeven_price=round(breakeven_price, 2) if breakeven_price is not None else None,\n'
        '            breakeven_armed=breakeven_armed,\n'
        '            profit_lock_active=profit_lock_active,\n'
        '            profit_lock_price=(\n'
        '                round(profit_lock_price, 2)\n'
        '                if profit_lock_price is not None\n'
        '                else None\n'
        '            ),\n'
        '            trailing_active=trailing_active,\n',
        "ExitHealth return fields",
    )

    backup = target.with_suffix(".py.before_profit_protection")
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(updated, encoding="utf-8")
    return target


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    target = apply(root)
    print(f"Applied Paper Profit Protection Change 1 to: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
