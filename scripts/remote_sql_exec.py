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

sql_command = "docker exec -u postgres supabase-db psql -d postgres -c 'TRUNCATE TABLE bible_sections;'"

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=pw)
    
    print(f"Connected to {host}")
    print("Cleaning up bible_sections table...")
    stdin, stdout, stderr = ssh.exec_command(sql_command)
    
    out = stdout.read().decode()
    err = stderr.read().decode()
    
    if out: print(f"Output: {out}")
    if err: print(f"Error: {err}")
    
    ssh.close()
    print("Table truncated successfully. Ready for a clean start.")
except Exception as e:
    print(f"Failed to execute command: {e}")
    sys.exit(1)
