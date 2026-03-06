import psycopg2
import os
from urllib.parse import urlparse

def check_milestone_schema():
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
    
    print("Columns in milestones:")
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'milestones'")
    for row in cur.fetchall():
        print(row)
        
    print("\nColumns in tasks:")
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'tasks'")
    for row in cur.fetchall():
        print(row)
        
    conn.close()

if __name__ == "__main__":
    check_milestone_schema()
