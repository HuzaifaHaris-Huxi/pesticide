# Install PostgreSQL Client Tools on Windows

## Method 1: Full PostgreSQL Installation (Recommended)

### Using Chocolatey
```powershell
# Install full PostgreSQL (includes psql client)
choco install postgresql

# Or specify a version
choco install postgresql15
```

### Using winget (Windows 10/11)
```powershell
# Install PostgreSQL
winget install PostgreSQL.PostgreSQL

# Or specify version
winget install PostgreSQL.PostgreSQL --version 15.8
```

### Manual Installation
1. Download from: https://www.postgresql.org/download/windows/
2. Run the installer
3. **Important**: During installation, make sure to check "Command Line Tools"
4. Default installation path: `C:\Program Files\PostgreSQL\15\bin`

---

## Method 2: Add PostgreSQL to PATH (if already installed)

### Check if PostgreSQL is already installed
```powershell
# Search for PostgreSQL
Get-ChildItem "C:\Program Files" -Filter "*PostgreSQL*" -Directory
Get-ChildItem "C:\Program Files (x86)" -Filter "*PostgreSQL*" -Directory

# Check common installation paths
Test-Path "C:\Program Files\PostgreSQL"
Test-Path "C:\Program Files\PostgreSQL\15\bin\psql.exe"
Test-Path "C:\Program Files\PostgreSQL\16\bin\psql.exe"
```

### Add to PATH (Temporary - Current Session Only)
```powershell
# Replace 15 with your version number
$env:Path += ";C:\Program Files\PostgreSQL\15\bin"

# Test
psql --version
```

### Add to PATH (Permanent)
```powershell
# Replace 15 with your version number
$pgPath = "C:\Program Files\PostgreSQL\15\bin"

if (Test-Path $pgPath) {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    
    if ($currentPath -notlike "*$pgPath*") {
        [Environment]::SetEnvironmentVariable("Path", "$currentPath;$pgPath", "User")
        Write-Host "✓ Added PostgreSQL to PATH" -ForegroundColor Green
        Write-Host "Please restart your terminal/PowerShell for changes to take effect" -ForegroundColor Yellow
    } else {
        Write-Host "PostgreSQL is already in PATH" -ForegroundColor Green
    }
} else {
    Write-Host "PostgreSQL not found at $pgPath" -ForegroundColor Red
    Write-Host "Please install PostgreSQL first" -ForegroundColor Yellow
}
```

### Using GUI (Windows Settings)
1. Right-click "This PC" → Properties
2. Click "Advanced system settings"
3. Click "Environment Variables"
4. Under "User variables", select "Path" → "Edit"
5. Click "New"
6. Add: `C:\Program Files\PostgreSQL\15\bin` (replace 15 with your version)
7. Click OK on all windows
8. **Restart your terminal/PowerShell**

---

## Method 3: Verify Installation

After installation:

```powershell
# Check PostgreSQL version
psql --version

# Should output something like:
# psql (PostgreSQL) 15.x
```

---

## Method 4: Quick Script to Find and Add PostgreSQL

Run this PowerShell script to automatically find and add PostgreSQL to PATH:

```powershell
# Auto-detect and add PostgreSQL to PATH
$versions = @("17", "16", "15", "14", "13", "12")
$found = $false

foreach ($ver in $versions) {
    $pgPath = "C:\Program Files\PostgreSQL\$ver\bin"
    if (Test-Path "$pgPath\psql.exe") {
        Write-Host "Found PostgreSQL $ver at: $pgPath" -ForegroundColor Green
        
        $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
        
        if ($currentPath -notlike "*$pgPath*") {
            [Environment]::SetEnvironmentVariable("Path", "$currentPath;$pgPath", "User")
            Write-Host "✓ Added PostgreSQL $ver to PATH" -ForegroundColor Green
            Write-Host "Please restart your terminal for changes to take effect" -ForegroundColor Yellow
        } else {
            Write-Host "PostgreSQL is already in PATH" -ForegroundColor Green
        }
        
        Write-Host ""
        Write-Host "To test, restart terminal and run: psql --version" -ForegroundColor Cyan
        $found = $true
        break
    }
}

if (-not $found) {
    Write-Host "PostgreSQL not found. Please install it first:" -ForegroundColor Red
    Write-Host "  choco install postgresql" -ForegroundColor Yellow
    Write-Host "  OR download from: https://www.postgresql.org/download/windows/" -ForegroundColor Yellow
}
```

---

## Alternative: Use Django Without psql

**Remember**: You don't actually need `psql` to use PostgreSQL with Django!

```bash
# Test connection
python test_db_connection.py

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run server
python manage.py runserver
```

The `psql` tool is only needed for the `dbshell` command, which is optional.

---

## Troubleshooting

### Issue: "psql is not recognized"
**Solution**: PostgreSQL is not in PATH or not installed.

### Issue: "Command not found" after adding to PATH
**Solution**: Restart your terminal/PowerShell/IDE completely.

### Issue: Wrong version in PATH
**Solution**: Check which version:
```powershell
Get-Command psql | Select-Object Source
```

### Issue: Multiple PostgreSQL versions
**Solution**: Remove older versions from PATH, keep only the one you want.

---

## Recommended Installation Steps

1. **Install PostgreSQL using winget (easiest):**
   ```powershell
   winget install PostgreSQL.PostgreSQL
   ```

2. **Or using Chocolatey (full package):**
   ```powershell
   choco install postgresql
   ```

3. **Add to PATH (if not auto-added):**
   - Use the auto-detect script above, OR
   - Manually add: `C:\Program Files\PostgreSQL\15\bin` to PATH

4. **Restart terminal** and verify:
   ```powershell
   psql --version
   ```

5. **Test Django connection:**
   ```bash
   python test_db_connection.py
   ```

---

**Note**: If you're having trouble, you can continue using Django without `psql`. It's not required for the application to work!
