# SQLite Database Schema Reference

Complete SQLite schema for SLRD Dashboard with all tables, columns, data types, and relationships.

## Table of Contents

1. [User Management Tables](#user-management-tables)
2. [Project Management Tables](#project-management-tables)
3. [Task Management Tables](#task-management-tables)
4. [Reporting Tables](#reporting-tables)
5. [Audit & Activity Tables](#audit--activity-tables)

---

## User Management Tables

### Table: `usertypes`
Defines user roles in the system.

```sql
CREATE TABLE usertypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_role TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Default Roles:**
- Administrator
- Employee
- Project-Cordinator

---

### Table: `usertype_permissions`
Defines permissions for each user role.

```sql
CREATE TABLE usertype_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usertype_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    granted BOOLEAN DEFAULT 0,
    FOREIGN KEY (usertype_id) REFERENCES usertypes(id) ON DELETE CASCADE,
    UNIQUE(usertype_id, module, action)
);
```

**Sample Permissions:**
- ADMIN: VIEW_HIERARCHY, CREATE_USERTYPE, MANAGE_PERMISSIONS
- PROJ: VIEW_ALL, CREATE, EDIT, DELETE, ASSIGN_COORD
- TASK: VIEW, CREATE, ASSIGN, EDIT
- REP: VIEW, APPROVE, REJECT

---

### Table: `users`
User accounts and profiles.

```sql
CREATE TABLE users (
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
);
```

**Columns:**
- `username`: Unique login name
- `email`: Contact email
- `password`: Hashed password
- `user_type_id`: Reference to usertypes
- `granted`: Account approval status
- `status`: Active/Inactive
- `created_by_id`: Admin who created user

---

### Table: `user_permissions`
Individual user-specific permissions (overrides role permissions).

```sql
CREATE TABLE user_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    granted BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, module, action)
);
```

---

### Table: `user_skills`
Skills associated with users.

```sql
CREATE TABLE user_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    skill_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, skill_name)
);
```

---

## Project Management Tables

### Table: `projects`
Main project records.

```sql
CREATE TABLE projects (
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
);
```

**Columns:**
- `progress`: Percentage completion (0-100)
- `deadline`: Project due date
- `reporting_time`: Daily report submission time
- `status`: In Progress / Completed / On Hold / Cancelled

---

### Table: `milestones`
Project milestones/phases.

```sql
CREATE TABLE milestones (
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
);
```

**Columns:**
- `weightage`: Importance weight (1-5)
- `status`: Pending / In Progress / Completed

---

### Table: `project_assignments`
Links users to projects and assigns reporting managers.

```sql
CREATE TABLE project_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    reporting_manager_id INTEGER,
    reports_to_admin BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (reporting_manager_id) REFERENCES users(id),
    UNIQUE(user_id, project_id)
);
```

---

### Table: `progress_history`
Historical progress tracking for projects.

```sql
CREATE TABLE progress_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    progress_percentage INTEGER,
    tasks_completed INTEGER,
    total_tasks INTEGER,
    milestones_completed INTEGER,
    total_milestones INTEGER,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX idx_progress_project_date ON progress_history(project_id, recorded_at);
```

---

## Task Management Tables

### Table: `tasks`
Individual tasks within projects.

```sql
CREATE TABLE tasks (
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
);
```

**Columns:**
- `status`: Pending / In Progress / Completed / Blocked
- `priority`: Low / Medium / High / Critical
- `approval_status`: pending / approved / rejected
- `weightage`: Task importance (1-5)
- `progress`: Percentage completion (0-100)

---

### Table: `comments`
Comments on projects and tasks.

```sql
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    project_id INTEGER,
    task_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

---

### Table: `documents`
File uploads for projects and tasks.

```sql
CREATE TABLE documents (
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
);
```

---

## Reporting Tables

### Table: `daily_task_reports`
Daily task progress reports.

```sql
CREATE TABLE daily_task_reports (
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
);
```

