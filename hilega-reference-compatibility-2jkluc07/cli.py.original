
"""Integrity-checked lifecycle reference CLI. No order actions."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

EXPECTED_MANIFEST = "574197a2ba8e4db050e1192377acbfc62b2e09ac49219cc171df99e9c32cb87b"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    if (path.is_symlink() or not path.is_file()
            or any(parent.is_symlink() for parent in path.absolute().parents)):
        raise ValueError("REGULAR_SOURCE_REQUIRED")
    return path.read_bytes()


def checked(repo):
    folder = Path(__file__).absolute().parent
    raw = regular(folder / "manifest.json")
    if digest(raw) != EXPECTED_MANIFEST:
        raise ValueError("MANIFEST_CHANGED")
    manifest = json.loads(raw)
    if (manifest["model"] != "HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1"
            or manifest["order_actions_available"] is not False
            or manifest["production_execution_enabled"] is not False):
        raise ValueError("MANIFEST_INVALID")
    for name, expected in manifest["modules"].items():
        p = Path(name)
        if p.name != name or p.suffix != ".py":
            raise ValueError("PACKAGE_PATH_INVALID")
        if digest(regular(folder / name)) != expected:
            raise ValueError("PACKAGE_SOURCE_CHANGED")
    for name, expected in manifest["runtime"].items():
        p = Path(name)
        if (p.is_absolute() or ".." in p.parts
                or not p.parts or p.parts[0] != "backend"
                or p.suffix != ".py"):
            raise ValueError("RUNTIME_PATH_INVALID")
        if digest(regular(repo / p)) != expected:
            raise ValueError("RUNTIME_SOURCE_CHANGED")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "review"))
    parser.add_argument("--repo", type=Path, required=True)
    for name in ("application", "adapter", "pin-file", "token-file", "journal"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    try:
        repo = args.repo.absolute()
        folder = checked(repo)
    except Exception:
        print(json.dumps(dict(
            status="PACKAGE_OR_RUNTIME_CHECK_FAILED",
            database_modified=False, production_execution_enabled=False,
        )))
        return 2
    if args.action == "check":
        print(json.dumps(dict(
            status="PACKAGE_AND_RUNTIME_CHECK_PASS",
            database_access_performed=False,
            credentials_opened=False,
            broker_reads_performed=False,
            order_actions_available=False,
            production_execution_enabled=False,
        ), indent=2))
        return 0
    if any(getattr(args, name) is None for name in (
        "application", "adapter", "pin_file", "token_file", "journal",
    )):
        parser.error("review requires explicit database, credential and journal paths")
    sys.path.insert(0, str(folder))
    sys.path.insert(0, str(repo / "backend"))
    try:
        from operational_lifecycle_review import run_reference_review
        result = run_reference_review(
            args.application, args.adapter,
            pin_file=args.pin_file, token_file=args.token_file,
            journal=args.journal,
        )
    except Exception as exc:
        print(json.dumps(dict(
            status="LIFECYCLE_REVIEW_FAILED",
            error_type=type(exc).__name__,
            commit_outcome="NOT_CERTIFIED_INSPECT_BEFORE_RETRY",
            production_execution_enabled=False,
        )))
        return 2
    print(json.dumps({
        key: result[key] for key in (
            "status", "database_modified", "account_capture_requested",
            "orders_sent_to_upstox", "production_execution_enabled",
        ) if key in result
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
