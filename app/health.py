"""Контроль, что планировщик жив и ежедневный проход не потерян."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
p=Path(os.getenv('STATE_PATH','/app/data/unified.json'))
if not p.exists():sys.exit(1)
s=json.loads(p.read_text());last=dt.datetime.fromisoformat(s.get('last_run_at','1970-01-01T00:00:00+00:00'))
sys.exit(0 if (dt.datetime.now(dt.timezone.utc)-last).total_seconds()<36*3600 else 1)
