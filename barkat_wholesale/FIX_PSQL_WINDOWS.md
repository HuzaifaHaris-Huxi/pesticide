# Fix psql Not Found Error on Windows

## Problem
```
CommandError: You appear not to have the 'psql' program installed or on your path.
```

## Solution Options

### Option 1: Install PostgreSQL Client Tools (Recommended)

#### Method A: Full PostgreSQL Installation
1. Download PostgreSQL from: https://www.postgresql.org/download/windows/
2. Run the installer
3. During installation, make sure to check "Command Line Tools"
4. Add PostgreSQL bin to PATH:
   - Default location: `C:\Program Files\PostgreSQL\15\bin`
   - Add to PATH:
     - Open System Properties → Environment Variables
     - Edit "Path" variable
     - Add: `C:\Program Files\PostgreSQL\15\bin`
     - (Replace 15 with your PostgreSQL version number)

#### Method B: Install Only Client Tools (Lightweight)
```powershell
# Using Chocolatey (if installed)
choco install postgresql-client

# Using winget (Windows 10/11)
winget install PostgreSQL.PostgreSQL

# Using Scoop (if installed)
scoop install postgresql
```

#### Method C: Manual PATH Setup (if PostgreSQL already installed)
```powershell
# Find PostgreSQL installation (usually in Program Files)
# Add to PATH temporarily:
$env:Path += ";C:\Program Files\PostgreSQL\15\bin"

# Or add permanently:
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\PostgreSQL\15\bin", "User")

# Verify installation
psql --version
```

### Option 2: Use Django Without psql (Skip dbshell)

You don't actually need `psql` to use PostgreSQL with Django. You can:

**Test connection using Python:**
```bash
python manage.py shell
```

Then in Python shell:
```python
from django.db import connection
cursor = connection.cursor()
cursor.execute("SELECT version();")
print(cursor.fetchone())
cursor.close()
```

**Run migrations directly:**
```bash
python manage.py migrate
```

**Check if connection works:**
```bash
python manage.py check --database default
```

### Option 3: Use SQLite Temporarily (For Testing)

If you just want to test the application without PostgreSQL setup:

1. **Temporarily change settings.py:**
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

2. **Run migrations:**
```bash
python manage.py migrate
```

3. **Later, switch back to PostgreSQL when ready**

---

## Quick Fix Commands

### Check if PostgreSQL is installed
```powershell
# Check if PostgreSQL service exists
Get-Service -Name postgresql*

# Check if psql exists anywhere
Get-Command psql -ErrorAction SilentlyContinue

# Search for PostgreSQL installation
Get-ChildItem "C:\Program Files" -Filter "*PostgreSQL*" -Directory
```

### Add PostgreSQL to PATH (if found)
```powershell
# Replace 15 with your version
$pgPath = "C:\Program Files\PostgreSQL\15\bin"
if (Test-Path $pgPath) {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$pgPath*") {
        [Environment]::SetEnvironmentVariable("Path", "$currentPath;$pgPath", "User")
        Write-Host "Added PostgreSQL to PATH. Please restart your terminal."
    }
}
```

---

## Verify Installation

After installing PostgreSQL:

```powershell
# Check psql version
psql --version

# Test connection (if database exists)
psql -U postgres -d barkat_wholesale
```

---

## Fix .env File Issues

The .env parsing errors can be fixed:

**Option 1: Delete .env file (if not needed)**
```powershell
# Check if .env exists
if (Test-Path .env) {
    Remove-Item .env
}
```

**Option 2: Fix .env file format**
The .env file should look like this (no spaces around =):
```env
DB_NAME=barkat_wholesale
DB_USER=barkat_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

**NOT like this (with spaces):**
```env
DB_NAME = barkat_wholesale  ❌ Wrong
DB_NAME=barkat_wholesale    ✅ Correct
```

**Option 3: Settings.py already fixed to handle .env errors gracefully**

---

## Recommended Solution

Since `python manage.py dbshell` is optional, you can:

1. **Skip installing psql for now**
2. **Use Django's built-in database connection:**
   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

3. **Install PostgreSQL client tools later when needed**

The application will work fine without `psql` - it's only needed for the `dbshell` command, which is just a convenience wrapper around psql.

---

## Next Steps

1. ✅ Settings.py is fixed to handle .env errors gracefully
2. Choose one:
   - **Option A**: Install PostgreSQL (full installation)
   - **Option B**: Skip psql and use Django directly
3. Test connection:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```
