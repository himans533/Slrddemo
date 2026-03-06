import psycopg2
import os
from urllib.parse import urlparse

def check_schema():
    database_url = 'postgresql://postgres:VrRTkkkxSWEVvXEGSBAhrsCmFPpQWPJD@postgres.railway.internal:5432/railway'
    if not database_url:
        print("No DATABASE_URL")
        return
    
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    result = urlparse(database_url)
    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    cur = conn.cursor()
    
    print("Columns in project_assignments:")
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'project_assignments'")
    for row in cur.fetchall():
        print(row)
        
    print("\nSearching for 'Rishi' in users:")
    cur.execute("SELECT id, username, email FROM users WHERE username ILIKE '%Rishi%'")
    for row in cur.fetchall():
        print(row)
        
    print("\nRecent assignments for project 4:")
    cur.execute("SELECT pa.*, u.username FROM project_assignments pa JOIN users u ON pa.user_id = u.id WHERE project_id = 4")
    for row in cur.fetchall():
        print(row)
        
    conn.close()

if __name__ == "__main__":
    check_schema()
