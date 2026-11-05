"""Atomic daily API reservations, separate from restorable library backups.

No secrets, prompts or provider bodies. A reservation is committed BEFORE send;
timeouts/crashes retain it. Settings changes and application restarts cannot
clear the ledger. This is a local estimate, not a provider-account billing cap.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import sqlite3
import uuid
from .sqlite_utils import ClosingConnection

_SCALE = Decimal(10**9)


def units(usd):
    return int((Decimal(str(usd)) * _SCALE).to_integral_value(rounding=ROUND_CEILING))


class BudgetError(ValueError):
    pass


class APIBudget:
    def __init__(self, path):
        self.path = Path(path)
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS api_reservations(
                id TEXT PRIMARY KEY, day TEXT NOT NULL, reserved INTEGER NOT NULL,
                actual INTEGER, input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0)''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)

    @staticmethod
    def day():
        return datetime.now(timezone.utc).date().isoformat()

    def status(self):
        day = self.day()
        with self.connect() as c:
            row = c.execute('''SELECT count(*),coalesce(sum(reserved),0),
                coalesce(sum(actual),0),coalesce(sum(input_tokens),0),coalesce(sum(output_tokens),0)
                FROM api_reservations WHERE day=?''', (day,)).fetchone()
        return dict(day_utc=day, calls=row[0], reserved_cost_usd=row[1]/1e9,
            estimated_cost_usd=row[2]/1e9, total_input_tokens=row[3], total_output_tokens=row[4])

    def reserve(self, estimate, config):
        reservation = uuid.uuid4().hex
        day = self.day()
        amount = units(estimate)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            count, held = c.execute('''SELECT count(*),coalesce(sum(reserved),0)
                FROM api_reservations WHERE day=?''', (day,)).fetchone()
            if count >= config.max_calls:
                raise BudgetError('오늘의 API 호출 한도에 도달했습니다 (UTC 기준).')
            if held + amount > units(config.max_cost_usd):
                raise BudgetError('오늘의 API 예상 비용 한도에 도달했습니다 (UTC 기준).')
            c.execute('INSERT INTO api_reservations(id,day,reserved) VALUES(?,?,?)',
                (reservation, day, amount))
        return reservation

    def settle(self, reservation, actual, input_tokens, output_tokens):
        with self.connect() as c:
            c.execute('''UPDATE api_reservations SET reserved=?,actual=?,input_tokens=?,output_tokens=?
                WHERE id=? AND actual IS NULL''',
                (units(actual), units(actual), input_tokens, output_tokens, reservation))
