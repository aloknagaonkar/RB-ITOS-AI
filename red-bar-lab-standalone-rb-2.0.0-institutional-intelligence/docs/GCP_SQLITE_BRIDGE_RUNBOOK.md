# Runbook: Stand up `rb-itos-ai-validation` on GCP and connect SQLite

## 0. One-time prereqs on THIS machine (Windows / PowerShell)

```powershell
# Install gcloud SDK if not already: https://cloud.google.com/sdk/docs/install
gcloud --version

# Login (browser-based)
gcloud auth login
gcloud auth application-default login

# Set defaults
gcloud config set project <YOUR_PROJECT_ID>
gcloud config set compute/region asia-south1
gcloud config set compute/zone  asia-south1-a

# Discover your public IP (used to scope the SSH firewall rule)
curl ifconfig.me
```

## 1. Create the VM + persistent disk

```powershell
$PROJECT   = "<YOUR_PROJECT_ID>"
$REGION    = "asia-south1"
$ZONE      = "asia-south1-a"
$VM        = "rb-itos-ai-validation"
$DISK      = "rb-itos-ai-validation-data"
$DISK_SIZE = "50"
$SRC_IP    = "<YOUR_PUBLIC_IP>/32"   # e.g. 203.0.113.10/32

# 1a. Static external IP (so the address never changes)
gcloud compute addresses create rb-itos-ai-validation-ip `
  --project=$PROJECT --region=$REGION

# 1b. Persistent disk (separate from boot disk so we can resize/reattach)
gcloud compute disks create $DISK `
  --project=$PROJECT --zone=$ZONE `
  --size=$DISK_SIZE --type=pd-balanced

# 1c. Firewall: only allow SSH from your IP
gcloud compute firewall-rules create allow-ssh-rb-itos-ai `
  --project=$PROJECT `
  --direction=INGRESS --action=ALLOW --rules=tcp:22 `
  --source-ranges=$SRC_IP `
  --target-tags=rb-itos-ai-ssh

# 1d. VM
gcloud compute instances create $VM `
  --project=$PROJECT --zone=$ZONE `
  --machine-type=e2-standard-2 `
  --image-family=debian-12 --image-project=debian-cloud `
  --address=rb-itos-ai-validation-ip `
  --tags=rb-itos-ai-ssh `
  --disk=name=$DISK,device-name=$DISK,mode=rw,auto-delete=no `
  --scopes=cloud-platform `
  --metadata=enable-oslogin=TRUE

# 1e. Reserve the IP for later
$IP = gcloud compute addresses describe rb-itos-ai-validation-ip `
        --project=$PROJECT --region=$REGION --format="value(address)"
Write-Host "VM external IP: $IP"
```

## 2. On the VM: format, mount, install Python

```powershell
gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE --command="
set -euo pipefail

# 2a. Format + mount the persistent disk at /var/lib/rb-itos-ai
sudo mkdir -p /var/lib/rb-itos-ai
if ! lsblk /dev/disk/by-id/google-${DISK} >/dev/null 2>&1; then
  echo 'disk not visible'; exit 1
fi
if ! blkid /dev/disk/by-id/google-${DISK} >/dev/null 2>&1; then
  sudo mkfs.ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0 \
    /dev/disk/by-id/google-${DISK}
fi
sudo mount -o discard,defaults /dev/disk/by-id/google-${DISK} /var/lib/rb-itos-ai
echo '/dev/disk/by-id/google-${DISK} /var/lib/rb-itos-ai ext4 discard,defaults,nofail 0 2' \
  | sudo tee -a /etc/fstab
sudo chown -R \$USER:\$USER /var/lib/rb-itos-ai

# 2b. Python 3.11 + pip + venv
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip sqlite3
python3.11 -m venv /var/lib/rb-itos-ai/venv
source /var/lib/rb-itos-ai/venv/bin/activate
pip install --upgrade pip
"
```

## 3. Copy the local SQLite DB up

```powershell
# From this machine (PowerShell)
gcloud compute scp `
  "red-bar-lab-standalone-rb-2.0.0-institutional-intelligence\data\red_bar.db" `
  "${VM}:/var/lib/rb-itos-ai/red_bar.db" `
  --project=$PROJECT --zone=$ZONE

# Sanity check: list tables over SSH
gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE --command="
sqlite3 /var/lib/rb-itos-ai/red_bar.db \".tables\"
"
```

## 4. Read-only HTTP bridge (so Python can query over the network)

SQLite is a file format — Python's `sqlite3` module can only open local files. We
expose a tiny FastAPI server on the VM that accepts SQL over HTTPS, opens the DB
in read-only mode, and returns rows as JSON.

### 4a. Bridge files (create on the VM)

```powershell
gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE --command="
mkdir -p /var/lib/rb-itos-ai/bridge
"
```

`/var/lib/rb-itos-ai/bridge/server.py`:

```python
import os
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("RB_DB_PATH", "/var/lib/rb-itos-ai/red_bar.db")
MAX_ROWS = int(os.environ.get("RB_MAX_ROWS", "10000"))

