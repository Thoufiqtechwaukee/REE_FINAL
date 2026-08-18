import psycopg2

conn = psycopg2.connect("postgresql://postgres.gzwwwjksyrpkspxrcuny:Thoufiq%40techwaukee@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres")
cur = conn.cursor()

for table in ["resumes", "resume_chunks", "resume_extractions", "resume_sections", "resume_skills"]:
    cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}';")
    cols = [r[0] for r in cur.fetchall()]
    print(f"Table '{table}' columns: {cols}")

conn.close()
