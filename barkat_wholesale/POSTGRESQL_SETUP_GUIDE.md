# PostgreSQL Setup Guide for Barkat Wholesale ERP

## 📋 Table of Contents
1. [PostgreSQL Installation](#1-postgresql-installation)
2. [PostgreSQL Database Setup](#2-postgresql-database-setup)
3. [Connect Django Project to PostgreSQL](#3-connect-django-project-to-postgresql)
4. [Database Migrations](#4-database-migrations)
5. [Useful PostgreSQL Commands](#5-useful-postgresql-commands)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. PostgreSQL Installation

### Windows Installation
```powershell
# Download PostgreSQL from: https://www.postgresql.org/download/windows/
# Or use Chocolatey:
choco install postgresql

# Or use winget:
winget install PostgreSQL.PostgreSQL
```

### Linux (Ubuntu/Debian)
```bash
# Update package list
sudo apt update

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Check status
sudo systemctl status postgresql
```

### macOS
```bash
# Using Homebrew
brew install postgresql@15

# Start PostgreSQL service
brew services start postgresql@15
```

---

## 2. PostgreSQL Database Setup

### Step 1: Access PostgreSQL
```bash
# Windows (open psql from PostgreSQL installation folder)
# Or use Command Prompt:
psql -U postgres

# Linux/macOS
sudo -u postgres psql
```

### Step 2: Create Database and User

```sql
-- Connect to PostgreSQL as superuser
-- psql -U postgres

-- Create a new database
CREATE DATABASE barkat_wholesale;

-- Create a new user (replace 'your_password' with a strong password)
CREATE USER barkat_user WITH PASSWORD 'your_strong_password_here';

-- Grant all privileges on database to the user
GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO barkat_user;

-- Grant privileges on schema (PostgreSQL 15+)
\c barkat_wholesale
GRANT ALL ON SCHEMA public TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO barkat_user;

-- Optional: Make user a superuser (for development only)
ALTER USER barkat_user CREATEDB;

-- Exit PostgreSQL
\q
```

### Alternative: One-line command (Linux/macOS)
```bash
sudo -u postgres psql << EOF
CREATE DATABASE barkat_wholesale;
CREATE USER barkat_user WITH PASSWORD 'your_strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO barkat_user;
\c barkat_wholesale
GRANT ALL ON SCHEMA public TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO barkat_user;
EOF
```

---

## 3. Connect Django Project to PostgreSQL

### Step 1: Verify psycopg2 is installed
```bash
# Already in requirements.txt, but verify:
pip install psycopg2-binary==2.9.9

# Or install all requirements
pip install -r requirements.txt
```

### Step 2: Update settings.py (Already configured!)
The `barkat_wholesale/settings.py` is already configured. You can:

**Option A: Use default values (for development)**
```python
# settings.py is already configured with these defaults:
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'barkat_wholesale',
        'USER': 'postgres',
        'PASSWORD': 'postgres',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

**Option B: Use environment variables (Recommended for production)**
```bash
# Windows PowerShell
$env:DB_NAME="barkat_wholesale"
$env:DB_USER="barkat_user"
$env:DB_PASSWORD="your_strong_password_here"
$env:DB_HOST="localhost"
$env:DB_PORT="5432"

# Windows CMD
set DB_NAME=barkat_wholesale
set DB_USER=barkat_user
set DB_PASSWORD=your_strong_password_here
set DB_HOST=localhost
set DB_PORT=5432

# Linux/macOS
export DB_NAME="barkat_wholesale"
export DB_USER="barkat_user"
export DB_PASSWORD="your_strong_password_here"
export DB_HOST="localhost"
export DB_PORT="5432"

# For permanent setup, add to ~/.bashrc or ~/.zshrc:
echo 'export DB_NAME="barkat_wholesale"' >> ~/.bashrc
echo 'export DB_USER="barkat_user"' >> ~/.bashrc
echo 'export DB_PASSWORD="your_strong_password_here"' >> ~/.bashrc
```

**Option C: Create .env file (Most Secure)**
```bash
# Create .env file in project root
# Windows
echo DB_NAME=barkat_wholesale > .env
echo DB_USER=barkat_user >> .env
echo DB_PASSWORD=your_strong_password_here >> .env
echo DB_HOST=localhost >> .env
echo DB_PORT=5432 >> .env

# Linux/macOS
cat > .env << EOF
DB_NAME=barkat_wholesale
DB_USER=barkat_user
DB_PASSWORD=your_strong_password_here
DB_HOST=localhost
DB_PORT=5432
EOF
```

**Then install python-dotenv and update settings.py:**
```bash
pip install python-dotenv
```

Update `settings.py` to load .env:
```python
from dotenv import load_dotenv
load_dotenv()
```

### Step 3: Test Database Connection
```bash
# Test connection using Django
python manage.py dbshell

# You should see: psql prompt if successful
# Type \q to exit
```

Or test from Python:
```bash
python manage.py shell
```
```python
from django.db import connection
cursor = connection.cursor()
cursor.execute("SELECT version();")
print(cursor.fetchone())
```

---

## 4. Database Migrations

### Step 1: Remove old SQLite database (if exists)
```bash
# Backup SQLite if needed
# Windows
if exist db.sqlite3 copy db.sqlite3 db.sqlite3.backup

# Linux/macOS
if [ -f db.sqlite3 ]; then cp db.sqlite3 db.sqlite3.backup; fi
```

### Step 2: Create migrations
```bash
# Make migrations for all apps
python manage.py makemigrations

# Create migrations for specific app
python manage.py makemigrations barkat
```

### Step 3: Run migrations
```bash
# Apply all migrations
python manage.py migrate

# Apply migrations for specific app
python manage.py migrate barkat

# Show migration status
python manage.py showmigrations

# Check what migrations would be applied
python manage.py migrate --plan
```

### Step 4: Create superuser
```bash
python manage.py createsuperuser
```

---

## 5. Useful PostgreSQL Commands

### Connection Commands
```bash
# Connect to PostgreSQL
psql -U postgres
psql -U barkat_user -d barkat_wholesale

# Connect with password prompt
psql -U barkat_user -d barkat_wholesale -h localhost

# Connect from command line with connection string
psql postgresql://barkat_user:password@localhost:5432/barkat_wholesale
```

### Database Management
```sql
-- List all databases
\l

-- Connect to a database
\c barkat_wholesale

-- List all tables in current database
\dt

-- List all tables with details
\dt+

-- Describe a table structure
\d table_name

-- List all schemas
\dn

-- List all users/roles
\du

-- Show current database
SELECT current_database();

-- Show current user
SELECT current_user;

-- Show all tables and their sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### User Management
```sql
-- Create user
CREATE USER username WITH PASSWORD 'password';

-- Change password
ALTER USER username WITH PASSWORD 'new_password';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE dbname TO username;

-- Revoke privileges
REVOKE ALL PRIVILEGES ON DATABASE dbname FROM username;

-- List all users
\du

-- Drop user
DROP USER username;
```

### Database Backup & Restore
```bash
# Backup database (Windows)
pg_dump -U barkat_user -d barkat_wholesale -F c -f backup.dump

# Backup database (Linux/macOS)
pg_dump -U barkat_user -d barkat_wholesale > backup.sql

# Backup with custom format
pg_dump -U barkat_user -d barkat_wholesale -F c -f backup.dump

# Restore from SQL file
psql -U barkat_user -d barkat_wholesale < backup.sql

# Restore from custom format
pg_restore -U barkat_user -d barkat_wholesale backup.dump

# Backup with timestamp
pg_dump -U barkat_user -d barkat_wholesale > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Performance & Maintenance
```sql
-- Show database size
SELECT pg_size_pretty(pg_database_size('barkat_wholesale'));

-- Show table sizes
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Vacuum database (clean up)
VACUUM;

-- Analyze database (update statistics)
ANALYZE;

-- Vacuum and analyze
VACUUM ANALYZE;

-- Show active connections
SELECT * FROM pg_stat_activity;

-- Kill a specific connection
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'barkat_wholesale' AND pid <> pg_backend_pid();
```

### Query Commands
```sql
-- Count rows in a table
SELECT COUNT(*) FROM table_name;

-- Show table columns
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'table_name';

-- Show indexes
\di

-- Show foreign keys
SELECT
    tc.table_name, 
    kcu.column_name, 
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name 
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE constraint_type = 'FOREIGN KEY';
```

---

## 6. Troubleshooting

### Connection Issues

**Error: "FATAL: password authentication failed"**
```bash
# Edit pg_hba.conf (location varies by OS)
# Windows: C:\Program Files\PostgreSQL\15\data\pg_hba.conf
# Linux: /etc/postgresql/15/main/pg_hba.conf
# macOS: /usr/local/var/postgres/pg_hba.conf

# Change this line:
# host    all             all             127.0.0.1/32            md5
# To:
host    all             all             127.0.0.1/32            trust

# Restart PostgreSQL
# Windows: Restart service from Services
# Linux: sudo systemctl restart postgresql
```

**Error: "could not connect to server"**
```bash
# Check if PostgreSQL is running
# Windows: Check Services
# Linux: sudo systemctl status postgresql
# macOS: brew services list

# Check if port 5432 is open
netstat -an | grep 5432
# or
lsof -i :5432
```

**Error: "database does not exist"**
```sql
-- List databases
\l

-- Create database if missing
CREATE DATABASE barkat_wholesale;
```

**Error: "permission denied"**
```sql
-- Grant privileges again
GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO barkat_user;
\c barkat_wholesale
GRANT ALL ON SCHEMA public TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO barkat_user;
```

### Migration Issues

**Reset all migrations (CAUTION: Deletes all data!)**
```bash
# Delete migration files (keep __init__.py)
# Windows PowerShell
Get-ChildItem -Path barkat\migrations -Filter "*.py" | Where-Object { $_.Name -ne "__init__.py" } | Remove-Item

# Linux/macOS
find barkat/migrations -name "*.py" ! -name "__init__.py" -delete

# Drop all tables and recreate
python manage.py flush
python manage.py makemigrations
python manage.py migrate
```

**Check migration status**
```bash
python manage.py showmigrations
python manage.py migrate --plan
```

### Performance Issues

**Slow queries**
```sql
-- Enable query logging (temporarily)
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log queries > 1 second
SELECT pg_reload_conf();

-- Check slow queries
SELECT query, calls, total_time, mean_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

---

## Quick Start Checklist

- [ ] Install PostgreSQL
- [ ] Start PostgreSQL service
- [ ] Create database: `CREATE DATABASE barkat_wholesale;`
- [ ] Create user: `CREATE USER barkat_user WITH PASSWORD 'password';`
- [ ] Grant privileges
- [ ] Install psycopg2-binary: `pip install psycopg2-binary`
- [ ] Configure settings.py (already done!)
- [ ] Test connection: `python manage.py dbshell`
- [ ] Run migrations: `python manage.py migrate`
- [ ] Create superuser: `python manage.py createsuperuser`
- [ ] Test application

---

## Production Recommendations

1. **Use environment variables** for database credentials
2. **Never commit** `.env` files to version control
3. **Use strong passwords** for database users
4. **Enable SSL** for remote connections
5. **Set up regular backups** using pg_dump
6. **Monitor database** performance and size
7. **Use connection pooling** (pgBouncer) for high traffic
8. **Restrict database user** permissions (avoid superuser in production)

---

For more information, visit: https://www.postgresql.org/docs/
