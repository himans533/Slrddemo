
from flask import Flask, jsonify, request, render_template, session, g, send_from_directory
from flask_cors import CORS
import os
import sqlite3

# Rate limiting - using simple in-memory storage for local development
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:
    Limiter = None
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import secrets
import json
import re
import io
import logging
import traceback
from flask.json.provider import DefaultJSONProvider
from datetime import datetime, timezone, timedelta, date , time
from flask import redirect, url_for
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from itsdangerous import URLSafeTimedSerializer



class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()
        return super().default(obj)


# Helper function to safely convert database rows to dicts
def safe_dict(row, keys=None):
    """Safely convert a database row to a dictionary"""
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return dict(row)
    if isinstance(row, (list, tuple)):
        if keys:
            return dict(zip(keys, row))
        return {'value': row[0]} if row else {}
    return row


# Helper function to safely get a value from a row
def safe_get(row, key, default=None):
    """Safely get a value from a database row"""
    if row is None:
        return default
    if hasattr(row, 'keys'):
        return row.get(key, default) if hasattr(row, 'get') else (row[key] if key in row else default)
    return default


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
app = Flask(__name__)
app.json = CustomJSONProvider(app)
csrf = CSRFProtect(app)
CORS(app)

# Use a local development secret key
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-secret-key-change-in-production")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # Set to False for local development
)

valid_tokens = {}

# In-memory store for failed login attempts (simple rate limiter)
failed_login_attempts = {}
LOGIN_BLOCK_THRESHOLD = 5  
LOGIN_BLOCK_WINDOW = 15 * 60  # 15 minutes


def get_client_ip():
    # Respect X-Forwarded-For if present
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


def is_ip_blocked(ip):
    info = failed_login_attempts.get(ip)
    if not info:
        return False
    blocked_until = info.get('blocked_until')
    if blocked_until and blocked_until > time.time():
        return True
    # If window expired, clear
    if time.time() - info.get('first_failed', 0) > LOGIN_BLOCK_WINDOW:
        failed_login_attempts.pop(ip, None)
        return False
    return False


def register_failed_login(ip):
    now = time.time()
    info = failed_login_attempts.get(ip)
    if not info:
        failed_login_attempts[ip] = {'count': 1, 'first_failed': now}
    else:
        # Reset if outside window
        if now - info.get('first_failed', 0) > LOGIN_BLOCK_WINDOW:
            failed_login_attempts[ip] = {'count': 1, 'first_failed': now}
        else:
            info['count'] = info.get('count', 0) + 1
            if info['count'] >= LOGIN_BLOCK_THRESHOLD:
                info['blocked_until'] = now + LOGIN_BLOCK_WINDOW


def reset_failed_login(ip):
    failed_login_attempts.pop(ip, None)



# CSRF helpers
def generate_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


@app.context_processor
def inject_csrf():
    # Make csrf_token available in templates
    return {'csrf_token': generate_csrf_token()}


@app.before_request
def csrf_protect():
    # Skip CSRF for GET requests
    if request.method == 'GET':
        return
    
    # Skip CSRF for API endpoints with Bearer token authentication
    # Bearer tokens are already cryptographically signed and provide implicit CSRF protection
    if request.path.startswith('/api/'):
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            return
    
    # Let Flask-WTF handle CSRF for session-based requests (forms, etc.)
    # This will be skipped by @csrf.exempt where needed


# Global error handlers to ensure JSON responses for API endpoints
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Endpoint not found"}), 404
    # For non-API routes, use default handler
    return e

@app.errorhandler(500)
def internal_error(e):
    if request.path.startswith('/api/'):
        logger.error(f"Internal server error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    # For non-API routes, use default handler
    return e


@app.after_request
def set_security_headers(response):
    try:
    # HSTS disabled for local development
    except Exception:
        pass

    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Minimal Permissions-Policy header to opt-out of sensors
    response.headers['Permissions-Policy'] = 'geolocation=()'
    return response

# Make session cookies secure when appropriate
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # Local development

# Initialize rate limiter for local development (in-memory storage)
limiter = None
if Limiter is not None:
    try:
        limiter = Limiter(
            key_func=get_client_ip, 
            app=app, 
            storage_uri="memory://",
            default_limits=["1000 per hour"]
        )
        logger.info("✓ Rate limiter configured (in-memory storage)")
    except Exception as e:
        logger.warning(f"Rate limiter initialization failed: {e}")
        limiter = None
else:
    logger.info("flask-limiter not installed; skipping rate-limiter setup")

ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'anubha@yeseartheco.com').lower()
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Anubha@#46')
ADMIN_OTP = os.environ.get('ADMIN_OTP', '123456')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads', 'profiles')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# SQLite database configuration
DB_PATH = os.path.join(os.path.dirname(__file__), 'slrddemo.db')


def get_db_connection():
    """Create a SQLite connection with proper error handling"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # Makes rows accessible like dictionaries
        conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        logger.info("✓ Database connection successful!")
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise Exception(f"Database connection failed: {e}")

   

def init_db():
    """Initialize SQLite database (idempotent)"""
    conn = None
    try:
        logger.info("Starting database initialization...")
        conn = get_db_connection()
        cursor = conn.cursor()

        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        # Create usertypes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usertypes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_role TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("✓ usertypes table ready")

        # Create usertype_permissions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usertype_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usertype_id INTEGER NOT NULL,
                module TEXT NOT NULL,
                action TEXT NOT NULL,
                granted BOOLEAN DEFAULT 0,
                FOREIGN KEY (usertype_id) REFERENCES usertypes(id) ON DELETE CASCADE,
                UNIQUE(usertype_id, module, action)
            )
        ''')
        logger.debug("✓ usertype_permissions table ready")

        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                user_type_id INTEGER NOT NULL,
                granted BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'Active',
                phone TEXT,
                department TEXT,
                bio TEXT,
                avatar_url TEXT,
                is_system INTEGER DEFAULT 0,
                created_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_type_id) REFERENCES usertypes(id),
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
            )
        ''')
        logger.debug("✓ users table ready")

        # Create user_permissions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                module TEXT NOT NULL,
                action TEXT NOT NULL,
                granted BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, module, action)
            )
        ''')
        logger.debug("✓ user_permissions table ready")

        # Create projects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'In Progress',
                progress INTEGER DEFAULT 0,
                deadline DATE,
                reporting_time TIME DEFAULT '09:00',
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (created_by_id) REFERENCES users(id)
            )
        ''')
        logger.debug("✓ projects table ready")

        # Create milestones table (must be created before tasks that reference it)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                due_date DATE,
                status TEXT DEFAULT 'Pending',
                project_id INTEGER NOT NULL,
                weightage INTEGER DEFAULT 1,
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (created_by_id) REFERENCES users(id)
            )
        ''')
        logger.debug("✓ milestones table ready")

        # Create tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'Pending',
                priority TEXT DEFAULT 'Medium',
                deadline DATE,
                project_id INTEGER NOT NULL,
                created_by_id INTEGER NOT NULL,
                assigned_to_id INTEGER,
                milestone_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                approval_status TEXT DEFAULT 'pending',
                weightage INTEGER DEFAULT 1,
                progress INTEGER DEFAULT 0,
                notes TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (created_by_id) REFERENCES users(id),
                FOREIGN KEY (assigned_to_id) REFERENCES users(id),
                FOREIGN KEY (milestone_id) REFERENCES milestones(id)
            )
        ''')


        # Create comments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author_id) REFERENCES users(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        ''')
        logger.debug("✓ comments table ready")

        # Create documents table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_size INTEGER,
                uploaded_by_id INTEGER NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (uploaded_by_id) REFERENCES users(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        ''')
        logger.debug("✓ documents table ready")

        # Create project_assignments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS project_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                reporting_manager_id INTEGER,
                reports_to_admin BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (reporting_manager_id) REFERENCES users(id),
                UNIQUE(user_id, project_id)
            )
        ''')
        logger.debug("✓ project_assignments table ready")

        # Create progress_history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS progress_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                progress_percentage INTEGER,
                tasks_completed INTEGER,
                total_tasks INTEGER,
                milestones_completed INTEGER,
                total_milestones INTEGER,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_progress_project_date 
            ON progress_history(project_id, recorded_at)
        ''')
        logger.debug("✓ progress_history table ready")

        # Create activities table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                description TEXT NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                milestone_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (milestone_id) REFERENCES milestones(id)
            )
        ''')
        logger.debug("✓ activities table ready")

        # Create user_skills table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                skill_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, skill_name)
            )
        ''')
        logger.debug("✓ user_skills table ready")

        # Create daily_task_reports table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_task_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id INTEGER,
                project_id INTEGER NOT NULL,
                report_date DATE NOT NULL,
                work_description TEXT,
                result_of_effort TEXT,
                remarks TEXT,
                communication_email TEXT,
                communication_phone TEXT,
                task_assigned_by_id INTEGER,
                time_spent REAL DEFAULT 0,
                status TEXT DEFAULT 'In Progress',
                blocker TEXT,
                approval_status TEXT DEFAULT 'pending',
                reviewed_by INTEGER,
                review_comment TEXT,
                is_locked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id)
            )
        ''')
        logger.debug("✓ daily_task_reports table ready")

        # Create report_comments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS report_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                commenter_id INTEGER NOT NULL,
                comment TEXT NOT NULL,
                internal BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES daily_task_reports(id) ON DELETE CASCADE,
                FOREIGN KEY (commenter_id) REFERENCES users(id)
            )
        ''')
        logger.debug("✓ report_comments table ready")

        # Create audit_logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("✓ audit_logs table ready")

        # Seed initial data if usertypes are empty or missing details
        cursor.execute("SELECT id, user_role FROM usertypes WHERE user_role IN ('Administrator', 'Employee', 'Project-Cordinator')")
        existing_types = {row['user_role']: row['id'] for row in cursor.fetchall()}
        
        defaults = {
            'Administrator': 'Full system access and management',
            'Employee': 'Standard employee access for reporting',
            'Project-Cordinator': 'Project management and team coordination'
        }
        
        ids = {}
        for role, desc in defaults.items():
            if role not in existing_types:
                cursor.execute("INSERT INTO usertypes (user_role, description) VALUES (?, ?)", (role, desc))
                ids[role] = cursor.lastrowid
            else:
                ids[role] = existing_types[role]
                cursor.execute("UPDATE usertypes SET description = ? WHERE id = ? AND (description IS NULL OR description = '' OR description = '-')",
                (desc, ids[role]))
        # Helper to seed permissions
        def seed_perms(ut_id, perms):
            if not ut_id: return
            for module, action in perms:
                cursor.execute("SELECT id FROM usertype_permissions WHERE usertype_id = ? AND module = ? AND action = ?", (ut_id, module, action))
                exists_row = cursor.fetchone()
                if exists_row:
                    cursor.execute("UPDATE usertype_permissions SET granted = ? WHERE id = ?", (True, exists_row['id']))
                else:
                    cursor.execute("INSERT INTO usertype_permissions (usertype_id, module, action, granted) VALUES (?, ?, ?, ?)", (ut_id, module, action, True))

        # Get IDs for seeding permissions
        admin_id = ids.get('Administrator')
        employee_id = ids.get('Employee')
        coord_id = ids.get('Project-Cordinator')

        # Administrator permissions
        admin_perms = [
            ('ADMIN', 'VIEW_HIERARCHY'), ('ADMIN', 'CREATE_USERTYPE'), ('ADMIN', 'MANAGE_PERMISSIONS'),
            ('PROJ', 'VIEW_ALL'), ('PROJ', 'CREATE'), ('PROJ', 'EDIT'), ('PROJ', 'DELETE'), ('PROJ', 'ASSIGN_COORD'),
            ('TASK', 'VIEW'), ('TASK', 'CREATE'), ('TASK', 'ASSIGN'), ('TASK', 'EDIT'),
            ('TEAM', 'VIEW'), ('TEAM', 'ADD_MEMBER'), ('TEAM', 'REMOVE_MEMBER'), ('TEAM', 'MANAGE'),
            ('REP', 'VIEW'), ('REP', 'APPROVE'), ('REP', 'REJECT')
        ]
        seed_perms(admin_id, admin_perms)
            
        # Employee permissions
        employee_perms = [
            ('PROJ', 'VIEW_ALL'), ('TASK', 'VIEW'), ('REP', 'VIEW')
        ]
        seed_perms(employee_id, employee_perms)

        # Project Coordinator permissions
        coord_perms = [
            ('PROJ', 'VIEW_ALL'), ('PROJ', 'EDIT'), ('TASK', 'VIEW'), ('TASK', 'CREATE'), ('TASK', 'ASSIGN'), ('TASK', 'EDIT'),
            ('TEAM', 'VIEW'), ('TEAM', 'ADD_MEMBER'), ('REP', 'VIEW'), ('REP', 'APPROVE')
        ]
        seed_perms(coord_id, coord_perms)

        conn.commit()
        print("[OK] Database initialized successfully (verified schema)!")

    except Exception as e:
        print(f"[ERROR] Database initialization failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def migrate_db():
    """Add missing columns to existing tables (non-destructive)"""
    conn = None
    try:
        logger.info("Running database migration...")
        conn = get_db_connection()
        cursor = conn.cursor()

        # List of columns to add (table, column, col_type)
        columns_to_add = [
            ("users", "phone", "TEXT"),
            ("users", "department", "TEXT"),
            ("users", "bio", "TEXT"),
            ("users", "avatar_url", "TEXT"),
            ("projects", "completed_at", "TIMESTAMP"),
            ("projects", "reporting_time", "TIME"),
        ]

        for table, column, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                logger.debug(f"Added column {column} to table {table}")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    pass  # Column already exists, skip
                else:
                    logger.warning(f"Could not add {column} to {table}: {e}")

        conn.commit()
        logger.info("✓ Database migration completed!")
        return True

    except Exception as e:
        logger.error(f"✗ Database migration failed: {e}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def init_daily_report_module():
    """Ensure Daily Task Reporting tables exist (non-destructive)"""
    conn = None
    try:
        logger.info("Initializing daily report module...")
        conn = get_db_connection()
        cursor = conn.cursor()

        # Daily Task Reports Table (already created in init_db, this is redundant but harmless)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_task_reports (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                task_id INTEGER,
                project_id INTEGER NOT NULL,
                report_date DATE NOT NULL,
                work_description TEXT,
                result_of_effort TEXT,
                remarks TEXT,
                communication_email TEXT,
                communication_phone TEXT,
                task_assigned_by_id INTEGER,
                time_spent REAL DEFAULT 0,
                status TEXT DEFAULT 'In Progress',
                blocker TEXT,
                approval_status TEXT DEFAULT 'pending',
                reviewed_by INTEGER,
                review_comment TEXT,
                is_locked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id)
            )
        ''')

        # Report Comments Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS report_comments (
                id SERIAL PRIMARY KEY,
                report_id INTEGER NOT NULL,
                commenter_id INTEGER NOT NULL,
                comment TEXT NOT NULL,
                internal BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES daily_task_reports(id) ON DELETE CASCADE,
                FOREIGN KEY (commenter_id) REFERENCES users(id)
            )
        ''')

        # Audit logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                actor_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        logger.info("✓ Daily Report Module Initialized")
        return True

    except Exception as e:
        logger.error(f"✗ Init Daily Report Module failed: {e}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def safe_init_db():
    """Safely initialize database on app startup"""
    try:
        logger.info("=" * 60)
        logger.info("DATABASE STARTUP")
        logger.info("=" * 60)
        
        if not init_db():
            logger.warning("Database initialization encountered issues")
        if not migrate_db():
            logger.warning("Database migration encountered issues")
        if not init_daily_report_module():
            logger.warning("Daily report module initialization encountered issues")
            
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Critical error during database startup: {e}")

def validate_password_complexity(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."

    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter."

    if len(re.findall(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>/%s\\|]', password)) < 2:
        return False, "Password must contain at least two special characters."

    return True, "Password is valid."


def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check session first
        if session.get("is_authenticated"):
            g.current_user_id = session.get("user_id")
            g.current_user_type = session.get("user_type", "employee")
            return f(*args, **kwargs)
        
        # Check Bearer token for API requests
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                s = URLSafeTimedSerializer(app.secret_key)
                data = s.loads(token, max_age=86400)
                user_id = data.get("user_id")
                if user_id:
                    g.current_user_id = user_id
                    return f(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Bearer token validation failed: {str(e)}")
                if request.is_json:
                    return jsonify({"error": "Invalid or expired token"}), 401
                return redirect("/login")

        if request.is_json:
            return jsonify({"error": "Authentication required"}), 401

        return redirect("/login")

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Try session first
        if session.get("is_authenticated") and session.get("user_type") == "admin":
            g.current_user_id = session.get("user_id")
            return f(*args, **kwargs)

        # 2. Try Bearer token
        user_id = get_current_user_id()
        if user_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT ut.user_role 
                    FROM users u 
                    JOIN usertypes ut ON u.user_type_id = ut.id 
                    WHERE u.id = %s
                """, (user_id,))
                row = cursor.fetchone()
                conn.close()
                if row and (row['user_role'] == 'Administrator' or 'admin' in row['user_role'].lower()):
                    g.current_user_id = user_id
                    return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in admin_required token check: {e}")

        if request.is_json:
            return jsonify({"error": "Admin access required"}), 403

        return redirect("/login")

    return decorated_function


def employee_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Try session first
        if session.get("is_authenticated") and session.get("user_type") == "employee":
            g.current_user_id = session.get("user_id")
            return f(*args, **kwargs)

        # 2. Try Bearer token
        user_id = get_current_user_id()
        if user_id:
            # For employees, any valid user_id with an associated role might be enough, 
            # but let's be strict if needed.
            g.current_user_id = user_id
            return f(*args, **kwargs)

        if request.is_json:
            return jsonify({"error": "Employee access required"}), 403

        return redirect("/login")

    return decorated_function


def get_current_user_id():
    """Get current user ID from session or Bearer token"""
    # Try session first (for form-based auth)
    user_id = session.get("user_id")
    if user_id:
        return user_id
    
    # Try Bearer token (for API clients)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            s = URLSafeTimedSerializer(app.secret_key)
            data = s.loads(token, max_age=86400)
            return data.get("user_id")
        except:
            return None
    
    return None


@app.before_request
def debug_session():
    print("SESSION:", dict(session))


@app.route("/")
def index():
    return render_template("login.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/admin-dashboard")
def admin_dashboard():
    if not session.get("is_authenticated") or session.get(
            "user_type") != "admin":
        return redirect(url_for("login"))

    csrf_token = generate_csrf()
    return render_template("admin-dashboard.html",
                           username=session.get("username"),
                           csrf_token=csrf_token)


@app.route("/employee-dashboard")
@employee_required
def employee_dashboard():
    csrf_token = generate_csrf()
    session['csrf_token'] = csrf_token  # Store in session for CSRF protection
    session.modified = True
    return render_template("employee-dashboard.html",
                           csrf_token=csrf_token)


@app.route("/super-admin-dashboard")
@app.route("/admin/daily-reports")
@admin_required
def super_admin_dashboard():
    """Super Admin Daily Reports Dashboard"""
    return render_template("super-admin-dashboard.html")


@app.route('/admin/projects/<int:project_id>')
@login_required
def admin_project_detail(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Project basic info + creator
        cursor.execute(
            '''
            SELECT p.*, u.username as creator_name
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            WHERE p.id = %s
        ''', (project_id, ))
        project = cursor.fetchone()
        if not project:
            conn.close()
            return "Project not found", 404

        project_dict = dict(project)

        # Team members
        cursor.execute(
            '''
            SELECT u.id, u.username, u.email, ut.user_role
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s
        ''', (project_id, ))
        members = [dict(r) for r in cursor.fetchall()]

        # Tasks for this project
        cursor.execute(
            '''
            SELECT t.id, t.title, t.status, t.assigned_to_id, u.username as assigned_to
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to_id = u.id
            WHERE t.project_id = %s
            ORDER BY t.updated_at DESC
        ''', (project_id, ))
        tasks = [dict(r) for r in cursor.fetchall()]

        # Activities grouped by user for this project
        cursor.execute(
            '''
            SELECT a.user_id, u.username, COUNT(a.id) as activity_count
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.project_id = %s
            GROUP BY a.user_id, u.username
            ORDER BY activity_count DESC
        ''', (project_id, ))
        activities_by_user = {r['user_id']: dict(r) for r in cursor.fetchall()}

        # For each member, gather metrics (tasks assigned/completed and other projects)
        member_details = []
        for m in members:
            uid = m['id']
            cursor.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed FROM tasks WHERE project_id = %s AND assigned_to_id = %s",
                (project_id, uid))
            tcounts = cursor.fetchone()

            cursor.execute(
                '''
                SELECT COUNT(DISTINCT pa.project_id) as projects_count
                FROM project_assignments pa
                JOIN projects p ON pa.project_id = p.id
                WHERE pa.user_id = %s AND pa.project_id != %s
            ''', (uid, project_id))
            proj_cnt = cursor.fetchone()

            member_details.append({
                'id':
                uid,
                'username':
                m.get('username'),
                'email':
                m.get('email'),
                'role':
                m.get('user_role'),
                'tasks_total':
                tcounts['total'] or 0,
                'tasks_completed':
                tcounts['completed'] or 0,
                'other_projects':
                proj_cnt['projects_count'] or 0,
                'activities_count':
                activities_by_user.get(uid, {}).get('activity_count', 0)
            })

        conn.close()

        return render_template('project-detail.html',
                               project=project_dict,
                               members=member_details,
                               tasks=tasks)
    except Exception as e:
        logger.exception('Error loading project detail')
        return str(e), 500


