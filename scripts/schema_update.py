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
    "ALTER TABLE bible_verses ADD COLUMN IF NOT EXISTS section_id UUID REFERENCES bible_sections(id) ON DELETE SET NULL;"
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
