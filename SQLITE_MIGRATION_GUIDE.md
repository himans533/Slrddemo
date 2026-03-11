# SQLite Migration Guide

## Overview

Your SLRD Dashboard has been successfully converted from PostgreSQL to SQLite. This guide explains the changes, how to use the new setup, and important considerations.

## What Changed

### 1. Database System
- **From:** PostgreSQL (remote database on Railway)
- **To:** SQLite (local file-based database)

### 2. Files Added/Modified

#### New Files Created:
- **`init_sqlite.py`** - SQLite database initialization script
- **`slrddemo.db`** - Local SQLite database file (auto-created)

#### Files Modified:
- **`main.py`** - Updated to use SQLite instead of PostgreSQL

### 3. Key Differences

#### PostgreSQL vs SQLite SQL Syntax

| Aspect | PostgreSQL | SQLite |
|--------|-----------|--------|
| **Auto-increment** | `SERIAL PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| **Parameters** | `%s` for placeholders | `?` for placeholders |
| **RETURNING clause** | `INSERT ... RETURNING id` | Use `cursor.lastrowid` |
| **Boolean** | `BOOLEAN` | `INTEGER (0/1)` |
| **Connection** | `psycopg2` | `sqlite3` |
| **Row Factory** | `RealDictCursor` | `sqlite3.Row` |
| **Database Location** | Remote server | Local file (`slrddemo.db`) |

## Database Schema

### All Tables Included:
1. **usertypes** - User role definitions
2. **usertype_permissions** - Role-based permissions
3. **users** - User accounts and profiles
4. **user_permissions** - Individual user permissions
5. **projects** - Project management
6. **tasks** - Task tracking
7. **milestones** - Project milestones
8. **comments** - Project/task comments
9. **documents** - File uploads
10. **project_assignments** - User-project assignments
11. **progress_history** - Project progress tracking
12. **activities** - User activity logs
13. **user_skills** - User skill tracking
14. **daily_task_reports** - Daily task reporting
15. **report_comments** - Report comments
16. **audit_logs** - System audit trail

All foreign key relationships are preserved.

## Setup Instructions

### Step 1: Initialize the Database

Run the initialization script to create the SQLite database with all tables:

```bash
python init_sqlite.py
```

Output:
```
============================================================
SQLite Database Initialization
============================================================
Creating new database at /path/to/slrddemo.db
Database initialization completed successfully!
Database has 16 tables: [list of tables]
```

### Step 2: Start the Flask Application

The Flask application will automatically use SQLite:

```bash
python main.py
```

The database connection is now managed locally.

### Step 3: Verify Setup

1. Check if `slrddemo.db` file exists in project root
2. Log in with admin credentials
3. Verify projects, tasks, and reports load correctly

## Important Changes in main.py

### Database Connection

**Old (PostgreSQL):**
```python
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    conn = psycopg2.connect(...)
    return PostgreSQLConnection(conn)
```

**New (SQLite):**
```python
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), 'slrddemo.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

### SQL Parameter Placeholders

**Old (PostgreSQL):**
```python
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

**New (SQLite):**
```python
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### Getting Last Inserted ID

**Old (PostgreSQL):**
```python
cursor.execute("INSERT INTO users ... RETURNING id")
new_id = cursor.fetchone()['id']
```

**New (SQLite):**
```python
cursor.execute("INSERT INTO users ...")
new_id = cursor.lastrowid
```

## Advantages of SQLite

✅ **Faster Setup** - No remote server configuration needed
✅ **Self-Contained** - Single database file that travels with code
✅ **Development Friendly** - Perfect for development and testing
✅ **No Dependencies** - SQLite is built into Python
✅ **Easier Backup** - Just copy the `slrddemo.db` file
✅ **Lower Cost** - No database service fees

## When to Consider Alternatives

You might want to switch back to PostgreSQL if:
- ❌ Multiple server instances need shared database access
- ❌ You have high concurrent write operations
- ❌ You need advanced PostgreSQL features
- ❌ Database file size exceeds 100GB
- ❌ You need replication/backup to multiple servers

## Backup and Recovery

### Backing Up Data

Simply copy the `slrddemo.db` file:

```bash
cp slrddemo.db slrddemo_backup_$(date +%Y%m%d_%H%M%S).db
```

### Restoring Data

Copy the backup back:

```bash
cp slrddemo_backup_YYYYMMDD_HHMMSS.db slrddemo.db
```

## Database Optimization

### Enable WAL Mode (Optional)

For better concurrent access:

```python
conn.execute("PRAGMA journal_mode = WAL")
```

### Create Indexes

Add indexes for frequently queried columns:

```python
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_users_email 
    ON users(email)
""")
```

### Vacuum Database

Optimize storage:

```python
cursor.execute("VACUUM")
```

## Troubleshooting

### Issue: Database locked error

**Solution:** Ensure only one process is writing at a time. SQLite locks during writes.

### Issue: Foreign key constraint failed

**Solution:** Make sure `PRAGMA foreign_keys = ON` is set in connection.

### Issue: Database file keeps growing

**Solution:** Run `VACUUM` command periodically.

### Issue: Connection timeout

**Solution:** SQLite doesn't have connection timeouts. Check file permissions.

## Migration Checklist

- [x] PostgreSQL imports removed
- [x] SQLite imports added
- [x] Database connection updated
- [x] SQL syntax converted (SERIAL → AUTOINCREMENT)
- [x] Parameter placeholders converted (% → ?)
- [x] All 16 tables recreated
- [x] Foreign key relationships preserved
- [x] Permissions seeding updated
- [x] Init script created
- [x] Documentation added

## SQL Query Examples

### Create a Project

```python
cursor.execute("""
    INSERT INTO projects (title, description, created_by_id)
    VALUES (?, ?, ?)
""", ('My Project', 'Description', user_id))
conn.commit()
```

### Query with Joins

```python
cursor.execute("""
    SELECT u.username, p.title
    FROM project_assignments pa
    JOIN users u ON pa.user_id = u.id
    JOIN projects p ON pa.project_id = p.id
    WHERE p.id = ?
""", (project_id,))
results = cursor.fetchall()
```

### Update Multiple Rows

```python
cursor.execute("""
    UPDATE tasks
    SET status = ?
    WHERE project_id = ?
""", ('Completed', project_id))
conn.commit()
```

## Monitoring Database Size

```python
import os
db_size = os.path.getsize('slrddemo.db')
print(f"Database size: {db_size / 1024 / 1024:.2f} MB")
```

## Next Steps

1. ✅ Initialize database: `python init_sqlite.py`
2. ✅ Start application: `python main.py`
3. ✅ Test functionality
4. ✅ Create backups regularly
5. ✅ Monitor database size

## Support

For issues specific to SQLite:
- Official SQLite Documentation: https://www.sqlite.org/docs.html
- Python sqlite3 Module: https://docs.python.org/3/library/sqlite3.html

## Version Info

- **SQLite Version:** 3.40+ (built-in with Python 3.11+)
- **Python:** 3.8+
- **Framework:** Flask
- **Migration Date:** 2026-03-11
