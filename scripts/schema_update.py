import os
import sys

import paramiko
from dotenv import find_dotenv, load_dotenv

# Load credentials from .env (SSH_HOST, SSH_USER, SSH_PASSWORD)
load_dotenv(find_dotenv())

host = os.environ.get("SSH_HOST")
user = os.environ.get("SSH_USER", "root")
pw = os.environ.get("SSH_PASSWORD")

if not host or not pw:
    print("Error: SSH_HOST and SSH_PASSWORD must be set in .env")
    sys.exit(1)

sql_commands = [
    "ALTER TABLE bible_verses ADD COLUMN IF NOT EXISTS version TEXT;",
    "UPDATE bible_verses SET version = 'NKRV' WHERE version IS NULL;",
    "ALTER TABLE bible_sections ADD COLUMN IF NOT EXISTS version TEXT;",
    "UPDATE bible_sections SET version = 'NKRV' WHERE version IS NULL;",
    "ALTER TABLE bible_verses DROP CONSTRAINT IF EXISTS bible_verses_unique_verse;",
    "ALTER TABLE bible_verses ADD CONSTRAINT bible_verses_unique_verse UNIQUE (book, chapter, verse_start, version);",
    "CREATE OR REPLACE FUNCTION public.match_bible_sections_v(query_embedding vector, match_threshold double precision, match_count integer, version_filter text) RETURNS TABLE(id uuid, book text, chapter integer, verse_range text, title text, content text, similarity double precision) LANGUAGE plpgsql AS 'begin return query select bs.id, bs.book, bs.chapter, bs.verse_range, bs.title, bs.content, 1 - (bs.embedding <=> query_embedding) as similarity from bible_sections bs where 1 - (bs.embedding <=> query_embedding) > match_threshold and bs.version = version_filter order by bs.embedding <=> query_embedding limit match_count; end;'"
]

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=pw)
    
    print(f"Connected to {host}")
    
    for cmd in sql_commands:
        print(f"Executing: {cmd}")
        full_cmd = f"docker exec -u postgres supabase-db psql -d postgres -c \"{cmd}\""
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        
        out = stdout.read().decode()
        err = stderr.read().decode()
        
        if out: print(f"Output: {out}")
        if err: print(f"Error: {err}")
    
    ssh.close()
    print("Schema update completed successfully.")
except Exception as e:
    print(f"Failed to execute command: {e}")
    sys.exit(1)
