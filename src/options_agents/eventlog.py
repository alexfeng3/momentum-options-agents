"""Append-only JSONL event log. Every agent writes here; nothing is silent."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]


class EventLog:
    def __init__(self, run_id: str, echo: bool = True, log_dir: Path | None = None):
        self.run_id, self.echo = run_id, echo
        d = log_dir or (ROOT / "logs")
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"events-{datetime.now(ET):%Y-%m-%d}.jsonl"
        self._seq = 0

    def emit(self, agent: str, event: str, payload: Any = None, **kw) -> dict:
        self._seq += 1
        rec = {"seq": self._seq, "run_id": self.run_id,
               "ts_utc": datetime.now(timezone.utc).isoformat(),
               "ts_et": datetime.now(ET).isoformat(),
               "agent": agent, "event": event,
               "payload": payload if payload is not None else {}}
        rec.update(kw)
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        if self.echo:
            print(f"  [{agent:<11}] {event}", file=sys.stderr)
        return rec
