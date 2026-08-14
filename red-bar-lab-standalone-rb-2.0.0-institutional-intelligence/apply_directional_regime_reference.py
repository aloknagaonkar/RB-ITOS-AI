from __future__ import annotations

from pathlib import Path
import shutil


TARGET = Path("red_bar_lab/execution/automation.py")
BACKUP = TARGET.with_suffix(".py.before_directional_regime_reference")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(
            f"Could not find insertion point for {label}. "
            "The local automation.py differs from the expected branch."
        )
    return text.replace(old, new, 1)


def main() -> None:
    if not TARGET.exists():
        raise FileNotFoundError(
            "Run this script from the project root. "
            f"Missing {TARGET}."
        )

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)

    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from red_bar_lab.execution.exit_engine import PaperExitEngine\n",
        (
            "from red_bar_lab.execution.exit_engine import PaperExitEngine\n"
            "from red_bar_lab.execution.directional_regime_reference import (\n"
            "    DirectionalRegimeReferenceService,\n"
            ")\n"
        ),
        "Directional Regime Intelligence import",
    )

    text = replace_once(
        text,
        "        minimum_opportunity_health: float = 75.0,\n"
        "    ):\n",
        (
            "        minimum_opportunity_health: float = 75.0,\n"
            "        enable_directional_regime_reference: bool = True,\n"
            "        directional_regime_maximum_age_minutes: int = 30,\n"
            "    ):\n"
        ),
        "constructor arguments",
    )

    text = replace_once(
        text,
        "        self.underlying_name = underlying_name\n",
        (
            "        self.underlying_name = underlying_name\n"
            "        self.enable_directional_regime_reference = bool(\n"
            "            enable_directional_regime_reference\n"
            "        )\n"
            "        self.directional_regime_reference = (\n"
            "            DirectionalRegimeReferenceService(\n"
            "                runs_root=settings.runs_root,\n"
            "                maximum_age_minutes=(\n"
            "                    directional_regime_maximum_age_minutes\n"
            "                ),\n"
            "            )\n"
            "            if self.enable_directional_regime_reference\n"
            "            else None\n"
            "        )\n"
        ),
        "reference service initialization",
    )

    anchor = (
        "            previous_events = "
        "self.database.read_execution_state_events(\n"
        "                signal_id=signal_id, limit=1\n"
        "            )\n"
    )
    addition = anchor + (
        "\n"
        "            directional_reference = None\n"
        "            if self.directional_regime_reference is not None:\n"
        "                try:\n"
        "                    directional_reference = (\n"
        "                        self.directional_regime_reference.evaluate(\n"
        "                            signal_direction=str(\n"
        "                                signal.get(\"direction\") or \"\"\n"
        "                            ),\n"
        "                            instrument_key=instrument_key,\n"
        "                            at_time=(\n"
        "                                confirmation_timestamp\n"
        "                                or now.isoformat()\n"
        "                            ),\n"
        "                        )\n"
        "                    )\n"
        "                    self._record_state(\n"
        "                        signal_id=signal_id,\n"
        "                        state=\"DIRECTIONAL_REGIME_REFERENCE\",\n"
        "                        detail=(\n"
        "                            f\"status={directional_reference.status}; \"\n"
        "                            f\"regime={directional_reference.regime}; \"\n"
        "                            f\"bundle_direction=\"\n"
        "                            f\"{directional_reference.bundle_direction or 'NA'}; \"\n"
        "                            f\"bundle_id=\"\n"
        "                            f\"{directional_reference.bundle_id or 'NA'}; \"\n"
        "                            f\"setup=\"\n"
        "                            f\"{directional_reference.primary_setup_type or 'NA'}; \"\n"
        "                            f\"alignment_score=\"\n"
        "                            f\"{directional_reference.alignment_score:.1f}; \"\n"
        "                            f\"reason={directional_reference.reason}; \"\n"
        "                            \"mode=REFERENCE_ONLY\"\n"
        "                        ),\n"
        "                        score=(\n"
        "                            directional_reference.alignment_score\n"
        "                        ),\n"
        "                    )\n"
        "                except Exception as exc:\n"
        "                    errors.append(\n"
        "                        \"Directional Regime Intelligence reference \"\n"
        "                        f\"unavailable for {signal_id}: \"\n"
        "                        f\"{type(exc).__name__}: {exc}\"\n"
        "                    )\n"
    )
    text = replace_once(
        text,
        anchor,
        addition,
        "per-signal directional reference evaluation",
    )

    TARGET.write_text(text, encoding="utf-8")
    print(
        "Directional Regime Intelligence reference added to Paper Trading."
    )
    print(f"Backup: {BACKUP}")
    print("Mode: REFERENCE_ONLY (no execution gate or override).")


if __name__ == "__main__":
    main()