@app.route('/admin/tasks/<int:task_id>')
@login_required
def admin_task_detail(task_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Fetch Task Details with basic relations
        cursor.execute('''
            SELECT t.*, p.title as project_title, u.username as assigned_to_name, m.title as milestone_title
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN milestones m ON t.milestone_id = m.id
            WHERE t.id = %s
        ''', (task_id, ))
        task = cursor.fetchone()
        if not task:
            conn.close()
            return "Task not found", 404

        task_dict = dict(task)
        if task_dict.get('deadline'):
            task_dict['deadline'] = task_dict['deadline'].isoformat()

        # 2. Fetch Available Users (for reassignment) - Filter out "Super Admin"
        cursor.execute("SELECT id, username, email FROM users WHERE username != 'Super Admin' ORDER BY username ASC")
        users = [dict(r) for r in cursor.fetchall()]

        # 3. Fetch Project Milestones (for this task's project)
        cursor.execute('SELECT id, title FROM milestones WHERE project_id = %s ORDER BY due_date ASC', (task_dict['project_id'],))
        milestones = [dict(r) for r in cursor.fetchall()]

        # 4. Fetch Task History/Activities
        cursor.execute('''
            SELECT a.*, u.username
            FROM activities a
            JOIN users u ON a.user_id = u.id
            WHERE a.task_id = %s
            ORDER BY a.created_at DESC
        ''', (task_id, ))
        activities = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return render_template('task-detail.html',
                               task=task_dict,
                               users=users,
                               milestones=milestones,
                               activities=activities)
    except Exception as e:
        logger.exception(f'Error loading task detail for task {task_id}')
        return str(e), 500



@app.route('/admin/users/<int:user_id>')
@login_required
def admin_user_detail(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT u.id, u.username, u.email, u.phone, u.department, u.bio, u.user_type_id, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (user_id, ))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return "User not found", 404

        user_dict = dict(user)

        # 1. Direct Permissions
        cursor.execute('SELECT module, action, granted FROM user_permissions WHERE user_id = %s', (user_id,))
        direct_perms = cursor.fetchall()

        # 2. Role Permissions
        cursor.execute('SELECT module, action, granted FROM usertype_permissions WHERE usertype_id = %s', (user_dict['user_type_id'],))
        role_perms = cursor.fetchall()

        # Merge
        permissions = {}
        for p in role_perms:
            if p['module'] not in permissions: permissions[p['module']] = {}
            permissions[p['module']][p['action']] = bool(p['granted'])
        for p in direct_perms:
            if p['module'] not in permissions: permissions[p['module']] = {}
            permissions[p['module']][p['action']] = bool(p['granted'])
        
        user_dict['permissions'] = permissions

        # Projects the user is assigned to
        cursor.execute(
            '''
            SELECT p.id, p.title, p.status
            FROM project_assignments pa
            JOIN projects p ON pa.project_id = p.id
            WHERE pa.user_id = %s
        ''', (user_id, ))
        projects = [dict(r) for r in cursor.fetchall()]

        # Tasks assigned to the user
        cursor.execute(
            '''
            SELECT t.id, t.title, t.status, p.title as project_title
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.assigned_to_id = %s
            ORDER BY t.updated_at DESC
        ''', (user_id, ))
        tasks = [dict(r) for r in cursor.fetchall()]

        # Recent activities
        cursor.execute(
            '''
            SELECT a.id, a.activity_type, a.description, a.project_id, a.task_id, a.created_at
            FROM activities a
            WHERE a.user_id = %s
            ORDER BY a.created_at DESC
            LIMIT 200
        ''', (user_id, ))
        activities = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return render_template('user-detail.html',
                               user=user_dict,
                               projects=projects,
                               tasks=tasks,
                               activities=activities)
    except Exception as e:
        logger.exception('Error loading user detail')
        return str(e), 500


@app.route("/api/admin/login/step1", methods=["POST"])
@csrf.exempt
def login_step1():
    data = request.get_json() or {}
    identifier = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    client_ip = get_client_ip()
    if is_ip_blocked(client_ip):
        return jsonify({"error": "Too many failed login attempts. Try again later."}), 429

    if not identifier or not password:
        register_failed_login(client_ip)
        return jsonify({"error": "All fields are required."}), 400

    # Support login by either admin email or reserved "super admin" username
    admin_identifier_ok = False
    if "@" in identifier:
        # Validate basic email format
        if "." not in identifier.split("@")[-1]:
            return jsonify({"error": "Invalid email format."}), 400
        admin_identifier_ok = (identifier == ADMIN_EMAIL)
    else:
        # Allow reserved username variants (case-insensitive)
        normalized = identifier.replace("_", " ").strip()
        if normalized in ("super admin", "admin", "superadmin"):
            admin_identifier_ok = True
        else:
            admin_identifier_ok = False

    if not admin_identifier_ok:
        register_failed_login(client_ip)
        return jsonify({"error": "Email or username not found."}), 400

    if password != ADMIN_PASSWORD:
        register_failed_login(client_ip)
        return jsonify({"error": "Incorrect password."}), 400

    # Successful step1 -> reset attempts
    reset_failed_login(client_ip)

    return jsonify({
        "message": "OTP has been sent to your registered email (simulated).",
        "admin_id": 0,
        "success": True,
    }), 200

@app.route("/api/admin/login/step2", methods=["POST"])
@csrf.exempt
def login_step2():
    """Admin login step 2 - OTP verification"""
    data = request.get_json() or {}
    otp = data.get("otp") or ""

    client_ip = get_client_ip()
    if is_ip_blocked(client_ip):
        return jsonify({"error": "Too many failed login attempts. Try again later."}), 429

    ADMIN_OTP = os.environ.get('ADMIN_OTP', '123456')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'anubha@yeseartheco.com').lower()
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Anubha@#46')

    if otp != ADMIN_OTP:
        register_failed_login(client_ip)
        return jsonify({"error": "Invalid OTP"}), 400

    reset_failed_login(client_ip)

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Try to find an existing admin user
        cur.execute("SELECT id FROM users WHERE LOWER(email) = %s", (ADMIN_EMAIL.lower(),))
        row = cur.fetchone()

        if row:
            admin_id = row['id']
            logger.info(f"Admin user already exists: {admin_id}")
        else:
            # Create new admin user
            logger.info("Creating new admin user...")
            
            # Ensure "Administrator" usertype exists
            cur.execute("SELECT id FROM usertypes WHERE LOWER(user_role) LIKE %s", ('%admin%',))
            ut = cur.fetchone()
            
            if ut:
                utid = ut['id']
            else:
                # Create Administrator usertype
                cur.execute(
                    "INSERT INTO usertypes (user_role, created_at) VALUES (%s, CURRENT_TIMESTAMP) RETURNING id",
                    ('Administrator',)
                )
                utid = cur.fetchone()['id']

            # Hash the admin password
            hashed = generate_password_hash(ADMIN_PASSWORD)

            # ✓ FIX: Use PostgreSQL syntax instead of SQLite "INSERT OR IGNORE"
            # PostgreSQL: INSERT ... ON CONFLICT ... DO NOTHING
            cur.execute(
                """
                INSERT INTO users (username, email, password, user_type_id, granted, is_system, created_at) 
                VALUES (%s, %s, %s, %s, TRUE, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
                """,
                ('Super Admin', ADMIN_EMAIL, hashed, utid)
            )
            
            result = cur.fetchone()
            if result:
                admin_id = result['id']
                logger.info(f"New admin user created: {admin_id}")
            else:
                # User already existed (conflict), fetch existing
                cur.execute("SELECT id FROM users WHERE LOWER(email) = %s", (ADMIN_EMAIL.lower(),))
                admin_id = cur.fetchone()['id']
                logger.info(f"Admin user already existed: {admin_id}")

        # Set session
        session.clear()
        session.permanent = True
        session["is_authenticated"] = True
        session["user_id"] = admin_id
        session["username"] = "Super Admin"
        session["user_type"] = "admin"
        session["admin"] = True
        
        # Generate signed token for admin
        csrf_for_token = secrets.token_urlsafe(16)
        s = URLSafeTimedSerializer(app.secret_key)
        auth_token = s.dumps({
            'user_id': admin_id,
            'username': "Super Admin",
            'user_type': 'admin',
            'csrf_token': csrf_for_token,
            'created_at': str(datetime.now(timezone.utc))
        })
        
        conn.commit()
        logger.info(f"✓ Admin login successful for user {admin_id}")
        
        return jsonify({
            "success": True, 
            "user_id": admin_id,
            "token": auth_token,
            "csrf_token": csrf_for_token
        }), 200

    except Exception as e:
        logger.error(f"✗ Login step 2 failed: {e}")
        logger.exception("Full traceback:")
        if conn:
            conn.rollback()
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/admin/dashboard/overdue-items", methods=["GET"])
@admin_required
def get_overdue_items():
    """Get all overdue items for admin"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Overdue tasks
        cursor.execute('''
            SELECT t.id, t.title, t.description, t.status, t.priority, 
                   t.deadline, t.project_id, p.title as project_name,
                   t.assigned_to_id, u.username as assigned_to_name,
                   t.created_by_id, uc.username as created_by_name,
                   t.created_at, t.approval_status,
                   CURRENT_DATE - t.deadline as days_overdue
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN users uc ON t.created_by_id = uc.id
            WHERE t.deadline < CURRENT_DATE 
            AND t.status != 'Completed'
            AND t.status != 'Overdue'
            ORDER BY t.deadline ASC
        ''')
        overdue_tasks = cursor.fetchall()

        # Overdue projects
        cursor.execute('''
            SELECT p.id, p.title, p.description, p.status, p.progress, 
                   p.deadline, p.created_by_id, u.username as creator_name,
                   p.created_at,
                   CURRENT_DATE - p.deadline as days_overdue
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            WHERE p.deadline < CURRENT_DATE 
            AND p.status != 'Completed'
            ORDER BY p.deadline ASC
        ''')
        overdue_projects = cursor.fetchall()

        conn.close()

        return jsonify({
            "overdue_tasks": [dict(row) for row in overdue_tasks],
            "overdue_projects": [dict(row) for row in overdue_projects],
            "total_overdue_tasks":
            len(overdue_tasks),
            "total_overdue_projects":
            len(overdue_projects)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/daily-report', methods=['POST'])
@login_required
def create_daily_report():
    """Submit a daily report.
    Rules:
    - One report per task per day.
    - Hours between 0 and 24.
    - Admins can submit on behalf of employees.
    """
    try:
        current_user_id = get_current_user_id()
        data = request.get_json() or {}

        # Check if admin is submitting on behalf of someone
        report_user_id = data.get(
            'user_id')  # Admin can specify who the report is for

        # Get current user's role
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (current_user_id, ))
        current_user_role_row = cursor.fetchone()
        current_role = (current_user_role_row['user_role']
                        if current_user_role_row else 'employee').lower()

        # If user_id is specified, only admins/super-admins can do this
        if report_user_id and report_user_id != current_user_id:
            if current_role not in ['admin', 'super admin']:
                conn.close()
                return jsonify({
                    'error':
                    'Only admins can submit reports for other users'
                }), 403
            user_id = report_user_id
        else:
            user_id = current_user_id

        task_id = data.get('task_id')
        project_id = data.get('project_id')
        report_date = data.get('report_date') or datetime.now().strftime(
            '%Y-%m-%d')
        work_description = data.get('work_description') or data.get(
            'result_of_effort')
        time_spent_str = data.get('time_spent', 0)
        status = data.get('status', 'In Progress')
        blocker = data.get('blocker', '')
        communication_email = data.get('communication_email') or data.get(
            'email') or ''
        communication_phone = data.get('communication_phone') or data.get(
            'phone') or ''
        result_of_effort = data.get(
            'result_of_effort') or work_description or ''
        remarks = data.get('remarks') or ''

        if not task_id or not work_description:
            conn.close()
            return jsonify({'error': 'Task and Description are required'}), 400

        try:
            time_spent = float(time_spent_str)
            if not (0 <= time_spent <= 24):
                raise ValueError
        except (ValueError, TypeError):
            conn.close()
            return jsonify({'error':
                            'Hours spent must be between 0 and 24'}), 400

        # Verify task existence
        cursor.execute(
            "SELECT id, project_id, assigned_to_id FROM tasks WHERE id = %s",
            (task_id, ))
        task = cursor.fetchone()
        if not task:
            conn.close()
            return jsonify({'error': 'Task not found'}), 404

        # Allow admins to report on any task, but employees only on their assigned tasks
        # OR if they created the task (only for non-admin users)
        if current_role == 'employee' and user_id == current_user_id:
            if task['assigned_to_id'] != user_id and task.get(
                    'created_by_id') != user_id:
                conn.close()
                return jsonify({
                    'error':
                    'You can only report on your assigned or created tasks'
                }), 403

        # Use project_id from task if not provided or mismatch
        real_project_id = project_id or task['project_id']

        # Check duplicate
        cursor.execute(
            "SELECT id FROM daily_task_reports WHERE user_id = %s AND task_id = %s AND report_date = %s",
            (user_id, task_id, report_date))
        if cursor.fetchone():
            conn.close()
            return jsonify({
                'error':
                'A report for this task already exists for this date.'
            }), 409

        cursor.execute(
            '''
            INSERT INTO daily_task_reports 
            (user_id, task_id, project_id, report_date, work_description, result_of_effort, remarks, communication_email, communication_phone, time_spent, status, blocker, task_assigned_by_id, approval_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        ''', (user_id, task_id, real_project_id, report_date, work_description,
              result_of_effort, remarks, communication_email,
              communication_phone, time_spent, status,
              blocker, data.get('task_assigned_by_id')))

        report_id = cursor.fetchone()['id']
        conn.commit()

        log_activity(user_id,
                     'daily_report_created',
                     f'Submitted daily report for task {task_id}',
                     real_project_id,
                     task_id=task_id)
        try:
            conn2 = get_db_connection()
            cur2 = conn2.cursor()
            cur2.execute(
                'INSERT INTO audit_logs (actor_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)',
                (user_id, 'create_report', 'daily_report', report_id,
                 json.dumps({
                     'task_id': task_id,
                     'project_id': real_project_id
                 })))
            conn2.commit()
        except Exception:
            pass
        finally:
            try:
                conn2.close()
            except Exception:
                pass

        conn.close()
        return jsonify({'success': True, 'id': report_id}), 201

    except Exception as e:
        logger.exception('create_daily_report failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/<int:report_id>', methods=['PUT'])
@admin_required
def edit_daily_report(report_id):
    """Edit a report (admin/superadmin)."""
    try:
        data = request.get_json() or {}
        user_type = getattr(g, 'current_user_type', session.get('user_type'))
        is_admin = session.get('admin') or user_type == 'admin'

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM daily_task_reports WHERE id = %s',
                       (report_id, ))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Report not found'}), 404

        if row['approval_status'] == 'approved' and not is_admin:
            conn.close()
            return jsonify({'error': 'Approved reports are locked'}), 403

        updates = []
        params = []
        if 'work_description' in data:
            updates.append('work_description = %s')
            params.append(data['work_description'])
        if 'time_spent' in data:
            try:
                ts = float(data['time_spent'])
            except Exception:
                conn.close()
                return jsonify({'error': 'time_spent must be a number'}), 400
            if ts < 0 or ts > 24:
                conn.close()
                return jsonify(
                    {'error': 'time_spent must be between 0 and 24'}), 400
            updates.append('time_spent = %s')
            params.append(ts)
        if 'status' in data:
            if data['status'] not in ('In Progress', 'Completed', 'Blocked'):
                conn.close()
                return jsonify({'error': 'Invalid status'}), 400
            updates.append('status = %s')
            params.append(data['status'])

        if not updates:
            conn.close()
            return jsonify({'error': 'Nothing to update'}), 400

        params.append(report_id)
        sql = 'UPDATE daily_task_reports SET ' + ', '.join(
            updates) + ', updated_at = CURRENT_TIMESTAMP WHERE id = %s'
        cursor.execute(sql, params)
        conn.commit()
        log_activity(get_current_user_id(), 'daily_report_edited',
                     f'Edited report {report_id}', row['project_id'])
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('edit_daily_report failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/<int:report_id>/action', methods=['POST'])
@login_required
def action_daily_report(report_id):
    """Approve or reject a report. Admins only."""
    try:
        data = request.get_json() or {}
        action = data.get('action')
        comment = data.get('comment', '')
        user_id = get_current_user_id()
        user_type = getattr(g, 'current_user_type', session.get('user_type'))
        is_admin = session.get('admin') or user_type == 'admin'

        if action not in ('approve', 'reject'):
            return jsonify({'error': 'Invalid action'}), 400

        if not is_admin:
            return jsonify({'error': 'Admin access required'}), 403

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM daily_task_reports WHERE id = %s',
                       (report_id, ))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Report not found'}), 404

        new_status = 'approved' if action == 'approve' else 'rejected'
        cursor.execute(
            'UPDATE daily_task_reports SET approval_status = %s, reviewed_by = %s, review_comment = %s, updated_at = CURRENT_TIMESTAMP, is_locked = CASE WHEN %s = \'approved\' THEN 1 ELSE is_locked END WHERE id = %s',
            (new_status, user_id, comment, new_status, report_id))
        conn.commit()
        log_activity(user_id, 'daily_report_reviewed',
                     f'{new_status} report {report_id}', row['project_id'])
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('action_daily_report failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/<int:report_id>', methods=['DELETE'])
@admin_required
def delete_daily_report(report_id):
    """Delete report (super admin only)."""
    try:
        user_type = getattr(g, 'current_user_type', session.get('user_type'))
        if not (session.get('admin') or user_type == 'admin'):
            return jsonify({'error':
                            'Only admin can delete reports'}), 403
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT project_id FROM daily_task_reports WHERE id = %s',
            (report_id, ))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Report not found'}), 404
        cursor.execute('DELETE FROM report_comments WHERE report_id = %s',
                       (report_id, ))
        cursor.execute('DELETE FROM daily_task_reports WHERE id = %s',
                       (report_id, ))
        conn.commit()
        log_activity(get_current_user_id(), 'daily_report_deleted',
                     f'deleted report {report_id}', row['project_id'])
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('delete_daily_report failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/<int:report_id>/comments', methods=['POST'])
@login_required
def add_report_comment(report_id):
    try:
        data = request.get_json() or {}
        comment = data.get('comment')
        internal = bool(data.get('internal', False))
        if not comment:
            return jsonify({'error': 'comment is required'}), 400
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM daily_task_reports WHERE id = %s',
                       (report_id, ))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Report not found'}), 404
        cursor.execute(
            'INSERT INTO report_comments (report_id, commenter_id, comment, internal, created_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)',
            (report_id, user_id, comment, 1 if internal else 0))
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 201
    except Exception as e:
        logger.exception('add_report_comment failed')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-reports/export', methods=['GET'])
@admin_required
def export_daily_reports():
    """Export filtered reports to CSV (admin/superadmin)."""
    try:
        import csv
        from io import StringIO

        params = []
        where = ['1=1']
        start = request.args.get('start_date')
        end = request.args.get('end_date')
        employee = request.args.get('employee_id')
        project = request.args.get('project_id')
        task = request.args.get('task_id')

        if start:
            where.append('report_date >= %s')
            params.append(start)
        if end:
            where.append('report_date <= %s')
            params.append(end)
        if employee:
            where.append('d.user_id = %s')
            params.append(employee)
        if project:
            where.append('d.project_id = %s')
            params.append(project)
        if task:
            where.append('d.task_id = %s')
            params.append(task)

        where_sql = ' AND '.join(where)
        conn = get_db_connection()
        cursor = conn.cursor()
        query = f"SELECT d.*, u.username as employee_name, p.title as project_title, t.title as task_title FROM daily_task_reports d LEFT JOIN users u ON d.user_id = u.id LEFT JOIN projects p ON d.project_id = p.id LEFT JOIN tasks t ON d.task_id = t.id WHERE {where_sql} ORDER BY d.report_date DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()

        si = StringIO()
        cw = csv.writer(si)
        cw.writerow([
            'id', 'report_date', 'employee', 'project', 'task',
            'work_description', 'time_spent', 'status', 'approval_status',
            'reviewed_by', 'review_comment', 'created_at'
        ])
        for r in rows:
            cw.writerow([
                r['id'], r['report_date'], r['employee_name'],
                r['project_title'], r['task_title'], r['work_description'],
                r['time_spent'], r['status'], r['approval_status'],
                r['reviewed_by'], r['review_comment'], r['created_at']
            ])
        output = si.getvalue()
        conn.close()
        return app.response_class(output,
                                  mimetype='text/csv',
                                  headers={
                                      "Content-Disposition":
                                      "attachment;filename=daily_reports.csv"
                                  })
    except Exception as e:
        logger.exception('export_daily_reports failed')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/dashboard/completed-outcomes", methods=["GET"])
@admin_required
def get_completed_outcomes():
    """Get all completed projects (outcomes)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT p.id, p.title, p.description, p.status, p.progress, 
                   p.deadline, p.created_by_id, u.username as creator_name,
                   p.created_at, p.completed_at,
                   COUNT(DISTINCT t.id) as total_tasks,
                   COUNT(DISTINCT CASE WHEN t.status = 'Completed' THEN t.id END) as completed_tasks,
                   COUNT(DISTINCT m.id) as total_milestones,
                   COUNT(DISTINCT CASE WHEN m.status = 'Completed' THEN m.id END) as completed_milestones
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            LEFT JOIN tasks t ON p.id = t.project_id
            LEFT JOIN milestones m ON p.id = m.project_id
            WHERE p.status = 'Completed'
            GROUP BY p.id, u.username
            ORDER BY p.completed_at DESC
        ''')

        completed_projects = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in completed_projects]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/dashboard/recent-actions", methods=["GET"])
@admin_required
def get_recent_actions():
    """Get recent actions from all employees"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT a.id, a.activity_type, a.description, a.created_at,
                   u.username, u.email, u.user_type_id, ut.user_role,
                   p.title as project_title, t.title as task_title,
                   m.title as milestone_title,
                   CASE 
                     WHEN a.activity_type = 'project_created' THEN 'fas fa-folder-plus'
                     WHEN a.activity_type = 'task_created' THEN 'fas fa-tasks'
                     WHEN a.activity_type = 'task_completed' THEN 'fas fa-check-circle'
                     WHEN a.activity_type = 'milestone_created' THEN 'fas fa-flag'
                     WHEN a.activity_type = 'milestone_completed' THEN 'fas fa-flag-checkered'
                     WHEN a.activity_type = 'document_uploaded' THEN 'fas fa-file-upload'
                     WHEN a.activity_type = 'document_deleted' THEN 'fas fa-file-times'
                     ELSE 'fas fa-history'
                   END as icon_class
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            LEFT JOIN projects p ON a.project_id = p.id
            LEFT JOIN tasks t ON a.task_id = t.id
            LEFT JOIN milestones m ON a.milestone_id = m.id
            ORDER BY a.created_at DESC
            LIMIT 50
        ''')

        activities = cursor.fetchall()
        conn.close()

        result = []
        for row in activities:
            result.append(dict(row))

        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] /api/admin/dashboard/recent-actions failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/dashboard/activities", methods=["GET"])
@admin_required
def get_admin_activities():
    """Get all activities for admin dashboard"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT a.id, a.activity_type, a.description, a.created_at,
                   u.username, u.email, p.title as project_title,
                   t.title as task_title, m.title as milestone_title
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.id
            LEFT JOIN projects p ON a.project_id = p.id
            LEFT JOIN tasks t ON a.task_id = t.id
            LEFT JOIN milestones m ON a.milestone_id = m.id
            ORDER BY a.created_at DESC
            LIMIT 100
        ''')

        activities = cursor.fetchall()
        conn.close()

        result = []
        for row in activities:
            result.append(dict(row))

        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] /api/admin/dashboard/activities failed: {str(e)}")
        return jsonify({"error": str(e)}), 500







@app.route("/api/projects/<int:project_id>/calculate-progress",
           methods=["GET"])
@login_required
def calculate_project_progress(project_id):
    """
    Calculate project progress based on: 
    - 70% weight:  Task completion rate
    - 30% weight: Milestone completion rate
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get task progress data
        cursor.execute(
            '''
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                COALESCE(SUM(weightage), 0) as total_weightage,
                COALESCE(SUM(CASE WHEN status = 'Completed' THEN weightage ELSE 0 END), 0) as completed_weightage
            FROM tasks 
            WHERE project_id = %s
        ''', (project_id, ))
        task_data = cursor.fetchone()

        # Get milestone progress data
        cursor.execute(
            '''
            SELECT 
                COUNT(*) as total_milestones,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_milestones,
                COALESCE(SUM(weightage), 0) as total_m_weightage,
                COALESCE(SUM(CASE WHEN status = 'Completed' THEN weightage ELSE 0 END), 0) as completed_m_weightage
            FROM milestones 
            WHERE project_id = %s
        ''', (project_id, ))
        milestone_data = cursor.fetchone()

        # Calculate weighted progress
        task_progress = 0
        if task_data['total_weightage'] and task_data['total_weightage'] > 0:
            task_progress = (task_data['completed_weightage'] /
                             task_data['total_weightage']) * 100

        milestone_progress = 0
        if milestone_data['total_m_weightage'] and milestone_data[
                'total_m_weightage'] > 0:
            milestone_progress = (milestone_data['completed_m_weightage'] /
                                  milestone_data['total_m_weightage']) * 100

        # Overall progress:  70% tasks + 30% milestones
        overall_progress = int((task_progress * 0.7) +
                               (milestone_progress * 0.3))

        # Update project progress in database
        cursor.execute(
            '''
            UPDATE projects 
            SET progress = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        ''', (overall_progress, project_id))

        # Record progress history
        cursor.execute(
            '''
            INSERT INTO progress_history (
                project_id, progress_percentage, 
                tasks_completed, total_tasks,
                milestones_completed, total_milestones
            ) VALUES (%s, %s, %s, %s, %s, %s)
        ''', (project_id, overall_progress, task_data['completed_tasks']
              or 0, task_data['total_tasks']
              or 0, milestone_data['completed_milestones']
              or 0, milestone_data['total_milestones'] or 0))

        conn.commit()

        return jsonify({
            "project_id":
            project_id,
            "progress":
            overall_progress,
            "task_progress":
            round(task_progress, 2),
            "milestone_progress":
            round(milestone_progress, 2),
            "tasks_completed":
            task_data['completed_tasks'] or 0,
            "total_tasks":
            task_data['total_tasks'] or 0,
            "milestones_completed":
            milestone_data['completed_milestones'] or 0,
            "total_milestones":
            milestone_data['total_milestones'] or 0,
            "message":
            "Progress calculated successfully"
        }), 200

    except Exception as e:
        print(f"[ERROR] calculate_project_progress failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/projects/<int:project_id>/progress-history", methods=["GET"])
@login_required
def get_project_progress_history(project_id):
    """
    Retrieve historical progress data for charts/graphs
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT 
                progress_percentage,
                tasks_completed,
                total_tasks,
                milestones_completed,
                total_milestones,
                recorded_at
            FROM progress_history 
            WHERE project_id = %s
            ORDER BY recorded_at DESC
            LIMIT 30
        ''', (project_id, ))

        history = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in history]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/users/<int:user_id>/permissions", methods=["GET"])
@admin_required
def get_user_permissions(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT module, action, granted FROM user_permissions 
            WHERE user_id = %s ORDER BY module, action
        ''', (user_id, ))
        permissions = cursor.fetchall()
        conn.close()

        result = {}
        for perm in permissions:
            module = perm['module']
            if module not in result:
                result[module] = {}
            result[module][perm['action']] = bool(perm['granted'])

        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/users/<int:user_id>/permissions", methods=["POST"])
@admin_required
def set_user_permissions(user_id):
    try:
        data = request.get_json()
        module = data.get("module")
        action = data.get("action")
        granted = data.get("granted")

        if not module or not action:
            return jsonify({'error': 'Module and action are required'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if permission exists
        cursor.execute(
            '''
            SELECT id FROM user_permissions 
            WHERE user_id = %s AND module = %s AND action = %s
        ''', (user_id, module, action))

        if cursor.fetchone():
            cursor.execute(
                '''
                UPDATE user_permissions 
                SET granted = %s 
                WHERE user_id = %s AND module = %s AND action = %s
            ''', (granted, user_id, module, action))
        else:
            cursor.execute(
                '''
                INSERT INTO user_permissions (user_id, module, action, granted)
                VALUES (%s, %s, %s, %s)
            ''', (user_id, module, action, granted))

        conn.commit()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('set_user_permissions failed')
        return jsonify({'error': str(e)}), 500


@app.route("/api/users", methods=["GET"])
@login_required
def get_users():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role, u.created_at
            FROM users u 
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE COALESCE(u.is_system, 0) != 1
            ORDER BY u.created_at DESC
        ''')
        users = cursor.fetchall()
        conn.close()

        result = []
        for row in users:
            created_at = row['created_at']
            if created_at and hasattr(created_at, 'isoformat'):
                created_at_str = created_at.isoformat()
            else:
                created_at_str = str(created_at) if created_at else None

            result.append({
                "id": row['id'],
                "username": row['username'],
                "email": row['email'],
                "user_type_id": row['user_type_id'],
                "user_role": row['user_role'],
                "created_at": created_at_str
            })

        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] /api/users GET failed: {str(e)}")
        return jsonify({"error": str(e)}), 500



@app.route("/api/employees", methods=["GET"])
@login_required
def get_employees():
    """Get all employees (users with role 'employee')"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role, u.created_at, u.department
            FROM users u 
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE LOWER(ut.user_role) = 'employee'
            ORDER BY u.username ASC
        ''')
        users = cursor.fetchall()
        conn.close()

        result = []
        for row in users:
            created_at = row['created_at']
            if created_at and hasattr(created_at, 'isoformat'):
                created_at_str = created_at.isoformat()
            else:
                created_at_str = str(created_at) if created_at else None

            result.append({
                "id": row['id'],
                "username": row['username'],
                "email": row['email'],
                "user_type_id": row['user_type_id'],
                "user_role": row['user_role'],
                "department": row['department'],
                "created_at": created_at_str
            })

        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] /api/employees GET failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/users", methods=["POST"])
@csrf.exempt
@admin_required
def create_user():
    conn = None
    try:
        logger.info("[CREATE_USER] Starting user creation process")
        current_user_id = get_current_user_id()  # 🔥 hierarchy support
        logger.info(f"[CREATE_USER] Current user ID: {current_user_id}")

        # Get JSON data with error handling
        try:
            data = request.get_json()
            if not data:
                logger.error("[CREATE_USER] No JSON data received")
                return jsonify({"error": "No data provided"}), 400
        except Exception as json_error:
            logger.error(f"[CREATE_USER] JSON parsing error: {str(json_error)}")
            return jsonify({"error": f"Invalid JSON data: {str(json_error)}"}), 400

        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""
        user_type_id = data.get("user_type_id")
        permissions_data = data.get("permissions")

        logger.info(f"[CREATE_USER] Received data - username: {username}, email: {email}, user_type_id: {user_type_id}")

        # Parse permissions safely
        if isinstance(permissions_data, str):
            try:
                permissions = json.loads(permissions_data)
            except json.JSONDecodeError:
                permissions = {}
        else:
            permissions = permissions_data or {}

        # ================= VALIDATIONS =================

        if not all([username, email, password, confirm_password, user_type_id]):
            logger.warning("[CREATE_USER] Missing required fields")
            return jsonify({"error": "All mandatory fields are required."}), 400

        if len(username) < 3:
            logger.warning(f"[CREATE_USER] Username too short: {username}")
            return jsonify({"error": "Username must be at least 3 characters."}), 400

        if username.lower() == 'super admin':
            logger.warning(f"[CREATE_USER] Reserved username attempted: {username}")
            return jsonify({"error": "Username reserved."}), 400

        if "@" not in email or "." not in email.split("@")[-1]:
            logger.warning(f"[CREATE_USER] Invalid email format: {email}")
            return jsonify({"error": "Invalid email format."}), 400

        try:
            is_valid, validation_message = validate_password_complexity(password)
            if not is_valid:
                logger.warning(f"[CREATE_USER] Password validation failed: {validation_message}")
                return jsonify({"error": validation_message}), 400
        except Exception as pwd_error:
            logger.error(f"[CREATE_USER] Password validation error: {str(pwd_error)}")
            return jsonify({"error": "Password validation failed"}), 400

        if password != confirm_password:
            logger.warning("[CREATE_USER] Passwords do not match")
            return jsonify({"error": "Passwords do not match."}), 400

        # ================= DATABASE =================

        try:
            conn = get_db_connection()
            if not conn:
                logger.error("[CREATE_USER] Failed to get database connection")
                return jsonify({"error": "Database connection failed"}), 500
            cursor = conn.cursor()
            logger.info("[CREATE_USER] Database connection established")
        except Exception as db_error:
            logger.error(f"[CREATE_USER] Database connection error: {str(db_error)}")
            return jsonify({"error": f"Database connection error: {str(db_error)}"}), 500

        # Check user type exists
        try:
            cursor.execute('SELECT id FROM usertypes WHERE id = %s', (user_type_id,))
            if not cursor.fetchone():
                logger.warning(f"[CREATE_USER] Invalid user type ID: {user_type_id}")
                conn.close()
                return jsonify({"error": "Invalid user type selected."}), 400
            logger.info(f"[CREATE_USER] User type validated: {user_type_id}")
        except Exception as ut_error:
            logger.error(f"[CREATE_USER] User type check error: {str(ut_error)}")
            if conn:
                conn.close()
            return jsonify({"error": f"User type validation error: {str(ut_error)}"}), 500

        # Check for existing username/email explicitly for better error messages
        try:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": f"Username '{username}' is already taken."}), 409
            
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": f"Email '{email}' is already registered."}), 409
        except Exception as check_error:
            logger.error(f"[CREATE_USER] Check error: {str(check_error)}")
            if conn:
                conn.close()
            return jsonify({"error": f"Database check error: {str(check_error)}"}), 500

        try:
            # 🔥 Hash password correctly
            logger.info("[CREATE_USER] Hashing password")
            hashed_password = generate_password_hash(
                password,
                method='pbkdf2:sha256'
            )

            # 🔥 Handle created_by_id - it can be None
            # Log the value for debugging
            logger.info(f"[CREATE_USER] created_by_id value: {current_user_id} (type: {type(current_user_id)})")
            
            # If current_user_id is None or 0, we'll insert NULL
            created_by_value = current_user_id if current_user_id else None

            # 🔥 Insert user with hierarchy support
            logger.info(f"[CREATE_USER] Inserting user into database with created_by_id: {created_by_value}")
            cursor.execute("""
                INSERT INTO users 
                (username, email, password, user_type_id, created_by_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (username, email, hashed_password, user_type_id, created_by_value))

            result = cursor.fetchone()
            if not result:
                logger.error("[CREATE_USER] Failed to get user ID after insert")
                conn.rollback()
                conn.close()
                return jsonify({"error": "Failed to create user"}), 500

            # Handle both tuple and dict-like cursor results
            if isinstance(result, dict):
                user_id = result.get('id')
            else:
                user_id = result[0]
                
            if not user_id:
                logger.error("[CREATE_USER] Failed to extract user ID from result")
                conn.rollback()
                conn.close()
                return jsonify({"error": "Failed to create user"}), 500
                
            logger.info(f"[CREATE_USER] User created with ID: {user_id}")

            # ================= PERMISSIONS INSERT =================
            logger.info(f"[CREATE_USER] Inserting permissions: {permissions}")
            for module, actions in permissions.items():
                if isinstance(actions, dict):
                    for action, granted in actions.items():
                        try:
                            cursor.execute("""
                                INSERT INTO user_permissions 
                                (user_id, module, action, granted)
                                VALUES (%s, %s, %s, %s)
                            """, (user_id, module, action, bool(granted)))
                            logger.debug(f"[CREATE_USER] Permission added: {module}.{action} = {granted}")
                        except psycopg2.IntegrityError as perm_error:
                            logger.warning(f"[CREATE_USER] Permission insert failed (duplicate?): {str(perm_error)}")
                            conn.rollback()
                            continue

            conn.commit()
            logger.info(f"[CREATE_USER] User creation committed successfully")
            conn.close()

            return jsonify({
                "id": user_id,
                "username": username,
                "email": email,
                "user_type_id": user_type_id,
                "permissions": permissions,
                "created_at": datetime.now().isoformat(),
                "message": "User created successfully!"
            }), 201

        except psycopg2.IntegrityError as e:
            logger.error(f"[CREATE_USER] Integrity error: {str(e)}")
            logger.error(f"[CREATE_USER] Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            logger.error(f"[CREATE_USER] Error details: {e.pgerror if hasattr(e, 'pgerror') else 'N/A'}")
            if conn:
                conn.rollback()
                conn.close()
            return jsonify({"error": "Username or email already exists."}), 409
        except psycopg2.DatabaseError as db_err:
            logger.error(f"[CREATE_USER] Database error: {str(db_err)}")
            logger.error(f"[CREATE_USER] Error type: {type(db_err).__name__}")
            logger.error(f"[CREATE_USER] Error code: {db_err.pgcode if hasattr(db_err, 'pgcode') else 'N/A'}")
            logger.error(f"[CREATE_USER] Error details: {db_err.pgerror if hasattr(db_err, 'pgerror') else 'N/A'}")
            logger.error(f"[CREATE_USER] Traceback: {traceback.format_exc()}")
            if conn:
                conn.rollback()
                conn.close()
            # Provide more detailed error message
            error_msg = f"Database error: {type(db_err).__name__}"
            if hasattr(db_err, 'pgerror') and db_err.pgerror:
                error_msg += f" - {db_err.pgerror}"
            elif str(db_err):
                error_msg += f" - {str(db_err)}"
            return jsonify({"error": error_msg}), 500
        except Exception as insert_error:
            logger.error(f"[CREATE_USER] Insert error: {str(insert_error)}")
            logger.error(f"[CREATE_USER] Error type: {type(insert_error).__name__}")
            logger.error(f"[CREATE_USER] Traceback: {traceback.format_exc()}")
            if conn:
                conn.rollback()
                conn.close()
            # Provide detailed error message
            error_msg = f"{type(insert_error).__name__}: {str(insert_error)}" if str(insert_error) else type(insert_error).__name__
            return jsonify({"error": f"Database error: {error_msg}"}), 500

    except Exception as e:
        logger.error(f"[CREATE_USER] Unexpected error: {str(e)}")
        logger.error(f"[CREATE_USER] Traceback: {traceback.format_exc()}")
        if conn:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/api/users/<int:id>", methods=["GET"])
@csrf.exempt
@admin_required
def get_user(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get user basic info
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role, u.created_at, u.status
            FROM users u 
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (id, ))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({"error": "User not found."}), 404

        # 1. Get Direct User Permissions
        cursor.execute('''
            SELECT module, action, granted FROM user_permissions 
            WHERE user_id = %s ORDER BY module, action
        ''', (id, ))
        direct_perms = cursor.fetchall()

        # 2. Get Role-based (UserType) Permissions
        cursor.execute('''
            SELECT module, action, granted FROM usertype_permissions 
            WHERE usertype_id = %s ORDER BY module, action
        ''', (user['user_type_id'], ))
        role_perms = cursor.fetchall()
        
        conn.close()

        # Merge permissions (Direct takes precedence if same module-action)
        permissions = {}
        
        # Add role permissions first
        for perm in role_perms:
            module = perm['module']
            if module not in permissions:
                permissions[module] = {}
            permissions[module][perm['action']] = bool(perm['granted'])
            
        # Add direct permissions (overwriting if necessary)
        for perm in direct_perms:
            module = perm['module']
            if module not in permissions:
                permissions[module] = {}
            permissions[module][perm['action']] = bool(perm['granted'])

        user_dict = dict(user)
        user_dict['permissions'] = permissions
        
        # Safe Date Serialization
        if user_dict.get('created_at'):
            created_at = user_dict['created_at']
            if hasattr(created_at, 'isoformat'):
                user_dict['created_at'] = created_at.isoformat()
            else:
                user_dict['created_at'] = str(created_at)

        return jsonify(user_dict), 200
    except Exception as e:
        logger.exception(f"Error fetching user {id}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/users/<int:id>", methods=["PUT"])
@csrf.exempt
@admin_required
def update_user(id):
    try:
        data = request.get_json() or {}
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password")
        user_type_id = data.get("user_type_id")
        permissions_data = data.get("permissions")

        if isinstance(permissions_data, str):
            try:
                permissions = json.loads(permissions_data)
            except json.JSONDecodeError:
                permissions = {}
        else:
            permissions = permissions_data or {}

        if not username or not email or not user_type_id:
            logger.warning(f"Update User: Missing fields. username={username}, email={email}, user_type_id={user_type_id}")
            return jsonify(
                {"error": "Username, email, and user type are required."}), 400

        try:
            user_type_id = int(user_type_id)
        except (ValueError, TypeError):
             logger.warning(f"Update User: Invalid user_type_id: {user_type_id}")
             return jsonify({"error": "Invalid user type ID"}), 400

        logger.info(f"Updating user {id}: username={username}, email={email}, type={user_type_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT id FROM users WHERE id = %s', (id, ))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "User not found."}), 404

        try:
            if password:
                is_valid, validation_message = validate_password_complexity(
                    password)
                if not is_valid:
                    conn.close()
                    return jsonify({"error": validation_message}), 400
                hashed_password = generate_password_hash(
                    password, method='pbkdf2:sha256')
                cursor.execute(
                    '''
                    UPDATE users SET username = %s, email = %s, password = %s, user_type_id = %s
                    WHERE id = %s
                ''', (username, email, hashed_password, user_type_id, id))
            else:
                cursor.execute(
                    '''
                    UPDATE users SET username = %s, email = %s, user_type_id = %s
                    WHERE id = %s
                ''', (username, email, user_type_id, id))

            cursor.execute('DELETE FROM user_permissions WHERE user_id = %s',
                           (id, ))

            for module, actions in permissions.items():
                if isinstance(actions, dict):
                    for action, granted in actions.items():
                        try:
                            cursor.execute(
                                '''
                                INSERT INTO user_permissions (user_id, module, action, granted)
                                VALUES (%s,%s,%s,%s)
                            ''', (id, module, action, bool(granted)))
                        except psycopg2.IntegrityError as e:
                            print(f"[DEBUG] Permission insert conflict: {e}")
                            pass

            conn.commit()
            conn.close()

            return jsonify({
                "id": id,
                "username": username,
                "email": email,
                "user_type_id": user_type_id,
                "permissions": permissions,
                "message": "User updated successfully!"
            }), 200

        except psycopg2.IntegrityError as e:
            print(f"[ERROR] User update conflict: {e}")
            conn.close()
            return jsonify({"error": "Username or email already exists."}), 409

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/users/<int:id>", methods=["DELETE"])
@csrf.exempt
@admin_required
def delete_user(id):
    try:
        current_admin_id = get_current_user_id()
        if id == current_admin_id:
            return jsonify({"error": "You cannot delete your own account while logged in."}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT id FROM users WHERE id = %s', (id, ))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "User not found."}), 404

        # 1. Reassign ownership for NOT NULL columns
        # Tasks created by user -> assign to admin
        cursor.execute('UPDATE tasks SET created_by_id = %s WHERE created_by_id = %s', (current_admin_id, id))
        # Projects created by user -> assign to admin
        cursor.execute('UPDATE projects SET created_by_id = %s WHERE created_by_id = %s', (current_admin_id, id))
        # Milestones created by user -> assign to admin
        cursor.execute('UPDATE milestones SET created_by_id = %s WHERE created_by_id = %s', (current_admin_id, id))
        # Documents uploaded by user -> assign to admin
        cursor.execute('UPDATE documents SET uploaded_by_id = %s WHERE uploaded_by_id = %s', (current_admin_id, id))

        # 2. Nullify nullable references
        cursor.execute('UPDATE tasks SET assigned_to_id = NULL WHERE assigned_to_id = %s', (id,))
        cursor.execute('UPDATE daily_task_reports SET task_assigned_by_id = NULL WHERE task_assigned_by_id = %s', (id,))
        cursor.execute('UPDATE daily_task_reports SET reviewed_by = NULL WHERE reviewed_by = %s', (id,))

        # 3. Delete dependent records that should be removed
        cursor.execute('DELETE FROM project_assignments WHERE user_id = %s', (id,))
        cursor.execute('DELETE FROM user_permissions WHERE user_id = %s', (id,))
        cursor.execute('DELETE FROM user_skills WHERE user_id = %s', (id,))
        cursor.execute('DELETE FROM activities WHERE user_id = %s', (id,))
        cursor.execute('DELETE FROM comments WHERE author_id = %s', (id,))
        cursor.execute('DELETE FROM report_comments WHERE commenter_id = %s', (id,))
        cursor.execute('DELETE FROM daily_task_reports WHERE user_id = %s', (id,))

        # 4. Finally delete the user
        cursor.execute('DELETE FROM users WHERE id = %s', (id, ))
        
        conn.commit()
        conn.close()

        logger.info(f"User {id} deleted by Admin {current_admin_id}")
        return jsonify({"message": "User deleted successfully!"}), 200

    except Exception as e:
        logger.error(f"Error deleting user {id}: {str(e)}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 500




@app.route("/api/user/login", methods=["POST"])
@csrf.exempt
def user_login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT u.id, u.username, u.email, u.password, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.email = %s
        ''', (email, ))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({"error": "Invalid email or password."}), 401

        if not check_password_hash(user['password'], password):
            conn.close()
            return jsonify({"error": "Invalid email or password."}), 401

        cursor.execute(
            '''
            SELECT module, action, granted FROM user_permissions
            WHERE user_id = %s ORDER BY module, action
        ''', (user['id'], ))
        permissions_rows = cursor.fetchall()
        conn.close()

        permissions = {}
        for perm in permissions_rows:
            module = perm['module']
            if module not in permissions:
                permissions[module] = {}
            permissions[module][perm['action']] = bool(perm['granted'])

        # Store authentication info in session
        session.clear()
        session.permanent = True
        session['user_id'] = user['id']
        session['user_type'] = 'employee'
        session['username'] = user['username']
        session['permissions'] = permissions
        session['is_authenticated'] = True

        # Generate signed token
        csrf_for_token = secrets.token_urlsafe(16)
        s = URLSafeTimedSerializer(app.secret_key)
        auth_token = s.dumps({
            'user_id': user['id'],
            'username': user['username'],
            'user_type': 'employee',
            'csrf_token': csrf_for_token,
            'created_at': str(datetime.now(timezone.utc))
        })
        
        # Store token in session (optional, but good for tracking)
        session['auth_token'] = auth_token
        
        # Keep valid_tokens for any legacy parts that might check it check it (though ideally deprecated)
        # We don't need valid_tokens anymore for auth, so skipping its update.

        return jsonify({
            "user_id": user['id'],
            "username": user['username'],
            "email": user['email'],
            "user_role": user['user_role'],
            "permissions": permissions,
            "token": auth_token,
            "csrf_token": csrf_for_token,
            "message": "Login successful!"
        }), 200

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/user/logout", methods=["POST"])
@csrf.exempt
def user_logout():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        if token in valid_tokens:
            del valid_tokens[token]
    # Clear session data
    session.clear()
    return jsonify({"message": "Logout successful!"}), 200


