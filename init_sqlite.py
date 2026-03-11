"""
SQLite Database Initialization Script
Converts PostgreSQL schema to SQLite with all required tables
"""

import sqlite3
import os
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path - creates SQLite database in project root
DB_PATH = os.path.join(os.path.dirname(__file__), 'slrddemo.db')


def get_db_connection():
    """Create SQLite connection with row factory"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Makes rows accessible like dictionaries
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
    return conn


def init_db():
    """Initialize SQLite database with all tables (idempotent)"""
    conn = None
    cursor = None
    try:
        logger.info(f"Starting SQLite database initialization at {DB_PATH}...")
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

        # Create milestones table (must come before tasks that reference it)
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
        logger.debug("✓ tasks table ready")

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
        
        # Create index on progress_history for better query performance
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

        # Seed initial data if usertypes are empty
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
                cursor.execute(
                    "INSERT INTO usertypes (user_role, description) VALUES (?, ?)",
                    (role, desc)
                )
                ids[role] = cursor.lastrowid
            else:
                ids[role] = existing_types[role]
                cursor.execute(
                    "UPDATE usertypes SET description = ? WHERE id = ? AND (description IS NULL OR description = '' OR description = '-')",
                    (desc, ids[role])
                )

        # Helper to seed permissions
        def seed_perms(ut_id, perms):
            if not ut_id:
                return
            for module, action in perms:
                cursor.execute(
                    "SELECT id FROM usertype_permissions WHERE usertype_id = ? AND module = ? AND action = ?",
                    (ut_id, module, action)
                )
                exists_row = cursor.fetchone()
                if exists_row:
                    cursor.execute(
                        "UPDATE usertype_permissions SET granted = ? WHERE id = ?",
                        (True, exists_row['id'])
                    )
                else:
                    cursor.execute(
                        "INSERT INTO usertype_permissions (usertype_id, module, action, granted) VALUES (?, ?, ?, ?)",
                        (ut_id, module, action, True)
                    )

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
        logger.info(f"[OK] SQLite database initialized successfully at {DB_PATH}!")
        return True

    except Exception as e:
        logger.error(f"[ERROR] Database initialization failed: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def check_db_status():
    """Check if database exists and has tables"""
    try:
        if not os.path.exists(DB_PATH):
            logger.info(f"Database file does not exist at {DB_PATH}")
            return False
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        logger.info(f"Database has {len(tables)} tables: {[t[0] for t in tables]}")
        cursor.close()
        conn.close()
        return len(tables) > 0
    except Exception as e:
        logger.error(f"Error checking database status: {e}")
        return False


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("SQLite Database Initialization")
    logger.info("=" * 60)
    
    # Check if database already exists
    if os.path.exists(DB_PATH):
        logger.info(f"Database file already exists at {DB_PATH}")
        logger.info("Checking schema...")
        check_db_status()
    else:
        logger.info(f"Creating new database at {DB_PATH}")
    
    # Initialize database
    if init_db():
        logger.info("Database initialization completed successfully!")
        check_db_status()
    else:
        logger.error("Database initialization failed!")
        exit(1)
