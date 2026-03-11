# SQLite Quick Start - 5 Minutes Setup

## TL;DR - Just 3 Steps

### Step 1: Initialize Database
```bash
python init_sqlite.py
```
Expected output:
```
[OK] SQLite database initialized successfully at /path/to/slrddemo.db!
```

### Step 2: Start Application
```bash
python main.py
```

### Step 3: Open Browser
Visit: `http://localhost:5000`

**Done!** 🎉 Your application is now using SQLite.

---

## What Happened?

- ✅ PostgreSQL removed
- ✅ SQLite installed (built-in)
- ✅ Local database file created (`slrddemo.db`)
- ✅ All 16 tables automatically created
- ✅ Default permissions seeded

## Verify It Works

1. Log in with admin credentials
2. Navigate to Admin Dashboard
3. Create a new project
4. Check database file exists: `ls -lh slrddemo.db`

## Key Files

| File | Purpose |
|------|---------|
| `init_sqlite.py` | Creates database & tables |
| `slrddemo.db` | Your actual database file |
| `main.py` | Updated Flask app (uses SQLite) |

## Common Commands

### Start fresh (delete old data)
```bash
rm slrddemo.db
python init_sqlite.py
python main.py
```

### Backup database
```bash
cp slrddemo.db slrddemo.db.backup
```

### Check database size
```bash
ls -lh slrddemo.db
```

### View database contents (sqlite3 CLI)
```bash
sqlite3 slrddemo.db ".tables"  # List tables
sqlite3 slrddemo.db "SELECT COUNT(*) FROM users;"  # Count users
```

## Troubleshooting

**Issue:** `ModuleNotFoundError: No module named 'init_sqlite'`
- **Fix:** Run `python init_sqlite.py` not import it

**Issue:** `Database is locked`
- **Fix:** Close other processes accessing the database

**Issue:** No `slrddemo.db` file created
- **Fix:** Check file permissions in the directory

## Next Steps

- Read full guide: `SQLITE_MIGRATION_GUIDE.md`
- Check responsive design: `RESPONSIVE_DESIGN_SUMMARY.md`
- Review code examples: `RESPONSIVE_CODE_EXAMPLES.md`

---

**Database Ready!** Continue with your application development. 🚀
