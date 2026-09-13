from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESEARCH_VERSION = "PCR_REGIME_RESEARCH_V1"

ALLOWED_DEVELOPMENT_BLOCKS = {
    "TRAIN",
    "OOS_A",
    "OOS_B",
    "OOS_C",
    "OOS_D",
}

FORBIDDEN_BLOCKS = {
    "OOS_E",
    "OOS_F",
    "OOS_G",
    "OOS_H",
}

FORBIDDEN_FEATURE_PREFIXES = (
    "forward_change_",
    "future_",
)


@dataclass(frozen=True)
class BlockInput:
    name: str
    methodology_path: Path
    backtest_path: Path
    evidence_path: Path
    positioning_path: Path


def _normalize_block_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "--block must be "
            "NAME|METHODOLOGY_JSON|BACKTEST_JSON|EVIDENCE_CSV|POSITIONING_CSV"
        )

    name, methodology, backtest, evidence, positioning = parts
    normalized_name = _normalize_block_name(name)

    if normalized_name in FORBIDDEN_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"{normalized_name} is forbidden for PCR Regime Research V1 construction"
        )

    if normalized_name not in ALLOWED_DEVELOPMENT_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"Unsupported development block {normalized_name}. "
            f"Allowed: {sorted(ALLOWED_DEVELOPMENT_BLOCKS)}"
        )

    return BlockInput(
        name=normalized_name,
        methodology_path=Path(methodology),
        backtest_path=Path(backtest),
        evidence_path=Path(evidence),
        positioning_path=Path(positioning),
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)

    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")

    return value


def read_csv_header(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return next(reader)
        except StopIteration:
            raise ValueError(f"{path} is empty") from None


def future_like_columns(columns: list[str]) -> list[str]:
    violations: list[str] = []
    for column in columns:
        lowered = column.lower()
        if any(lowered.startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES):
            violations.append(column)
    return violations


def describe_json_node(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())}

    if isinstance(value, list):
        result: dict[str, Any] = {"type": "array", "count": len(value)}
        if value:
            first = value[0]
            result["first_item_type"] = type(first).__name__
            if isinstance(first, dict):
                result["first_item_keys"] = list(first.keys())
        return result

    return {"type": type(value).__name__, "value": value}


def direction_schema(root: dict[str, Any], direction: str) -> dict[str, Any]:
    directions = root.get("directions")

    if isinstance(directions, dict) and direction in directions:
        node = directions[direction]
        return {
            "location": f"directions.{direction}",
            "description": describe_json_node(node),
            "children": (
                {key: describe_json_node(value) for key, value in node.items()}
                if isinstance(node, dict)
                else None
            ),
        }

    node = root.get(direction)

    if node is not None:
        return {
            "location": direction,
            "description": describe_json_node(node),
            "children": (
                {key: describe_json_node(value) for key, value in node.items()}
                if isinstance(node, dict)
                else None
            ),
        }

    return {"location": None, "description": None, "children": None}


def validate_methodology(methodology: dict[str, Any], block: str) -> None:
    if methodology.get("status") != "AVAILABLE":
        raise ValueError(
            f"{block}: methodology status is not AVAILABLE: "
            f"{methodology.get('status')}"
        )

    version = methodology.get("methodology_version")
    if version != "PCR_RESEARCH_METHODOLOGY_V2":
        raise ValueError(
            f"{block}: expected PCR_RESEARCH_METHODOLOGY_V2, got {version!r}"
        )

    profile = methodology.get("profile") or methodology.get("confidence_profile")
    if profile != "FROZEN_D5_D15":
        raise ValueError(f"{block}: expected FROZEN_D5_D15, got {profile!r}")

    guard = methodology.get("leakage_guard") or {}
    required_guard_values = {
        "current_holdout_validation_input_used": False,
        "panel_any_confirmation_allowed": False,
        "moving_atm_substitution_allowed": False,
    }

    for key, expected in required_guard_values.items():
        actual = guard.get(key)
        if actual != expected:
            raise ValueError(
                f"{block}: methodology leakage guard {key} "
                f"expected {expected!r}, got {actual!r}"
            )


