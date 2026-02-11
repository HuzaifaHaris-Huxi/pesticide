# PostgreSQL Setup Script for Barkat Wholesale ERP (Windows PowerShell)
# Run with: .\setup_postgres.ps1

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Setup for Barkat Wholesale" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# Database configuration
$DB_NAME = "barkat_wholesale"
$DB_USER = "barkat_user"

# Prompt for password
$securePassword = Read-Host "Enter password for '$DB_USER'" -AsSecureString
$DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword))

Write-Host ""
Write-Host "Step 1: Creating database and user..." -ForegroundColor Yellow

# SQL commands
$sqlCommands = @"
CREATE DATABASE $DB_NAME;
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;
ALTER USER $DB_USER CREATEDB;
"@

# Execute PostgreSQL commands
$sqlCommands | & psql -U postgres

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Database and user created successfully!" -ForegroundColor Green
} else {
    Write-Host "✗ Error creating database/user" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 2: Creating .env file..." -ForegroundColor Yellow

# Create .env file
@"
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
DB_PORT=5432
"@ | Out-File -FilePath .env -Encoding utf8

Write-Host "✓ .env file created!" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3: Installing dependencies..." -ForegroundColor Yellow
pip install psycopg2-binary python-dotenv

Write-Host "✓ Dependencies installed!" -ForegroundColor Green

Write-Host ""
Write-Host "Step 4: Testing database connection..." -ForegroundColor Yellow
python manage.py dbshell

Write-Host ""
Write-Host "Step 5: Running migrations..." -ForegroundColor Yellow
python manage.py migrate

Write-Host ""
Write-Host "===================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Create superuser: python manage.py createsuperuser"
Write-Host "2. Run server: python manage.py runserver"
Write-Host ""
Write-Host "Database credentials saved in .env file" -ForegroundColor Yellow
Write-Host ""
