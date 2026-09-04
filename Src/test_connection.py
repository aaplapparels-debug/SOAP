#!/usr/bin/env python
"""Test SQL Server connection and check data availability."""

import os
import sys
import pyodbc
from config_loader import load_config

config = load_config()
sql_cfg = config['sql_server']
pg_cfg = config['postgres']
division_cfg = config['divisions'][0]

print("=" * 60)
print("TESTING SHOPER SQL SERVER CONNECTION & DATA")
print("=" * 60)

# Get password from environment
sa_password = os.getenv('SHOPER_SA_PASSWORD', 'NOT_SET')
if sa_password == 'NOT_SET':
    print("⚠️  ERROR: SHOPER_SA_PASSWORD environment variable not set!")
    sys.exit(1)

print(f"\n✓ Server: {sql_cfg['host']}")
print(f"✓ Database: {division_cfg['staging_db']}")
print(f"✓ Username: {sql_cfg['sa_username']}")

try:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={sql_cfg['host']};"
        f"DATABASE={division_cfg['staging_db']};"
        f"UID={sql_cfg['sa_username']};"
        f"PWD={sa_password};"
        "TrustServerCertificate=yes;"
    )
    print(f"\nConnecting to SQL Server...")
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    print("✓ SQL Server connection successful!")
    
    # Check if tables exist and have data
    print("\n" + "=" * 60)
    print("TABLE DATA COUNTS")
    print("=" * 60)
    
    tables_to_check = ['Customers', 'ItemMaster', 'SaleTrnHdr', 'SaleTrnDtl', 'PurchOrderHdr', 'PurchOrderDtl']
    
    for table_name in tables_to_check:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            result = cursor.fetchone()
            count = result[0] if result else 0
            status = "✓" if count > 0 else "⚠️ "
            print(f"{status} {table_name:20} : {count:10,} rows")
        except Exception as e:
            print(f"✗ {table_name:20} : ERROR - {str(e)[:50]}")
    
    # Sample data from Customers
    print("\n" + "=" * 60)
    print("SAMPLE DATA: First 3 Customers")
    print("=" * 60)
    try:
        cursor.execute("SELECT TOP 3 Code, Nm, CreditDays, CreditLimit FROM Customers")
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"  Code: {row[0]}, Name: {row[1]}, CreditDays: {row[2]}, CreditLimit: {row[3]}")
        else:
            print("  (No data found)")
    except Exception as e:
        print(f"  Error querying Customers: {e}")
    
    conn.close()
    print("\n✓ Connection closed")

except Exception as e:
    print(f"\n✗ SQL Server connection FAILED: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TESTING POSTGRES CONNECTION & DATA")
print("=" * 60)

try:
    import psycopg2
    
    print(f"\n✓ Connection string (masked): postgresql://...@{pg_cfg['connection_string'].split('@')[1] if '@' in pg_cfg['connection_string'] else 'UNKNOWN'}")
    
    # Extract connection params from connection_string
    # Format: postgresql://user:password@host/database
    conn_str = pg_cfg['connection_string']
    print(f"\nConnecting to Postgres...")
    conn = psycopg2.connect(conn_str)
    cursor = conn.cursor()
    print("✓ Postgres connection successful!")
    
    # Check if canonical tables exist and have data
    print("\n" + "=" * 60)
    print("CANONICAL TABLE DATA COUNTS")
    print("=" * 60)
    
    tables_to_check = ['customers', 'items', 'sales', 'sales_orders', 'purchases', 'outstanding_debtors']
    
    for table_name in tables_to_check:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            result = cursor.fetchone()
            count = result[0] if result else 0
            status = "✓" if count > 0 else "⚠️ "
            print(f"{status} {table_name:20} : {count:10,} rows")
        except Exception as e:
            print(f"✗ {table_name:20} : ERROR - {str(e)[:50]}")
    
    # Sample data from customers
    print("\n" + "=" * 60)
    print("SAMPLE DATA: First 3 Customers (Postgres)")
    print("=" * 60)
    try:
        cursor.execute("SELECT customer_code, customer_name, source_system FROM customers LIMIT 3")
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"  Code: {row[0]}, Name: {row[1]}, Source: {row[2]}")
        else:
            print("  (No data found in Postgres customers table)")
    except Exception as e:
        print(f"  Error querying customers: {e}")
    
    conn.close()
    print("\n✓ Connection closed")

except Exception as e:
    print(f"\n✗ Postgres connection FAILED: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ ALL TESTS COMPLETE")
print("=" * 60)