def validate_backtest(backtest: dict[str, Any], block: str) -> None:
    if backtest.get("status") != "AVAILABLE":
        raise ValueError(
            f"{block}: backtest status is not AVAILABLE: "
            f"{backtest.get('status')}"
        )

    if backtest.get("methodology_version") != "PCR_RESEARCH_METHODOLOGY_V2":
        raise ValueError(f"{block}: unexpected methodology version in backtest")

    if backtest.get("confidence_profile") != "FROZEN_D5_D15":
        raise ValueError(f"{block}: unexpected confidence profile in backtest")

    if backtest.get("entry_rule") != "NEXT_MINUTE_OPEN":
        raise ValueError(f"{block}: expected NEXT_MINUTE_OPEN entry rule")

    if (
        backtest.get("contract_selection_rule")
        != "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION"
    ):
        raise ValueError(f"{block}: unexpected contract selection rule")


def inspect_block(block: BlockInput) -> dict[str, Any]:
    methodology = load_json(block.methodology_path)
    backtest = load_json(block.backtest_path)

    validate_methodology(methodology, block.name)
    validate_backtest(backtest, block.name)

    evidence_columns = read_csv_header(block.evidence_path)
    positioning_columns = read_csv_header(block.positioning_path)

    return {
        "block": block.name,
        "methodology": {
            "top_level_keys": list(methodology.keys()),
            "bearish": direction_schema(methodology, "bearish"),
            "bullish": direction_schema(methodology, "bullish"),
        },
        "backtest": {
            "top_level_keys": list(backtest.keys()),
            "bearish": direction_schema(backtest, "bearish"),
            "bullish": direction_schema(backtest, "bullish"),
        },
        "evidence": {
            "path": str(block.evidence_path),
            "columns": evidence_columns,
            "future_like_columns_excluded": future_like_columns(evidence_columns),
        },
        "positioning": {
            "path": str(block.positioning_path),
            "columns": positioning_columns,
            "future_like_columns_excluded": future_like_columns(positioning_columns),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Leakage-guarded PCR Regime Research V1 foundation. "
            "Development blocks only."
        )
    )

    parser.add_argument(
        "--block",
        action="append",
        required=True,
        type=parse_block,
        help=(
            "Development block: "
            "NAME|METHODOLOGY_JSON|BACKTEST_JSON|"
            "EVIDENCE_CSV|POSITIONING_CSV"
        ),
    )

    parser.add_argument("--output", required=True, help="Output JSON path")

    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help=(
            "Validate inputs and emit source schema without performing "
            "regime calculations"
        ),
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    blocks: list[BlockInput] = args.block
    names = [block.name for block in blocks]

    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate block names supplied: {names}")

    inspection = [inspect_block(block) for block in blocks]

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DEVELOPMENT_SCHEMA_VALIDATED",
        "development_blocks": names,
        "regime_dimensions": {
            "trend": ["UP", "DOWN", "RANGE"],
            "volatility": ["LOW", "NORMAL", "HIGH"],
            "momentum_alignment": ["ALIGNED", "AGAINST", "NEUTRAL"],
            "time_of_day": ["EARLY", "MID", "LATE"],
            "pcr_spot_alignment": ["ALIGNED", "DIVERGENT", "NEUTRAL"],
        },
        "frozen_trade_policy": {
            "target_pct": 5.0,
            "stop_pct": -10.0,
            "time_exit_minutes": 15,
            "ambiguous_same_bar": "STOP",
            "round_trip_cost_pct_points": 0.50,
            "entry_rule": "NEXT_MINUTE_OPEN",
            "contract_selection_rule": "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION",
        },
        "leakage_guard": {
            "allowed_development_blocks": sorted(ALLOWED_DEVELOPMENT_BLOCKS),
            "oos_e_f_g_h_allowed_for_regime_construction": False,
            "future_return_features_used": False,
            "forbidden_feature_prefixes": list(FORBIDDEN_FEATURE_PREFIXES),
            "cut_point_source": "DEVELOPMENT_FEATURE_DISTRIBUTION_ONLY",
            "profitability_used_to_define_cut_points": False,
            "oos_h_used": False,
        },
        "inspection": inspection,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(
        json.dumps(
            {
                "status": result["status"],
                "research_version": result["research_version"],
                "research_status": result["research_status"],
                "development_blocks": result["development_blocks"],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
