# ⚡ Quick Start - SLRD Dashboard (Local SQLite)

## 30 Second Setup

### Step 1: Initialize Database
```bash
python init_sqlite.py
```

### Step 2: Start App
```bash
python main.py
```

### Step 3: Open Browser
```
http://localhost:5000
```

---

## Login Credentials

```
Email:    anubha@yeseartheco.com
Password: Anubha@#46
OTP:      123456
```

---

## Key Information

| Item | Value |
|------|-------|
| **Database** | SQLite (local file) |
| **Database File** | `slrddemo.db` |
| **URL** | http://localhost:5000 |
| **Port** | 5000 |
| **Host** | 127.0.0.1 (localhost) |
| **Debug Mode** | Enabled |
| **Database Backup** | `cp slrddemo.db slrddemo.db.backup` |

---

## Common Commands

```bash
# Initialize database (first time only)
python init_sqlite.py

# Start application
python main.py

# Run with custom port
PORT=5001 python main.py

# Reset database
rm slrddemo.db
python init_sqlite.py

# Backup database
cp slrddemo.db slrddemo.db.backup

# Restore from backup
cp slrddemo.db.backup slrddemo.db
```

---

## What Changed

### ✅ Removed
- PostgreSQL/Railway cloud config
- Environment variables (DATABASE_URL, etc.)
- REDIS dependencies
- Production security headers

### ✅ Added
- Local SQLite database (`slrddemo.db`)
- Simple configuration
- No external dependencies
- Mobile responsive UI

---

## If Something Goes Wrong

| Problem | Solution |
|---------|----------|
| Database not found | Run `python init_sqlite.py` |
| Port already in use | Use `PORT=5001 python main.py` |
| Slow performance | Database is still compact, should be fast |
| Database locked | Close app, wait 5 seconds, restart |
| Can't login | Check credentials in QUICK_START.md |

---

## Documentation

- 📖 **LOCAL_SETUP_GUIDE.md** - Detailed setup guide
- 🗄️ **SQLITE_SCHEMA_REFERENCE.md** - Database schema
- 📱 **RESPONSIVE_REDESIGN_SUMMARY.md** - Mobile features
- 🔧 **RAILWAY_CLEANUP_COMPLETE.md** - What was removed

---

## File Locations

```
project/
├── main.py                  ← Application
├── init_sqlite.py           ← Database setup
├── slrddemo.db             ← Database (created on first run)
├── static/                 ← CSS, JS, uploads
├── templates/              ← HTML pages
└── LOCAL_SETUP_GUIDE.md    ← Full documentation
```

---

## Dashboard Access

Once app is running at `http://localhost:5000`:

- **Admin Dashboard**: `/admin/dashboard`
- **Employee Dashboard**: `/employee/dashboard`
- **Super Admin**: `/super-admin/daily-reports`
- **Login**: `/login`
- **Profile**: `/profile`

---

## First Time Checklist

- [ ] Run `python init_sqlite.py`
- [ ] Run `python main.py`
- [ ] Open `http://localhost:5000`
- [ ] Login with credentials above
- [ ] Explore dashboards
- [ ] Check everything works

**That's it! You're ready to go.** 🎉

---

## Need Help?

Read the full documentation:
- **Setup Issues?** → LOCAL_SETUP_GUIDE.md
- **Database Questions?** → SQLITE_SCHEMA_REFERENCE.md
- **Mobile Issues?** → RESPONSIVE_REDESIGN_SUMMARY.md
- **What Changed?** → RAILWAY_CLEANUP_COMPLETE.md
