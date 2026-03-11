# Local Setup Guide - SLRD Dashboard with SQLite

## Overview
Your SLRD Dashboard has been completely converted from PostgreSQL (Railway cloud) to SQLite (local database). All Railway configuration has been removed.

## Quick Start (5 minutes)

### Step 1: Initialize the Database
```bash
python init_sqlite.py
```
This will:
- Create `slrddemo.db` (SQLite database file)
- Create all 16 tables with proper schema
- Set up relationships and constraints
- Create default admin user

### Step 2: Start the Application
```bash
python main.py
```

You should see:
```
✓ Database connection successful!
✓ Rate limiter configured (in-memory storage)
✓ Flask app initialized
 * Running on http://127.0.0.1:5000
```

### Step 3: Access the Application
Open your browser and visit:
```
http://localhost:5000
```

## Default Credentials

**Admin User:**
- Email: `anubha@yeseartheco.com`
- Password: `Anubha@#46`
- OTP: `123456`

You can change these in `main.py` lines 218-220 if needed.

## What's Changed

### ✅ Removed
- ❌ All PostgreSQL/Railway configuration
- ❌ REDIS_URL dependencies
- ❌ Environment variable requirements (DATABASE_URL, ENV, FLASK_ENV)
- ❌ check_schema.py (PostgreSQL diagnostics)
- ❌ check_db.py (PostgreSQL diagnostics)
- ❌ Production security headers (HSTS)
- ❌ Cloud deployment settings

### ✅ Added/Updated
- ✅ SQLite database (local file: `slrddemo.db`)
- ✅ Local development configuration
- ✅ Port 5000 default (localhost)
- ✅ Debug mode enabled by default
- ✅ init_sqlite.py initialization script
- ✅ Session cookies configured for HTTP (local development)

## Configuration

### Environment Variables (Optional)
You can optionally set these environment variables:

```bash
# Port (default: 5000)
export PORT=5000

# Debug mode (default: True)
export DEBUG=True

# Admin credentials (optional - defaults are in code)
export ADMIN_EMAIL=admin@example.com
export ADMIN_PASSWORD=your_password
export ADMIN_OTP=123456

# Secret key (optional - defaults to local dev key)
export SECRET_KEY=your-secret-key
```

### Without Environment Variables
If you don't set any environment variables, the application will run with:
- Port: 5000
- Debug: True
- Host: 127.0.0.1 (localhost only)
- Database: `slrddemo.db` (local SQLite file)

## File Structure

```
project/
├── main.py                          # Flask application (updated for SQLite)
├── init_sqlite.py                   # Database initialization script
├── slrddemo.db                      # SQLite database (created on first run)
├── static/
│   ├── css/
│   │   ├── style.css
│   │   ├── responsive.css           # Mobile responsive styles
│   │   └── mobile-enhancements.css  # Mobile enhancements
│   ├── js/
│   │   ├── common-utils.js          # Updated with mobile utilities
│   │   └── other JS files
│   └── uploads/                     # User uploads (avatars, etc.)
├── templates/
│   ├── admin-dashboard.html
│   ├── employee-dashboard.html
│   ├── super-admin-dashboard.html
│   ├── login.html
│   └── other HTML templates
├── SQLITE_README.md                 # Database documentation
├── LOCAL_SETUP_GUIDE.md             # This file
└── other config files
```

## Database Information

### Database File
- Location: `./slrddemo.db`
- Type: SQLite 3
- Size: ~500KB (initially, grows with data)
- Backup: Simply copy the `.db` file

### Tables (16 total)
1. **User Management**
   - `users` - User accounts and profiles
   - `usertypes` - Role definitions (Admin, Manager, Employee)
   - `user_permissions` - User-specific permissions
   - `user_skills` - User skills and expertise

2. **Project Management**
   - `projects` - Project information
   - `project_assignments` - User project assignments
   - `milestones` - Project milestones

3. **Task Management**
   - `tasks` - Individual tasks
   - `comments` - Task comments
   - `documents` - File uploads

4. **Reporting**
   - `daily_task_reports` - Daily work reports
   - `report_comments` - Comments on reports

5. **System**
   - `activities` - User activity log
   - `audit_logs` - Audit trail
   - `progress_history` - Project progress tracking

## Common Issues & Solutions

### Issue: "slrddemo.db not found"
**Solution:** Run `python init_sqlite.py` first to create the database

### Issue: "Address already in use"
**Solution:** Change the PORT:
```bash
export PORT=5001
python main.py
```

### Issue: "CORS errors"
**Solution:** This is normal in development. The app handles it with CORS configuration.

### Issue: "Session not persisting"
**Solution:** Clear your browser cookies and log in again

### Issue: Database locked error
**Solution:** Make sure only one instance of the app is running

## Running in VS Code

### 1. Open Terminal
Press `Ctrl + `` (backtick) or go to Terminal → New Terminal

### 2. Initialize Database (first time only)
```bash
python init_sqlite.py
```

### 3. Start Application
```bash
python main.py
```

### 4. Debug in VS Code
Create `.vscode/launch.json`:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Flask",
            "type": "python",
            "request": "launch",
            "module": "flask",
            "env": {
                "FLASK_APP": "main.py",
                "FLASK_ENV": "development",
                "DEBUG": "True",
                "PORT": "5000"
            },
            "args": ["run", "--host=127.0.0.1"],
            "jinja": true,
            "justMyCode": true
        }
    ]
}
```

Then press F5 to start debugging.

## Performance Tips

1. **Use SQLite for development** - Great for testing, single user
2. **Keep database under 100MB** - Compact and fast
3. **Clear old activities** - Use `/admin/maintenance` (if available)
4. **Backup regularly** - Copy `slrddemo.db` to backup folder

## Migration to Production

When you're ready to deploy:

1. **Use PostgreSQL in production** - Not SQLite
2. **Never commit `slrddemo.db`** - Add to `.gitignore`
3. **Use environment variables** - For production secrets
4. **Enable HTTPS** - Update `SESSION_COOKIE_SECURE = True`
5. **Use proper secret key** - Set `SECRET_KEY` env var

## Getting Help

Refer to these documentation files:
- `SQLITE_SCHEMA_REFERENCE.md` - Database schema details
- `RESPONSIVE_REDESIGN_SUMMARY.md` - Mobile responsiveness
- `RESPONSIVE_CODE_EXAMPLES.md` - Code examples
- `POSTGRESQL_TO_SQLITE_CHANGES.md` - Technical changes

## Summary

✅ Your SLRD Dashboard is now:
- Fully responsive on mobile, tablet, and desktop
- Running on local SQLite database
- No external dependencies or cloud services
- Ready for local development in VS Code
- Easy to backup and restore

**You can now run the entire application locally without any internet or cloud services!**
