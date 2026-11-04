import argparse

from filelock import FileLock
from sqlalchemy.orm import Session

from .storage import active_config, initialize, make_engine, record, replay
from .worker import demo_next


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed-demo", "replay"])
    parser.add_argument("--count", type=int, default=90)
    args = parser.parse_args()
    engine = make_engine()
    initialize(engine)
    with Session(engine) as session:
        config_id, config, enabled = active_config(session)
    if args.command == "replay":
        import json

        print(json.dumps(replay(engine, config_id), indent=2))
        return
    if config.provider != "demo":
        raise SystemExit("Demo seed requires an active demo configuration.")
    if enabled:
        raise SystemExit("Pause collection before seeding.")
    if not 1 <= args.count <= 360:
        raise SystemExit("Count must be between 1 and 360.")
    with FileLock("data/collector.lock", timeout=0):
        for _ in range(args.count):
            record(engine, config_id, demo_next(engine, config_id, config))
    print(f"Recorded {args.count} synthetic observations for configuration {config_id}.")


if __name__ == "__main__":
    main()
