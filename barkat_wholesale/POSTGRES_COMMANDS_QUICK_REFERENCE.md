# PostgreSQL Quick Reference Commands

## 🚀 Quick Setup (Copy & Paste)

### 1. Install PostgreSQL & Connect
```bash
# Linux - Install
sudo apt update && sudo apt install postgresql postgresql-contrib

# Connect as postgres user
sudo -u postgres psql
```

### 2. Create Database & User (Run in psql)
```sql
-- Create database
CREATE DATABASE barkat_wholesale;

-- Create user with password
CREATE USER barkat_user WITH PASSWORD 'your_password_here';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO barkat_user;

-- Connect to database
\c barkat_wholesale

-- Grant schema privileges (PostgreSQL 15+)
GRANT ALL ON SCHEMA public TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO barkat_user;
```

### 3. Django Setup Commands
```bash
# Install PostgreSQL adapter (already in requirements.txt)
pip install psycopg2-binary

# Install python-dotenv for .env support (optional)
pip install python-dotenv

# Test connection
python manage.py dbshell

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

---

## 📝 Essential PostgreSQL Commands

### Connection
```bash
# Connect to database
psql -U barkat_user -d barkat_wholesale

# Connect with host
psql -U barkat_user -d barkat_wholesale -h localhost

# Exit psql
\q
```

### Database Info
```sql
-- List databases
\l

-- List tables
\dt

-- Describe table
\d table_name

-- List users
\du

-- Show current database
SELECT current_database();

-- Show database size
SELECT pg_size_pretty(pg_database_size('barkat_wholesale'));
```

### Backup & Restore
```bash
# Backup
pg_dump -U barkat_user -d barkat_wholesale > backup.sql

# Restore
psql -U barkat_user -d barkat_wholesale < backup.sql

# Backup with timestamp
pg_dump -U barkat_user -d barkat_wholesale > backup_$(date +%Y%m%d).sql
```

---

## 🔧 Environment Variables Setup

### Windows PowerShell
```powershell
$env:DB_NAME="barkat_wholesale"
$env:DB_USER="barkat_user"
$env:DB_PASSWORD="your_password"
$env:DB_HOST="localhost"
$env:DB_PORT="5432"
```

### Windows CMD
```cmd
set DB_NAME=barkat_wholesale
set DB_USER=barkat_user
set DB_PASSWORD=your_password
set DB_HOST=localhost
set DB_PORT=5432
```

### Linux/macOS
```bash
export DB_NAME="barkat_wholesale"
export DB_USER="barkat_user"
export DB_PASSWORD="your_password"
export DB_HOST="localhost"
export DB_PORT="5432"
```

### Create .env File
```bash
# Linux/macOS/Windows Git Bash
cat > .env << EOF
DB_NAME=barkat_wholesale
DB_USER=barkat_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
EOF
```

---

## ✅ Complete Setup Sequence

```bash
# 1. Install PostgreSQL
sudo apt install postgresql postgresql-contrib  # Linux
# OR download from postgresql.org for Windows/Mac

# 2. Start PostgreSQL
sudo systemctl start postgresql  # Linux
sudo systemctl enable postgresql  # Auto-start on boot

# 3. Create database & user
sudo -u postgres psql
# Then run SQL commands from section 2 above

# 4. Install Python dependencies
pip install -r requirements.txt
pip install python-dotenv  # Optional for .env support

# 5. Set environment variables OR create .env file

# 6. Test connection
python manage.py dbshell
# Type \q to exit

# 7. Run migrations
python manage.py migrate

# 8. Create admin user
python manage.py createsuperuser

# 9. Run server
python manage.py runserver
```

---

## 🐛 Common Issues & Fixes

### Issue: "password authentication failed"
```sql
-- Edit pg_hba.conf, change 'md5' to 'trust' for local connections
-- Then restart PostgreSQL
sudo systemctl restart postgresql
```

### Issue: "could not connect to server"
```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list  # macOS

# Start if not running
sudo systemctl start postgresql
```

### Issue: "permission denied"
```sql
-- Re-grant privileges
\c barkat_wholesale
GRANT ALL ON SCHEMA public TO barkat_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO barkat_user;
```

---

## 📊 Useful Queries

```sql
-- Count rows in all tables
SELECT 
    schemaname,
    tablename,
    n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;

-- Show largest tables
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Show active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'barkat_wholesale';
```

---

**For detailed setup instructions, see `POSTGRESQL_SETUP_GUIDE.md`**