@app.route("/api/employee/projects", methods=["GET"])
@csrf.exempt
def get_employee_projects():
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT DISTINCT p.id, p.title, p.description, p.status, p.progress, 
                   p.deadline, p.created_by_id, u.username as creator_name, p.created_at
            FROM projects p 
            LEFT JOIN users u ON p.created_by_id = u.id
            JOIN project_assignments pa ON p.id = pa.project_id
            WHERE pa.user_id = %s
            ORDER BY p.created_at DESC
        ''', (user_id,))

        projects = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in projects]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/employee/projects", methods=["POST"])
@csrf.exempt
def create_employee_project():
    """
    Create a new project.
    Ensures created_by_id references an existing users.id.
    If session user_id == 0 (super-admin placeholder), attempt to map to a real admin user or create a minimal system user.
    """
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        description = data.get("description") or ""
        deadline = data.get("deadline") or None
        reporting_time = data.get("reporting_time") or "09:00"
        team_members = data.get("team_members") or []

        if not title:
            return jsonify({"error": "title is required"}), 400
        
        # Validate that at least one team member is assigned
        if not team_members or len(team_members) == 0:
            return jsonify({
                "error": "At least one team member must be assigned to the project. Please select team members before creating the project."
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # Resolve a valid created_by_id (don't use 0 as that doesn't exist in users)
        created_by_id = get_current_user_id()
        if created_by_id == 0 or created_by_id is None:
            # Try to find an Administrator user
            cur.execute("""
                SELECT u.id FROM users u
                JOIN usertypes ut ON u.user_type_id = ut.id
                WHERE lower(ut.user_role) LIKE '%admin%'
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                created_by_id = row["id"]
            else:
                # Try any existing user
                cur.execute("SELECT id FROM users LIMIT 1")
                row2 = cur.fetchone()
                if row2:
                    created_by_id = row2["id"]
                else:
                    # No users exist — create a minimal system Administrator user
                    cur.execute("SELECT id FROM usertypes WHERE lower(user_role) LIKE %s LIMIT 1", ('%admin%',))
                    ut = cur.fetchone()
                    if ut:
                        usertype_id = ut["id"]
                    else:
                        cur.execute("INSERT INTO usertypes (user_role) VALUES (%s) RETURNING id", ("Administrator",))
                        usertype_id = cur.fetchone()['id']

                    # create a minimal system user (password hash not important for system account)
                    dummy_password = generate_password_hash(secrets.token_hex(8))
                    cur.execute("""
                        INSERT INTO users (username, email, password, user_type_id, granted, created_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        RETURNING id
                    """, ("system", "system@example.com", dummy_password, usertype_id, 1))
                    created_by_id = cur.fetchone()['id']
                    conn.commit()

        # Insert project
        try:
            cur.execute("""
                INSERT INTO projects (title, description, deadline, reporting_time, created_by_id, status, progress, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """, (title, description, deadline, reporting_time, created_by_id, 'In Progress', 0))
            project_id = cur.fetchone()['id']

            # Assign team members if provided (silently ignore duplicates)
            for uid in (team_members or []):
                try:
                    uid_int = int(uid)
                except Exception:
                    continue
                try:
                    cur.execute("""
                        INSERT INTO project_assignments (user_id, project_id) 
                        VALUES (%s, %s)
                        ON CONFLICT (user_id, project_id) DO NOTHING
                    """, (uid_int, project_id))
                except Exception:
                    # continue on per-user errors
                    continue

            conn.commit()
        except psycopg2.IntegrityError as ie:
            conn.rollback()
            logger.exception("create_employee_project failed (IntegrityError)")
            return jsonify({"error": "Database integrity error when creating project: " + str(ie)}), 500
        except psycopg2.OperationalError as oe:
            conn.rollback()
            logger.exception("create_employee_project failed (OperationalError)")
            return jsonify({"error": "Database operational error. Please try again: " + str(oe)}), 500
        except Exception as e:
            conn.rollback()
            logger.exception("create_employee_project failed")
            return jsonify({"error": "An unexpected error occurred: " + str(e)}), 500

        # Log activity if you have log_activity helper
        try:
            log_activity(created_by_id, 'project_created', f'Project {title} created', project_id)
        except Exception:
            pass

        conn.close()
        return jsonify({"success": True, "id": project_id}), 201

    except Exception as e:
        logger.exception("create_employee_project failed")
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/tasks", methods=["GET"])
@csrf.exempt
def get_employee_tasks():
    conn = None
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        project_id = request.args.get("project_id")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                t.id,
                t.title,
                COALESCE(t.description,'') AS description,
                COALESCE(t.status,'Pending') AS status,
                COALESCE(t.priority,'Medium') AS priority,
                t.deadline,
                t.project_id,
                COALESCE(p.title,'No Project') AS project_name,
                t.assigned_to_id,
                COALESCE(u.username,'Unassigned') AS assigned_to_name,
                t.created_at,
                COALESCE(t.approval_status,'Pending') AS approval_status,
                COALESCE(t.progress,0) AS progress,
                COALESCE(t.notes,'') AS notes
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
        """

        params = []

        if project_id:
            query += """
                WHERE t.project_id = %s
                AND (t.assigned_to_id = %s OR t.created_by_id = %s)
                ORDER BY t.created_at DESC
            """
            params = [project_id, user_id, user_id]
        else:
            query += """
                WHERE t.assigned_to_id = %s
                OR t.created_by_id = %s
                ORDER BY t.created_at DESC
            """
            params = [user_id, user_id]

        cursor.execute(query, params)
        tasks = cursor.fetchall()

        # classify tasks
        today = date.today()

        pending = []
        completed = []
        overdue = []

        for t in tasks:
            if t["status"] == "Completed":
                completed.append(t)
            elif t["deadline"] and t["deadline"] < today:
                overdue.append(t)
            else:
                pending.append(t)

        return jsonify({
            "pending": pending,
            "completed": completed,
            "overdue": overdue,
            "all": tasks
        }), 200

    except Exception as e:
        logger.exception("Error fetching employee tasks")
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()


@app.route("/api/employee/tasks", methods=["POST"])
@csrf.exempt
@login_required
def create_employee_task():
    """
    Create a new task for a project.
    Requires 'task' module 'Add' permission.

    POST payload:
    {
        "title": "Task Title",           # Required
        "description": "...",             # Optional
        "project_id": 1,                  # Required (integer)
        "assigned_to_id": 2,              # Optional (integer or null)
        "priority": "High|Medium|Low",    # Optional, default "Medium"
        "deadline": "YYYY-MM-DD"          # Optional
    }
    """
    conn = None
    try:
        # Step 1: Parse and validate incoming payload
        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        description = data.get("description") or ""
        project_id = data.get("project_id")
        assigned_to_id = data.get("assigned_to_id")
        priority = data.get("priority") or "Medium"
        deadline = data.get("deadline")
        milestone_id = data.get("milestone_id")

        # Validate required fields
        if not title:
            return jsonify({"error": "Task title is required"}), 400
        if project_id is None:
            return jsonify({"error": "Project ID is required"}), 400

        # Normalize and validate project_id type
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return jsonify({"error":
                            "Project ID must be a valid integer"}), 400

        # Normalize and validate assigned_to_id type
        if assigned_to_id is not None and assigned_to_id != "":
            try:
                assigned_to_id = int(assigned_to_id)
            except (ValueError, TypeError):
                return jsonify({
                    "error":
                    "assigned_to_id must be a valid integer or null"
                }), 400
        else:
            assigned_to_id = None

        # Normalize and validate milestone_id type
        if milestone_id is not None and milestone_id != "":
            try:
                milestone_id = int(milestone_id)
            except (ValueError, TypeError):
                return jsonify({
                    "error":
                    "milestone_id must be a valid integer or null"
                }), 400
        else:
            milestone_id = None

        # Validate deadline format if provided
        if deadline:
            try:
                datetime.strptime(deadline, "%Y-%m-%d")
            except ValueError:
                return jsonify(
                    {"error": "Invalid deadline format. Use YYYY-MM-DD"}), 400

        # Get current user
        user_id = get_current_user_id()
        if user_id is None:
            logger.error("Could not determine current user ID")
            return jsonify(
                {"error": "Authentication error: User ID not found"}), 401

        # Step 2: Perform all read operations first (checks/validations)
        # This minimizes the time we hold write locks
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Check permission to create tasks (Super Admin bypass)
            if user_id != 0:
                cursor.execute(
                    'SELECT granted FROM user_permissions WHERE user_id = %s AND module = %s AND action = %s',
                    (user_id, 'task', 'Add'))
                perm = cursor.fetchone()

                # Allow creation if permission is explicitly granted OR if permission system not fully initialized
                # (This allows employees to create tasks even if permissions table is being set up)
                if perm and not perm['granted']:
                    logger.warning(
                        f"User {user_id} lacks permission to create tasks")
                    return jsonify({
                        "error":
                        "Permission denied: You don't have permission to create tasks"
                    }), 403
                elif not perm:
                    # Permission not found - this is OK for transitional state
                    logger.info(
                        f"Permission not found for user {user_id}, allowing task creation (permission system may not be initialized)"
                    )

            # Verify project exists and user is assigned
            cursor.execute('''
                SELECT p.id 
                FROM projects p
                JOIN project_assignments pa ON p.id = pa.project_id
                WHERE p.id = %s AND (p.created_by_id = %s OR pa.user_id = %s)
            ''', (project_id, user_id, user_id))
            
            if not cursor.fetchone():
                logger.warning(
                    f"Project {project_id} not found or user {user_id} not assigned for task creation")
                return jsonify(
                    {"error": f"Project not found or access denied (ID: {project_id})"}), 403

            # Verify assigned_to user exists (if specified)
            if assigned_to_id:
                cursor.execute('SELECT id FROM users WHERE id = %s',
                               (assigned_to_id, ))
                if not cursor.fetchone():
                    logger.warning(
                        f"User {assigned_to_id} not found for task assignment")
                    return jsonify({
                        "error":
                        f"Assigned user not found (ID: {assigned_to_id})"
                    }), 404

        except psycopg2.DatabaseError as db_err:
            logger.exception(f"Database error during validation: {db_err}")
            return jsonify({
                "error": "Database error during validation",
                "details": str(db_err)
            }), 503

        # Decide status based on whether assigned at creation
        status_to_set = 'In Progress' if assigned_to_id else 'Pending'

        # Step 3: Insert the task (write operation with explicit transaction control)
        task_id = None
        try:
            cursor.execute(
                '''
                INSERT INTO tasks (title, description, project_id, created_by_id, assigned_to_id, milestone_id, priority, deadline, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                ''', (title, description, project_id, user_id, assigned_to_id,
                      milestone_id, priority, deadline or None, status_to_set))

            task_id = cursor.fetchone()['id']
            conn.commit()
            logger.info(
                f"Task {task_id} created successfully by user {user_id}")

        except psycopg2.OperationalError as op_err:
            conn.rollback()
            logger.exception(
                f"PostgreSQL lock error while inserting task: {op_err}")
            return jsonify({
                "error": "Database is temporarily unavailable. Please try again.",
                "type": "DB_LOCKED"
            }), 503
        except psycopg2.IntegrityError as int_err:
            conn.rollback()
            logger.exception(f"Integrity constraint error: {int_err}")
            return jsonify(
                {"error": "Task creation failed: Constraint violation"}), 400
        except Exception as insert_err:
            if conn:
                conn.rollback()
            logger.exception(
                f"Unexpected error during task insert: {insert_err}")
            return jsonify({
                "error": "Failed to create task",
                "details": str(insert_err)
            }), 500

        # Close the connection early - don't hold locks for subsequent operations
        conn.close()
        conn = None

        # Step 4: Post-creation operations (these use their own connections)
        # These are non-critical and fail gracefully without affecting the response
        try:
            log_activity(user_id,
                         'task_created',
                         f'Created task: {title}',
                         project_id=project_id,
                         task_id=task_id)
        except Exception as log_err:
            logger.warning(
                f"Failed to log activity for task {task_id}: {log_err}")

        try:
            calculate_project_progress(project_id)
        except Exception as progress_err:
            logger.warning(
                f"Failed to update project progress for project {project_id}: {progress_err}"
            )

        # Step 5: Return success response
        return jsonify({
            "id": task_id,
            "title": title,
            "message": "Task created successfully!"
        }), 201

    except psycopg2.OperationalError as oe:
        logger.exception(f"Uncaught SQLite OperationalError: {oe}")
        return jsonify({
            "error": "Database operation failed",
            "type": "DB_ERROR",
            "details": str(oe)
        }), 503
    except Exception as e:
        logger.exception(f"Unexpected error in create_employee_task: {e}")
        return jsonify({
            "error": "An unexpected error occurred",
            "type": "INTERNAL_ERROR",
            "details": str(e) if app.debug else None
        }), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_err:
                logger.warning(
                    f"Error closing database connection: {close_err}")


@app.route("/api/employee/tasks/<int:task_id>/complete", methods=["POST"])
@csrf.exempt
@login_required
def complete_employee_task(task_id):
    """Complete a task (mark as Completed)"""
    conn = None
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User ID not found"}), 401

        conn = get_db_connection()
        cursor = conn.cursor()

        # Step 1: Fetch task details (validation)
        try:
            cursor.execute(
                '''
                SELECT status, project_id FROM tasks WHERE id = %s AND (assigned_to_id = %s OR created_by_id = %s)
            ''', (task_id, user_id, user_id))
            task = cursor.fetchone()

            if not task:
                logger.warning(
                    f"Task {task_id} not found or user {user_id} lacks permission"
                )
                return jsonify(
                    {"error": "Task not found or permission denied"}), 404

            if task['status'] == 'Completed':
                logger.info(f"Task {task_id} is already completed")
                return jsonify({"message": "Task is already completed"}), 200

            project_id = task['project_id']

        except psycopg2.DatabaseError as db_err:
            logger.exception(
                f"Database error while fetching task {task_id}: {db_err}")
            return jsonify({"error": "Database error during task fetch"}), 503

        # Step 2: Update task status with explicit transaction control
        try:
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                '''
                UPDATE tasks SET status = %s, completed_at = CURRENT_TIMESTAMP WHERE id = %s
            ''', ('Completed', task_id))
            cursor.execute('COMMIT')
            logger.info(
                f"Task {task_id} marked as completed by user {user_id}")

        except psycopg2.OperationalError as op_err:
            cursor.execute('ROLLBACK')
            logger.exception(
                f"Lock error while updating task {task_id}: {op_err}")
            return jsonify({
                "error": "Database is temporarily locked. Please try again.",
                "type": "DB_LOCKED"
            }), 503
        except Exception as update_err:
            cursor.execute('ROLLBACK')
            logger.exception(f"Error updating task {task_id}: {update_err}")
            return jsonify({"error": "Failed to update task status"}), 500

        conn.close()
        conn = None

        # Step 3: Post-update operations (non-critical, use separate connections)
        try:
            log_activity(user_id,
                         'task_completed',
                         f'Completed task {task_id}',
                         task_id=task_id)
        except Exception as log_err:
            logger.warning(
                f"Failed to log activity for task completion: {log_err}")

        try:
            progress_response = calculate_project_progress(project_id)
            if isinstance(progress_response,
                          tuple) and progress_response[1] == 200:
                progress_data = progress_response[0].get_json() if hasattr(
                    progress_response[0], 'get_json') else {}
                return jsonify({
                    "message": "Task completed successfully!",
                    "project_progress": progress_data
                }), 200
        except Exception as progress_err:
            logger.warning(
                f"Failed to calculate project progress: {progress_err}")

        return jsonify({"message": "Task completed successfully!"}), 200

    except Exception as e:
        logger.exception(f"Unexpected error in complete_employee_task: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_err:
                logger.warning(f"Error closing connection: {close_err}")


@app.route("/api/employee/milestones", methods=["GET"])
@csrf.exempt
def get_employee_milestones():
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT m.id, m.title, m.description, m.status, m.due_date, m.project_id,
                   p.title as project_title, m.created_at
            FROM milestones m
            LEFT JOIN projects p ON m.project_id = p.id
            WHERE p.created_by_id = %s OR m.project_id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            )
            ORDER BY m.created_at DESC
        ''', (user_id, user_id))

        milestones = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in milestones]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Replace your existing /api/employee/milestones POST handler with this ---
@app.route('/api/employee/milestones', methods=['POST'])
@csrf.exempt
@login_required
def create_milestone_employee():
    """
    Create milestone for a project. Ensures created_by is a valid user id
    and handles busy database / FK issues gracefully.
    """
    conn = None
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        description = data.get('description') or ''
        due_date = data.get('due_date') or None
        project_id = data.get('project_id')

        if not title:
            return jsonify({'error': 'Milestone title is required'}), 400
        if not project_id:
            return jsonify({'error': 'project_id is required'}), 400

        conn = get_db_connection()
        # Note: PostgreSQL doesn't use PRAGMA busy_timeout (SQLite only)
        cur = conn.cursor()

        # Verify project exists and user is assigned
        # Explicitly check project_assignments for user access
        cur.execute('''
            SELECT p.id 
            FROM projects p
            JOIN project_assignments pa ON p.id = pa.project_id
            WHERE p.id = %s AND (p.created_by_id = %s OR pa.user_id = %s)
        ''', (int(project_id), user_id, user_id))
        
        if not cur.fetchone():
            return jsonify({'error': 'Project not found or access denied'}), 404

        # Ensure created_by is valid (same logic as create_project_employee)
        session_user_id = get_current_user_id() or None
        created_by = None
        if session_user_id:
            cur.execute("SELECT id FROM users WHERE id = %s", (session_user_id,))
            row = cur.fetchone()
            if row:
                created_by = row['id']

        if not created_by:
            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                created_by = row['id']
            else:
                # create fallback system user
                cur.execute("SELECT id FROM usertypes WHERE LOWER(user_role) LIKE %s LIMIT 1", ('admin%',))
                ut = cur.fetchone()
                if ut:
                    user_type_id = ut['id']
                else:
                    cur.execute("INSERT INTO usertypes (user_role) VALUES (%s) RETURNING id", ('Administrator',))
                    user_type_id = cur.fetchone()['id']
                from werkzeug.security import generate_password_hash
                pw = generate_password_hash(secrets.token_urlsafe(12))
                cur.execute(
                    "INSERT INTO users (username, email, password, user_type_id, granted, created_at) VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP) RETURNING id",
                    ('system', 'system@example.local', pw, user_type_id)
                )
                created_by = cur.fetchone()['id']

        # Insert milestone
        cur.execute(
            '''INSERT INTO milestones (title, description, due_date, project_id, created_by_id, created_at)
               VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
               RETURNING id''',
            (title, description, due_date, int(project_id), int(created_by))
        )
        milestone_id = cur.fetchone()['id']
        conn.commit()

        try:
            log_activity(created_by, 'milestone_created', f'Created milestone {title}', project_id=int(project_id), milestone_id=milestone_id)
        except Exception:
            pass

        return jsonify({'success': True, 'id': milestone_id}), 201

    except psycopg2.IntegrityError as e:
        if conn:
            conn.rollback()
        logger.exception('create_milestone_employee failed (integrity)')
        return jsonify({'error': 'Database integrity error', 'detail': str(e)}), 400
    except psycopg2.OperationalError as e:
        if conn:
            conn.rollback()
        logger.exception('create_milestone_employee failed (operational)')
        return jsonify({'error': 'Database is busy or locked. Try again.', 'detail': str(e)}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        logger.exception('create_milestone_employee failed')
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


@app.route("/api/employee/milestones/<int:milestone_id>/complete",
           methods=["POST"])
@csrf.exempt
@login_required
def complete_employee_milestone(milestone_id):
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT project_id FROM milestones WHERE id = %s',
                       (milestone_id, ))
        milestone = cursor.fetchone()

        if not milestone:
            conn.close()
            return jsonify({"error": "Milestone not found"}), 404

        cursor.execute(
            '''
            UPDATE milestones SET status = %s
            WHERE id = %s
        ''', ('Completed', milestone_id))

        conn.commit()
        conn.close()

        log_activity(user_id,
                     'milestone_completed',
                     f'Completed milestone ID: {milestone_id}',
                     milestone_id=milestone_id)

        # Update project progress
        try:
            calculate_project_progress(milestone['project_id'])
        except:
            pass

        return jsonify({"message": "Milestone completed successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === TEAM MEMBERS ENDPOINTS ===

# @app.route("/api/employee/team-members", methods=["GET"])
# @csrf.exempt
# def get_employee_team_members():
#     """Get all team members for projects the employee is assigned to"""
#     try:
#         user_id = get_current_user_id()
#         if not user_id:
#             return jsonify({"error": "Unauthorized"}), 401
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         # Get all project IDs where the current user is assigned
#         cursor.execute('''
#             SELECT DISTINCT project_id FROM project_assignments
#             WHERE user_id = %s
#         ''', (user_id,))
        
#         projects = cursor.fetchall()
#         project_ids = [p['project_id'] for p in projects]
        
#         if not project_ids:
#             conn.close()
#             return jsonify([]), 200
        
#         # Get all team members from those projects
#         placeholders = ','.join(['%s'] * len(project_ids))
#         cursor.execute(f'''
#             SELECT DISTINCT u.id, u.username, u.email, u.user_type_id
#             FROM users u
#             JOIN project_assignments pa ON u.id = pa.user_id
#             WHERE pa.project_id IN ({placeholders})
#             ORDER BY u.username
#         ''', project_ids)
        
#         team_members = cursor.fetchall()
#         conn.close()
        
#         return jsonify([dict(member) for member in team_members]), 200
#     except Exception as e:
#         logger.error(f"Error getting team members: {str(e)}")
#         return jsonify({"error": str(e)}), 500


@app.route("/api/employee/team-members", methods=["GET"])
@csrf.exempt
def get_employee_team_members():
    """Get all team members for projects the employee is assigned to, including project info"""
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all project IDs where the current user is assigned or created
        cursor.execute('''
            SELECT DISTINCT p.id 
            FROM projects p
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            WHERE p.created_by_id = %s OR pa.user_id = %s
        ''', (user_id, user_id))
        
        projects = cursor.fetchall()
        project_ids = [p['id'] for p in projects]
        
        if not project_ids:
            conn.close()
            return jsonify([]), 200
        
        # Get all team members from those projects with project info
        placeholders = ','.join(['%s'] * len(project_ids))
        cursor.execute(f'''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role, pa.project_id, p.title as project_name
            FROM users u
            JOIN project_assignments pa ON u.id = pa.user_id
            JOIN projects p ON pa.project_id = p.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id IN ({placeholders})
            ORDER BY p.title, u.username
        ''', project_ids)
        
        team_members = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(member) for member in team_members]), 200
    except Exception as e:
        logger.error(f"Error getting team members: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/team-members", methods=["POST"])
