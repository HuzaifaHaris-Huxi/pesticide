"""
Test PostgreSQL Database Connection
Run: python test_db_connection.py
"""
import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from django.db import connection
from django.conf import settings

print("=" * 50)
print("Testing PostgreSQL Database Connection")
print("=" * 50)
print()

# Display configuration
print("Database Configuration:")
print(f"  Engine: {settings.DATABASES['default']['ENGINE']}")
print(f"  Name: {settings.DATABASES['default']['NAME']}")
print(f"  User: {settings.DATABASES['default']['USER']}")
print(f"  Host: {settings.DATABASES['default']['HOST']}")
print(f"  Port: {settings.DATABASES['default']['PORT']}")
print()

# Test connection
try:
    cursor = connection.cursor()
    print("✓ Connection successful!")
    print()
    
    # Get PostgreSQL version
    cursor.execute("SELECT version();")
    version = cursor.fetchone()[0]
    print("PostgreSQL Version:")
    print(f"  {version}")
    print()
    
    # Get current database
    cursor.execute("SELECT current_database();")
    db_name = cursor.fetchone()[0]
    print(f"Connected to database: {db_name}")
    print()
    
    # Get current user
    cursor.execute("SELECT current_user;")
    user = cursor.fetchone()[0]
    print(f"Connected as user: {user}")
    print()
    
    # List tables (if any exist)
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    tables = cursor.fetchall()
    
    if tables:
        print(f"Tables in database ({len(tables)}):")
        for table in tables[:10]:  # Show first 10
            print(f"  - {table[0]}")
        if len(tables) > 10:
            print(f"  ... and {len(tables) - 10} more")
    else:
        print("No tables found. Run migrations: python manage.py migrate")
    
    cursor.close()
    print()
    print("=" * 50)
    print("✓ Database connection test PASSED!")
    print("=" * 50)
    
except Exception as e:
    print("✗ Connection FAILED!")
    print()
    print(f"Error: {str(e)}")
    print()
    print("Troubleshooting:")
    print("1. Check if PostgreSQL is running")
    print("2. Verify database credentials in settings.py")
    print("3. Ensure database exists: CREATE DATABASE barkat_wholesale;")
    print("4. Check user permissions")
    print()
    print("=" * 50)
    sys.exit(1)
