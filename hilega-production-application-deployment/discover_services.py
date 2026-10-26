"""Read-only candidate unit inventory. Never prints service command lines or env."""
import json
import subprocess


def main():
    try:
        result=subprocess.run(['systemctl','list-units','--all','--type=service','--plain','--no-pager','--no-legend'],
                              text=True,capture_output=True,timeout=10)
        if result.returncode:raise ValueError()
        candidates=[]
        for line in result.stdout.splitlines():
            fields=line.split(None,4)
            if len(fields)<4:continue
            if any(word in line.lower() for word in ('hilega','itos','market','upstox','uvicorn','gunicorn','api.service')):
                candidates.append(dict(unit=fields[0],load=fields[1],active=fields[2],sub=fields[3]))
        print(json.dumps(dict(status='CANDIDATE_UNITS_ONLY',units=candidates,
            all_application_processes_identified=False,services_stopped=False,configuration_changed=False)))
        return 0
    except Exception:
        print(json.dumps(dict(status='SERVICE_INVENTORY_UNAVAILABLE',services_stopped=False)))
        return 2


if __name__=='__main__':raise SystemExit(main())