@csrf.exempt
@login_required
def add_employee_team_member():
    """Add a new team member to a project"""
    try:
        # Use the user_id set by @login_required decorator
        user_id = g.get('current_user_id') or get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        
        # Get JSON data with proper error handling
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
        
        try:
            data = request.get_json()
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({"error": f"Invalid JSON: {str(json_error)}"}), 400
        
        # Validate required fields
        required_fields = ['username', 'email', 'password', 'project_id']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400
        
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not email or not password:
            return jsonify({"error": "Username, email, and password cannot be empty"}), 400
        
        try:
            project_id = int(data.get('project_id', 0))
            if project_id <= 0:
                raise ValueError("project_id must be positive")
        except (ValueError, TypeError) as e:
             return jsonify({"error": f"Invalid project_id: {str(e)}"}), 400
        
        logger.info(f"[ADD TEAM MEMBER] user_id={user_id}, username={username}, project_id={project_id}")
        
        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500
            cursor = conn.cursor()
        except Exception as db_error:
            logger.error(f"Database connection error: {str(db_error)}")
            return jsonify({"error": f"Database connection error: {str(db_error)}"}), 500
        
        # Check permissions: Is user admin or coordinator?
        try:
            cursor.execute("SELECT ut.user_role FROM users u JOIN usertypes ut ON u.user_type_id = ut.id WHERE u.id = %s", (user_id,))
            role_row = cursor.fetchone()
            user_role = role_row['user_role'] if role_row else ''
            
            logger.info(f"[ADD TEAM MEMBER] User role check: user_id={user_id}, user_role={user_role}")
            
            # Admins, Coordinators, or the project creator should be allowed
            # Note: Fixed typo from "Project-Cordinator" to "Project-Coordinator" but check both for backwards compatibility
            is_allowed = user_role in ('Administrator', 'Project-Coordinator', 'Project-Cordinator', 'Coordinator', 'Employee')
            
            if not is_allowed:
                 # More granular check: is user assigned to this project via project_assignments?
                 cursor.execute("SELECT created_by_id FROM projects WHERE id = %s", (project_id,))
                 proj = cursor.fetchone()
                 if not proj or proj['created_by_id'] != user_id:
                     # Also check if user is assigned to this project
                     cursor.execute("SELECT id FROM project_assignments WHERE user_id = %s AND project_id = %s", (user_id, project_id))
                     if not cursor.fetchone():
                         logger.warning(f"[ADD TEAM MEMBER] Permission denied for user {user_id} on project {project_id}")
                         conn.close()
                         return jsonify({"error": "You don't have permission to add members to this project"}), 403
        except Exception as perm_error:
            logger.error(f"[ADD TEAM MEMBER] Permission check error: {str(perm_error)}")
            conn.close()
            return jsonify({"error": f"Permission check failed: {str(perm_error)}"}), 500
        
        # Check if username already exists
        try:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": "Username already exists"}), 400
        except Exception as e:
            logger.error(f"[ADD TEAM MEMBER] Username check error: {str(e)}")
            conn.close()
            return jsonify({"error": f"Username check error: {str(e)}"}), 500
        
        # Check if email already exists
        try:
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": "Email already exists"}), 400
        except Exception as e:
            logger.error(f"[ADD TEAM MEMBER] Email check error: {str(e)}")
            conn.close()
            return jsonify({"error": f"Email check error: {str(e)}"}), 500
        
        # Hash password
        try:
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            logger.info(f"[ADD TEAM MEMBER] Password hashed successfully")
        except Exception as hash_error:
            logger.error(f"[ADD TEAM MEMBER] Password hashing error: {str(hash_error)}")
            conn.close()
            return jsonify({"error": f"Password hashing error: {str(hash_error)}"}), 500
        
        # Get default team_member user type
        try:
            cursor.execute('SELECT id FROM usertypes WHERE user_role = %s', ('Employee',)) 
            user_type = cursor.fetchone()
            if not user_type:
                # Fallback
                logger.info(f"[ADD TEAM MEMBER] No Employee user type found, using first available")
                cursor.execute('SELECT id FROM usertypes LIMIT 1')
                user_type = cursor.fetchone()
            
            if not user_type:
                logger.error("[ADD TEAM MEMBER] No user types found in database")
                conn.close()
                return jsonify({"error": "No user types configured in database"}), 500
                
            user_type_id = user_type['id']
            logger.info(f"[ADD TEAM MEMBER] Using user_type_id={user_type_id}")
        except Exception as utype_error:
            logger.error(f"[ADD TEAM MEMBER] User type lookup error: {str(utype_error)}")
            conn.close()
            return jsonify({"error": f"User type lookup error: {str(utype_error)}"}), 500
        
        # Create new user
        try:
            cursor.execute('''
                INSERT INTO users (username, email, password, user_type_id, status)
                VALUES (%s, %s, %s, %s, 'Active')
                RETURNING id
            ''', (username, email, hashed_password, user_type_id))
            
            result = cursor.fetchone()
            if result:
                new_user_id = result['id']
            else:
                new_user_id = cursor.lastrowid
                
            logger.info(f"[ADD TEAM MEMBER] New user created: user_id={new_user_id}, username={username}")
        except Exception as create_error:
            logger.error(f"[ADD TEAM MEMBER] User creation error: {str(create_error)}")
            conn.rollback()
            conn.close()
            return jsonify({"error": f"User creation error: {str(create_error)}"}), 500

        
        # Assign user to project
        try:
            cursor.execute('''
                INSERT INTO project_assignments (user_id, project_id)
                VALUES (%s, %s)
            ''', (new_user_id, project_id))
            logger.info(f"[ADD TEAM MEMBER] User assigned to project: user_id={new_user_id}, project_id={project_id}")
        except Exception as assign_error:
            logger.error(f"[ADD TEAM MEMBER] Project assignment error: {str(assign_error)}")
            conn.rollback()
            conn.close()
            return jsonify({"error": f"Project assignment error: {str(assign_error)}"}), 500
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Team member added successfully",
            "user_id": new_user_id,
            "username": username,
            "email": email
        }), 201
    except Exception as e:
        logger.error(f"Error adding team member: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            if 'conn' in locals() and conn:
                conn.rollback()
                conn.close()
        except:
            pass
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/api/employee/documents", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_documents():
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT d.id, d.filename, d.original_filename, d.file_size,
                   d.uploaded_by_id, u.username as uploaded_by, d.project_id, d.task_id,
                   d.uploaded_at
            FROM documents d
            LEFT JOIN users u ON d.uploaded_by_id = u.id
            WHERE d.uploaded_by_id = %s OR d.project_id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            )
            ORDER BY d.uploaded_at DESC
        ''', (user_id, user_id))

        documents = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in documents]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/documents/upload", methods=["POST"])
@csrf.exempt
@login_required
def upload_employee_document():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        project_id = request.form.get('project_id')

        if not file.filename or not project_id:
            return jsonify({"error": "File and project ID are required"}), 400

        user_id = get_current_user_id()

        # Ensure upload folder exists
        upload_dir = os.path.join('uploads', 'documents')
        os.makedirs(upload_dir, exist_ok=True)

        # Use a secure and unique filename
        filename = f"{secrets.token_hex(8)}_{secure_filename(file.filename)}"
        file_path = os.path.join(upload_dir, filename)

        # Save the file
        file.save(file_path)

        file_size = os.path.getsize(file_path)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO documents (filename, original_filename, file_size, uploaded_by_id, project_id)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING id
        ''', (filename, file.filename, file_size, user_id, project_id))

        doc_id = cursor.fetchone()['id']
        conn.commit()
        conn.close()

        log_activity(user_id,
                     'document_uploaded',
                     f'Uploaded document: {file.filename}',
                     project_id=project_id)

        return jsonify({
            "id": doc_id,
            "filename": file.filename,
            "message": "Document uploaded successfully!"
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/documents/<int:doc_id>/delete", methods=["DELETE"])
@csrf.exempt
@login_required
def delete_employee_document(doc_id):
    try:
        user_id = get_current_user_id()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT uploaded_by_id, project_id, filename FROM documents WHERE id = %s',
            (doc_id, ))
        doc_info = cursor.fetchone()

        if not doc_info:
            conn.close()
            return jsonify({"error": "Document not found."}), 404

        # Check ownership or project assignment
        if doc_info['uploaded_by_id'] != user_id:
            cursor.execute(
                '''
                SELECT 1 FROM project_assignments WHERE user_id = %s AND project_id = %s
            ''', (user_id, doc_info['project_id']))
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Permission denied"}), 403

        # Delete file from storage
        file_path = os.path.join('uploads', 'documents', doc_info['filename'])
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            print(f"[WARNING] Could not delete file {file_path}: {e}")
            # Continue with deletion from DB even if file deletion fails

        cursor.execute('DELETE FROM documents WHERE id = %s', (doc_id, ))
        conn.commit()
        conn.close()

        log_activity(user_id,
                     'document_deleted',
                     f'Deleted document ID: {doc_id}',
                     project_id=doc_info['project_id'])

        return jsonify({"message": "Document deleted successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/dashboard/stats", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_dashboard_stats():
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT COUNT(DISTINCT id) as count FROM projects 
            WHERE created_by_id = %s OR id IN (SELECT project_id FROM project_assignments WHERE user_id = %s)
        ''', (user_id, user_id))
        result = cursor.fetchone()
        total_projects = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        cursor.execute(
            'SELECT COUNT(*) as count FROM tasks WHERE assigned_to_id = %s OR created_by_id = %s',
            (user_id, user_id))
        result = cursor.fetchone()
        total_tasks = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        cursor.execute(
            'SELECT COUNT(*) as count FROM tasks WHERE (assigned_to_id = %s OR created_by_id = %s) AND status = %s',
            (user_id, user_id, 'Completed'))
        result = cursor.fetchone()
        completed_tasks = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM milestones m 
            WHERE m.project_id IN (
                SELECT id FROM projects WHERE created_by_id = %s OR id IN (
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                )
            )
        ''', (user_id, user_id))
        result = cursor.fetchone()
        total_milestones = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        conn.close()

        return jsonify({
            "total_projects": total_projects,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "total_milestones": total_milestones,
            "pending_tasks": total_tasks - completed_tasks
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/activities", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_activities():
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT a.id, a.activity_type, a.description, a.created_at,
                   u.username, p.title as project_title, p.description as project_description, p.deadline as project_deadline,
                   t.title as task_title, m.title as milestone_title
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.id
            LEFT JOIN projects p ON a.project_id = p.id
            LEFT JOIN tasks t ON a.task_id = t.id
            LEFT JOIN milestones m ON a.milestone_id = m.id
            WHERE a.user_id = %s OR a.project_id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            ) OR a.task_id IN (
                SELECT id FROM tasks WHERE assigned_to_id = %s OR created_by_id = %s
            ) OR a.milestone_id IN (
                SELECT id FROM milestones WHERE project_id IN (
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                )
            )
            ORDER BY a.created_at DESC
            LIMIT 50
        ''', (user_id, user_id, user_id, user_id, user_id))

        activities = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in activities]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/search", methods=["GET"])
@csrf.exempt
@login_required
def search():
    try:
        query = request.args.get('q', '').strip()
        if not query or len(query) < 2:
            return jsonify({"results": []}), 200

        # Check if admin or employee
        is_admin = session.get('admin') or session.get('user_type') == 'admin'
        user_id = get_current_user_id()

        conn = get_db_connection()
        cursor = conn.cursor()

        results = []

        # Search projects
        if is_admin:
            cursor.execute(
                '''
                SELECT 'project' as type, id, title as name, description,
                       created_at, NULL as project_name, NULL as status
                FROM projects
                WHERE title LIKE %s OR description LIKE %s
                ORDER BY created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%'))
        else:
            cursor.execute(
                '''
                SELECT 'project' as type, p.id, p.title as name, p.description,
                       p.created_at, NULL as project_name, NULL as status
                FROM projects p
                WHERE (p.title LIKE %s OR p.description LIKE %s) AND
                      (p.created_by_id = %s OR p.id IN (
                          SELECT project_id FROM project_assignments WHERE user_id = %s
                      ))
                ORDER BY p.created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%', user_id, user_id))

        projects = cursor.fetchall()
        for project in projects:
            results.append({
                "type":
                "project",
                "id":
                project['id'],
                "name":
                project['name'],
                "description":
                project['description'][:100] + "..."
                if project['description'] and len(project['description']) > 100
                else project['description'],
                "url":
                "/admin-dashboard" if is_admin else "/employee-dashboard",
                "tab":
                "projects-tab" if not is_admin else None
            })

        # Search tasks
        if is_admin:
            cursor.execute(
                '''
                SELECT 'task' as type, t.id, t.title as name, t.description,
                       t.created_at, p.title as project_name, t.status
                FROM tasks t
                LEFT JOIN projects p ON t.project_id = p.id
                WHERE t.title LIKE %s OR t.description LIKE %s
                ORDER BY t.created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%'))
        else:
            cursor.execute(
                '''
                SELECT 'task' as type, t.id, t.title as name, t.description,
                       t.created_at, p.title as project_name, t.status
                FROM tasks t
                LEFT JOIN projects p ON t.project_id = p.id
                    WHERE (t.title LIKE %s OR t.description LIKE %s) AND
                        (t.assigned_to_id = %s OR t.created_by_id = %s)
                ORDER BY t.created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%', user_id, user_id))

        tasks = cursor.fetchall()
        for task in tasks:
            results.append({
                "type":
                "task",
                "id":
                task['id'],
                "name":
                task['name'],
                "description":
                task['description'][:100] if task['description']
                and len(task['description']) > 100 else task['description'],
                "project_name":
                task['project_name'],
                "status":
                task['status'],
                "url":
                "/admin-dashboard" if is_admin else "/employee-dashboard",
                "tab":
                "tasks-tab" if not is_admin else None
            })

        # Search users (admin only)
        if is_admin:
            cursor.execute(
                '''
                SELECT 'user' as type, id, username as name, email as description,
                       created_at, NULL as project_name, NULL as status
                FROM users
                WHERE username LIKE %s OR email LIKE %s
                ORDER BY created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%'))

            users = cursor.fetchall()
            for user in users:
                results.append({
                    "type": "user",
                    "id": user['id'],
                    "name": user['name'],
                    "description": user['description'],
                    "url": "/admin-dashboard",
                    "tab": "users-tab"
                })

        # Search milestones
        if is_admin:
            cursor.execute(
                '''
                SELECT 'milestone' as type, m.id, m.title as name, m.description,
                       m.created_at, p.title as project_name, m.status
                FROM milestones m
                LEFT JOIN projects p ON m.project_id = p.id
                WHERE m.title LIKE %s OR m.description LIKE %s
                ORDER BY m.created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%'))
        else:
            cursor.execute(
                '''
                SELECT 'milestone' as type, m.id, m.title as name, m.description,
                       m.created_at, p.title as project_name, m.status
                FROM milestones m
                LEFT JOIN projects p ON m.project_id = p.id
                WHERE (m.title LIKE %s OR m.description LIKE %s) AND
                      (p.created_by_id = %s OR m.project_id IN (
                          SELECT project_id FROM project_assignments WHERE user_id = %s
                      ))
                ORDER BY m.created_at DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%', user_id, user_id))

        milestones = cursor.fetchall()
        for milestone in milestones:
            results.append({
                "type":
                "milestone",
                "id":
                milestone['id'],
                "name":
                milestone['name'],
                "description":
                milestone['description'][:100] if milestone['description']
                and len(milestone['description']) > 100 else
                milestone['description'],
                "project_name":
                milestone['project_name'],
                "status":
                milestone['status'],
                "url":
                "/admin-dashboard" if is_admin else "/employee-dashboard",
                "tab":
                "milestones-tab" if not is_admin else None
            })

        # Search documents
        if is_admin:
            cursor.execute(
                '''
                SELECT 'document' as type, d.id, d.original_filename as name,
                       d.file_size, d.uploaded_at, p.title as project_name, NULL as status
                FROM documents d
                LEFT JOIN projects p ON d.project_id = p.id
                WHERE d.original_filename LIKE %s
                ORDER BY d.uploaded_at DESC
                LIMIT 10
            ''', (f'%{query}%', ))
        else:
            cursor.execute(
                '''
                SELECT 'document' as type, d.id, d.original_filename as name,
                       d.file_size, d.uploaded_at, p.title as project_name, NULL as status
                FROM documents d
                LEFT JOIN projects p ON d.project_id = p.id
                WHERE d.original_filename LIKE %s AND
                      (d.uploaded_by_id = %s OR d.project_id IN (
                          SELECT project_id FROM project_assignments WHERE user_id = %s
                      ))
                ORDER BY d.uploaded_at DESC
                LIMIT 10
            ''', (f'%{query}%', user_id, user_id))

        documents = cursor.fetchall()
        for doc in documents:
            results.append({
                "type": "document",
                "id": doc['id'],
                "name": doc['name'],
                "description": f"Size: {doc['file_size']} bytes",
                "project_name": doc['project_name'],
                "url":
                "/admin-dashboard" if is_admin else "/employee-dashboard",
                "tab": "documents-tab" if not is_admin else None
            })

        conn.close()

        return jsonify({"results": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/projects", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_projects():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT p.id, p.title, p.description, p.status, p.progress, 
                   p.deadline, p.created_by_id, u.username as creator_name, 
                   p.created_at, COUNT(DISTINCT pa.user_id) as team_count,
                   COUNT(DISTINCT t.id) as task_count
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            LEFT JOIN tasks t ON p.id = t.project_id
            GROUP BY p.id, u.username
            ORDER BY p.created_at DESC
        ''')

        projects = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in projects]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/tasks", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_tasks():
    """
    Get admin tasks. Supports optional query parameters:
    - status: filter by task.status (e.g., 'In Progress','Pending','Completed','Overdue')
    - assigned_to: user id
    - project_id: project id
    - limit, offset (pagination)
    """
    try:
        status = request.args.get('status')
        assigned_to = request.args.get('assigned_to')
        project_id = request.args.get('project_id')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        conn = get_db_connection()
        cursor = conn.cursor()

        base_query = '''
            SELECT t.id, t.title, t.description, t.status, t.priority, t.deadline,
                   t.project_id, p.title as project_name,
                   t.assigned_to_id, u.username as assigned_to_name,
                   t.created_by_id, uc.username as created_by_name,
                   t.created_at, t.approval_status, t.completed_at,
                   COALESCE(t.weightage,1) AS weightage
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN users uc ON t.created_by_id = uc.id
            WHERE 1=1
        '''
        params = []

        if status:
            # special handling for 'Overdue'
            if status.lower() == 'overdue':
                base_query += " AND t.deadline < date('now') AND t.status != 'Completed'"
            else:
                base_query += " AND t.status = %s"
                params.append(status)
        if assigned_to:
            base_query += " AND t.assigned_to_id = %s"
            params.append(int(assigned_to))
        if project_id:
            base_query += " AND t.project_id = %s"
            params.append(int(project_id))

        base_query += ' ORDER BY t.created_at DESC LIMIT %s OFFSET %s'
        params.extend([limit, offset])

        cursor.execute(base_query, params)
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            task = dict(r)
            # Calculate a simple progress percent if possible: using task weight and related completed sub-items is complex.
            # For now, attempt to compute percent of completed subtasks if any stored; fallback to 0.
            task['progress_percent'] = task.get(
                'progress_percent', 0) if 'progress_percent' in task else 0
            results.append(task)

        return jsonify(results), 200
    except Exception as e:
        logger.exception('get_admin_tasks failed')
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<int:task_id>/history", methods=["GET"])
@csrf.exempt
@admin_required
def task_history(task_id):
    """
    Return task details and activity history related to the task.
    Useful for Task History view on admin dashboard.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Task details
        cursor.execute(
            '''
            SELECT t.*, p.title as project_name, u.username as assigned_to_name, uc.username as created_by_name
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN users uc ON t.created_by_id = uc.id
            WHERE t.id = %s
        ''', (task_id, ))
        task_row = cursor.fetchone()
        if not task_row:
            conn.close()
            return jsonify({'error': 'Task not found'}), 404
        task = dict(task_row)

        # Activity history for this task
        cursor.execute(
            '''
            SELECT a.id, a.activity_type, a.description, a.user_id, u.username, a.project_id, a.task_id, a.created_at
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.task_id = %s
            ORDER BY a.created_at ASC
        ''', (task_id, ))
        history_rows = cursor.fetchall()
        history = [dict(r) for r in history_rows]

        conn.close()

        return jsonify({'task': task, 'history': history}), 200
    except Exception as e:
        logger.exception('task_history failed')
        return jsonify({'error': str(e)}), 500


# @app.route("/api/admin/user-hierarchy", methods=["GET"])
# @csrf.exempt
# @admin_required
# def get_user_hierarchy():
#     """
#     Build a professional user hierarchy:
#     Super Admin -> Projects -> Coordinator -> Employees -> Team Members -> Tasks
    
#     Structure:
#     - Super Admin (root)
#       - Project A
#         - Coordinator (who created/manages it)
#         - Employees (assigned to project)
#           - Team Members (assigned to project)
#             - Tasks & Progress
#         - Milestones & Project Progress
#       - Project B ...
#       - Employees Section
#         - Each Employee with their Assigned Projects, Team Members, Task Performance
    
#     Returns JSON tree with clickable navigation.
#     """
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()

#         # Get all users with their roles
#         cursor.execute('''
#             SELECT u.id, u.username, u.email, ut.user_role, ut.id as user_type_id
#             FROM users u 
#             LEFT JOIN usertypes ut ON u.user_type_id = ut.id
#             WHERE COALESCE(u.is_system, 0) != 1
#             ORDER BY u.username
#         ''')
#         all_users = [dict(r) for r in cursor.fetchall()]
#         logger.info(f"[Hierarchy] Total users fetched: {len(all_users)}")

#         # Categorise users
#         super_admin_user = None
#         employee_list = []
#         for u in all_users:
#             role = (u.get('user_role') or '').lower()
#             if 'super admin' in role or 'system administrator' in role:
#                 super_admin_user = u
#             else:
#                 employee_list.append(u)

#         # ---------- PROJECTS ----------
#         cursor.execute('''
#             SELECT p.id, p.title, p.status, p.progress, p.deadline, p.description,
#                    p.created_by_id,
#                    (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count,
#                    (SELECT COUNT(*) FROM milestones WHERE project_id = p.id) as milestone_count,
#                    (SELECT COUNT(*) FROM tasks WHERE project_id = p.id) as task_count,
#                    (SELECT COUNT(*) FROM tasks WHERE project_id = p.id AND status = 'Completed') as completed_tasks
#             FROM projects p
#             ORDER BY p.title
#         ''')
#         all_projects = [dict(r) for r in cursor.fetchall()]
#         total_projects = len(all_projects)

#         # Build a quick user lookup
#         user_map = {u['id']: u for u in all_users}

#         # Build project nodes
#         project_nodes = []
#         for proj in all_projects:
#             proj_id = proj['id']

#             # Coordinator / creator of the project
#             creator_id = proj.get('created_by_id')
#             creator = user_map.get(creator_id)
#             coordinator_info = None
#             if creator:
#                 coordinator_info = {
#                     'id': creator['id'],
#                     'name': creator['username'],
#                     'email': creator.get('email'),
#                     'role': creator.get('user_role') or 'Coordinator'
#                 }

#             # Get all assigned members for this project
#             cursor.execute('''
#                 SELECT u.id, u.username, u.email, ut.user_role,
#                        (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id) as task_count,
#                        (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id AND status = 'Completed') as completed_tasks
#                 FROM users u
#                 JOIN project_assignments pa ON u.id = pa.user_id
#                 LEFT JOIN usertypes ut ON u.user_type_id = ut.id
#                 WHERE pa.project_id = %s
#                 ORDER BY u.username
#             ''', (proj_id, proj_id, proj_id))
#             members_raw = [dict(r) for r in cursor.fetchall()]

#             # Separate employees (coordinators/admins) vs team members
#             employees_in_proj = []
#             team_members_in_proj = []
#             for m in members_raw:
#                 m_role = (m.get('user_role') or '').lower()
#                 is_emp = any(k in m_role for k in ['coordinator', 'manager', 'admin', 'project coordinator'])
#                 member_data = {
#                     'id': m['id'],
#                     'name': m['username'],
#                     'email': m.get('email'),
#                     'role': m.get('user_role') or 'Team Member',
#                     'task_count': m.get('task_count', 0),
#                     'completed_tasks': m.get('completed_tasks', 0)
#                 }

#                 # Get tasks for this member in this project
#                 cursor.execute('''
#                     SELECT id, title, status, priority, deadline
#                     FROM tasks
#                     WHERE project_id = %s AND assigned_to_id = %s
#                     ORDER BY 
#                         CASE WHEN status = 'Completed' THEN 1 ELSE 0 END,
#                         created_at DESC
#                 ''', (proj_id, m['id']))
#                 member_data['tasks'] = [dict(t) for t in cursor.fetchall()]

#                 if is_emp:
#                     employees_in_proj.append(member_data)
#                 else:
#                     team_members_in_proj.append(member_data)

#             # Milestones for this project
#             cursor.execute('''
#                 SELECT id, title, status, due_date as deadline
#                 FROM milestones
#                 WHERE project_id = %s
#                 ORDER BY due_date
#             ''', (proj_id,))
#             milestones_raw = [dict(r) for r in cursor.fetchall()]
            
#             # Ensure deadlines are serializable
#             milestones = []
#             for ms in milestones_raw:
#                 ms['deadline'] = ms['deadline'].isoformat() if ms.get('deadline') else None
#                 milestones.append(ms)

#             task_total = proj.get('task_count') or 0
#             task_completed = proj.get('completed_tasks') or 0
#             progress_pct = round((task_completed / task_total * 100), 1) if task_total > 0 else 0

#             project_node = {
#                 'id': f'project-{proj_id}',
#                 'project_id': proj_id,
#                 'name': proj['title'],
#                 'type': 'project',
#                 'class': 'project',
#                 'icon': 'fas fa-project-diagram',
#                 'status': proj.get('status') or 'Active',
#                 'progress': progress_pct,
#                 'deadline': proj['deadline'].isoformat() if proj.get('deadline') else None,
#                 'description': proj.get('description'),
#                 'team_count': proj.get('team_count') or 0,
#                 'task_count': task_total,
#                 'completed_tasks': task_completed,
#                 'milestone_count': proj.get('milestone_count') or 0,
#                 'coordinator': coordinator_info,
#                 'employees': employees_in_proj,
#                 'team_members': team_members_in_proj,
#                 'milestones': milestones
#             }
#             project_nodes.append(project_node)

#         # ---------- EMPLOYEES SECTION ----------
#         employee_nodes = []
#         for emp in employee_list:
#             emp_id = emp['id']
#             emp_role = emp.get('user_role') or 'Employee'
#             role_lower = emp_role.lower()
#             is_coordinator = any(k in role_lower for k in ['admin', 'coordinator', 'manager', 'project coordinator'])

#             # Projects where employee is creator
#             cursor.execute('''
#                 SELECT p.id, p.title, p.status, p.progress
#                 FROM projects p WHERE p.created_by_id = %s
#                 ORDER BY p.title
#             ''', (emp_id,))
#             created_projs = [dict(r) for r in cursor.fetchall()]

#             # Projects where employee is assigned
#             cursor.execute('''
#                 SELECT DISTINCT p.id, p.title, p.status, p.progress
#                 FROM projects p
#                 JOIN project_assignments pa ON p.id = pa.project_id
#                 WHERE pa.user_id = %s AND p.created_by_id != %s
#                 ORDER BY p.title
#             ''', (emp_id, emp_id))
#             assigned_projs = [dict(r) for r in cursor.fetchall()]

#             all_emp_projects = {p['id']: p for p in created_projs}
#             for p in assigned_projs:
#                 if p['id'] not in all_emp_projects:
#                     all_emp_projects[p['id']] = p
#             emp_projects_list = list(all_emp_projects.values())

#             # Team members working under this employee across all their projects
#             cursor.execute('''
#                 SELECT DISTINCT u.id, u.username, ut.user_role
#                 FROM users u
#                 JOIN project_assignments pa ON u.id = pa.user_id
#                 LEFT JOIN usertypes ut ON u.user_type_id = ut.id
#                 WHERE pa.project_id IN (
#                     SELECT p.id FROM projects p WHERE p.created_by_id = %s
#                     UNION
#                     SELECT pa2.project_id FROM project_assignments pa2 WHERE pa2.user_id = %s
#                 )
#                 AND u.id != %s
#                 ORDER BY u.username
#             ''', (emp_id, emp_id, emp_id))
#             emp_team = [dict(r) for r in cursor.fetchall()]

#             # Task performance for this employee
#             cursor.execute('''
#                 SELECT COUNT(*) as total,
#                        SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
#                        SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress,
#                        SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending
#                 FROM tasks WHERE assigned_to_id = %s
#             ''', (emp_id,))
#             perf_row = cursor.fetchone()
#             perf = dict(perf_row) if perf_row else {}

#             employee_node = {
#                 'id': f'employee-{emp_id}',
#                 'user_id': emp_id,
#                 'name': emp['username'],
#                 'email': emp.get('email'),
#                 'role': emp_role,
#                 'type': 'employee',
#                 'class': 'coordinator' if is_coordinator else 'employee',
#                 'icon': 'fas fa-user-tie' if is_coordinator else 'fas fa-user',
#                 'projects': emp_projects_list,
#                 'projects_count': len(emp_projects_list),
#                 'team_members': emp_team,
#                 'team_members_count': len(emp_team),
#                 'performance': {
#                     'total_tasks': perf.get('total') or 0,
#                     'completed': perf.get('completed') or 0,
#                     'in_progress': perf.get('in_progress') or 0,
#                     'pending': perf.get('pending') or 0
#                 }
#             }
#             employee_nodes.append(employee_node)

#         # ---------- BUILD TREE ----------
#         tree = {
#             'super_admin': {
#                 'id': 'super-admin',
#                 'name': super_admin_user['username'] if super_admin_user else 'Super Admin',
#                 'email': super_admin_user.get('email') if super_admin_user else None,
#                 'role': 'Full Access - System Administrator',
#                 'type': 'super_admin',
#                 'icon': 'fas fa-crown',
#                 'class': 'super-admin'
#             },
#             'projects': project_nodes,
#             'employees': employee_nodes,
#             'summary': {
#                 'total_projects': total_projects,
#                 'total_employees': len(employee_list),
#                 'total_team_members': sum(len(p.get('team_members') or []) for p in project_nodes),
#                 'total_tasks': sum(p.get('task_count') or 0 for p in project_nodes),
#                 'completed_tasks': sum(p.get('completed_tasks') or 0 for p in project_nodes)
#             }
#         }

#         conn.close()
#         logger.info(f"[Hierarchy] Built hierarchy: {total_projects} projects, {len(employee_list)} employees")
#         return jsonify(tree), 200
#     except Exception as e:
#         if 'conn' in locals() and conn:
#             conn.close()
#         logger.exception(f'[Hierarchy] get_user_hierarchy failed: {str(e)}')
#         return jsonify({'error': str(e)}), 500

# @app.route("/api/admin/user-hierarchy", methods=["GET"])
# @admin_required
# def get_user_hierarchy():
#     """Get complete user hierarchy with reporting relationships"""
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
        
#         # Get Super Admin
#         cursor.execute("""
#             SELECT u.id, u.username, ut.user_role, u.user_type_id
#             FROM users u
#             LEFT JOIN usertypes ut ON u.user_type_id = ut.id
#             WHERE u.username = 'Super Admin'
#         """)
#         super_admin = cursor.fetchone()
        
#         if not super_admin:
#             conn.close()
#             return jsonify({"error": "Super Admin not found"}), 404
        
#         # Get all projects
#         cursor.execute("""
#             SELECT id, title, status, progress, deadline
#             FROM projects
#             ORDER BY created_at DESC
#         """)
#         projects = [dict(row) for row in cursor.fetchall()]
        
#         # Get all users with their reporting managers
#         cursor.execute("""
#             SELECT u.id, u.username, u.email, u.department, ut.user_role, u.user_type_id,
#                    pa.reporting_manager_id, rm.username as reporting_manager_name
#             FROM users u
#             LEFT JOIN usertypes ut ON u.user_type_id = ut.id
#             LEFT JOIN project_assignments pa ON u.id = pa.user_id
#             LEFT JOIN users rm ON pa.reporting_manager_id = rm.id
#             WHERE u.username != 'Super Admin'
#             ORDER BY u.id
#         """)
#         users_data = cursor.fetchall()
        
#         # Get project team members
#         cursor.execute("""
#             SELECT user_id, project_id, reporting_manager_id
#             FROM project_assignments
#         """)
#         assignments = [dict(row) for row in cursor.fetchall()]
        
#         conn.close()
        
#         return jsonify({
#             "super_admin": dict(super_admin),
#             "projects": projects,
#             "users": [dict(row) for row in users_data],
#             "assignments": assignments
#         }), 200
        
#     except Exception as e:
#         logger.exception("get_user_hierarchy failed")
#         return jsonify({"error": str(e)}), 500


# ADD THIS ENDPOINT to your main.py

@app.route("/api/admin/user-hierarchy", methods=["GET"])
@csrf.exempt
@admin_required
def get_user_hierarchy():
    """
    Build professional user hierarchy:
    Super Admin -> Projects -> Team Leaders -> Team Members
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get all users
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role, ut.id as user_type_id
            FROM users u 
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE COALESCE(u.is_system, 0) != 1
            ORDER BY u.username
        ''')
        all_users = [dict(r) for r in cursor.fetchall()]

        # Find super admin
        super_admin_user = None
        for u in all_users:
            role = (u.get('user_role') or '').lower()
            if 'admin' in role:
                super_admin_user = u
                break

        # Get all projects with team structure
        cursor.execute('''
            SELECT p.id, p.title, p.status, p.progress, p.deadline, p.description,
                   p.created_by_id,
                   (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count,
                   (SELECT COUNT(*) FROM tasks WHERE project_id = p.id) as task_count,
                   (SELECT COUNT(*) FROM tasks WHERE project_id = p.id AND status = 'Completed') as completed_tasks
            FROM projects p
            ORDER BY p.title
        ''')
        all_projects = [dict(r) for r in cursor.fetchall()]

        # Build user map
        user_map = {u['id']: u for u in all_users}

        # Build project nodes
        project_nodes = []
        for proj in all_projects:
            proj_id = proj['id']
            creator_id = proj.get('created_by_id')
            creator = user_map.get(creator_id)

            # Get milestones for this project
            cursor.execute('''
                SELECT id, title, status, due_date as deadline
                FROM milestones
                WHERE project_id = %s
                ORDER BY due_date ASC
            ''', (proj_id,))
            milestones_raw = [dict(r) for r in cursor.fetchall()]
            
            milestones = []
            for ms in milestones_raw:
                ms['deadline'] = ms['deadline'].isoformat() if ms.get('deadline') else None
                milestones.append(ms)

            # Get all assigned members with reporting manager information
            cursor.execute('''
                SELECT u.id, u.username, u.email, ut.user_role, pa.reporting_manager_id,
                (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id) as task_count,
                (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id AND status = 'Completed') as completed_tasks
                FROM users u
                JOIN project_assignments pa ON u.id = pa.user_id
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                WHERE pa.project_id = %s
                ORDER BY CASE WHEN pa.reporting_manager_id IS NULL THEN 0 ELSE 1 END, u.username
            ''', (proj_id, proj_id, proj_id))
            members_raw = [dict(r) for r in cursor.fetchall()]

            # Build a map of members by ID for easy lookup
            members_by_id = {}
            coordinators = []
            team_members_flat = []  # Flat list

            # Fetch all tasks for this project
            cursor.execute('''
                SELECT id, title, status, priority, deadline, assigned_to_id, milestone_id
                FROM tasks
                WHERE project_id = %s
                ORDER BY CASE WHEN status = 'Completed' THEN 1 ELSE 0 END, created_at DESC
            ''', (proj_id,))
            proj_tasks_raw = [dict(t) for t in cursor.fetchall()]

            # Group tasks by assigned user
            tasks_by_user = {}
            for t in proj_tasks_raw:
                uid = t['assigned_to_id']
                if uid not in tasks_by_user:
                    tasks_by_user[uid] = []
                if t.get('deadline'):
                    t['deadline'] = t['deadline'].isoformat()
                tasks_by_user[uid].append(t)

            for m in members_raw:
                role = (m.get('user_role') or '').lower()
                is_coordinator = any(k in role for k in ['coordinator', 'manager', 'admin', 'leader'])
                
                # Group member's tasks by milestone
                member_tasks = tasks_by_user.get(m['id'], [])
                member_milestones = []
                
                tasks_by_milestone = {}
                no_milestone_tasks = []
                for t in member_tasks:
                    mid = t.get('milestone_id')
                    if mid:
                        if mid not in tasks_by_milestone:
                            tasks_by_milestone[mid] = []
                        tasks_by_milestone[mid].append(t)
                    else:
                        no_milestone_tasks.append(t)
                
                for ms in milestones:
                    if ms['id'] in tasks_by_milestone:
                        member_milestones.append({
                            'id': ms['id'],
                            'title': ms['title'],
                            'status': ms['status'],
                            'deadline': ms['deadline'],
                            'tasks': tasks_by_milestone[ms['id']]
                        })

                member_data = {
                    'id': m['id'],
                    'name': m['username'],
                    'email': m.get('email'),
                    'role': m.get('user_role') or 'Team Member',
                    'task_count': m.get('task_count', 0),
                    'completed_tasks': m.get('completed_tasks', 0),
                    'reporting_manager_id': m.get('reporting_manager_id'),
                    'milestones': member_milestones,
                    'tasks': no_milestone_tasks,
                    'team_members': []  # For nested team members
                }

                members_by_id[m['id']] = member_data

                if is_coordinator or m['id'] == creator_id:
                    coordinators.append(member_data)
                else:
                    team_members_flat.append(member_data)

            # If creator is not in coordinators, add them
            if creator and creator_id not in [c['id'] for c in coordinators]:
                creator_member = {
                    'id': creator['id'],
                    'name': creator['username'],
                    'email': creator.get('email'),
                    'role': 'Team Leader',
                    'task_count': 0,
                    'completed_tasks': 0,
                    'reporting_manager_id': None,
                    'team_members': []
                }
                coordinators.insert(0, creator_member)
                members_by_id[creator['id']] = creator_member

            # Build hierarchical structure: Employees -> Team Members
            # Employees are people with coordinator/manager/team lead role
            # Team Members are assigned under employees
            
            employees = []
            team_members_unassigned = []
            
            for member in members_raw:
                role = (member.get('user_role') or '').lower()
                is_employee = any(k in role for k in ['employee', 'officer', 'coordinator', 'manager', 'leader', 'team lead'])
                
                member_data_full = members_by_id.get(member['id'])
                if member_data_full:
                    if is_employee or member['id'] == creator_id:
                        employees.append(member_data_full)
                    else:
                        team_members_unassigned.append(member_data_full)
            
            # Nest team members under their reporting managers (employees)
            for tm in team_members_unassigned:
                reporting_mgr_id = tm.get('reporting_manager_id')
                if reporting_mgr_id and reporting_mgr_id in members_by_id:
                    # Add to employee's team_members
                    members_by_id[reporting_mgr_id]['team_members'].append(tm)
                else:
                    # Add to top level team members
                    pass

            task_total = proj.get('task_count') or 0
            task_completed = proj.get('completed_tasks') or 0
            progress_pct = round((task_completed / task_total * 100), 1) if task_total > 0 else 0

            project_node = {
                'id': f'project-{proj_id}',
                'project_id': proj_id,
                'name': proj['title'],
                'type': 'project',
                'status': proj.get('status') or 'Active',
                'progress': progress_pct,
                'deadline': proj['deadline'].isoformat() if proj.get('deadline') else None,
                'description': proj.get('description'),
                'team_count': proj.get('team_count') or 0,
                'task_count': task_total,
                'completed_tasks': task_completed,
                'milestones': milestones,
                'milestone_count': len(milestones),
                'employees': employees,  # EMPLOYEES (Previously coordinators)
                'team_members': team_members_unassigned   # UNASSIGNED TEAM MEMBERS
            }
            project_nodes.append(project_node)

        # Build employees section for full organization view
        employees_list = []
        for u in all_users:
            role = (u.get('user_role') or '').lower()
            if 'admin' in role or 'super' in role:
                continue
            
            uid = u['id']
            # Basic stats for global employee view
            cursor.execute('SELECT COUNT(*) as count FROM project_assignments WHERE user_id = %s', (uid,))
            p_count = cursor.fetchone()['count']
            cursor.execute('SELECT COUNT(*) as count FROM project_assignments WHERE reporting_manager_id = %s', (uid,))
            tm_count = cursor.fetchone()['count']
            
            employees_list.append({
                'user_id': uid,
                'name': u['username'],
                'role': u.get('user_role') or 'Employee',
                'projects_count': p_count,
                'team_members_count': tm_count,
                'icon': 'fas fa-user-tie' if 'coordinator' in role or 'manager' in role else 'fas fa-user'
            })

        # Build final tree
        tree = {
            'super_admin': {
                'id': 'super-admin',
                'name': super_admin_user['username'] if super_admin_user else 'Super Admin',
                'email': super_admin_user.get('email') if super_admin_user else None,
                'role': 'Full Access',
                'type': 'super_admin'
            },
            'projects': project_nodes,
            'employees': employees_list,
            'summary': {
                'total_projects': len(all_projects),
                'total_users': len(all_users),
                'total_employees': len(employees_list),
                'total_tasks': sum(p.get('task_count') or 0 for p in project_nodes)
            }
        }

        conn.close()
        return jsonify(tree), 200

    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.exception(f'get_user_hierarchy failed: {e}')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/super-admin/details", methods=["GET"])
@csrf.exempt
@admin_required
def get_super_admin_details():
    """
    Get Super Admin details - all employees with their projects and team members
    This is shown when clicking on Super Admin in the hierarchy
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get all non-admin users (employees/coordinators)
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE COALESCE(u.is_system, 0) != 1
            AND (ut.user_role NOT LIKE '%super admin%' AND ut.user_role NOT LIKE '%system administrator%')
            ORDER BY
                CASE
                    WHEN LOWER(ut.user_role) LIKE '%coordinator%' OR LOWER(ut.user_role) LIKE '%manager%' THEN 0
                    ELSE 1
                END,
                u.username
        ''')
        employees = [dict(r) for r in cursor.fetchall()]
        logger.info(f"[v0] Found {len(employees)} employees under Super Admin")

        # Build employee data with their projects and team members
        employee_data = []
        
        for emp in employees:
            emp_id = emp['id']
            emp_name = emp['username']
            
            # Get projects where this employee is the creator/coordinator
            cursor.execute('''
                SELECT p.id, p.title, p.status, p.progress, p.deadline, p.description,
                       (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count
                FROM projects p
                WHERE p.created_by_id = %s
                ORDER BY p.title
            ''', (emp_id,))
            created_projects = [dict(r) for r in cursor.fetchall()]
            
            # Get projects where employee is assigned as member
            cursor.execute('''
                SELECT DISTINCT p.id, p.title, p.status, p.progress, p.deadline, p.description,
                       (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count
                FROM projects p
                JOIN project_assignments pa ON p.id = pa.project_id
                WHERE pa.user_id = %s AND p.created_by_id != %s
                ORDER BY p.title
            ''', (emp_id, emp_id))
            assigned_projects = [dict(r) for r in cursor.fetchall()]
            
            # Merge and deduplicate projects
            all_projects = {p['id']: p for p in created_projects}
            for p in assigned_projects:
                if p['id'] not in all_projects:
                    all_projects[p['id']] = p
            
            projects = list(all_projects.values())
            
            # For each project, get team members
            project_data = []
            for proj in projects:
                proj_id = proj['id']
                
                # Get team members for this project
                cursor.execute('''
                    SELECT u.id, u.username, u.email, ut.user_role,
                           (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id) as task_count
                    FROM users u
                    JOIN project_assignments pa ON u.id = pa.user_id
                    LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                    WHERE pa.project_id = %s AND u.id != %s
                    ORDER BY u.username
                ''', (proj_id, proj_id, emp_id))
                team_members = [dict(r) for r in cursor.fetchall()]
                
                project_data.append({
                    'id': proj['id'],
                    'title': proj['title'],
                    'status': proj.get('status'),
                    'progress': proj.get('progress', 0),
                    'deadline': proj['deadline'].isoformat() if proj.get('deadline') else None,
                    'description': proj.get('description'),
                    'team_count': proj.get('team_count', 0),
                    'team_members': [
                        {
                            'id': tm['id'],
                            'username': tm['username'],
                            'email': tm.get('email'),
                            'role': tm.get('user_role', 'Team Member'),
                            'task_count': tm.get('task_count', 0)
                        }
                        for tm in team_members
                    ]
                })
            
            # Determine if user is coordinator/admin or regular employee
            role = emp.get('user_role') or ''
            role_lower = role.lower()
            is_coordinator = any(keyword in role_lower for keyword in ['coordinator', 'manager', 'admin', 'project coordinator'])
            
            employee_data.append({
                'id': emp['id'],
                'username': emp['username'],
                'email': emp.get('email'),
                'role': emp.get('user_role', 'Employee'),
                'is_coordinator': is_coordinator,
                'projects_count': len(projects),
                'projects': project_data
            })

        conn.close()

        return jsonify({
            'super_admin': {
                'name': 'Super Admin',
                'role': 'Full Access - System Administrator',
                'total_employees': len(employee_data),
                'total_projects': sum(len(emp['projects']) for emp in employee_data)
            },
            'employees': employee_data
        }), 200
    except Exception as e:
        logger.error(f'Error getting super admin details: {e}')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/employee/<int:employee_id>/details", methods=["GET"])
@csrf.exempt
@admin_required
def get_employee_details(employee_id):
    """
    Get detailed information about an employee including:
    - Employee info
    - All projects (created by them and assigned to them)
    - Team members working on each project
    - Tasks for each team member
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get employee info
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.phone, u.department, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (employee_id,))
        
        employee = cursor.fetchone()
        if not employee:
            conn.close()
            return jsonify({'error': 'Employee not found'}), 404
        
        employee = dict(employee)
        
        # Get projects created by this employee
        cursor.execute('''
            SELECT p.id, p.title, p.status, p.progress, p.deadline, p.description,
                   (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count
            FROM projects p
            WHERE p.created_by_id = %s
            ORDER BY p.title
        ''', (employee_id,))
        created_projects = [dict(r) for r in cursor.fetchall()]
        
        # Get projects assigned to this employee (where they are a team member)
        cursor.execute('''
            SELECT DISTINCT p.id, p.title, p.status, p.progress, p.deadline, p.description,
                   (SELECT COUNT(*) FROM project_assignments WHERE project_id = p.id) as team_count
            FROM projects p
            JOIN project_assignments pa ON p.id = pa.project_id
            WHERE pa.user_id = %s AND p.created_by_id != %s
            ORDER BY p.title
        ''', (employee_id, employee_id))
        assigned_projects = [dict(r) for r in cursor.fetchall()]
        
        # Merge projects
        all_projects = {p['id']: p for p in created_projects}
        for p in assigned_projects:
            if p['id'] not in all_projects:
                all_projects[p['id']] = p
        
        # Build project details with team members
        project_details = []
        for proj in all_projects.values():
            proj_id = proj['id']
            
            # Get team members for this project
            cursor.execute('''
                SELECT u.id, u.username, u.email, ut.user_role
                FROM users u
                JOIN project_assignments pa ON u.id = pa.user_id
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                WHERE pa.project_id = %s AND u.id != %s
                ORDER BY u.username
            ''', (proj_id, employee_id))
            team_members = [dict(r) for r in cursor.fetchall()]
            
            # Get tasks for each team member in this project
            for member in team_members:
                cursor.execute('''
                    SELECT id, title, status, priority, deadline
                    FROM tasks
                    WHERE project_id = %s AND assigned_to_id = %s
                    ORDER BY created_at DESC
                ''', (proj_id, member['id']))
                member['tasks'] = [dict(r) for r in cursor.fetchall()]
            
            project_details.append({
                'id': proj_id,
                'title': proj['title'],
                'status': proj.get('status'),
                'progress': proj.get('progress', 0),
                'deadline': proj['deadline'].isoformat() if proj.get('deadline') else None,
                'description': proj.get('description'),
                'team_count': proj.get('team_count', 0),
                'team_members': team_members
            })

        conn.close()
        
        return jsonify({
            'employee': {
                'id': employee['id'],
                'username': employee['username'],
                'email': employee['email'],
                'phone': employee.get('phone'),
                'department': employee.get('department'),
                'role': employee.get('user_role')
            },
            'projects': project_details,
            'total_projects': len(project_details),
            'total_team_members': sum(len(p.get('team_members', [])) for p in project_details)
        }), 200
        
    except Exception as e:
        logger.error(f'Error getting employee details: {e}')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/coordinators/<int:coordinator_id>/details", methods=["GET"])
@csrf.exempt
@admin_required
def get_coordinator_details(coordinator_id):
    """
    Get detailed information about a project coordinator including:
    - Coordinator info
    - Assigned projects
    - Team members under this coordinator
    """
    try:
        # Input validation
        if not coordinator_id or coordinator_id <= 0:
            return jsonify({'error': 'Invalid coordinator ID'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get coordinator info
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (coordinator_id,))
        
        coordinator_row = cursor.fetchone()
        if not coordinator_row:
            conn.close()
            return jsonify({'error': 'Coordinator not found'}), 404

        # Convert Row to dict safely
        try:
            coordinator = dict(coordinator_row) if hasattr(coordinator_row, 'keys') else {
                'id': coordinator_row[0], 
                'username': coordinator_row[1], 
                'email': coordinator_row[2], 
                'user_role': coordinator_row[3]
            }
        except Exception as e:
            logger.exception(f'Error converting coordinator row to dict for id={coordinator_id}')
            conn.close()
            return jsonify({'error': 'Invalid database response format'}), 500

        # Get projects created by this coordinator
        try:
            cursor.execute('''
                SELECT DISTINCT p.id, p.title, p.status, p.deadline, p.description,
                       COUNT(DISTINCT pa2.user_id) as team_count
                FROM projects p
                LEFT JOIN project_assignments pa2 ON p.id = pa2.project_id
                WHERE p.created_by_id = %s
                GROUP BY p.id, p.title, p.status, p.deadline, p.description
                ORDER BY p.title
            ''', (coordinator_id,))
            created_projects_raw = cursor.fetchall()
            created_projects = {}
            for r in created_projects_raw:
                try:
                    pd = dict(r) if hasattr(r, 'keys') else {
                        'id': r[0], 'title': r[1], 'status': r[2],
                        'deadline': r[3], 'description': r[4], 'team_count': r[5]
                    }
                    created_projects[pd['id']] = pd
                except Exception as e:
                    logger.exception(f'Error processing created project row for coordinator {coordinator_id}')
                    continue
        except Exception as e:
            logger.exception(f'Error fetching created projects for coordinator {coordinator_id}')
            created_projects = {}

        # Also get projects where coordinator is assigned as a team member (assigned by Super Admin)
        try:
            cursor.execute('''
                SELECT DISTINCT p.id, p.title, p.status, p.deadline, p.description,
                       COUNT(DISTINCT pa2.user_id) as team_count
                FROM projects p
                JOIN project_assignments pa ON p.id = pa.project_id AND pa.user_id = %s
                LEFT JOIN project_assignments pa2 ON p.id = pa2.project_id
                WHERE p.created_by_id != %s
                GROUP BY p.id, p.title, p.status, p.deadline, p.description
                ORDER BY p.title
            ''', (coordinator_id, coordinator_id))
            assigned_projects_raw = cursor.fetchall()
            for r in assigned_projects_raw:
                try:
                    pd = dict(r) if hasattr(r, 'keys') else {
                        'id': r[0], 'title': r[1], 'status': r[2],
                        'deadline': r[3], 'description': r[4], 'team_count': r[5]
                    }
                    if pd['id'] not in created_projects:
                        created_projects[pd['id']] = pd
                except Exception as e:
                    logger.exception(f'Error processing assigned project row for coordinator {coordinator_id}')
                    continue
        except Exception as e:
            logger.exception(f'Error fetching assigned projects for coordinator {coordinator_id}')

        projects = list(created_projects.values())
        logger.info(f'[Coordinator] Found {len(projects)} total projects for coordinator {coordinator_id}')

        # For each project, get team members
        projects_with_members = []
        for proj in projects:
            proj_id = proj['id']
            try:
                cursor.execute('''
                    SELECT u.id, u.username, u.email, ut.user_role,
                           (SELECT COUNT(*) FROM tasks WHERE project_id = %s AND assigned_to_id = u.id) as task_count
                    FROM users u
                    JOIN project_assignments pa ON u.id = pa.user_id
                    LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                    WHERE pa.project_id = %s AND u.id != %s
                    ORDER BY u.username
                ''', (proj_id, proj_id, coordinator_id))
                proj_members_raw = cursor.fetchall()
                proj_members = []
                for r in proj_members_raw:
                    try:
                        md = dict(r) if hasattr(r, 'keys') else {
                            'id': r[0], 'username': r[1], 'email': r[2], 'user_role': r[3], 'task_count': r[4]
                        }
                        proj_members.append({
                            'id': md['id'],
                            'username': md['username'],
                            'email': md.get('email'),
                            'role': md.get('user_role') or 'Team Member',
                            'task_count': md.get('task_count', 0)
                        })
                    except Exception:
                        continue
            except Exception as e:
                logger.exception(f'Error fetching team members for project {proj_id}')
                proj_members = []

            projects_with_members.append({
                'id': proj['id'],
                'title': proj['title'],
                'status': proj.get('status'),
                'deadline': proj['deadline'].isoformat() if proj.get('deadline') else None,
                'description': proj.get('description'),
                'team_count': proj.get('team_count', 0),
                'team_members': proj_members
            })

        # Get all team members across all coordinator's projects
        try:
            cursor.execute('''
                SELECT DISTINCT u.id, u.username, u.email, ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                LEFT JOIN project_assignments pa ON u.id = pa.user_id
                WHERE pa.project_id IN (
                    SELECT p.id FROM projects p
                    WHERE p.created_by_id = %s
                    UNION
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                )
                AND u.id != %s
                ORDER BY u.username
            ''', (coordinator_id, coordinator_id, coordinator_id))
            team_members_raw = cursor.fetchall()
            team_members = []
            for r in team_members_raw:
                try:
                    member_dict = dict(r) if hasattr(r, 'keys') else {
                        'id': r[0], 'username': r[1], 'email': r[2], 'user_role': r[3]
                    }
                    team_members.append(member_dict)
                except Exception as e:
                    logger.exception(f'Error processing team member row for coordinator {coordinator_id}')
                    continue
        except Exception as e:
            logger.exception(f'Error fetching team members for coordinator {coordinator_id}')
            team_members = []
        
        # Format team members
        team_members_list = [
            {
                'id': m['id'],
                'username': m['username'],
                'email': m['email'],
                'role': m.get('user_role') or 'Team Member'
            }
            for m in team_members
        ]

        conn.close()
        
        return jsonify({
            'name': coordinator.get('username', 'Unknown'),
            'email': coordinator.get('email'),
            'role': coordinator.get('user_role') or 'Project Coordinator',
            'projects': projects_with_members,
            'team_members': team_members_list
        }), 200
    except Exception as e:
        logger.exception(f'Error getting coordinator details for id={coordinator_id}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/admin/projects/<int:project_id>/details", methods=["GET"])
@csrf.exempt
@admin_required
def get_project_details(project_id):
    """
    Get project details with assigned team members and available team members
    """
    try:
        # Input validation
        if not project_id or project_id <= 0:
            return jsonify({'error': 'Invalid project ID'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get project info
        cursor.execute('''
            SELECT p.id, p.title, p.status, p.deadline, p.description,
                   u.username as coordinator_name, u.id as coordinator_id
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            WHERE p.id = %s
        ''', (project_id,))
        
        project_result = cursor.fetchone()
        if not project_result:
            conn.close()
            return jsonify({'error': 'Project not found'}), 404

        # Safely convert to dict
        try:
            project = dict(project_result) if hasattr(project_result, 'keys') else {
                'id': project_result[0], 'title': project_result[1], 'status': project_result[2],
                'deadline': project_result[3], 'description': project_result[4],
                'coordinator_name': project_result[5], 'coordinator_id': project_result[6]
            }
        except Exception as e:
            logger.exception(f'Error converting project row to dict for id={project_id}')
            conn.close()
            return jsonify({'error': 'Invalid database response format'}), 500

        # Get assigned team members
        assigned_members = []
        try:
            cursor.execute('''
                SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                JOIN project_assignments pa ON u.id = pa.user_id
                WHERE pa.project_id = %s AND u.username != 'Super Admin'
                ORDER BY u.username
            ''', (project_id,))
            assigned_members_raw = cursor.fetchall()
            for r in assigned_members_raw:
                try:
                    member_dict = dict(r) if hasattr(r, 'keys') else {
                        'id': r[0], 'username': r[1], 'email': r[2], 'user_type_id': r[3], 'user_role': r[4]
                    }
                    assigned_members.append(member_dict)
                except Exception as e:
                    logger.exception(f'Error processing assigned member row for project {project_id}')
                    continue
        except Exception as e:
            logger.exception(f'Error fetching assigned members for project {project_id}')
        # Get all team members NOT assigned to this project (available for addition)
        available_members = []
        try:
            cursor.execute('''
                SELECT DISTINCT u.id, u.username, u.email, u.user_type_id, ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                WHERE u.username != 'Super Admin' AND u.id NOT IN (
                    SELECT user_id FROM project_assignments WHERE project_id = %s
                )
                ORDER BY u.username
            ''', (project_id,))
            available_members_raw = cursor.fetchall()
            for r in available_members_raw:
                try:
                    member_dict = dict(r) if hasattr(r, 'keys') else {
                        'id': r[0], 'username': r[1], 'email': r[2], 'user_type_id': r[3], 'user_role': r[4]
                    }
                    available_members.append(member_dict)
                except Exception as e:
                    logger.exception(f'Error processing available member row for project {project_id}')
                    continue
        except Exception as e:
            logger.exception(f'Error fetching available members for project {project_id}')

        # Get milestones
        milestones = []
        try:
            cursor.execute('SELECT id, title, description, status, due_date FROM milestones WHERE project_id = %s ORDER BY due_date ASC', (project_id,))
            for m in cursor.fetchall():
                row = dict(m) if hasattr(m, 'keys') else {'id': m[0], 'title': m[1], 'description': m[2], 'status': m[3], 'due_date': m[4]}
                milestones.append({
                    'id': row['id'],
                    'title': row['title'],
                    'description': row.get('description'),
                    'status': row.get('status', 'Pending'),
                    'deadline': row['due_date'].isoformat() if row.get('due_date') else None
                })
        except Exception:
            logger.exception(f'Error fetching milestones for project {project_id}')

        # Get tasks
        tasks = []
        try:
            cursor.execute('''
                SELECT t.id, t.title, t.description, t.status, t.priority, t.deadline, u.username as assigned_to_name
                FROM tasks t
                LEFT JOIN users u ON t.assigned_to_id = u.id
                WHERE t.project_id = %s
                ORDER BY t.created_at DESC
            ''', (project_id,))
            for t in cursor.fetchall():
                if hasattr(t, 'keys'):
                    row = dict(t)
                else:
                    row = {
                        'id': t[0], 'title': t[1], 'description': t[2], 'status': t[3], 
                        'priority': t[4], 'deadline': t[5], 'assigned_to_name': t[6]
                    }
                tasks.append({
                    'id': row['id'],
                    'title': row['title'],
                    'description': row.get('description'),
                    'status': row.get('status'),
                    'priority': row.get('priority'),
                    'assigned_to_name': row.get('assigned_to_name'),
                    'deadline': row['deadline'].isoformat() if row.get('deadline') else None
                })
        except Exception:
            logger.exception(f'Error fetching tasks for project {project_id}')

        conn.close()
        
        return jsonify({
            'id': project['id'],
            'title': project.get('title', 'Unknown'),
            'status': project.get('status', 'Unknown'),
            'deadline': project['deadline'].isoformat() if project.get('deadline') else None,
            'description': project.get('description'),
            'coordinator_name': project.get('coordinator_name'),
            'coordinator_id': project.get('coordinator_id'),
            'milestones': milestones,
            'tasks': tasks,
            'assigned_members': [
                {
                    'id': m['id'],
                    'username': m['username'],
                    'email': m['email'],
                    'role': m.get('user_role'),
                    'user_type_id': m.get('user_type_id')
                }
                for m in assigned_members
            ],
            'available_members': [
                {
                    'id': m['id'],
                    'username': m['username'],
                    'email': m['email'],
                    'role': m.get('user_role'),
                    'user_type_id': m.get('user_type_id')
                }
                for m in available_members
            ],
            'team_count': len(assigned_members)
        }), 200
    except Exception as e:
        logger.exception(f'Error getting project details for id={project_id}')
        return jsonify({'error': 'Internal server error'}), 500




@app.route("/api/admin/team-members/<int:member_id>/details", methods=["GET"])
@csrf.exempt
@admin_required
def get_team_member_details(member_id):
    """
    Get detailed information about a team member including:
    - Member info
    - Assigned project
    - Reporting coordinator
    - Assigned tasks
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get team member info
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (member_id,))
        
        member = cursor.fetchone()
        if not member:
            conn.close()
            return jsonify({'error': 'Team member not found'}), 404

        member = dict(member)

        # Get reporting coordinator (project creator or assignment manager)
        cursor.execute('''
            SELECT DISTINCT u.username
            FROM users u
            WHERE u.id IN (
                SELECT DISTINCT p.created_by_id FROM projects p
                WHERE p.id IN (
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                )
            )
            LIMIT 1
        ''', (member_id,))
        
        coordinator_result = cursor.fetchone()
        coordinator_name = coordinator_result['username'] if coordinator_result else None

        # Get assigned projects
        cursor.execute('''
            SELECT DISTINCT p.id, p.title, p.status, p.deadline, p.description
            FROM projects p
            JOIN project_assignments pa ON p.id = pa.project_id
            WHERE pa.user_id = %s
            ORDER BY p.title
        ''', (member_id,))
        
        projects_raw = cursor.fetchall()
        projects_list = []
        for r in projects_raw:
            try:
                p_dict = dict(r) if hasattr(r, 'keys') else {
                    'id': r[0], 'title': r[1], 'status': r[2],
                    'deadline': r[3], 'description': r[4]
                }
                projects_list.append({
                    'id': p_dict['id'],
                    'title': p_dict['title'],
                    'status': p_dict['status'],
                    'deadline': p_dict['deadline'].isoformat() if p_dict.get('deadline') else None,
                    'description': p_dict.get('description')
                })
            except Exception:
                continue

        # Get assigned tasks (already has tasks)
        # Get assigned tasks
        cursor.execute('''
            SELECT id, title, status, priority, deadline
            FROM tasks
            WHERE assigned_to_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        ''', (member_id,))
        
        tasks = [dict(r) for r in cursor.fetchall()]

        conn.close()
        return jsonify({
            'name': member['username'],
            'email': member.get('email'),
            'role': member.get('user_role') or 'Team Member',
            'coordinator_name': coordinator_name,
            'projects': projects_list,
            'tasks': [

                {
                    'id': t['id'],
                    'title': t['title'],
                    'status': t['status'],
                    'priority': t.get('priority'),
                    'deadline': t.get('deadline').isoformat() if t.get('deadline') else None
                }
                for t in tasks
            ]
        }), 200
    except Exception as e:
        logger.error(f'Error getting team member details: {e}')
        return jsonify({'error': str(e)}), 500


@app.route("/api/dashboard/live-progress", methods=["GET"])
@csrf.exempt
@login_required
def get_live_dashboard_progress_enhanced():
    """
    Enhance live progress endpoint: include overdue_tasks, pending_tasks counts per project
    This wraps existing logic but makes per-project overdue/pending counts explicit.
    """
    try:
        user_id = get_current_user_id()
        is_admin = session.get('admin') or session.get('user_type') == 'admin'

        conn = get_db_connection()
        cursor = conn.cursor()

        if is_admin:
            cursor.execute('''
                SELECT 
                    p.id,
                    p.title,
                    p.description,
                    p.status,
                    p.progress,
                    p.deadline,
                    p.reporting_time,
                    p.created_at,
                    p.updated_at,
                    u.username as creator_name,
                    COUNT(DISTINCT t.id) as total_tasks,
                    SUM(CASE WHEN t.status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                    COUNT(DISTINCT m.id) as total_milestones,
                    SUM(CASE WHEN m.status = 'Completed' THEN 1 ELSE 0 END) as completed_milestones,
                    COUNT(DISTINCT pa.user_id) as team_size
                FROM projects p
                LEFT JOIN users u ON p.created_by_id = u.id
                LEFT JOIN tasks t ON p.id = t.project_id
                LEFT JOIN milestones m ON p.id = m.project_id
                LEFT JOIN project_assignments pa ON p.id = pa.project_id
                WHERE p.status != 'Completed'
                GROUP BY p.id, u.username
                ORDER BY p.updated_at DESC
            ''')
            raw_projects = cursor.fetchall()
        else:
            cursor.execute(
                '''
                SELECT DISTINCT
                    p.id,
                    p.title,
                    p.description,
                    p.status,
                    p.progress,
                    p.deadline,
                    p.reporting_time,
                    p.created_at,
                    p.updated_at,
                    u.username as creator_name,
                    COUNT(DISTINCT t.id) as total_tasks,
                    SUM(CASE WHEN t.status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                    COUNT(DISTINCT m.id) as total_milestones,
                    SUM(CASE WHEN m.status = 'Completed' THEN 1 ELSE 0 END) as completed_milestones,
                    COUNT(DISTINCT pa.user_id) as team_size
                FROM projects p
                LEFT JOIN users u ON p.created_by_id = u.id
                LEFT JOIN tasks t ON p.id = t.project_id
                LEFT JOIN milestones m ON p.id = m.project_id
                LEFT JOIN project_assignments pa ON p.id = pa.project_id
                WHERE (p.created_by_id = %s OR p.id IN (
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                ))
                AND p.status != 'Completed'
                GROUP BY p.id, u.username
                ORDER BY p.updated_at DESC
            ''', (user_id, user_id))
            raw_projects = cursor.fetchall()

        formatted_projects = []
        for project in raw_projects:
            p = dict(project)
            # compute overdue and pending counts
            cursor2 = conn.cursor()
            cursor2.execute(
                "SELECT COUNT(*) as overdue_count FROM tasks WHERE project_id = %s AND deadline < date('now') AND status != 'Completed'",
                (p['id'], ))
            overdue_count = cursor2.fetchone()['overdue_count'] or 0
            cursor2.execute(
                "SELECT COUNT(*) as pending_count FROM tasks WHERE project_id = %s AND status != 'Completed' AND (deadline IS NULL OR deadline >= date('now'))",
                (p['id'], ))
            pending_count = cursor2.fetchone()['pending_count'] or 0

            total_tasks = p.get('total_tasks') or 0
            completed = p.get('completed_tasks') or 0
            milestones_total = p.get('total_milestones') or 0
            milestones_completed = p.get('completed_milestones') or 0

            # health_status
            health_status = 'good' if (
                p.get('progress') or 0) >= 70 else 'warning' if (
                    p.get('progress') or 0) >= 40 else 'danger'

            p.update({
                'overdue_tasks': overdue_count,
                'pending_tasks': pending_count,
                'total_tasks': total_tasks,
                'completed_tasks': completed,
                'total_milestones': milestones_total,
                'completed_milestones': milestones_completed,
                'health_status': health_status
            })
            formatted_projects.append(p)

        # average progress
        avg_progress = 0
        if formatted_projects:
            avg_progress = round(
                sum(p.get('progress', 0)
                    for p in formatted_projects) / len(formatted_projects), 2)

        conn.close()
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "total_projects": len(formatted_projects),
            "average_progress": avg_progress,
            "projects": formatted_projects
        }), 200
    except Exception as e:
        logger.exception('get_live_dashboard_progress_enhanced failed')
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<int:project_id>/milestones', methods=['GET'])
@csrf.exempt
@login_required
def api_get_project_milestones(project_id):
    """Return milestones for a project (used by admin dashboard project detail)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, title, description, due_date, status, weightage, created_by_id, created_at
            FROM milestones
            WHERE project_id = %s
            ORDER BY created_at DESC
        ''', (project_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        logger.exception('api_get_project_milestones failed')
        return jsonify({'error': str(e)}), 500


@app.route("/api/projects/<int:project_id>/tasks", methods=["GET"])
@csrf.exempt
@login_required
def get_project_tasks(project_id):
    """Get all tasks for a specific project"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT t.id, t.title, t.description, t.status, t.priority, 
                   t.deadline, t.project_id, p.title as project_name,
                   t.assigned_to_id, u.username as assigned_to_name,
                   t.created_by_id, uc.username as created_by_name,
                   t.created_at, t.approval_status, t.completed_at
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN users uc ON t.created_by_id = uc.id
            WHERE t.project_id = %s
            ORDER BY t.created_at DESC
        ''', (project_id, ))

        tasks = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in tasks]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<int:project_id>/create-team-member", methods=["POST"])
@csrf.exempt
@login_required
def create_and_assign_team_member(project_id):
    """Create a new user and assign them to a project"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        # Validation
        if not name or not email or not password:
            return jsonify({'error': 'Name, email, and password are required'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if project exists
        cursor.execute('SELECT id FROM projects WHERE id = %s', (project_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Project not found'}), 404
        
        # Check if email already exists
        cursor.execute('SELECT id FROM users WHERE LOWER(email) = %s', (email.lower(),))
        existing_user = cursor.fetchone()
        
        user_id = None
        if existing_user:
            # User already exists, just assign them to project
            user_id = existing_user['id']
        else:
            # Create new user
            hashed_password = generate_password_hash(password)
            
            # Get employee user type
            cursor.execute('SELECT id FROM usertypes WHERE user_role LIKE %s', ('%employee%',))
            user_type_result = cursor.fetchone()
            user_type_id = user_type_result['id'] if user_type_result else 1
            
            cursor.execute('''
                INSERT INTO users (username, email, password, user_type_id, granted, created_at)
                VALUES (%s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                RETURNING id
            ''', (name, email, hashed_password, user_type_id))
            
            user_result = cursor.fetchone()
            user_id = user_result['id']
        
        # Check if already assigned to this project
        cursor.execute('''
            SELECT id FROM project_assignments
            WHERE project_id = %s AND user_id = %s
        ''', (project_id, user_id))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({'error': 'User already assigned to this project'}), 400
        
        # Assign user to project
        cursor.execute('''
            INSERT INTO project_assignments (project_id, user_id, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        ''', (project_id, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Team member added successfully',
            'user_id': user_id,
            'name': name,
            'email': email
        }), 201
        
    except Exception as e:
        logger.error(f'Error creating team member: {e}')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/milestones", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_milestones():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT m.id, m.title, m.description, m.status, m.due_date,
                   m.project_id, p.title as project_name,
                   m.created_by_id, u.username as created_by_name,
                   m.created_at
            FROM milestones m
            LEFT JOIN projects p ON m.project_id = p.id
            LEFT JOIN users u ON m.created_by_id = u.id
            ORDER BY m.due_date ASC
        ''')

        milestones = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in milestones]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
@csrf.exempt
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/employee/skills", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_skills():
    """Get all skills for the logged-in employee"""
    try:
        user_id = session.get('user_id')
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT id, skill_name, created_at 
            FROM user_skills 
            WHERE user_id = %s
            ORDER BY skill_name
        ''', (user_id, ))

        skills = cursor.fetchall()
        conn.close()

        return jsonify([dict(row) for row in skills]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/skills", methods=["POST"])
@csrf.exempt
@login_required
def add_employee_skill():
    """Add a new skill for the logged-in employee"""
    try:
        data = request.get_json() or {}
        skill_name = (data.get("skill_name") or "").strip()

        if not skill_name:
            return jsonify({"error": "Skill name is required"}), 400

        user_id = session.get('user_id')
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO user_skills (user_id, skill_name)
                VALUES (%s, %s)
                RETURNING id
            ''', (user_id, skill_name))
            skill_id = cursor.fetchone()['id']
            conn.commit()
            conn.close()

            return jsonify({
                "id": skill_id,
                "skill_name": skill_name,
                "message": "Skill added successfully!"
            }), 201
        except psycopg2.IntegrityError:
            conn.close()
            return jsonify({"error": "Skill already exists"}), 409

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/skills/<int:skill_id>", methods=["DELETE"])
@csrf.exempt
@login_required
def delete_employee_skill(skill_id):
    """Delete a skill for the logged-in employee"""
    try:
        user_id = session.get('user_id')
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT id FROM user_skills WHERE id = %s AND user_id = %s',
            (skill_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Skill not found"}), 404

        cursor.execute('DELETE FROM user_skills WHERE id = %s AND user_id = %s',
                       (skill_id, user_id))
        conn.commit()
        conn.close()

        return jsonify({"message": "Skill deleted successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/profile", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_profile():
    """Get profile for the logged-in employee"""
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role,
                   u.phone, u.department, u.bio, u.avatar_url, u.created_at
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (user_id, ))

        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404

        cursor.execute(
            '''
            SELECT skill_name FROM user_skills WHERE user_id = %s ORDER BY skill_name
        ''', (user_id, ))
        skills = [row['skill_name'] for row in cursor.fetchall()]

        # 1. Get Direct User Permissions
        cursor.execute('''
            SELECT module, action, granted FROM user_permissions 
            WHERE user_id = %s ORDER BY module, action
        ''', (user_id, ))
        direct_perms = cursor.fetchall()

        # 2. Get Role-based (UserType) Permissions
        cursor.execute('''
            SELECT module, action, granted FROM usertype_permissions 
            WHERE usertype_id = %s ORDER BY module, action
        ''', (user['user_type_id'], ))
        role_perms = cursor.fetchall()

        conn.close()

        # Merge permissions (Direct takes precedence)
        permissions = {}
        
        # Add role permissions first
        for perm in role_perms:
            module = perm['module']
            if module not in permissions:
                permissions[module] = {}
            permissions[module][perm['action']] = bool(perm['granted'])
            
        # Add direct permissions (overwriting if necessary)
        for perm in direct_perms:
            module = perm['module']
            if module not in permissions:
                permissions[module] = {}
            permissions[module][perm['action']] = bool(perm['granted'])

        profile = dict(user)
        profile['skills'] = skills
        profile['permissions'] = permissions

        return jsonify(profile), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/profile", methods=["PUT"])
@csrf.exempt
@login_required
def update_employee_profile():
    """Update profile for the logged-in employee with validation"""
    try:
        data = request.get_json() or {}
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        phone = data.get("phone", "").strip() if data.get("phone") else None
        department = data.get("department",
                              "").strip() if data.get("department") else None
        bio = data.get("bio", "").strip() if data.get("bio") else None

        if phone and len(phone) > 20:
            return jsonify({"error": "Phone number too long"}), 400
        if department and len(department) > 100:
            return jsonify({"error": "Department name too long"}), 400
        if bio and len(bio) > 500:
            return jsonify({"error": "Bio too long"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            UPDATE users 
            SET phone = %s, department = %s, bio = %s
            WHERE id = %s
        ''', (phone, department, bio, user_id))

        conn.commit()
        conn.close()

        return jsonify({"message": "Profile updated successfully!"}), 200
    except Exception as e:
        print(f"[ERROR] Profile update failed: {str(e)}")
        return jsonify({"error": f"Update failed: {str(e)}"}), 500


@app.route("/api/admin/profile", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_profile():
    """Get admin profile"""
    return jsonify({
        "name": "Super Admin",
        "email": ADMIN_EMAIL,
        "role": "Administrator",
        "department": "Administration",
        "created_at": datetime.now().isoformat()
    }), 200


def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit(
        '.', 1)[1].lower() in ALLOWED_EXTENSIONS


def optimize_image(image_file, max_width=500, max_height=500):
    """
    Optimize and validate uploaded image
    Resize to reasonable dimensions and compress for efficient storage
    Returns: BytesIO object with optimized image bytes
    """
    try:
        img = Image.open(image_file)

        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(
                img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Resize image maintaining aspect ratio
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Save optimized image to BytesIO
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)

        return output
    except Exception as e:
        print(f"Error optimizing image: {str(e)}")
        raise


@app.route("/api/employee/profile/upload-avatar", methods=["POST"])
@csrf.exempt
@login_required
def upload_avatar():
    """Upload and optimize profile avatar"""
    try:
        if 'avatar' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['avatar']
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify({
                "error":
                "Invalid file type. Only PNG, JPG, JPEG, GIF, and WebP are allowed"
            }), 400

        user_id = get_current_user_id()

        # Ensure upload folder exists
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        # Optimize image
        try:
            optimized_image_bytes = optimize_image(file)
        except Exception as e:
            print(f"[ERROR] Failed to optimize image: {str(e)}")
            return jsonify(
                {"error":
                 "Failed to process image. Please try another file."}), 400

        # Generate secure filename
        filename = f"{user_id}_{secrets.token_hex(8)}.jpg"
        file_path = os.path.join(UPLOAD_FOLDER, filename)

        try:
            # Save optimized image bytes to file
            with open(file_path, 'wb') as f:
                f.write(optimized_image_bytes.getvalue())
        except Exception as save_error:
            print(f"[ERROR] Error saving avatar: {str(save_error)}")
            return jsonify({
                "error":
                "Failed to save file to server. Check folder permissions."
            }), 500

        # Update database with new avatar URL
        conn = get_db_connection()
        cursor = conn.cursor()

        avatar_url = f"/uploads/profiles/{filename}"

        try:
            cursor.execute('UPDATE users SET avatar_url = %s WHERE id = %s',
                           (avatar_url, user_id))
            conn.commit()
        except psycopg2.OperationalError as db_error:
            # If column doesn't exist, add it
            if "no such column: avatar_url" in str(db_error):
                try:
                    cursor.execute(
                        'ALTER TABLE users ADD COLUMN avatar_url TEXT')
                    conn.commit()
                    cursor.execute(
                        'UPDATE users SET avatar_url = %s WHERE id = %s',
                        (avatar_url, user_id))
                    conn.commit()
                    print(f"[INFO] Added avatar_url column for user {user_id}")
                except Exception as alter_error:
                    conn.close()
                    print(
                        f"[ERROR] Failed to add avatar_url column: {str(alter_error)}"
                    )
                    return jsonify({
                        "error":
                        "Database configuration issue. Please contact administrator."
                    }), 500

        conn.close()

        return jsonify({
            "message": "Profile picture uploaded successfully!",
            "avatar_url": avatar_url
        }), 200

    except Exception as e:
        print(f"[ERROR] Error uploading avatar: {str(e)}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route("/api/employee/profile/avatar", methods=["DELETE"])
@csrf.exempt
@login_required
def delete_avatar():
    """
    Enhanced avatar deletion with proper file cleanup
    """
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT avatar_url FROM users WHERE id = %s',
                       (user_id, ))
        user = cursor.fetchone()

        if not user or not user['avatar_url']:
            conn.close()
            return jsonify({"error": "No profile picture found"}), 404

        # Delete file from storage
        filename = user['avatar_url'].split('/')[-1]
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass

        # Update database
        cursor.execute('UPDATE users SET avatar_url = NULL WHERE id = %s',
                       (user_id, ))
        conn.commit()
        conn.close()

        return jsonify({"message":
                        "Profile picture deleted successfully!"}), 200

    except Exception as e:
        print(f"[v0] Error deleting avatar: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/uploads/profiles/<path:filename>")
@csrf.exempt
def serve_profile_picture(filename):
    """
    Serve profile pictures with proper security
    Validates filename before serving
    """
    try:
        # Security check: only allow alphanumeric and underscores
        if not re.match(r'^[\w\-]+\.jpg$', filename):
            return jsonify({"error": "Invalid file"}), 400

        return send_from_directory(UPLOAD_FOLDER,
                                   filename,
                                   as_attachment=False)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404


@app.route("/api/projects/<int:project_id>/progress", methods=["GET"])
@csrf.exempt
@login_required
def get_project_progress(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Count total tasks
        cursor.execute(
            "SELECT COUNT(*) as total FROM tasks WHERE project_id = %s",
            (project_id, ))
        result = cursor.fetchone()
        total = (dict(result) if hasattr(result, 'keys') else {'total': result[0]})['total'] if result else 0

        # Count completed tasks
        cursor.execute(
            "SELECT COUNT(*) as completed FROM tasks WHERE project_id = %s AND status = 'Completed'",
            (project_id, ))
        result = cursor.fetchone()
        completed = (dict(result) if hasattr(result, 'keys') else {'completed': result[0]})['completed'] if result else 0

        # Avoid division by zero
        progress = 0
        if total > 0:
            progress = int((completed / total) * 100)

        # Save progress in DB
        cursor.execute(
            "UPDATE projects SET progress = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (progress, project_id))
        conn.commit()
        conn.close()

        return jsonify({"project_id": project_id, "progress": progress}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/documents/<int:doc_id>/download", methods=["GET"])
@csrf.exempt
@login_required
def download_document(doc_id):
    """Download a document file with proper error handling"""
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user has access to this document
        cursor.execute(
            '''
            SELECT d.filename, d.original_filename, d.project_id
            FROM documents d
            WHERE d.id = %s AND (
                d.uploaded_by_id = %s OR 
                d.project_id IN (
                    SELECT project_id FROM project_assignments WHERE user_id = %s
                ) OR
                d.project_id IN (
                    SELECT id FROM projects WHERE created_by_id = %s
                )
            )
        ''', (doc_id, user_id, user_id, user_id))

        doc = cursor.fetchone()
        conn.close()

        if not doc:
            return jsonify({"error":
                            "Document not found or access denied"}), 404

        file_path = os.path.join('uploads', 'documents', doc['filename'])

        if not os.path.exists(file_path):
            print(f"[ERROR] File not found at path: {file_path}")
            return jsonify({"error": "File not found on server"}), 404

        # Log download activity
        log_activity(user_id,
                     'document_downloaded',
                     f'Downloaded document: {doc["original_filename"]}',
                     project_id=doc['project_id'])

        return send_from_directory('uploads/documents',
                                   doc['filename'],
                                   as_attachment=True,
                                   download_name=doc['original_filename'])

    except Exception as e:
        print(f"[ERROR] Document download failed: {str(e)}")
        return jsonify({"error": f"Download failed: {str(e)}"}), 500


@app.route("/api/admin/documents/<int:doc_id>/download", methods=["GET"])
@csrf.exempt
@admin_required
def admin_download_document(doc_id):
    """Admin download a document file"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT filename, original_filename, project_id
            FROM documents
            WHERE id = %s
        ''', (doc_id, ))

        doc = cursor.fetchone()
        conn.close()

        if not doc:
            return jsonify({"error": "Document not found"}), 404

        file_path = os.path.join('uploads', 'documents', doc['filename'])

        if not os.path.exists(file_path):
            print(
                f"[ERROR] Admin document file not found at path: {file_path}")
            return jsonify({"error": "File not found on server"}), 404

        return send_from_directory('uploads/documents',
                                   doc['filename'],
                                   as_attachment=True,
                                   download_name=doc['original_filename'])

    except Exception as e:
        print(f"[ERROR] Admin document download failed: {str(e)}")
        return jsonify({"error": f"Download failed: {str(e)}"}), 500


# Enhanced profile stats endpoint
@app.route("/api/employee/profile/stats", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_profile_stats():
    """Get detailed profile statistics for employee"""
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total projects
        cursor.execute(
            '''
            SELECT COUNT(DISTINCT id) as count FROM projects 
            WHERE created_by_id = %s OR id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            )
        ''', (user_id, user_id))
        result = cursor.fetchone()
        total_projects = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        # Completed tasks
        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM tasks 
            WHERE (assigned_to_id = %s OR created_by_id = %s) AND status = 'Completed'
        ''', (user_id, user_id))
        result = cursor.fetchone()
        completed_tasks = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        # Pending tasks
        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM tasks 
            WHERE (assigned_to_id = %s OR created_by_id = %s) 
            AND status != 'Completed'
        ''', (user_id, user_id))
        result = cursor.fetchone()
        pending_tasks = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        # Total milestones
        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM milestones m
            WHERE m.project_id IN (
                SELECT id FROM projects WHERE created_by_id = %s
                OR id IN (SELECT project_id FROM project_assignments WHERE user_id = %s)
            )
        ''', (user_id, user_id))
        result = cursor.fetchone()
        total_milestones = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        # Completed milestones
        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM milestones m
            WHERE m.status = 'Completed' AND m.project_id IN (
                SELECT id FROM projects WHERE created_by_id = %s
                OR id IN (SELECT project_id FROM project_assignments WHERE user_id = %s)
            )
        ''', (user_id, user_id))
        result = cursor.fetchone()
        completed_milestones = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        # Documents uploaded
        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM documents WHERE uploaded_by_id = %s
        ''', (user_id, ))
        result = cursor.fetchone()
        documents_uploaded = (dict(result) if hasattr(result, 'keys') else {'count': result[0]})['count'] if result else 0

        conn.close()

        return jsonify({
            "total_projects":
            total_projects,
            "completed_tasks":
            completed_tasks,
            "pending_tasks":
            pending_tasks,
            "total_milestones":
            total_milestones,
            "completed_milestones":
            completed_milestones,
            "documents_uploaded":
            documents_uploaded,
            "completion_rate":
            round((completed_tasks /
                   (completed_tasks + pending_tasks) * 100), 2) if
            (completed_tasks + pending_tasks) > 0 else 0
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/projects/realtime", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_realtime_projects():
    """Get real-time project updates for admin dashboard"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT p.id, p.title, p.description, p.status, p.progress,
                   p.deadline, p.reporting_time, p.created_at, p.updated_at,
                   u.username as creator_name,
                   COUNT(DISTINCT t.id) as total_tasks,
                   SUM(CASE WHEN t.status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                   COUNT(DISTINCT m.id) as total_milestones,
                   SUM(CASE WHEN m.status = 'Completed' THEN 1 ELSE 0 END) as completed_milestones,
                   COUNT(DISTINCT pa.user_id) as team_size
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            LEFT JOIN tasks t ON p.id = t.project_id
            LEFT JOIN milestones m ON p.id = m.project_id
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            WHERE p.status != 'Completed'
            GROUP BY p.id, u.username
            ORDER BY p.updated_at DESC
        ''')

        projects = cursor.fetchall()
        conn.close()

        result = []
        for row in projects:
            project_dict = dict(row)
            project_dict['completed_tasks'] = project_dict.get(
                'completed_tasks') or 0
            project_dict['total_tasks'] = project_dict.get('total_tasks') or 0
            project_dict['completed_milestones'] = project_dict.get(
                'completed_milestones') or 0
            project_dict['total_milestones'] = project_dict.get(
                'total_milestones') or 0
            project_dict['progress'] = project_dict.get('progress') or 0
            result.append(project_dict)

        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] Admin realtime projects error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/projects/<int:project_id>", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_project_detail(project_id):
    """Get detailed project information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT p.id, p.title, p.description, p.status, p.progress, p.deadline, p.reporting_time, 
                   p.created_by_id, p.created_at, p.updated_at, p.completed_at,
                   u.username as creator_name,
                   COUNT(DISTINCT t.id) as total_tasks,
                   COUNT(DISTINCT m.id) as total_milestones
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            LEFT JOIN tasks t ON p.id = t.project_id
            LEFT JOIN milestones m ON p.id = m.project_id
            WHERE p.id = %s
            GROUP BY p.id, p.title, p.description, p.status, p.progress, p.deadline, p.reporting_time, 
                     p.created_by_id, p.created_at, p.updated_at, p.completed_at, u.id, u.username
        ''', (project_id,))
        
        project_row = cursor.fetchone()
        conn.close()

        if not project_row:
            return jsonify({"error": "Project not found"}), 404

        # ✅ Convert PostgreSQL row to dict first
        project = dict(project_row) if hasattr(project_row, 'keys') else {
            'id': project_row[0],
            'title': project_row[1],
            'description': project_row[2],
            'status': project_row[3],
            'progress': project_row[4],
            'deadline': project_row[5],
            'reporting_time': project_row[6],
            'created_by_id': project_row[7],
            'created_at': project_row[8],
            'updated_at': project_row[9],
            'completed_at': project_row[10],
            'creator_name': project_row[11],
            'total_tasks': project_row[12],
            'total_milestones': project_row[13]
        }

        # ✅ Convert PostgreSQL date/time safely
        def format_dt(value):
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, time):
                return value.strftime("%H:%M")
            return value

        project_dict = {
            'id': project['id'],
            'title': project['title'],
            'description': project['description'],
            'status': project['status'],
            'progress': project['progress'],
            'deadline': format_dt(project.get('deadline')),
            'reporting_time': format_dt(project.get('reporting_time')),
            'created_by_id': project['created_by_id'],
            'created_at': format_dt(project.get('created_at')),
            'updated_at': format_dt(project.get('updated_at')),
            'completed_at': format_dt(project.get('completed_at')),
            'creator_name': project.get('creator_name'),
            'total_tasks': project['total_tasks'],
            'total_milestones': project['total_milestones']
        }

        return jsonify(project_dict), 200

    except Exception as e:
        logger.error(f"Error in get_admin_project_detail: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# Update project (admin)
@app.route("/api/admin/projects/<int:project_id>", methods=["PUT"])
@csrf.exempt
@admin_required
def admin_update_project(project_id):
    """Update project fields: title, description, status, deadline"""
    try:
        data = request.get_json() or {}
        title = data.get('title')
        description = data.get('description')
        status = data.get('status')
        deadline = data.get('deadline')  # expected YYYY-MM-DD or empty

        # Minimal validation
        if title is not None and len(title) > 255:
            return jsonify({"error": "Title too long"}), 400
        if description is not None and len(description) > 2000:
            return jsonify({"error": "Description too long"}), 400

        # Validate deadline format if provided
        if deadline:
            try:
                # accept date-only ISO
                datetime.strptime(deadline, '%Y-%m-%d')
            except Exception:
                return jsonify(
                    {"error": "Invalid deadline format. Use YYYY-MM-DD."}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Ensure project exists
        cursor.execute('SELECT id FROM projects WHERE id = %s', (project_id, ))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Project not found"}), 404

        # Build update statement dynamically
        updates = []
        params = []
        if title is not None:
            updates.append('title = %s')
            params.append(title)
        if description is not None:
            updates.append('description = %s')
            params.append(description)
        if status is not None:
            updates.append('status = %s')
            params.append(status)
        if deadline is not None:
            # allow clearing deadline by sending empty string
            updates.append('deadline = %s')
            params.append(deadline if deadline != '' else None)

        if updates:
            params.append(project_id)
            stmt = f"UPDATE projects SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
            cursor.execute(stmt, tuple(params))
            conn.commit()

        # Return updated project summary
        cursor.execute(
            '''
            SELECT p.id, p.title, p.description, p.status, p.progress, p.deadline, u.username as creator_name,
                   (SELECT COUNT(*) FROM project_assignments pa WHERE pa.project_id = p.id) as team_count,
                   (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) as task_count
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            WHERE p.id = %s
        ''', (project_id, ))
        proj = cursor.fetchone()
        conn.close()

        if not proj:
            return jsonify({"error": "Project not found after update"}), 404

        result = dict(proj)
        return jsonify({
            "message": "Project updated successfully",
            "project": result
        }), 200

    except Exception as e:
        print(f"[ERROR] admin_update_project: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/projects/<int:project_id>/add-member", methods=["POST"])
@csrf.exempt
@admin_required
def admin_add_project_member(project_id):
    """Add a member to a project with reporting structure"""
    try:
        data = request.get_json() or {}
        
        # Get user_id from various possible field names
        user_id = data.get('user_id') or data.get('member')
        
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        
        # Convert to int if it's a string
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid user ID format"}), 400
        
        # Get reporting structure
        reporting_manager_id = data.get('reporting_manager_id')
        if reporting_manager_id:
            try:
                reporting_manager_id = int(reporting_manager_id)
            except (ValueError, TypeError):
                reporting_manager_id = None
        
        reports_to_admin = data.get('reports_to_admin', False)
        
        logger.info(f"[ADD_MEMBER] Project: {project_id}, User: {user_id}, ReportsTo: {reporting_manager_id}, ReportsToAdmin: {reports_to_admin}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Lazy Migration: Ensure project_assignments has required columns
        try:
            cursor.execute("ALTER TABLE project_assignments ADD COLUMN IF NOT EXISTS reporting_manager_id INTEGER")
            cursor.execute("ALTER TABLE project_assignments ADD COLUMN IF NOT EXISTS reports_to_admin BOOLEAN DEFAULT FALSE")
            conn.commit()
        except Exception as mig_err:
            logger.warning(f"[ADD_MEMBER] Lazy migration check: {mig_err}")
            conn.rollback()
        
        # Verify project exists
        cursor.execute('SELECT id FROM projects WHERE id = %s', (project_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Project not found"}), 404
        
        # Verify user exists
        cursor.execute('SELECT id, username FROM users WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404
        
        # If reporting_manager_id provided, verify they exist and are in the project
        if reporting_manager_id:
            cursor.execute('''
                SELECT id FROM users WHERE id = %s
            ''', (reporting_manager_id,))
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Reporting manager not found"}), 404
            
            # Check if manager is in the project
            cursor.execute('''
                SELECT id FROM project_assignments 
                WHERE user_id = %s AND project_id = %s
            ''', (reporting_manager_id, project_id))
            if not cursor.fetchone():
                # If manager not in project, add them first? Or just warn?
                logger.warning(f"Reporting manager {reporting_manager_id} not in project {project_id}")
        
        # Check if user already in project
        cursor.execute('''
            SELECT id FROM project_assignments 
            WHERE user_id = %s AND project_id = %s
        ''', (user_id, project_id))
        
        existing = cursor.fetchone()
        logger.info(f"[ADD_MEMBER] Checked existing: {existing}")
        
        if existing:
            # Update existing assignment
            cursor.execute('''
                UPDATE project_assignments 
                SET reporting_manager_id = %s, reports_to_admin = %s
                WHERE user_id = %s AND project_id = %s
            ''', (reporting_manager_id, reports_to_admin, user_id, project_id))
            message = "Team member updated successfully"
            logger.info(f"[ADD_MEMBER] Updated existing assignment {existing['id']}")
        else:
            # Insert new assignment
            logger.info(f"[ADD_MEMBER] Inserting new assignment for User {user_id} in Project {project_id}")
            cursor.execute('''
                INSERT INTO project_assignments 
                (user_id, project_id, reporting_manager_id, reports_to_admin)
                VALUES (%s, %s, %s, %s)
            ''', (user_id, project_id, reporting_manager_id, reports_to_admin))
            message = "Team member added successfully"
        
        conn.commit()
        logger.info(f"[ADD_MEMBER] Transaction committed successfully")
        
        # Get updated team count
        cursor.execute('''
            SELECT COUNT(*) as count FROM project_assignments WHERE project_id = %s
        ''', (project_id,))
        result = cursor.fetchone()
        team_count = result['count'] if result else 0
        
        # Log activity
        try:
            current_admin_id = get_current_user_id()
            logger.info(f"[ADD_MEMBER] Logging activity for Admin {current_admin_id}")
            log_activity(
                current_admin_id or 0,
                'project_member_added',
                f'Added user {user_id} to project {project_id}',
                project_id=project_id
            )
        except Exception as log_err:
            logger.warning(f"Failed to log activity: {log_err}")
        
        conn.close()
        
        return jsonify({
            "success": True,
            "message": message,
            "team_count": team_count,
            "user_id": user_id
        }), 200
        
    except psycopg2.IntegrityError as e:
        logger.error(f"Integrity error adding member: {e}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": f"Database integrity error: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"CRITICAL ERROR adding team member: {str(e)}")
        logger.error(traceback.format_exc())
        error_details = str(e)
        if conn:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({"error": f"Internal Server Error: {error_details}"}), 500

# Get specific task details for admin
@app.route("/api/admin/tasks/<int:task_id>", methods=["GET"])
@csrf.exempt
@admin_required
def get_admin_task_detail(task_id):
    """Get detailed task information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT t.*, p.title as project_name,
                   u.username as assigned_to_name,
                   uc.username as created_by_name
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            LEFT JOIN users u ON t.assigned_to_id = u.id
            LEFT JOIN users uc ON t.created_by_id = uc.id
            WHERE t.id = %s
        ''', (task_id, ))

        task = cursor.fetchone()
        conn.close()

        if not task:
            return jsonify({"error": "Task not found"}), 404

        return jsonify(dict(task)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employee/team-members", methods=["GET"])
@csrf.exempt
def get_team_members():
    conn = None
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT id, username
            FROM users
            ORDER BY username
        """)

        members = cursor.fetchall()

        return jsonify(members), 200

    except Exception as e:
        logger.exception("Error fetching team members")
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()


# Employee real-time projects endpoint with live progress calculation
@app.route("/api/employee/projects/realtime", methods=["GET"])
@csrf.exempt
@login_required
def get_employee_realtime_projects():
    """Get real-time project updates with calculated progress percentage"""
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT DISTINCT p.id, p.title, p.description, p.status,
                   p.deadline, p.reporting_time, p.created_at, p.updated_at,
                   u.username as creator_name,
                   COUNT(DISTINCT t.id) as total_tasks,
                   SUM(CASE WHEN t.status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                   COUNT(DISTINCT m.id) as total_milestones,
                   SUM(CASE WHEN m.status = 'Completed' THEN 1 ELSE 0 END) as completed_milestones,
                   COUNT(DISTINCT pa.user_id) as team_size
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            LEFT JOIN tasks t ON p.id = t.project_id
            LEFT JOIN milestones m ON p.id = m.project_id
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            WHERE (p.created_by_id = %s OR p.id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            )) AND p.status != 'Completed'
            GROUP BY p.id, u.username
            ORDER BY p.updated_at DESC
        ''', (user_id, user_id))

        projects = cursor.fetchall()

        # Calculate live progress percentage for each project
        result = []
        for row in projects:
            project_dict = dict(row)
            total_tasks = project_dict.get('total_tasks') or 0         
            completed_tasks = project_dict.get('completed_tasks') or 0
            total_milestones = project_dict.get('total_milestones') or 0
            completed_milestones = project_dict.get(
                'completed_milestones') or 0

            # Calculate progress: if no tasks, progress is 0
            if total_tasks > 0:
                progress = int((completed_tasks / total_tasks) * 100)
            elif total_milestones > 0:
                progress = int((completed_milestones / total_milestones) * 100)
            else:
                progress = 0

            project_dict['progress'] = progress
            project_dict['completed_tasks'] = completed_tasks
            project_dict['total_tasks'] = total_tasks
            project_dict['completed_milestones'] = completed_milestones
            project_dict['total_milestones'] = total_milestones
            result.append(project_dict)

        conn.close()
        return jsonify(result), 200
    except Exception as e:
        print(f"[ERROR] Realtime projects error: {str(e)}")
        conn.close()
        return jsonify({"error": str(e)}), 500


def check_db_initialized():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_name='usertypes'
        """)
        
        exists = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return exists
    except Exception as e:
        print("DB check failed:", e)
        return False


safe_init_db()


def update_project_status(project_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get total + completed tasks
    cursor.execute(
        """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) as completed
        FROM tasks 
        WHERE project_id = %s
    """, (project_id, ))
    row = cursor.fetchone()

    total = row['total']
    completed = row['completed']

    # Decide project status
    new_status = None
    if total == 0:
        new_status = 'Pending'
    elif completed == total:
        new_status = 'Completed'
    else:
        new_status = 'In Progress'

        cursor.execute("UPDATE projects SET status = %s WHERE id = %s",
                       (new_status, project_id))

    conn.commit()
    conn.close()


@app.route("/api/admin/employees/<int:employee_id>/profile", methods=["GET"])
@csrf.exempt
@admin_required
def get_employee_profile_admin(employee_id):
    """Admin endpoint to get an employee's profile details"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role,
                   u.phone, u.department, u.bio, u.avatar_url, u.created_at
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (employee_id, ))

        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "Employee not found"}), 404

        # Get skills
        cursor.execute(
            '''
            SELECT skill_name FROM user_skills WHERE user_id = %s ORDER BY skill_name
        ''', (employee_id, ))
        skills = [row['skill_name'] for row in cursor.fetchall()]

        # Get stats
        cursor.execute(
            '''
            SELECT COUNT(DISTINCT id) as count FROM projects 
            WHERE created_by_id = %s OR id IN (
                SELECT project_id FROM project_assignments WHERE user_id = %s
            )
        ''', (employee_id, employee_id))
        projects_count = cursor.fetchone()['count']

        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM tasks 
            WHERE assigned_to_id = %s AND status = 'Completed'
        ''', (employee_id, ))
        tasks_completed = cursor.fetchone()['count']

        cursor.execute(
            '''
            SELECT COUNT(*) as count FROM documents WHERE uploaded_by_id = %s
        ''', (employee_id, ))
        documents_count = cursor.fetchone()['count']

        conn.close()

        profile = dict(user)
        profile['skills'] = skills
        profile['stats'] = {
            'projects': projects_count,
            'tasks_completed': tasks_completed,
            'documents': documents_count
        }

        return jsonify(profile), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Daily Task Reports Endpoints - CONSOLIDATED & IMPROVED
@app.route("/api/admin/daily-reports", methods=["GET"])
@app.route("/api/admin/daily_reports", methods=["GET"])
@app.route("/api/daily-reports", methods=["GET"])
@csrf.exempt
@login_required
def get_daily_reports():
    """Get all daily task reports with filtering.
    - Employee: Own reports.
    - Admin/Super Admin: All or filtered reports.
    """
    try:
        current_user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current user's role
        cursor.execute('''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (current_user_id, ))
        user_role_row = cursor.fetchone()
        current_role = (user_role_row['user_role'] if user_role_row else 'employee').lower()

        # Get query parameters for filtering
        employee_id = request.args.get('employee_id')
        project_id = request.args.get('project_id')
        report_date = request.args.get('date') or request.args.get('report_date')
        start_date = request.args.get('start_date') or request.args.get('date_from')
        end_date = request.args.get('end_date') or request.args.get('date_to')
        approval_status = request.args.get('approval_status')
        status = request.args.get('status')
        search = request.args.get('search', '')

        query = '''
            SELECT 
                dtr.id, dtr.report_date, dtr.user_id,
                u.username as employee_name, u.email as employee_email,
                p.title as project_name, t.title as task_title,
                dtr.task_id, dtr.project_id,
                assigned_by.username as assigned_by_name,
                dtr.communication_email, dtr.communication_phone,
                dtr.result_of_effort,
                dtr.remarks, dtr.work_description, dtr.time_spent,
                dtr.status, dtr.blocker, dtr.approval_status,
                dtr.review_comment, dtr.reviewed_by,
                reviewer.username as reviewer_name,
                dtr.created_at, dtr.updated_at
            FROM daily_task_reports dtr
            JOIN users u ON dtr.user_id = u.id
            LEFT JOIN projects p ON dtr.project_id = p.id
            LEFT JOIN tasks t ON dtr.task_id = t.id
            LEFT JOIN users assigned_by ON dtr.task_assigned_by_id = assigned_by.id
            LEFT JOIN users reviewer ON dtr.reviewed_by = reviewer.id
            WHERE 1=1
        '''
        params = []

        # Role-based restriction
        if current_role == 'employee':
            query += ' AND dtr.user_id = %s'
            params.append(current_user_id)
        elif employee_id:
            query += ' AND dtr.user_id = %s'
            params.append(employee_id)

        if project_id:
            query += ' AND dtr.project_id = %s'
            params.append(project_id)
        if report_date:
            query += ' AND dtr.report_date = %s'
            params.append(report_date)
        if start_date:
            query += ' AND dtr.report_date >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND dtr.report_date <= %s'
            params.append(end_date)
        if approval_status:
            query += ' AND dtr.approval_status = %s'
            params.append(approval_status)
        if status:
            query += ' AND dtr.status = %s'
            params.append(status)
        if search:
            query += ' AND (dtr.work_description ILIKE %s OR dtr.result_of_effort ILIKE %s OR t.title ILIKE %s)'
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        query += ' ORDER BY dtr.report_date DESC, dtr.created_at DESC'

        # Pagination support
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)  # cap at 200

        # Get total count first
        count_query = f"SELECT COUNT(*) as total FROM ({query}) sub"
        cursor.execute(count_query, params)
        total_row = cursor.fetchone()
        total = total_row['total'] if total_row else 0

        # Apply pagination
        offset = (page - 1) * per_page
        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, offset])

        cursor.execute(query, params)
        reports = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return jsonify({
            'data': reports,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 1
        }), 200
    except Exception as e:
        logger.exception("Error getting daily reports")
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/daily-reports/<int:report_id>/review', methods=['POST'])
@app.route('/api/daily-report/<int:report_id>/action', methods=['POST'])
@app.route('/api/daily-reports/<int:report_id>/approve', methods=['POST'])
@app.route('/api/daily-reports/<int:report_id>/reject', methods=['POST'])
@csrf.exempt
@login_required
def review_daily_report(report_id):
    """Admin reviews (approve/reject) a daily report."""
    try:
        reviewer_id = get_current_user_id()
        data = request.get_json() or {}
        
        # Determine action
        approval = data.get('approval_status') or data.get('action')
        if not approval:
            if '/approve' in request.path: approval = 'approved'
            elif '/reject' in request.path: approval = 'rejected'
        
        if approval == 'approve': approval = 'approved'
        if approval == 'reject': approval = 'rejected'

        if approval not in ('approved', 'rejected', 'pending'):
            return jsonify({'error': 'Invalid approval status'}), 400

        comment = data.get('review_comment') or data.get('comment', '')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Role Check
        user_role_row = cursor.execute('''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (reviewer_id, )).fetchone()
        role = (user_role_row['user_role'] if user_role_row else 'employee').lower()

        if role not in ['admin', 'super admin', 'manager']:
            conn.close()
            return jsonify({'error': 'Permission denied'}), 403

        # Check existence
        cursor.execute('SELECT id FROM daily_task_reports WHERE id = %s', (report_id, ))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Report not found'}), 404

        lock_clause = ", is_locked = 1" if approval == 'approved' else ""
        cursor.execute(f'''
            UPDATE daily_task_reports 
            SET approval_status = %s, reviewed_by = %s, review_comment = %s, updated_at = CURRENT_TIMESTAMP{lock_clause}
            WHERE id = %s
        ''', (approval, reviewer_id, comment, report_id))
        
        conn.commit()
        log_activity(reviewer_id, 'report_reviewed', f'Reviewed report {report_id} as {approval}',
                     target_type='daily_report', target_id=report_id)
        
        conn.close()
        return jsonify({'success': True, 'approval_status': approval}), 200
    except Exception as e:
        logger.exception('Failed to review report')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/daily-reports')
@csrf.exempt
@admin_required
def admin_daily_reports_page():
    return render_template('admin-daily-reports.html')


@app.route("/api/employee/daily-report", methods=["POST"])
@app.route("/api/daily-report", methods=["POST"])
@app.route("/api/daily-report/submit", methods=["POST"])
@app.route("/api/admin/daily_reports", methods=["POST"])
@csrf.exempt
@login_required
def submit_daily_report():
    """Submit daily task report. Both employees and admins (on behalf of) supported."""
    try:
        current_user_id = get_current_user_id()
        data = request.get_json() or {}
        
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current user's role
        cursor.execute('''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (current_user_id, ))
        user_role_row = cursor.fetchone()
        current_role = (user_role_row['user_role'] if user_role_row else 'employee').lower()

        # Determine target user
        target_user_id = data.get('user_id') or data.get('employee_id') or current_user_id
        
        # Admin check for on-behalf-of
        if str(target_user_id) != str(current_user_id):
            if current_role not in ['admin', 'super admin']:
                conn.close()
                return jsonify({'error': 'Only admins can submit reports for other users'}), 403
        
        # Validate required fields
        report_date = data.get('report_date') or data.get('date') or datetime.now().strftime('%Y-%m-%d')
        project_id = data.get('project_id')
        work_description = data.get('work_description') or data.get('task') or data.get('result_of_effort')

        if not (project_id and work_description):
            conn.close()
            return jsonify({"error": "Missing project_id or work_description"}), 400

        task_id = data.get('task_id')
        time_spent = data.get('time_spent') or data.get('hours', 0)
        status = data.get('status', 'In Progress')
        blocker = data.get('blocker', '')
        result_of_effort = data.get('result_of_effort') or data.get('result', '')
        remarks = data.get('remarks', '')
        comm_email = data.get('communication_email') or data.get('email', '')
        comm_phone = data.get('communication_phone') or data.get('phone', '')
        assigned_by_id = data.get('task_assigned_by_id')

        # Check for duplicate report if task_id exists
        if task_id:
            cursor.execute(
                'SELECT id FROM daily_task_reports WHERE user_id = %s AND task_id = %s AND report_date = %s',
                (target_user_id, task_id, report_date))
            if cursor.fetchone():
                conn.close()
                return jsonify({"error": "A report for this task already exists for this date"}), 409

        cursor.execute('''
            INSERT INTO daily_task_reports (
                user_id, report_date, project_id, task_id,
                work_description, time_spent, status, blocker, 
                task_assigned_by_id, result_of_effort, remarks, 
                communication_email, communication_phone, 
                approval_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
        ''', (target_user_id, report_date, project_id, task_id,
              work_description, time_spent, status, blocker,
              assigned_by_id, result_of_effort, remarks, comm_email, comm_phone))

        report_id = cursor.fetchone()['id']
        conn.commit()
        
        log_activity(current_user_id, 'daily_report_submitted', 
                     f'Submitted daily report for user {target_user_id}', 
                     project_id=project_id, target_type='daily_report', target_id=report_id)

        conn.close()
        return jsonify({"success": True, "report_id": report_id}), 201

    except Exception as e:
        logger.exception("Error submitting daily report")
        return jsonify({"error": str(e)}), 500


@app.route('/api/daily-report/<int:report_id>', methods=['PUT'])
@csrf.exempt
@login_required
def update_daily_report(report_id):
    """Edit report with permission checks."""
    try:
        user_id = get_current_user_id()
        data = request.get_json() or {}
        conn = get_db_connection()
        cur = conn.cursor()

        cursor.execute('SELECT * FROM daily_task_reports WHERE id = %s', (report_id, ))
        report = cursor.fetchone()
        if not report:
            conn.close()
            return jsonify({'error': 'Report not found'}), 404

        user_role_row = cur.execute('''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (user_id, )).fetchone()
        role = (user_role_row['user_role'] if user_role_row else 'employee').lower()

        # Permissions logic
        can_edit = (role == 'super admin' and not report.get('is_locked')) or \
                   (report['user_id'] == user_id and report['approval_status'] != 'approved' and not report.get('is_locked'))

        if not can_edit:
            conn.close()
            return jsonify({'error': 'Permission denied or report locked'}), 403

        update_map = {
            'work_description': 'work_description',
            'result_of_effort': 'result_of_effort',
            'remarks': 'remarks',
            'communication_email': 'communication_email',
            'communication_phone': 'communication_phone',
            'task_assigned_by_id': 'task_assigned_by_id',
            'time_spent': 'time_spent',
            'status': 'status',
            'blocker': 'blocker'
        }
        
        fields = []
        params = []
        for key, field in update_map.items():
            if key in data:
                fields.append(f"{field} = %s")
                params.append(data[key])
        
        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE daily_task_reports SET {', '.join(fields)} WHERE id = %s"
            params.append(report_id)
            cur.execute(query, params)
            conn.commit()
            log_activity(user_id, 'edit_report', f'Updated report {report_id}', target_type='daily_report', target_id=report_id)

        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception("Error updating report")
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/<int:report_id>', methods=['DELETE'])
@csrf.exempt
@login_required
def delete_daily_report_api(report_id):
    """Delete report (Super Admin only)."""
    try:
        user_id = get_current_user_id()
        conn = get_db_connection()
        cursor = conn.cursor()

        user_role_row = cursor.execute('''
            SELECT ut.user_role FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (user_id, )).fetchone()
        role = (user_role_row['user_role'] if user_role_row else 'employee').lower()

        if role != 'super admin':
            conn.close()
            return jsonify({'error': 'Only Super Admin can delete reports'}), 403

        cursor.execute('DELETE FROM daily_task_reports WHERE id = %s', (report_id, ))
        conn.commit()
        log_activity(user_id, 'delete_report', f'Deleted report {report_id}', target_type='daily_report', target_id=report_id)
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception("Error deleting report")
        return jsonify({'error': str(e)}), 500


@app.route("/api/daily-reports/stats", methods=["GET"])
@csrf.exempt
@admin_required
def get_daily_reports_stats():
    """Get statistics for daily reports - returns shape matching frontend charts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total reports
        cursor.execute('SELECT COUNT(*) as count FROM daily_task_reports')
        result = cursor.fetchone()
        total_reports = safe_get(result, 'count', 0) if result else 0

        # Pending approvals
        cursor.execute(
            "SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s",
            ('pending',)
        )
        result = cursor.fetchone()
        pending_reports = safe_get(result, 'count', 0) if result else 0

        # Approved reports
        cursor.execute(
            "SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s",
            ('approved',)
        )
        result = cursor.fetchone()
        approved_reports = safe_get(result, 'count', 0) if result else 0

        # Rejected reports
        cursor.execute(
            "SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s",
            ('rejected',)
        )
        result = cursor.fetchone()
        rejected_reports = safe_get(result, 'count', 0) if result else 0

        # Total hours logged
        cursor.execute(
            "SELECT COALESCE(SUM(time_spent), 0) as total_hours FROM daily_task_reports WHERE approval_status = %s",
            ('approved',)
        )
        result = cursor.fetchone()
        total_hours = safe_get(result, 'total_hours', 0) if result else 0

        # Reports today
        cursor.execute('''
            SELECT COUNT(*) as count FROM daily_task_reports
            WHERE report_date = CURRENT_DATE
        ''')
        result = cursor.fetchone()
        reports_today = safe_get(result, 'count', 0) if result else 0

        # Reports this week
        cursor.execute('''
            SELECT COUNT(*) as count FROM daily_task_reports
            WHERE report_date >= CURRENT_DATE - INTERVAL '7 days'
        ''')
        result = cursor.fetchone()
        reports_week = safe_get(result, 'count', 0) if result else 0

        # Unique employees with reports
        cursor.execute('''
            SELECT COUNT(DISTINCT user_id) as count FROM daily_task_reports
        ''')
        result = cursor.fetchone()
        unique_employees = safe_get(result, 'count', 0) if result else 0

        # Average hours per report
        avg_hours = 0
        if approved_reports > 0:
            avg_hours = total_hours / approved_reports

        # Reports by status (for chart)
        cursor.execute('''
            SELECT status, COUNT(*) as count FROM daily_task_reports GROUP BY status
        ''')
        by_status = {row['status']: row['count'] for row in cursor.fetchall()}

        # Daily trend (last 7 days)
        cursor.execute('''
            SELECT report_date, COUNT(*) as count
            FROM daily_task_reports
            WHERE report_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY report_date
            ORDER BY report_date ASC
        ''')
        daily_trend_data = {}
        for row in cursor.fetchall():
            d_str = row['report_date'].strftime('%Y-%m-%d') if hasattr(row['report_date'], 'strftime') else str(row['report_date'])
            daily_trend_data[d_str] = row['count']

        daily_trend = []
        for i in range(7):
            d = (datetime.now() - timedelta(days=6 - i)).strftime('%Y-%m-%d')
            daily_trend.append(daily_trend_data.get(d, 0))

        conn.close()

        return jsonify({
            "summary": {
                "total_reports": total_reports,
                "approved": approved_reports,
                "pending": pending_reports,
                "rejected": rejected_reports,
                "total_hours": float(total_hours),
                "avg_hours_per_report": round(float(avg_hours), 2)
            },
            "by_status": by_status,
            "daily_trend": daily_trend,
            "total_reports": total_reports,
            "pending_reports": pending_reports,
            "approved_reports": approved_reports,
            "rejected_reports": rejected_reports,
            "total_hours_logged": float(total_hours),
            "avg_hours_per_report": round(float(avg_hours), 2),
            "reports_today": reports_today,
            "reports_week": reports_week,
            "unique_employees": unique_employees
        }), 200
    except Exception as e:
        logger.exception("Error getting daily reports stats")
        return jsonify({"error": str(e)}), 500


@app.route("/api/daily-reports/dashboard/stats", methods=["GET"])
@csrf.exempt
@admin_required
def get_daily_reports_dashboard_stats():
    """Comprehensive daily reports statistics for Super Admin Dashboard"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total metrics
        cursor.execute('SELECT COUNT(*) as count FROM daily_task_reports')
        result = cursor.fetchone()
        total_reports = safe_get(result, 'count', 0) if result else 0

        cursor.execute(
            'SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s',
            ('approved', ))
        result = cursor.fetchone()
        approved_reports = safe_get(result, 'count', 0) if result else 0

        cursor.execute(
            'SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s',
            ('pending', ))
        result = cursor.fetchone()
        pending_reports = safe_get(result, 'count', 0) if result else 0

        cursor.execute(
            'SELECT COUNT(*) as count FROM daily_task_reports WHERE approval_status = %s',
            ('rejected', ))
        result = cursor.fetchone()
        rejected_reports = safe_get(result, 'count', 0) if result else 0

        # Total hours
        cursor.execute(
            'SELECT COALESCE(SUM(time_spent), 0) as total FROM daily_task_reports WHERE approval_status = %s',
            ('approved', ))
        result = cursor.fetchone()
        total_hours = safe_get(result, 'total', 0) if result else 0

        # Average hours per report
        if approved_reports > 0:
            avg_hours = total_hours / approved_reports
        else:
            avg_hours = 0

        # Reports by status
        cursor.execute('''
            SELECT status, COUNT(*) as count FROM daily_task_reports GROUP BY status
        ''')
        status_breakdown = {
            row['status']: row['count']
            for row in cursor.fetchall()
        }

        # Reports by project (top 10)
        cursor.execute('''
            SELECT p.title, COUNT(d.id) as count
            FROM daily_task_reports d
            LEFT JOIN projects p ON d.project_id = p.id
            GROUP BY d.project_id, p.title
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_projects = [{
            'project': row['title'],
            'count': row['count']
        } for row in cursor.fetchall()]

        # Reports by employee (top 10)
        cursor.execute('''
            SELECT u.username, COUNT(d.id) as count
            FROM daily_task_reports d
            LEFT JOIN users u ON d.user_id = u.id
            GROUP BY d.user_id, u.username
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_employees = [{
            'employee': row['username'],
            'count': row['count']
        } for row in cursor.fetchall()]

        # Date range analytics
        cursor.execute('''
            SELECT 
                report_date,
                COUNT(*) as count,
                SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending,
                COALESCE(SUM(time_spent), 0) as hours
            FROM daily_task_reports
            GROUP BY report_date
            ORDER BY report_date DESC
            LIMIT 30
        ''')
        date_analytics = []
        for row in cursor.fetchall():
            date_analytics.append({
                'date': row['report_date'],
                'reports': row['count'],
                'approved': row['approved'],
                'pending': row['pending'],
                'hours': float(row['hours'])
            })

        # Date range analytics - for trend chart (last 7 days)
        cursor.execute('''
            SELECT report_date, COUNT(*) as count
            FROM daily_task_reports
            WHERE report_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY report_date
            ORDER BY report_date ASC
        ''')
        daily_trend_data = {}
        for row in cursor.fetchall():
            d_str = row['report_date'].strftime('%Y-%m-%d') if hasattr(row['report_date'], 'strftime') else str(row['report_date'])
            daily_trend_data[d_str] = row['count']

        # Create trend array for last 7 days
        daily_trend = []
        for i in range(7):
            d = (datetime.now() - timedelta(days=6 - i)).strftime('%Y-%m-%d')
            daily_trend.append(daily_trend_data.get(d, 0))

        conn.close()

        return jsonify({
            'summary': {
                'total_reports': total_reports,
                'approved': approved_reports,
                'pending': pending_reports,
                'rejected': rejected_reports,
                'total_hours': float(total_hours),
                'avg_hours_per_report': round(float(avg_hours), 2)
            },
            'by_status': status_breakdown,
            'top_projects': top_projects,
            'top_employees': top_employees,
            'date_analytics': date_analytics,
            'daily_trend': daily_trend
        }), 200
    except Exception as e:
        logger.exception('Error getting daily reports dashboard stats')
        return jsonify({'error': str(e)}), 500


@app.route("/api/admin/activity", methods=["POST"])
@admin_required
def admin_activity():
    """Record an arbitrary admin activity from the dashboard UI.
    This endpoint lets the frontend record admin actions as activities
    so they appear in the global activity feed.
    """
    data = request.get_json() or {}
    description = data.get('description', '')
    activity_type = data.get('activity_type', 'admin_action')
    project_id = data.get('project_id')
    task_id = data.get('task_id')
    milestone_id = data.get('milestone_id')
    target_type = data.get('target_type')
    target_id = data.get('target_id')

    try:
        # Use admin user id 0 for system/admin actions
        user_id = get_current_user_id()
        log_activity(user_id, activity_type, description, project_id=project_id, task_id=task_id,
                     milestone_id=milestone_id)

        # Also log to audit logs if it's a significant action
        if activity_type in [
                'report_reviewed', 'report_deleted', 'report_edited'
        ]:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO audit_logs (actor_id, action, target_type, target_id, details, created_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, activity_type, target_type, target_id, description))
            conn.commit()
            conn.close()

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('Failed to log admin activity')
        return jsonify({'success': False, 'error': str(e)}), 500


# NEW: Batch approval endpoint
@app.route("/api/admin/daily-reports/batch-approve", methods=["POST"])
@admin_required
def batch_approve_reports():
    """Approve multiple reports at once"""
    try:
        data = request.get_json() or {}
        report_ids = data.get('report_ids', [])
        action = data.get('action', 'approve')  # 'approve' or 'reject'
        comment = data.get('comment', '')

        if not report_ids:
            return jsonify({'error': 'No report IDs provided'}), 400

        if action not in ['approve', 'reject']:
            return jsonify({'error': 'Invalid action'}), 400

        reviewer_id = get_current_user_id()
        new_status = 'approved' if action == 'approve' else 'rejected'

        conn = get_db_connection()
        cursor = conn.cursor()

        # Update all reports
        placeholders = ','.join(['%s'] * len(report_ids))
        cursor.execute(
            f'''
            UPDATE daily_task_reports 
            SET approval_status = %s, reviewed_by = %s, review_comment = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
        ''', [new_status, reviewer_id, comment] + report_ids)

        updated_count = cursor.rowcount
        conn.commit()

        # Log batch action
        log_activity(reviewer_id,
                     'batch_report_review',
                     f'{action.capitalize()}d {updated_count} reports',
                     target_type='daily_report_batch')

        conn.close()

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'action': action,
            'status': new_status
        }), 200

    except Exception as e:
        logger.exception("Error in batch approve")
        return jsonify({'error': str(e)}), 500


# NEW: Get report summary by employee
@app.route("/api/admin/daily-reports/employee-summary", methods=["GET"])
@admin_required
def get_employee_report_summary():
    """Get summary of reports by employee"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                u.id as employee_id,
                u.username as employee_name,
                u.email as employee_email,
                COUNT(dtr.id) as total_reports,
                SUM(CASE WHEN dtr.approval_status = 'approved' THEN 1 ELSE 0 END) as approved_reports,
                SUM(CASE WHEN dtr.approval_status = 'pending' THEN 1 ELSE 0 END) as pending_reports,
                SUM(CASE WHEN dtr.approval_status = 'rejected' THEN 1 ELSE 0 END) as rejected_reports,
                COALESCE(SUM(dtr.time_spent), 0) as total_hours,
                MAX(dtr.report_date) as last_report_date
            FROM users u
            LEFT JOIN daily_task_reports dtr ON u.id = dtr.user_id
            WHERE u.user_type_id = (SELECT id FROM usertypes WHERE user_role = 'Employee')
            GROUP BY u.id, u.username, u.email
            ORDER BY u.username
        ''')

        employees = []
        for row in cursor.fetchall():
            employees.append({
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'employee_email': row['employee_email'],
                'total_reports': row['total_reports'] or 0,
                'approved_reports': row['approved_reports'] or 0,
                'pending_reports': row['pending_reports'] or 0,
                'rejected_reports': row['rejected_reports'] or 0,
                'total_hours': float(row['total_hours'] or 0),
                'last_report_date': row['last_report_date']
            })

        conn.close()
        return jsonify(employees), 200

    except Exception as e:
        logger.exception("Error getting employee report summary")
        return jsonify({'error': str(e)}), 500


# NEW: Get reports for a specific employee (admin view)
@app.route("/api/admin/employees/<int:employee_id>/daily-reports",
           methods=["GET"])
@admin_required
def get_employee_daily_reports(employee_id):
    """Get all daily reports for a specific employee"""
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        approval_status = request.args.get('approval_status')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify employee exists
        cursor.execute('SELECT id, username FROM users WHERE id = %s',
                       (employee_id, ))
        employee = cursor.fetchone()
        if not employee:
            conn.close()
            return jsonify({'error': 'Employee not found'}), 404

        query = '''
            SELECT 
                dtr.*,
                p.title as project_title,
                t.title as task_title,
                reviewer.username as reviewer_name
            FROM daily_task_reports dtr
            LEFT JOIN projects p ON dtr.project_id = p.id
            LEFT JOIN tasks t ON dtr.task_id = t.id
            LEFT JOIN users reviewer ON dtr.reviewed_by = reviewer.id
            WHERE dtr.user_id = %s
        '''
        params = [employee_id]

        if start_date:
            query += ' AND dtr.report_date >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND dtr.report_date <= %s'
            params.append(end_date)
        if approval_status:
            query += ' AND dtr.approval_status = %s'
            params.append(approval_status)

        query += ' ORDER BY dtr.report_date DESC, dtr.created_at DESC'

        cursor.execute(query, params)
        reports = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'employee': {
                'id': employee['id'],
                'username': employee['username']
            },
            'reports': reports,
            'count': len(reports)
        }), 200

    except Exception as e:
        logger.exception("Error getting employee daily reports")
        return jsonify({'error': str(e)}), 500


# Enhanced log_activity function with target_type support
def log_activity(user_id,
                 activity_type,
                 description,
                 project_id=None,
                 task_id=None,
                 milestone_id=None,
                 target_type=None,
                 target_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO activities (user_id, activity_type, description, project_id, task_id, milestone_id)
            VALUES (%s,%s,%s,%s,%s,%s)
        ''', (user_id, activity_type, description, project_id, task_id,
              milestone_id))
        conn.commit()

        # Also log to audit logs for important actions
        if activity_type in [
                'report_reviewed', 'report_deleted', 'report_edited',
                'batch_report_review', 'daily_report_submitted'
        ]:
            cursor.execute(
                '''
                INSERT INTO audit_logs (actor_id, action, target_type, target_id, details, created_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, activity_type, target_type, target_id, description))
            conn.commit()

    except Exception as e:
        print(f"[ERROR] Failed to log activity: {str(e)}")
    finally:
        if conn:
            conn.close()


# Replace the previous get_all_users() function with this fixed version

@app.route("/api/admin/users", methods=["GET"])
@admin_required
def get_all_users():
    """
    Admin endpoint: return list of all users.
    Returns a JSON array with fields: id, username, email, user_role, user_type_id, created_at
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.username, u.email, u.user_type_id, ut.user_role, u.created_at
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE COALESCE(u.is_system, 0) != 1
            ORDER BY u.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()

        users = []
        for r in rows:
            created_at = r['created_at'] if r['created_at'] is not None else None
            # Ensure created_at is serialized as a string (ISO if possible)
            try:
                # If stored as text, leave as-is
                if isinstance(created_at, str):
                    created_at_str = created_at
                else:
                    # Postgres returns datetime objects; check for isoformat
                    created_at_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
            except Exception:
                created_at_str = str(created_at) if created_at is not None else None

            users.append({
                "id": r["id"],
                "username": r["username"],
                "email": r["email"],
                "user_type_id": r["user_type_id"],
                "user_role": r["user_role"],
                "created_at": created_at_str
            })

        return jsonify(users), 200
    except Exception as e:
        logger.exception("Error in /api/admin/users")
        return jsonify({"error": str(e)}), 500

# Get project team members
@app.route("/api/projects/<int:project_id>/team-members", methods=["GET"])
@login_required
def get_project_team_members(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get team members for the project
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role, pa.user_id
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s
        ''', (project_id,))
        
        team_members = cursor.fetchall()
        conn.close()
        
        # Convert to list of dictionaries
        result = []
        for member in team_members:
            member_dict = dict(member) if hasattr(member, 'keys') else {
                'id': member[0],
                'username': member[1],
                'email': member[2],
                'user_role': member[3],
                'user_id': member[4]
            }
            result.append({
                'id': member_dict['id'],
                'user_id': member_dict['user_id'],
                'username': member_dict['username'],
                'email': member_dict['email'],
                'user_role': member_dict.get('user_role')
            })
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error getting project team members: {e}")
        return jsonify({"error": str(e)}), 500


# Add team member to project
@app.route("/api/projects/<int:project_id>/add-team-member", methods=["POST"])
@csrf.exempt
@login_required
def add_team_member_to_project(project_id):
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        user_type_id = data.get("user_type_id")
        reporting_manager_id = data.get("reporting_manager_id")
        reports_to_admin = data.get("reports_to_admin", False)
        permissions = data.get("permissions", [])
        
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if user already assigned to project
        cursor.execute('''
            SELECT id FROM project_assignments 
            WHERE user_id = %s AND project_id = %s
        ''', (user_id, project_id))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({"error": "User is already assigned to this project"}), 400
        
        # Add user to project_assignments
        cursor.execute('''
            INSERT INTO project_assignments (user_id, project_id, reporting_manager_id, reports_to_admin)
            VALUES (%s, %s, %s, %s)
        ''', (user_id, project_id, reporting_manager_id, reports_to_admin))
        
        # Update user type if needed
        if user_type_id:
            cursor.execute('''
                UPDATE users SET user_type_id = %s WHERE id = %s
            ''', (user_type_id, user_id))
        
        # Store permissions if needed (you may need to create a user_permissions table)
        if permissions:
            for perm in permissions:
                cursor.execute('''
                    INSERT INTO user_permissions (user_id, module, action, granted)
                    VALUES (%s, %s, %s, 1)
                    ON CONFLICT (user_id, module, action) DO NOTHING
                ''', (user_id, 'project', perm))
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Team member added successfully"}), 201
    except Exception as e:
        logger.error(f"Error adding team member to project: {e}")
        return jsonify({"error": str(e)}), 500


# Remove team member from project
@app.route("/api/projects/<int:project_id>/remove-team-member", methods=["DELETE"])
@login_required
def remove_team_member_from_project(project_id):
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Remove user from project_assignments
        cursor.execute('''
            DELETE FROM project_assignments 
            WHERE user_id = %s AND project_id = %s
        ''', (user_id, project_id))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "User is not assigned to this project"}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Team member removed successfully"}), 200
    except Exception as e:
        logger.error(f"Error removing team member from project: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------------------
# USER TYPE MANAGEMENT ENDPOINTS
# -------------------------------------------------------------------------

# Ensure usertype_permissions table exists (Safety check)
def ensure_usertype_permissions_table():
    pass # No longer needed as init_db is now robust and idempotent

@app.route("/api/usertypes", methods=["GET"])
@csrf.exempt
@login_required
def get_usertypes():
    """Get all user types with their permissions"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM usertypes ORDER BY id")
        usertypes = [dict(row) for row in cursor.fetchall()]
        
        for ut in usertypes:
            # Safely get permissions
            try:
                # IMPORTANT: Only fetch granted = TRUE for "Assigned Permissions"
                cursor.execute("SELECT module, action FROM usertype_permissions WHERE usertype_id = %s AND granted = %s", (ut['id'], True))
                perms = cursor.fetchall()
                perm_list = []
                for p in perms:
                    mod = p['module']
                    act = p['action']
                    if mod == 'SYSTEM':
                        perm_list.append(act)
                    else:
                        perm_list.append(f"{mod}_{act}")
                ut['permissions'] = perm_list
            except Exception as e:
                print(f"Error fetching permissions for usertype {ut['id']}: {e}")
                ut['permissions'] = []
            
            # Count users
            try:
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE user_type_id = %s", (ut['id'],))
                ut['user_count'] = cursor.fetchone()['count']
            except:
                ut['user_count'] = 0

        conn.close()
        return jsonify(usertypes), 200
    except Exception as e:
        logger.exception("Error fetching user types")
        return jsonify({"error": str(e)}), 500

@app.route("/api/usertypes", methods=["POST"])
@csrf.exempt
@admin_required
def create_usertype():
    """Create a new user type with permissions"""
    try:
        data = request.get_json()
        user_role = data.get('user_role')
        description = data.get('description', '')
        permissions = data.get('permissions', []) # List of strings "MODULE_ACTION"
        
        logger.info(f"Creating user type: {user_role}, Perms count: {len(permissions)}")

        if not user_role:
            return jsonify({"error": "User role name is required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO usertypes (user_role, description) VALUES (%s, %s) RETURNING id", (user_role, description))
            usertype_id = cursor.fetchone()['id']
            
            for perm in permissions:
                parts = perm.split('_', 1)
                if len(parts) == 2:
                     module, action = parts
                else:
                     module = 'SYSTEM'
                     action = perm
                
                cursor.execute("INSERT INTO usertype_permissions (usertype_id, module, action, granted) VALUES (%s, %s, %s, %s)",
                               (usertype_id, module, action, True))
            
            conn.commit()
            return jsonify({"success": True, "message": "User type created", "id": usertype_id}), 201
            
        except psycopg2.IntegrityError:
            return jsonify({"error": "User type already exists"}), 409
        finally:
            conn.close()

    except Exception as e:
        logger.exception("Error creating user type")
        return jsonify({"error": str(e)}), 500

@app.route("/api/usertypes/<int:ut_id>", methods=["PUT"])
@csrf.exempt
@admin_required
def update_usertype(ut_id):
    """Update user type and permissions"""
    try:
        data = request.get_json()
        user_role = data.get('user_role') # Optional update
        description = data.get('description')
        permissions = data.get('permissions') # Optional update list

        conn = get_db_connection()
        cursor = conn.cursor()

        if user_role:
            try:
                cursor.execute("UPDATE usertypes SET user_role = %s WHERE id = %s", (user_role, ut_id))
            except psycopg2.IntegrityError:
                return jsonify({"error": "User role name already taken"}), 409
        
        if description is not None:
             cursor.execute("UPDATE usertypes SET description = %s WHERE id = %s", (description, ut_id))

        if permissions is not None:
            # Replace permissions
            cursor.execute("DELETE FROM usertype_permissions WHERE usertype_id = %s", (ut_id,))
            for perm in permissions:
                parts = perm.split('_', 1)
                if len(parts) == 2:
                     module, action = parts
                else:
                     module = 'SYSTEM'
                     action = perm
                cursor.execute("INSERT INTO usertype_permissions (usertype_id, module, action, granted) VALUES (%s, %s, %s, %s)",
                               (ut_id, module, action, True))
            
            # Optional: Update existing users of this type%s
            # For now, let's NOT automatically update existing users' personal permissions to avoid overwriting custom overrides.
            # But in a strict RBAC, we would.
        
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "User type updated"}), 200

    except Exception as e:
        logger.exception("Error updating user type")
        return jsonify({"error": str(e)}), 500

@app.route("/api/usertypes/<int:ut_id>", methods=["DELETE"])
@csrf.exempt
@admin_required
def delete_usertype(ut_id):
    """Delete a user type"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if users exist
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE user_type_id = %s", (ut_id,))
        if cursor.fetchone()['count'] > 0:
            conn.close()
            return jsonify({"error": "Cannot delete user type that has assigned users"}), 400

        cursor.execute("DELETE FROM usertypes WHERE id = %s", (ut_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "User type deleted"}), 200
    except Exception as e:
        logger.exception("Error deleting user type")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/dashboard/stats", methods=["GET"])
@admin_required
def get_admin_dashboard_stats():
    """Get general admin dashboard statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Helper function to safely get count
        def safe_count(result):
            if result:
                result_dict = dict(result) if hasattr(result, 'keys') else {'count': result[0]}
                return result_dict.get('count', 0)
            return 0

        # Active Projects
        cursor.execute("SELECT COUNT(*) AS count FROM projects WHERE status != 'Completed'")
        active_projects = safe_count(cursor.fetchone())

        # Active Tasks
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM tasks 
            WHERE status NOT IN ('Completed', 'Pending')
        """)
        active_tasks = safe_count(cursor.fetchone())

        # Pending Tasks
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM tasks 
            WHERE status = 'Pending'
        """)
        pending_tasks = safe_count(cursor.fetchone())

        # Overdue Tasks (Postgres syntax)
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM tasks 
            WHERE status != 'Completed' 
            AND deadline < CURRENT_DATE
        """)
        overdue_tasks = safe_count(cursor.fetchone())

        # Completed Tasks
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM tasks 
            WHERE status = 'Completed'
        """)
        completed_tasks = safe_count(cursor.fetchone())

        # Total Users
        cursor.execute("SELECT COUNT(*) AS count FROM users")
        total_users = safe_count(cursor.fetchone())

        # Total User Types
        cursor.execute("SELECT COUNT(*) AS count FROM usertypes")
        total_usertypes = safe_count(cursor.fetchone())

        cursor.close()
        conn.close()

        return jsonify({
            "active_projects": active_projects,
            "active_tasks": active_tasks,
            "pending_approvals": pending_tasks,
            "overdue_tasks": overdue_tasks,
            "completed_tasks": completed_tasks,
            "total_users": total_users,
            "total_usertypes": total_usertypes
        }), 200

    except Exception as e:
        logger.exception("Error getting admin dashboard stats")
        return jsonify({"error": str(e)}), 500

@app.route("/api/employee/task-summary", methods=["GET"])
@login_required
def get_employee_task_summary():
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        today = date.today()

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # =========================
        # PENDING
        # =========================
        cursor.execute("""
            SELECT *
            FROM tasks
            WHERE 
            (assigned_to_id = %s OR created_by_id = %s)
            AND LOWER(status) != 'completed'
            AND (deadline IS NULL OR deadline >= %s)
        """, (user_id, user_id, today))
        pending_tasks = cursor.fetchall()

        # =========================
        # COMPLETED
        # =========================
        cursor.execute("""
            SELECT *
            FROM tasks
            WHERE 
            (assigned_to_id = %s OR created_by_id = %s)
            AND LOWER(status) = 'completed'
        """, (user_id, user_id))
        completed_tasks = cursor.fetchall()

        # =========================
        # OVERDUE
        # =========================
        cursor.execute("""
            SELECT *
            FROM tasks
            WHERE 
            (assigned_to_id = %s OR created_by_id = %s)
            AND LOWER(status) != 'completed'
            AND deadline IS NOT NULL
            AND deadline < %s
        """, (user_id, user_id, today))
        overdue_tasks = cursor.fetchall()

        conn.close()

        return jsonify({
            "pending": pending_tasks,
            "completed": completed_tasks,
            "overdue": overdue_tasks,
            "pending_count": len(pending_tasks),
            "completed_count": len(completed_tasks),
            "overdue_count": len(overdue_tasks)
        }), 200

    except Exception as e:
        logger.exception("Error fetching task summary")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/api/employee/tasks/<int:task_id>/update", methods=["PUT"])
@csrf.exempt
def update_employee_task(task_id):
    conn = None
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json() or {}

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Fetch user role to determine if admin
        cursor.execute('''
            SELECT ut.user_role 
            FROM users u 
            JOIN usertypes ut ON u.user_type_id = ut.id 
            WHERE u.id = %s
        ''', (user_id,))
        user_role_row = cursor.fetchone()
        user_role = (user_role_row['user_role'] if user_role_row else 'employee').lower()
        is_admin = 'admin' in user_role

        # 2. Check existence and ownership (unless admin)
        cursor.execute("""
            SELECT id, assigned_to_id, created_by_id FROM tasks WHERE id = %s
        """, (task_id,))
        task = cursor.fetchone()
        
        if not task:
            conn.close()
            return jsonify({"error": "Task not found"}), 404

        if not is_admin:
            if task['assigned_to_id'] != user_id and task['created_by_id'] != user_id:
                conn.close()
                return jsonify({"error": "Permission denied"}), 403

        # 3. Build update query
        update_fields = []
        params = []

        # Employee/Basic fields
        if "status" in data:
            update_fields.append("status = %s")
            params.append(data["status"])
            if data["status"].lower() == 'completed':
                update_fields.append("progress = %s")
                params.append(100)
                update_fields.append("completed_at = CURRENT_TIMESTAMP")
        
        if "progress" in data:
            val = int(data["progress"])
            update_fields.append("progress = %s")
            params.append(val)
            if val >= 100:
                update_fields.append("status = %s")
                params.append("Completed")
                update_fields.append("completed_at = CURRENT_TIMESTAMP")

        if "notes" in data:
            update_fields.append("notes = %s")
            params.append(data["notes"])

        # Admin extra fields
        if is_admin:
            if "title" in data:
                update_fields.append("title = %s")
                params.append(data["title"])
            if "description" in data:
                update_fields.append("description = %s")
                params.append(data["description"])
            if "priority" in data:
                update_fields.append("priority = %s")
                params.append(data["priority"])
            if "milestone_id" in data:
                val = data["milestone_id"]
                update_fields.append("milestone_id = %s")
                params.append(int(val) if val else None)
            if "assigned_to_id" in data:
                val = data["assigned_to_id"]
                update_fields.append("assigned_to_id = %s")
                params.append(int(val) if val else None)
            if "deadline" in data:
                val = data["deadline"]
                update_fields.append("deadline = %s")
                params.append(val if val else None)

        if not update_fields:
            conn.close()
            return jsonify({"error": "No valid fields provided for update"}), 400

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"UPDATE tasks SET {', '.join(update_fields)} WHERE id = %s"
        params.append(task_id)

        # Switch to standard cursor for update execution
        cursor.execute(query, tuple(params))
        conn.commit()

        # Log activity
        log_activity(user_id, 'task_updated', f"Updated task {task_id}", None, task_id=task_id)

        conn.close()
        return jsonify({
            "message": "Task updated successfully",
            "task_id": task_id
        }), 200

    except Exception as e:
        logger.exception("Task update failed")
        if conn: conn.close()
        return jsonify({
            "error": "Task update failed",
            "details": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# Get project details with team members, milestones, tasks, and available members
# Note: /api/admin/projects/<id>/details is handled by get_project_details above
@app.route("/api/projects/<int:project_id>/details", methods=["GET"])
@csrf.exempt
@login_required
def get_project_details_consolidated(project_id):
    """
    Get project details with assigned team members, milestones, tasks, and available members.
    Supports both admin and employee project detail views.
    """
    try:
        # Input validation
        if not project_id or project_id <= 0:
            return jsonify({'error': 'Invalid project ID'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get project details including coordinator info
        cursor.execute('''
            SELECT p.id, p.title, p.description, p.status, p.progress, p.deadline, p.reporting_time, 
                   p.created_by_id, u.username as coordinator_name, u.id as coordinator_id
            FROM projects p
            LEFT JOIN users u ON p.created_by_id = u.id
            WHERE p.id = %s
        ''', (project_id,))
        project_result = cursor.fetchone()
        
        if not project_result:
            conn.close()
            return jsonify({"error": "Project not found"}), 404
        
        # Safely convert to dict
        project = dict(project_result) if hasattr(project_result, 'keys') else {
            'id': project_result[0], 'title': project_result[1], 'description': project_result[2],
            'status': project_result[3], 'progress': project_result[4], 'deadline': project_result[5],
            'reporting_time': project_result[6], 'created_by_id': project_result[7],
            'coordinator_name': project_result[8], 'coordinator_id': project_result[9]
        }

        # Get team members with reporting structure (deduplicated)
        cursor.execute('''
            SELECT DISTINCT
                pa.id as assignment_id, u.id as user_id, u.username, u.email, ut.user_role,
                pa.reporting_manager_id, pa.reports_to_admin,
                (SELECT COUNT(*) FROM project_assignments WHERE reporting_manager_id = u.id AND project_id = %s) as direct_reports_count
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s AND u.username != 'Super Admin'
            ORDER BY u.username
        ''', (project_id, project_id))
        
        team_members = [dict(r) for r in cursor.fetchall()]
        
        # Get milestones
        cursor.execute('SELECT id, title, description, status, due_date FROM milestones WHERE project_id = %s ORDER BY due_date ASC', (project_id,))
        milestones = []
        for m in cursor.fetchall():
            row = dict(m) if hasattr(m, 'keys') else {'id': m[0], 'title': m[1], 'description': m[2], 'status': m[3], 'due_date': m[4]}
            milestones.append({
                'id': row['id'], 
                'title': row['title'],
                'description': row.get('description'),
                'status': row['status'],
                'deadline': row['due_date'].isoformat() if row['due_date'] else None
            })

        # Get tasks
        cursor.execute('''
            SELECT t.id, t.title, t.description, t.status, t.priority, t.deadline, u.username as assigned_to_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to_id = u.id
            WHERE t.project_id = %s
            ORDER BY t.created_at DESC
        ''', (project_id,))
        tasks = []
        for t in cursor.fetchall():
            if hasattr(t, 'keys'):
                row = dict(t)
            else:
                row = {
                    'id': t[0], 'title': t[1], 'description': t[2], 'status': t[3], 
                    'priority': t[4], 'deadline': t[5], 'assigned_to_name': t[6]
                }
            tasks.append({
                'id': row['id'], 
                'title': row['title'],
                'description': row.get('description'),
                'status': row['status'], 
                'priority': row['priority'],
                'assigned_to_name': row.get('assigned_to_name'),
                'deadline': row['deadline'].isoformat() if row['deadline'] else None
            })

        # Get available members (those not in this project)
        cursor.execute('''
            SELECT DISTINCT u.id, u.username, u.email, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.username != 'Super Admin' AND u.id NOT IN (
                SELECT user_id FROM project_assignments WHERE project_id = %s
            )
            ORDER BY u.username
        ''', (project_id,))
        available_members = []
        for r in cursor.fetchall():
            available_members.append(dict(r) if hasattr(r, 'keys') else {
                'id': r[0], 'username': r[1], 'email': r[2], 'user_role': r[3]
            })

        conn.close()
        
        return jsonify({
            'id': project['id'],
            'title': project['title'],
            'description': project['description'],
            'status': project['status'],
            'progress': project['progress'],
            'deadline': project['deadline'].isoformat() if project['deadline'] else None,
            'reporting_time': str(project['reporting_time']) if project['reporting_time'] else None,
            'creator_name': project['coordinator_name'],
            'coordinator_name': project['coordinator_name'],
            'coordinator_id': project['coordinator_id'],
            'team_members': team_members,
            'milestones': milestones,
            'tasks': tasks,
            'available_members': available_members
        }), 200
    except Exception as e:
        logger.exception(f"Error getting project details: {e}")
        return jsonify({"error": str(e)}), 500


# Get project hierarchy
@app.route("/api/projects/<int:project_id>/hierarchy", methods=["GET"])
@csrf.exempt
@login_required
def get_project_hierarchy(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all team members with their reporting structure (deduplicated)
        cursor.execute('''
            SELECT DISTINCT
                pa.id,
                u.id as user_id,
                u.username,
                u.email,
                ut.user_role,
                pa.reporting_manager_id,
                pa.reports_to_admin,
                (SELECT COUNT(*) FROM project_assignments WHERE reporting_manager_id = u.id AND project_id = %s) as direct_reports_count
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s
            ORDER BY u.username
        ''', (project_id, project_id))
        
        team_members = cursor.fetchall()
        
        # Get root members (those without a manager or reporting to admin)
        cursor.execute('''
            SELECT DISTINCT
                pa.id,
                u.id as user_id,
                u.username,
                u.email,
                ut.user_role
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s AND (pa.reporting_manager_id IS NULL OR pa.reports_to_admin = TRUE)
            ORDER BY u.username
        ''', (project_id,))
        
        root_members = cursor.fetchall()
        conn.close()
        
        # Build tree structure with deduplication
        members_map = {}
        for member in team_members:
            # Safely convert member to dict
            if hasattr(member, 'keys'):
                member_dict = dict(member)
            else:
                member_dict = {
                    'id': member[0], 'user_id': member[1], 'username': member[2],
                    'email': member[3], 'user_role': member[4], 'reporting_manager_id': member[5],
                    'reports_to_admin': member[6], 'direct_reports_count': member[7]
                }
            
            if member_dict['user_id'] not in members_map:  # Only add if not already present
                members_map[member_dict['user_id']] = {
                    'assignment_id': member_dict['id'],
                    'user_id': member_dict['user_id'],
                    'username': member_dict['username'],
                    'email': member_dict['email'],
                    'user_role': member_dict['user_role'],
                    'reporting_manager_id': member_dict['reporting_manager_id'],
                    'reports_to_admin': member_dict['reports_to_admin'],
                    'direct_reports': [],
                    'direct_reports_count': member_dict['direct_reports_count']
                }
        
        # Build relationships
        for member in team_members:
            # Safely convert member to dict again
            if hasattr(member, 'keys'):
                member_dict = dict(member)
            else:
                member_dict = {
                    'id': member[0], 'user_id': member[1], 'username': member[2],
                    'email': member[3], 'user_role': member[4], 'reporting_manager_id': member[5],
                    'reports_to_admin': member[6], 'direct_reports_count': member[7]
                }
            
            if member_dict['reporting_manager_id'] and member_dict['reporting_manager_id'] in members_map:
                manager_id = member_dict['reporting_manager_id']
                if member_dict['user_id'] in members_map and members_map[member_dict['user_id']] not in members_map[manager_id]['direct_reports']:
                    members_map[manager_id]['direct_reports'].append(members_map[member_dict['user_id']])
        
        # Build tree for hierarchical view
        tree_structure = []
        for root in root_members:
            # Safely convert root to dict
            if hasattr(root, 'keys'):
                root_dict = dict(root)
            else:
                root_dict = {
                    'id': root[0], 'user_id': root[1], 'username': root[2],
                    'email': root[3], 'user_role': root[4]
                }
            
            root_id = root_dict['user_id']
            if root_id in members_map:
                tree_structure.append(members_map[root_id])
        
        # Flat list for table view (deduplicated)
        flat_list = list(members_map.values())
        
        return jsonify({
            'tree_view': tree_structure,
            'flat_view': flat_list
        }), 200
    except Exception as e:
        logger.error(f"Error getting project hierarchy: {e}")
        return jsonify({"error": str(e)}), 500


# Get available team members (not yet assigned to project)
@app.route("/api/projects/<int:project_id>/available-team-members", methods=["GET"])
@csrf.exempt
@login_required
def get_available_team_members(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all team members not assigned to this project
        cursor.execute('''
            SELECT DISTINCT u.id, u.username, u.email, ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id NOT IN (
                SELECT user_id FROM project_assignments WHERE project_id = %s
            )
            AND (ut.user_role IN ('employee', 'team-member') OR u.user_type_id IS NOT NULL)
            ORDER BY u.username
        ''', (project_id,))
        
        available_members = cursor.fetchall()
        conn.close()
        
        result = []
        for member in available_members:
            member_dict = dict(member) if hasattr(member, 'keys') else {
                'id': member[0], 'username': member[1], 'email': member[2], 'user_role': member[3]
            }
            result.append({
                'user_id': member_dict['id'],
                'username': member_dict['username'],
                'email': member_dict['email'],
                'user_role': member_dict['user_role'] or 'User'
            })
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error getting available team members: {e}")
        return jsonify({"error": str(e)}), 500


# Get assigned employees for a project
@app.route("/api/projects/<int:project_id>/assigned-employees", methods=["GET"])
@csrf.exempt
@login_required
def get_assigned_employees(project_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all employees assigned to this project
        cursor.execute('''
            SELECT DISTINCT
                u.id as user_id,
                u.username,
                u.email,
                ut.user_role,
                (SELECT COUNT(*) FROM project_assignments WHERE reporting_manager_id = u.id AND project_id = %s) as team_members_count
            FROM project_assignments pa
            JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE pa.project_id = %s
            ORDER BY u.username
        ''', (project_id, project_id))
        
        employees = cursor.fetchall()
        conn.close()
        
        result = []
        for emp in employees:
            emp_dict = dict(emp) if hasattr(emp, 'keys') else {
                'user_id': emp[0], 'username': emp[1], 'email': emp[2],
                'user_role': emp[3], 'team_members_count': emp[4]
            }
            result.append({
                'user_id': emp_dict['user_id'],
                'username': emp_dict['username'],
                'name': emp_dict['username'],
                'email': emp_dict['email'],
                'user_role': emp_dict['user_role'] or 'Employee',
                'team_members_count': emp_dict['team_members_count'] or 0
            })
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error getting assigned employees: {e}")
        return jsonify({"error": str(e)}), 500


# Update team member reporting structure
@app.route("/api/projects/<int:project_id>/team-members/<int:member_id>", methods=["PATCH"])
@csrf.exempt
@login_required
def update_team_member_reporting(project_id, member_id):
    try:
        data = request.get_json()
        reporting_manager_id = data.get("reporting_manager_id")
        reports_to_admin = data.get("reports_to_admin", False)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if assignment exists
        cursor.execute('''
            SELECT id FROM project_assignments
            WHERE user_id = %s AND project_id = %s
        ''', (member_id, project_id))
        
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Team member assignment not found"}), 404
        
        # Update reporting structure
        cursor.execute('''
            UPDATE project_assignments
            SET reporting_manager_id = %s, reports_to_admin = %s
            WHERE user_id = %s AND project_id = %s
        ''', (reporting_manager_id, reports_to_admin, member_id, project_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Team member reporting structure updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating team member reporting: {e}")
        return jsonify({"error": str(e)}), 500


# Get team member details with direct reports or remove team member
@app.route("/api/projects/<int:project_id>/team-members/<int:member_id>", methods=["GET", "DELETE"])
@csrf.exempt
@login_required
def manage_team_member(project_id, member_id):
    if request.method == "GET":
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get member details
            cursor.execute('''
                SELECT 
                    u.id,
                    u.username,
                    u.email,
                    ut.user_role,
                    pa.reporting_manager_id,
                    pa.reports_to_admin
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                LEFT JOIN project_assignments pa ON u.id = pa.user_id AND pa.project_id = %s
                WHERE u.id = %s
            ''', (project_id, member_id))
            
            member_row = cursor.fetchone()
            
            if not member_row:
                conn.close()
                return jsonify({"error": "Team member not found"}), 404
            
            # Convert member row to dict safely
            member = dict(member_row) if hasattr(member_row, 'keys') else {
                'id': member_row[0],
                'username': member_row[1],
                'email': member_row[2],
                'user_role': member_row[3],
                'reporting_manager_id': member_row[4],
                'reports_to_admin': member_row[5]
            }
            
            # Get reporting manager name if exists
            reporting_manager_name = None
            if member.get('reporting_manager_id'):
                cursor.execute('SELECT username FROM users WHERE id = %s', (member['reporting_manager_id'],))
                manager = cursor.fetchone()
                reporting_manager_name = dict(manager)['username'] if manager and hasattr(manager, 'keys') else (manager[0] if manager else None)
            
            # Get direct reports
            cursor.execute('''
                SELECT 
                    u.id,
                    u.username,
                    ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                WHERE u.id IN (
                    SELECT user_id FROM project_assignments 
                    WHERE reporting_manager_id = %s AND project_id = %s
                )
                ORDER BY u.username
            ''', (member_id, project_id))
            
            direct_reports_rows = cursor.fetchall()
            conn.close()
            
            # Convert direct_reports properly
            direct_reports_list = []
            for r in direct_reports_rows:
                r_dict = dict(r) if hasattr(r, 'keys') else {
                    'id': r[0],
                    'username': r[1],
                    'user_role': r[2]
                }
                direct_reports_list.append({
                    'user_id': r_dict['id'],
                    'username': r_dict['username'],
                    'user_role': r_dict.get('user_role')
                })
            
            return jsonify({
                'id': member['id'],
                'username': member['username'],
                'email': member['email'],
                'user_role': member['user_role'],
                'reporting_manager_name': reporting_manager_name,
                'reports_to_admin': member.get('reports_to_admin'),
                'direct_reports': direct_reports_list
            }), 200
        except Exception as e:
            logger.error(f"Error getting team member details: {e}")
            return jsonify({"error": str(e)}), 500
    
    elif request.method == "DELETE":
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if assignment exists
            cursor.execute('''
                SELECT id FROM project_assignments
                WHERE user_id = %s AND project_id = %s
            ''', (member_id, project_id))
            
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Team member assignment not found"}), 404
            
            # Delete the assignment
            cursor.execute('''
                DELETE FROM project_assignments
                WHERE user_id = %s AND project_id = %s
            ''', (member_id, project_id))
            
            conn.commit()
            conn.close()
            
            return jsonify({"message": "Team member removed successfully"}), 200
        except Exception as e:
            logger.error(f"Error removing team member: {e}")
            return jsonify({"error": str(e)}), 500


# Get available users (not in project) for adding to project
@app.route("/api/projects/<int:project_id>/available-users", methods=["GET"])
@csrf.exempt
@login_required
def get_available_users_for_project(project_id):
    """Get users not already assigned to this project"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT 
                u.id,
                u.username,
                u.email,
                ut.user_role
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id NOT IN (
                SELECT user_id FROM project_assignments WHERE project_id = %s
            )
            ORDER BY u.username
        ''', (project_id,))
        
        users = cursor.fetchall()
        conn.close()
        
        result = []
        for user in users:
            result.append({
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'user_role': user['user_role']
            })
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error getting available users: {e}")
        return jsonify({"error": str(e)}), 500

# Fix POST endpoint for adding team members - support both routes
@app.route("/api/projects/<int:project_id>/team-members", methods=["POST"])
@csrf.exempt
@login_required
def add_team_member_endpoint(project_id):
    """Add existing team member to project"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        reporting_manager_id = data.get("reporting_manager_id")
        reports_to_admin = data.get("reports_to_admin", True)
        
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "User not found"}), 404
        
        # Check if user already assigned to project
        cursor.execute('''
            SELECT id FROM project_assignments 
            WHERE user_id = %s AND project_id = %s
        ''', (user_id, project_id))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({"error": "User is already assigned to this project"}), 400
        
        # If reporting_manager_id is provided, verify it exists in the project
        if reporting_manager_id:
            cursor.execute('''
                SELECT id FROM project_assignments 
                WHERE user_id = %s AND project_id = %s
            ''', (reporting_manager_id, project_id))
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Reporting manager is not in this project"}), 400
        
        # Add user to project_assignments
        cursor.execute('''
            INSERT INTO project_assignments (user_id, project_id, reporting_manager_id, reports_to_admin)
            VALUES (%s, %s, %s, %s)
        ''', (user_id, project_id, reporting_manager_id, reports_to_admin))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Team member added successfully",
            "user_id": user_id
        }), 201
    except Exception as e:
        logger.error(f"Error adding team member: {e}")
        return jsonify({"error": str(e)}), 500


# Add these routes to main.py

@app.route('/api/users/<int:user_id>/projects', methods=['GET'])
@login_required
def get_user_projects(user_id):
    """Get all projects assigned to a user"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT p.id, p.title, p.status, p.progress, p.deadline
            FROM project_assignments pa
            JOIN projects p ON pa.project_id = p.id
            WHERE pa.user_id = %s
            ORDER BY p.created_at DESC
        ''', (user_id,))

        projects = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(projects), 200
    except Exception as e:
        logger.exception('Error getting user projects')
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<int:user_id>/tasks', methods=['GET'])
@login_required
def get_user_tasks(user_id):
    """Get all tasks assigned to a user"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT t.id, t.title, t.status, t.priority, t.deadline, p.title as project_title
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.assigned_to_id = %s
            ORDER BY t.deadline ASC
        ''', (user_id,))

        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(tasks), 200
    except Exception as e:
        logger.exception('Error getting user tasks')
        return jsonify({'error': str(e)}), 500


@app.route('/api/project-assignments', methods=['POST'])
@admin_required
def create_project_assignment():
    """Assign a user to a project"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        project_id = data.get('project_id')

        if not user_id or not project_id:
            return jsonify({'error': 'user_id and project_id required'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if already assigned
        cursor.execute(
            'SELECT id FROM project_assignments WHERE user_id = %s AND project_id = %s',
            (user_id, project_id)
        )

        if cursor.fetchone():
            conn.close()
            return jsonify({'error': 'User already assigned to this project'}), 409

        # Create assignment
        cursor.execute('''
            INSERT INTO project_assignments (user_id, project_id, reports_to_admin)
            VALUES (%s, %s, TRUE)
        ''', (user_id, project_id))

        conn.commit()
        conn.close()

        log_activity(get_current_user_id(), 'user_assigned_to_project',
                    f'Assigned user {user_id} to project {project_id}',
                    project_id)

        return jsonify({'success': True}), 201
    except Exception as e:
        logger.exception('Error creating project assignment')
        return jsonify({'error': str(e)}), 500


@app.route('/api/project-assignments/<int:user_id>/<int:project_id>', methods=['DELETE'])
@admin_required
def delete_project_assignment(user_id, project_id):
    """Remove a user from a project"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            'DELETE FROM project_assignments WHERE user_id = %s AND project_id = %s',
            (user_id, project_id)
        )

        conn.commit()
        conn.close()

        log_activity(get_current_user_id(), 'user_removed_from_project',
                    f'Removed user {user_id} from project {project_id}',
                    project_id)

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.exception('Error deleting project assignment')
        return jsonify({'error': str(e)}), 500

# ========================================================================
# ENHANCED MULTI-LEVEL USER HIERARCHY ENDPOINTS
# ========================================================================

@app.route("/api/hierarchy/projects", methods=["GET"])
@login_required
def get_projects_with_hierarchy():
    """Get all projects with team leader count and member count"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                p.id,
                p.title,
                p.description,
                p.deadline,
                p.status,
                p.progress,
                COUNT(DISTINCT CASE WHEN ut.user_role = 'Team Leader' THEN pa.user_id END) as team_leader_count,
                COUNT(DISTINCT pa.user_id) as total_members
            FROM projects p
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            LEFT JOIN users u ON pa.user_id = u.id
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            GROUP BY p.id, p.title, p.description, p.deadline, p.status, p.progress
            ORDER BY p.id DESC
        ''')
        
        projects = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(projects), 200
    except Exception as e:
        logger.exception("Error fetching projects with hierarchy")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/projects/<int:project_id>/details", methods=["GET"])
@login_required
def get_project_hierarchy_details(project_id):
    """Get project details with full hierarchy for modal display"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get project
        cursor.execute('''
            SELECT id, title, description, deadline, status, progress 
            FROM projects WHERE id = %s
        ''', (project_id,))
        project = cursor.fetchone()
        
        if not project:
            conn.close()
            return jsonify({"error": "Project not found"}), 404
        
        project_dict = dict(project)
        
        # Get team leaders
        cursor.execute('''
            SELECT DISTINCT
                u.id, u.username, u.email,
                COUNT(DISTINCT pa2.user_id) as sub_member_count
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            LEFT JOIN project_assignments pa ON u.id = pa.user_id AND pa.project_id = %s
            LEFT JOIN project_assignments pa2 ON u.id = pa2.reporting_manager_id AND pa2.project_id = %s
            WHERE ut.user_role = 'Team Leader' AND pa.project_id = %s
            GROUP BY u.id, u.username, u.email
        ''', (project_id, project_id, project_id))
        
        team_leaders = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            "project": project_dict,
            "team_leaders": team_leaders,
            "total_team_leaders": len(team_leaders),
            "overall_progress": project_dict.get("progress", 0)
        }), 200
    except Exception as e:
        logger.exception("Error fetching project hierarchy details")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/leaders/<int:leader_id>/details", methods=["GET"])
@login_required
def get_leader_hierarchy_details(leader_id):
    """Get team leader details with sub-members and progress"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get leader info
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role, u.department,
                   (SELECT COUNT(*) FROM project_assignments WHERE reporting_manager_id = u.id) as sub_members_count
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (leader_id,))
        
        leader = cursor.fetchone()
        if not leader:
            conn.close()
            return jsonify({"error": "Leader not found"}), 404
        
        leader_dict = dict(leader)
        
        # Get sub-members
        cursor.execute('''
            SELECT DISTINCT
                u.id, u.username, u.email, ut.user_role,
                (SELECT COUNT(*) FROM tasks WHERE assigned_to_id = u.id AND status = 'Completed') as completed_tasks,
                (SELECT COUNT(*) FROM tasks WHERE assigned_to_id = u.id) as total_tasks
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            LEFT JOIN project_assignments pa ON u.id = pa.user_id AND pa.reporting_manager_id = %s
            WHERE pa.reporting_manager_id = %s OR pa.user_id IN (
                SELECT user_id FROM project_assignments WHERE reporting_manager_id = %s
            )
            GROUP BY u.id, u.username, u.email, ut.user_role
        ''', (leader_id, leader_id, leader_id))
        
        sub_members = [dict(row) for row in cursor.fetchall()]
        
        # Calculate team progress
        cursor.execute('''
            SELECT 
                SUM(CASE WHEN t.status = 'Completed' THEN t.progress ELSE 0 END)::INTEGER / 
                NULLIF(COUNT(*), 0) as avg_progress
            FROM tasks t
            WHERE t.assigned_to_id IN (
                SELECT user_id FROM project_assignments WHERE reporting_manager_id = %s
            )
        ''', (leader_id,))
        
        progress_result = cursor.fetchone()
        team_progress = dict(progress_result).get("avg_progress", 0) if progress_result else 0
        
        # Get assigned tasks summary
        cursor.execute('''
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress_tasks,
                SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending_tasks
            FROM tasks
            WHERE assigned_to_id = %s
        ''', (leader_id,))
        
        tasks_summary = dict(cursor.fetchone())
        conn.close()
        
        return jsonify({
            "leader": leader_dict,
            "sub_members": sub_members,
            "team_progress": team_progress,
            "tasks_summary": tasks_summary
        }), 200
    except Exception as e:
        logger.exception("Error fetching leader hierarchy details")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/members/<int:member_id>/details", methods=["GET"])
@login_required
def get_member_hierarchy_details(member_id):
    """Get sub-member details with tasks and live progress"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get member info
        cursor.execute('''
            SELECT u.id, u.username, u.email, ut.user_role, u.department, u.phone, u.bio, u.avatar_url,
                   (SELECT COUNT(*) FROM tasks WHERE assigned_to_id = u.id) as total_tasks
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            WHERE u.id = %s
        ''', (member_id,))
        
        member = cursor.fetchone()
        if not member:
            conn.close()
            return jsonify({"error": "Member not found"}), 404
        
        member_dict = dict(member)
        
        # Get assigned project
        cursor.execute('''
            SELECT p.id, p.title, p.description
            FROM projects p
            LEFT JOIN project_assignments pa ON p.id = pa.project_id
            WHERE pa.user_id = %s
            LIMIT 1
        ''', (member_id,))
        
        project = cursor.fetchone()
        project_dict = dict(project) if project else None
        
        # Get all tasks
        cursor.execute('''
            SELECT id, title, description, status, priority, progress, deadline, created_at
            FROM tasks
            WHERE assigned_to_id = %s
            ORDER BY created_at DESC
        ''', (member_id,))
        
        tasks = [dict(row) for row in cursor.fetchall()]
        
        # Calculate statistics
        cursor.execute('''
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress_tasks,
                SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending_tasks,
                AVG(progress) as avg_progress
            FROM tasks
            WHERE assigned_to_id = %s
        ''', (member_id,))
        
        stats = dict(cursor.fetchone()) if cursor.fetchone() else {}
        
        # Get task completion stats
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
                ROUND(100.0 * SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as completion_rate
            FROM tasks
            WHERE assigned_to_id = %s
        ''', (member_id,))
        
        completion = dict(cursor.fetchone()) if cursor.fetchone() else {}
        
        conn.close()
        
        return jsonify({
            "member": member_dict,
            "assigned_project": project_dict,
            "all_tasks": tasks,
            "statistics": stats,
            "completion_stats": completion
        }), 200
    except Exception as e:
        logger.exception("Error fetching member hierarchy details")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/team/<int:team_leader_id>/members", methods=["GET"])
@login_required
def get_team_members_under_leader(team_leader_id):
    """Get all sub-members under a specific team leader"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT
                u.id, u.username, u.email, ut.user_role,
                (SELECT COUNT(*) FROM tasks WHERE assigned_to_id = u.id AND status = 'Completed') as completed_tasks,
                (SELECT COUNT(*) FROM tasks WHERE assigned_to_id = u.id) as total_tasks,
                (SELECT AVG(progress) FROM tasks WHERE assigned_to_id = u.id) as avg_progress
            FROM users u
            LEFT JOIN usertypes ut ON u.user_type_id = ut.id
            LEFT JOIN project_assignments pa ON u.id = pa.user_id
            WHERE pa.reporting_manager_id = %s
            ORDER BY u.username
        ''', (team_leader_id,))
        
        members = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(members), 200
    except Exception as e:
        logger.exception("Error fetching team members")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/live-progress/<int:member_id>", methods=["GET"])
@login_required
def get_member_live_progress(member_id):
    """Get live progress data for a member (auto-updates when task status changes)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks,
                SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress_tasks,
                AVG(progress) as avg_progress,
                ROUND(100.0 * SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as completion_rate
            FROM tasks
            WHERE assigned_to_id = %s
        ''', (member_id,))
        
        progress_data = dict(cursor.fetchone()) if cursor.fetchone() else {}
        conn.close()
        
        return jsonify(progress_data), 200
    except Exception as e:
        logger.exception("Error fetching live progress")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hierarchy/expand/<string:node_type>/<int:node_id>", methods=["GET"])
@login_required
def expand_hierarchy_node(node_type, node_id):
    """Dynamically expand a hierarchy node (project, leader, or member)"""
    try:
        if node_type == "project":
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get team leaders for this project
            cursor.execute('''
                SELECT DISTINCT
                    u.id, u.username, u.email, ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                LEFT JOIN project_assignments pa ON u.id = pa.user_id
                WHERE ut.user_role = 'Team Leader' AND pa.project_id = %s
                ORDER BY u.username
            ''', (node_id,))
            
            children = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return jsonify({"children": children}), 200
        
        elif node_type == "leader":
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get sub-members for this leader
            cursor.execute('''
                SELECT DISTINCT
                    u.id, u.username, u.email, ut.user_role
                FROM users u
                LEFT JOIN usertypes ut ON u.user_type_id = ut.id
                LEFT JOIN project_assignments pa ON u.id = pa.user_id
                WHERE pa.reporting_manager_id = %s
                ORDER BY u.username
            ''', (node_id,))
            
            children = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return jsonify({"children": children}), 200
        
        else:
            return jsonify({"error": "Invalid node type"}), 400
    except Exception as e:
        logger.exception(f"Error expanding hierarchy node {node_type}/{node_id}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Local development configuration
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "True").lower() == "true"
    app.run(host="127.0.0.1", port=port, debug=debug)
