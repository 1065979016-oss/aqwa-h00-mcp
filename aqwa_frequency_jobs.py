"""Atomic job status publication."""
from datetime import datetime, timezone
import json
import os
import time

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def write_status(folder,record):
    target,temp=folder/"frequency_job.json",folder/".frequency_job.pending"
    temp.write_text(json.dumps({**record,"updated_at":timestamp()},allow_nan=False),encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temp,target)
            return
        except PermissionError:
            if attempt==4:
                raise
            time.sleep(.025)