**Columns:**
- `report_date`: Date of report (DATE format YYYY-MM-DD)
- `time_spent`: Hours worked (REAL/FLOAT)
- `approval_status`: pending / approved / rejected
- `is_locked`: 1 = approved/locked, 0 = editable
- `blocker`: Obstacles encountered

---

### Table: `report_comments`
Comments on daily task reports.

```sql
CREATE TABLE report_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    commenter_id INTEGER NOT NULL,
    comment TEXT NOT NULL,
    internal BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES daily_task_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (commenter_id) REFERENCES users(id)
);
```

---

## Audit & Activity Tables

### Table: `activities`
User activity log.

```sql
CREATE TABLE activities (
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
);
```

**Activity Types:**
- LOGIN, LOGOUT
- PROJECT_CREATED, PROJECT_UPDATED, PROJECT_DELETED
- TASK_CREATED, TASK_ASSIGNED, TASK_COMPLETED
- REPORT_SUBMITTED, REPORT_APPROVED, REPORT_REJECTED

---

### Table: `audit_logs`
System audit trail.

```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Target Types:**
- USER, PROJECT, TASK, REPORT, MILESTONE

---

## Relationships Diagram

```
usertypes (1) ──── (M) usertype_permissions
              ──── (M) users
                        │
                        ├─ (M) projects
                        ├─ (M) tasks
                        ├─ (M) daily_task_reports
                        ├─ (M) activities
                        └─ (M) user_skills

projects (1) ──── (M) milestones
            ──── (M) tasks
            ──── (M) comments
            ──── (M) documents
            ──── (M) project_assignments
            ──── (M) progress_history
            ──── (M) daily_task_reports

tasks (1) ──── (M) comments
        ──── (M) documents
        ──── (M) daily_task_reports
        └─ (1) milestones

milestones (1) ──── (M) tasks
              ──── (M) activities

daily_task_reports (1) ──── (M) report_comments
```

---

## Data Type Mapping

| SQLite Type | Python Type | Usage |
|-------------|-------------|-------|
| INTEGER | int | IDs, counts, weights |
| TEXT | str | Names, descriptions, content |
| DATE | date | Deadlines, report dates |
| TIME | time | Report times |
| TIMESTAMP | datetime | Creation/update times |
| REAL | float | Hours, percentages |
| BOOLEAN | int (0/1) | Flags, status |

---

## Sample Queries

### Get all users in a project
```sql
SELECT u.id, u.username, u.email
FROM users u
JOIN project_assignments pa ON u.id = pa.user_id
WHERE pa.project_id = ?;
```

### Get daily reports by user for date range
```sql
SELECT * FROM daily_task_reports
WHERE user_id = ? 
AND report_date BETWEEN ? AND ?
ORDER BY report_date DESC;
```

### Count pending approvals by reviewer
```sql
SELECT reviewed_by, COUNT(*) as pending_count
FROM daily_task_reports
WHERE approval_status = 'pending'
GROUP BY reviewed_by;
```

### Get project progress over time
```sql
SELECT recorded_at, progress_percentage
FROM progress_history
WHERE project_id = ?
ORDER BY recorded_at;
```

---

## Backup and Restore

### SQLite Dump (text format)
```bash
sqlite3 slrddemo.db ".dump" > slrddemo.sql
```

### Restore from dump
```bash
sqlite3 slrddemo_new.db < slrddemo.sql
```

### Binary backup
```bash
cp slrddemo.db slrddemo_backup.db
```

---

## Maintenance Commands

### Optimize database (free unused space)
```sql
VACUUM;
```

### Analyze query performance
```sql
ANALYZE;
```

### Check database integrity
```sql
PRAGMA integrity_check;
```

### Enable foreign key constraints
```sql
PRAGMA foreign_keys = ON;
```

---

**Last Updated:** March 11, 2026
**Database Version:** SQLite 3.40+
**Python Version:** 3.8+