app = FastAPI(title="rb-itos-ai sqlite bridge", version="1.0.0")


class Query(BaseModel):
    sql: str = Field(..., min_length=1)
    params: list[Any] = Field(default_factory=list)


def _connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"db not found: {DB_PATH}")
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "db_path": DB_PATH}


@app.get("/schema")
def schema() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    return {"objects": [dict(r) for r in rows]}


@app.post("/query")
def query(q: Query) -> dict:
    head = q.sql.lstrip().split(None, 1)[0].lower() if q.sql.strip() else ""
    if head not in ("select", "with", "pragma"):
        raise HTTPException(
            status_code=400,
            detail="only SELECT/WITH/PRAGMA queries are allowed",
        )
    with _connect() as conn:
        cur = conn.execute(q.sql, q.params)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = [dict(r) for r in cur.fetchmany(MAX_ROWS)]
    return {"columns": cols, "row_count": len(rows), "rows": rows}
```

`/var/lib/rb-itos-ai/bridge/requirements.txt`:

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.9.2
```

### 4b. systemd unit (auto-restart on the VM)

`/etc/systemd/system/rb-sqlite-bridge.service`:

```
[Unit]
Description=rb-itos-ai sqlite read-only bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%i
WorkingDirectory=/var/lib/rb-itos-ai/bridge
Environment=RB_DB_PATH=/var/lib/rb-itos-ai/red_bar.db
Environment=RB_MAX_ROWS=10000
ExecStart=/var/lib/rb-itos-ai/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/rb-itos-ai

[Install]
WantedBy=multi-user.target
```

```powershell
gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE --command="
sudo chown -R \$USER:\$USER /var/lib/rb-itos-ai
cd /var/lib/rb-itos-ai/bridge
../venv/bin/pip install -r requirements.txt
sudo tee /etc/systemd/system/rb-sqlite-bridge.service >/dev/null <<'EOF'
[Unit]
Description=rb-itos-ai sqlite read-only bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/var/lib/rb-itos-ai/bridge
Environment=RB_DB_PATH=/var/lib/rb-itos-ai/red_bar.db
Environment=RB_MAX_ROWS=10000
ExecStart=/var/lib/rb-itos-ai/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/rb-itos-ai

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now rb-sqlite-bridge
sudo systemctl status rb-sqlite-bridge --no-pager
"
```

### 4c. Reverse SSH tunnel from this machine (no public port exposure)

This is the safest path — the bridge only listens on `127.0.0.1` of the VM, and
you talk to it via a local port forwarded over your existing SSH connection.

```powershell
# Foreground (Ctrl+C to stop). Use NSSM / Task Scheduler for a persistent tunnel.
gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE `
  --ssh-flag="-L 8765:127.0.0.1:8765" --ssh-flag="-N"

# In another terminal, smoke test
curl http://127.0.0.1:8765/healthz
curl -X POST http://127.0.0.1:8765/query `
  -H "Content-Type: application/json" `
  -d '{\"sql\":\"SELECT name FROM sqlite_master WHERE type=\\\"table\\\" LIMIT 5\"}'
```

## 5. Python client (drop into the project)

```python
# red_bar_lab/cloud/sqlite_bridge.py
from __future__ import annotations

import os
from typing import Any
from urllib import request
import json


class SqliteBridge:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("RB_SQLITE_BRIDGE_URL")
            or "http://127.0.0.1:8765"
        ).rstrip("/")

    def health(self) -> dict:
        return self._get("/healthz")

    def schema(self) -> list[dict[str, str]]:
        return self._get("/schema")["objects"]

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        body = json.dumps({"sql": sql, "params": params or []}).encode()
        req = request.Request(
            f"{self.base_url}/query",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        return payload["rows"]

    def _get(self, path: str) -> dict:
        with request.urlopen(f"{self.base_url}{path}", timeout=10) as resp:
            return json.loads(resp.read())


# usage
# bridge = SqliteBridge()
# bridge.health()
# rows = bridge.query("SELECT * FROM red_bar_v2_signal WHERE run_id = ?", [run_id])
```

## 6. Tear-down (if you ever want it gone)

```powershell
gcloud compute instances delete $VM --project=$PROJECT --zone=$ZONE --quiet
gcloud compute disks delete $DISK --project=$PROJECT --zone=$ZONE --quiet
gcloud compute addresses delete rb-itos-ai-validation-ip --project=$PROJECT --region=$REGION --quiet
gcloud compute firewall-rules delete allow-ssh-rb-itos-ai --project=$PROJECT --quiet
```

## 7. Cost expectations (USD, Mumbai region, on-demand)

- e2-standard-2: ~$0.067/hr  (~$49/mo if 24/7)
- pd-balanced 50 GB: ~$5/mo
- Static external IP (in-use): ~$0/month while attached
- Egress: first 1 GB/mo free, then $0.12/GB

Stop the VM when not in use to drop the compute line to zero (disk + IP still
incur small charges). To start/stop:

```powershell
gcloud compute instances stop   $VM --project=$PROJECT --zone=$ZONE
gcloud compute instances start  $VM --project=$PROJECT --zone=$ZONE
```
