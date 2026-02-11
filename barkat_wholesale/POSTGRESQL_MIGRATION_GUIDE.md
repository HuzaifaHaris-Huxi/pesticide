# PostgreSQL Migration Guide

This guide will help you migrate your Barkat Wholesale application from SQLite3 to PostgreSQL.

## Changes Made

### 1. **requirements.txt**
- Added `psycopg2-binary==2.9.9` (PostgreSQL adapter for Python)

### 2. **barkat_wholesale/settings.py**
- Updated database configuration to use PostgreSQL
- Added support for environment variables for database credentials

### 3. **barkat/management/commands/wipe_barkat_data.py**
- Fixed SQLite placeholder bug (changed `%s` to `?`)
- Enhanced PostgreSQL sequence reset handling

## Migration Steps

### Step 1: Install PostgreSQL

#### Windows:
1. Download PostgreSQL from: https://www.postgresql.org/download/windows/
2. Install PostgreSQL (default port: 5432)
3. Remember the postgres user password you set during installation

#### Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### macOS:
```bash
brew install postgresql@15
brew services start postgresql@15
```

### Step 2: Create PostgreSQL Database

```bash
# Login to PostgreSQL as postgres user
psql -U postgres

# Create database
CREATE DATABASE barkat_wholesale;

# Create a dedicated user (optional but recommended)
CREATE USER barkat_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO barkat_user;

# Exit psql
\q
```

### Step 3: Install Python Dependencies

```bash
# Install new dependencies
pip install -r requirements.txt
```

This will install `psycopg2-binary` along with other dependencies.

### Step 4: Configure Database Settings

You have two options:

#### Option A: Update settings.py directly (for development)
Edit `barkat_wholesale/settings.py` and update the database configuration:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'barkat_wholesale',          # Your database name
        'USER': 'postgres',                   # Your PostgreSQL username
        'PASSWORD': 'your_password',          # Your PostgreSQL password
        'HOST': 'localhost',                  # Database host
        'PORT': '5432',                       # Database port
    }
}
```

#### Option B: Use Environment Variables (recommended for production)
Set environment variables and keep settings.py as is:

**Windows (Command Prompt):**
```cmd
set DB_NAME=barkat_wholesale
set DB_USER=postgres
set DB_PASSWORD=your_password
set DB_HOST=localhost
set DB_PORT=5432
```

**Windows (PowerShell):**
```powershell
$env:DB_NAME="barkat_wholesale"
$env:DB_USER="postgres"
$env:DB_PASSWORD="your_password"
$env:DB_HOST="localhost"
$env:DB_PORT="5432"
```

**Linux/macOS:**
```bash
export DB_NAME=barkat_wholesale
export DB_USER=postgres
export DB_PASSWORD=your_password
export DB_HOST=localhost
export DB_PORT=5432
```

Or create a `.env` file and use `python-dotenv` (requires additional package).

### Step 5: Backup Existing SQLite Data (Optional but Recommended)

If you have existing data in SQLite that you want to migrate:

```bash
# Backup SQLite database
python manage.py dumpdata > backup.json

# Or backup only specific apps:
python manage.py dumpdata barkat > barkat_backup.json
python manage.py dumpdata auth > auth_backup.json
```

### Step 6: Run Migrations

```bash
# Create migration files (if needed)
python manage.py makemigrations

# Apply migrations to PostgreSQL
python manage.py migrate
```

### Step 7: Create Superuser (if needed)

```bash
python manage.py createsuperuser
```

### Step 8: Load Data from Backup (if you backed up earlier)

```bash
# Load all data
python manage.py loaddata backup.json

# Or load specific apps:
python manage.py loaddata barkat_backup.json
python manage.py loaddata auth_backup.json
```

## Verify Migration

### Test Database Connection

```bash
python manage.py dbshell
```

You should see a PostgreSQL prompt. Type `\q` to exit.

### Run Django Shell

```bash
python manage.py shell
```

```python
from django.db import connection
print(connection.vendor)  # Should output: 'postgresql'
```

## Important Notes

### 1. **Data Type Compatibility**
- SQLite and PostgreSQL handle some data types differently, but Django ORM abstracts most of this
- Decimal fields are properly handled in both databases
- Text fields may have slight differences, but Django handles them

### 2. **Performance Improvements**
PostgreSQL offers better performance for:
- Complex queries with joins
- Full-text search capabilities
- Concurrent access
- Large datasets

### 3. **Case Sensitivity**
- SQLite is case-insensitive for table/column names
- PostgreSQL is case-sensitive by default, but Django handles this automatically
- All identifiers are converted to lowercase by default

### 4. **Transactions**
- Both databases support transactions
- PostgreSQL has better ACID compliance guarantees

### 5. **Connection Pooling**
The settings now include `CONN_MAX_AGE` to keep connections alive, improving performance for repeated queries.

## Troubleshooting

### Error: "FATAL: password authentication failed"
- Check your PostgreSQL password
- Verify the user exists: `psql -U postgres -c "\du"`
- Reset password: `ALTER USER postgres WITH PASSWORD 'new_password';`

### Error: "FATAL: database 'barkat_wholesale' does not exist"
- Create the database: `CREATE DATABASE barkat_wholesale;`

### Error: "FATAL: could not connect to server"
- Check if PostgreSQL is running: `sudo systemctl status postgresql` (Linux)
- Verify host and port in settings
- Check PostgreSQL is listening: `netstat -an | grep 5432`

### Error: "permission denied for database"
- Grant privileges: `GRANT ALL PRIVILEGES ON DATABASE barkat_wholesale TO your_user;`

### Migration Errors
If you encounter migration errors:
1. Check that all migrations are up to date
2. Try running: `python manage.py migrate --run-syncdb`
3. For fresh start: Delete all migration files (except `__init__.py`) and run `makemigrations` again

## Production Deployment

For production, consider:

1. **Use a connection pooler** (like pgBouncer) for better performance
2. **Set up SSL connections**:
   ```python
   'OPTIONS': {
       'sslmode': 'require',
   }
   ```
3. **Use read replicas** for read-heavy workloads
4. **Set up regular backups** using `pg_dump`
5. **Monitor database performance** using PostgreSQL tools

## Rollback (if needed)

If you need to rollback to SQLite:

1. Update `settings.py` to use SQLite again
2. Restore from backup: `python manage.py loaddata backup.json`
3. Reinstall if needed: `pip uninstall psycopg2-binary`

## Additional Resources

- PostgreSQL Documentation: https://www.postgresql.org/docs/
- Django Database Setup: https://docs.djangoproject.com/en/5.2/ref/settings/#databases
- psycopg2 Documentation: https://www.psycopg.org/docs/
