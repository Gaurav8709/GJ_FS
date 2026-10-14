#!/usr/bin/env python3
"""
Migration: Add attendance columns to employee_detections table in RDS.

Adds:
  - status          VARCHAR(20) DEFAULT 'detected'   (detected | present | absent)
  - attendance_date VARCHAR(20)                       (DD-MM-YYYY format)

Run on EC2:
    cd /home/ubuntu/app/backend
    source venv/bin/activate
    python3 scripts/migrate_add_attendance_columns.py
"""

import os
import sys
import asyncio

# Make sure backend app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


MIGRATIONS = [
    # Add status column (present | absent | detected)
    {
        "name": "add status column",
        "check_sql": """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'employee_detections' AND column_name = 'status'
        """,
        "apply_sql": """
            ALTER TABLE employee_detections
            ADD COLUMN status VARCHAR(20) DEFAULT 'detected'
        """
    },
    # Add attendance_date column (DD-MM-YYYY)
    {
        "name": "add attendance_date column",
        "check_sql": """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'employee_detections' AND column_name = 'attendance_date'
        """,
        "apply_sql": """
            ALTER TABLE employee_detections
            ADD COLUMN attendance_date VARCHAR(20)
        """
    },
    # Widen location column from VARCHAR(100) to VARCHAR(200)
    {
        "name": "widen location column to VARCHAR(200)",
        "check_sql": """
            SELECT character_maximum_length FROM information_schema.columns
            WHERE table_name = 'employee_detections' AND column_name = 'location'
              AND character_maximum_length >= 200
        """,
        "apply_sql": """
            ALTER TABLE employee_detections
            ALTER COLUMN location TYPE VARCHAR(200)
        """
    },
]


async def run_migrations():
    print("=" * 60)
    print("GJ-Fashion — RDS Migration: attendance columns")
    print("=" * 60)

    async with engine.begin() as conn:
        for migration in MIGRATIONS:
            name = migration["name"]
            # Check if already applied
            result = await conn.execute(text(migration["check_sql"]))
            existing = result.fetchone()

            if existing:
                print(f"  ✅ SKIP  [{name}] — already exists")
            else:
                try:
                    await conn.execute(text(migration["apply_sql"]))
                    print(f"  🔧 APPLIED [{name}]")
                except Exception as e:
                    print(f"  ❌ ERROR [{name}]: {e}")

    print()
    print("✅ Migration complete.")
    print()
    print("New endpoint summary:")
    print("  POST /api/face-alerts/upload-snapshot  → S3 employee_detections/")
    print("  POST /api/face-alerts/attendance       → RDS employee_detections table")
    print("  GET  /api/face-alerts/attendance       → Query attendance records")


if __name__ == "__main__":
    asyncio.run(run_migrations())
