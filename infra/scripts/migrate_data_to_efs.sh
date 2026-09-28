#!/bin/bash
# One-time copy of the app's data/ from the legacy EC2 server's EBS volume to
# EFS, for the move to ECS Fargate. Runs on the EC2 server (via SSM Run
# Command) as root:  migrate_data_to_efs.sh <efs-file-system-id> [region]
#
# - Stops the EC2 backend first: SQLite is single-writer, and nothing may
#   write between this copy and switching traffic to Fargate. The site is
#   down from here until the switch (adlc:serveFrom=fargate + pulumi up).
# - Copies into /adlc-data on EFS — the root of the access point the
#   container mounts at /app/data — owned by uid/gid 1000 (the container user).
# - Rewrites the absolute paths the app stores (/opt/adlc/app/data/… on EC2)
#   to where the container sees them (/app/data/…): tile paths in
#   metadata.json, documents.source_file_path, intake_resources.file_path.
# - Leaves the EBS volume untouched, so switching back stays possible.
set -euo pipefail

FS_ID="$1"
REGION="${2:-eu-central-1}"
SRC=/srv/adlc-data
MNT=/mnt/adlc-efs
DEST="$MNT/adlc-data"
OLD=/opt/adlc/app/data/
NEW=/app/data/

systemctl stop adlc-backend
echo "EC2 backend stopped."

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q nfs-common rsync >/dev/null

mkdir -p "$MNT"
mountpoint -q "$MNT" || mount -t nfs4 \
  -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport \
  "$FS_ID.efs.$REGION.amazonaws.com:/" "$MNT"

mkdir -p "$DEST"
rsync -a --delete --exclude lost+found "$SRC/" "$DEST/"

python3 - "$DEST" "$OLD" "$NEW" <<'PY'
import json, sqlite3, sys
from pathlib import Path

dest, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

meta = dest / "metadata.json"
if meta.exists():
    rows = json.loads(meta.read_text())
    changed = 0
    for row in rows:
        path = row.get("tile_path")
        if isinstance(path, str) and path.startswith(old):
            row["tile_path"] = new + path[len(old):]
            changed += 1
    meta.write_text(json.dumps(rows, indent=2))
    print(f"metadata.json: {changed} of {len(rows)} tile paths rewritten")

db = dest / "tkmind.db"
if db.exists():
    con = sqlite3.connect(db)
    for table, column in (("documents", "source_file_path"), ("intake_resources", "file_path")):
        n = con.execute(
            f"UPDATE {table} SET {column} = replace({column}, ?, ?) WHERE {column} LIKE ?",
            (old, new, old + "%"),
        ).rowcount
        print(f"{table}.{column}: {n} paths rewritten")
    con.commit()
    print("integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()
PY

chown -R 1000:1000 "$DEST"
chmod 750 "$DEST"
sync
echo "--- copied to EFS:"
du -sh "$DEST"
ls -la "$DEST"
umount "$MNT"
echo "Done. Next: pulumi config set adlc:serveFrom fargate && pulumi up"
