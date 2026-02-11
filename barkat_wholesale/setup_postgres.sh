#!/bin/bash
# PostgreSQL Setup Script for Barkat Wholesale ERP
# Run with: bash setup_postgres.sh

set -e  # Exit on error

echo "==================================="
echo "PostgreSQL Setup for Barkat Wholesale"
echo "==================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Prompt for database password
read -sp "Enter password for 'barkat_user': " DB_PASSWORD
echo ""
read -sp "Confirm password: " DB_PASSWORD_CONFIRM
echo ""

if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
    echo -e "${RED}Passwords do not match!${NC}"
    exit 1
fi

# Database configuration
DB_NAME="barkat_wholesale"
DB_USER="barkat_user"

echo -e "${YELLOW}Step 1: Creating database and user...${NC}"

# Run PostgreSQL commands
sudo -u postgres psql << EOF
-- Create database
CREATE DATABASE $DB_NAME;

-- Create user
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connect to database
\c $DB_NAME

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;

-- Allow user to create databases (for development)
ALTER USER $DB_USER CREATEDB;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database and user created successfully!${NC}"
else
    echo -e "${RED}✗ Error creating database/user${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 2: Creating .env file...${NC}"

# Create .env file
cat > .env << ENVEOF
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
DB_PORT=5432
ENVEOF

echo -e "${GREEN}✓ .env file created!${NC}"

echo -e "${YELLOW}Step 3: Installing dependencies...${NC}"
pip install psycopg2-binary python-dotenv

echo -e "${GREEN}✓ Dependencies installed!${NC}"

echo -e "${YELLOW}Step 4: Testing database connection...${NC}"
python manage.py dbshell << PSQLEOF
\q
PSQLEOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database connection successful!${NC}"
else
    echo -e "${RED}✗ Database connection failed${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 5: Running migrations...${NC}"
python manage.py migrate

echo -e "${GREEN}✓ Migrations completed!${NC}"

echo ""
echo -e "${GREEN}==================================="
echo "Setup Complete!"
echo "===================================${NC}"
echo ""
echo "Next steps:"
echo "1. Create superuser: python manage.py createsuperuser"
echo "2. Run server: python manage.py runserver"
echo ""
echo "Database credentials saved in .env file"
echo ""
