"""Explicitly restore the synthetic demonstration database. BACK UP real records first!"""
from pathlib import Path
import shutil
root = Path(__file__).resolve().parent
source = root / 'demo_database_backup.db'
target = root / 'instance' / 'attendance.db'
print('WARNING: This replaces the current attendance database with synthetic demo records.')
if input('Type RESTORE to continue: ').strip() == 'RESTORE':
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(source, target)
    print('Restored synthetic demo database.')
else:
    print('Cancelled.')
