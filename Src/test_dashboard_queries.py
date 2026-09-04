"""
Test script to verify dashboard queries work with canonical schema
"""

import os
import sys
from sqlalchemy import create_engine, text
from config_loader import load_config

def test_queries():
    try:
        config = load_config()
        engine = create_engine(config["postgres"]["connection_string"])
        
        print("[OK] Connected to Postgres")
        
        # Test 1: Outstanding Debtors (Tally-only)
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as row_count, 
                       COUNT(DISTINCT customer_name) as unique_customers
                FROM outstanding_debtors
            """)).fetchone()
            print(f"[OK] Outstanding Debtors: {result[0]} rows, {result[1]} unique customers")
        
        # Test 2: Sales (Shoper)
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as row_count,
                       COUNT(DISTINCT customer_code) as unique_customers,
                       SUM(net_value) as total_sales
                FROM sales
                WHERE source_system = 'shoper'
            """)).fetchone()
            total = result[2] or 0
            print(f"[OK] Sales (Shoper): {result[0]} rows, {result[1]} customers, {total:,.0f} total")
        
        # Test 3: Items (Shoper)
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as row_count,
                       SUM(stock_qty) as total_qty,
                       SUM(stock_value) as total_value
                FROM items
                WHERE source_system = 'shoper'
            """)).fetchone()
            total_val = result[2] or 0
            print(f"[OK] Items (Shoper): {result[0]} rows, {result[1] or 0:,.0f} units, {total_val:,.0f} value")
        
        # Test 4: Receipts (Tally) - PDCs
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as pdc_count,
                       SUM(amount) as pdc_amount
                FROM receipts
                WHERE instrument_date IS NOT NULL
                  AND CAST(instrument_date AS DATE) > CURRENT_DATE
            """)).fetchone()
            pdc_amt = result[1] or 0
            print(f"[OK] PDCs in Hand: {result[0]} cheques, {pdc_amt:,.0f}")
        
        # Test 5: Divisions
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT division FROM outstanding_debtors ORDER BY division
            """)).fetchall()
            divisions = [r[0] for r in result]
            print(f"[OK] Divisions from Outstanding: {', '.join(divisions) if divisions else 'None'}")
        
        # Test 6: Categories
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT category_1 FROM items 
                WHERE source_system = 'shoper' AND category_1 IS NOT NULL
                ORDER BY category_1
            """)).fetchall()
            categories = [r[0] for r in result]
            cat_str = ', '.join(categories[:5]) + '...' if len(categories) > 5 else ', '.join(categories)
            print(f"[OK] Categories: {cat_str if categories else 'None'}")
        
        # Test 7: Sales Dashboard Query
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT DATE_TRUNC('day', sale_date)::date as sale_date,
                       division,
                       SUM(net_value) as daily_sales
                FROM sales
                WHERE source_system = 'shoper'
                GROUP BY DATE_TRUNC('day', sale_date), division
                ORDER BY sale_date DESC
                LIMIT 1
            """)).fetchone()
            if result:
                print(f"[OK] Sales Dashboard Query: {result[0]} | Div: {result[1]} | {result[2]:,.0f}")
            else:
                print("[WARN] Sales Dashboard Query: No results (data may not be synced yet)")
        
        # Test 8: Stock Query
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as item_count,
                       SUM(stock_value) as total_value
                FROM items
                WHERE source_system = 'shoper'
                  AND division = (SELECT DISTINCT division FROM items WHERE source_system = 'shoper' LIMIT 1)
            """)).fetchone()
            val = result[1] or 0
            print(f"[OK] Stock Query: {result[0]} items, {val:,.0f} value")
        
        print("\n[SUCCESS] All dashboard queries are working correctly!")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Query test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Make sure SHOPER_SA_PASSWORD is set
    if not os.environ.get("SHOPER_SA_PASSWORD"):
        print("[WARN] SHOPER_SA_PASSWORD environment variable not set")
        print("[INFO] Set it with: $env:SHOPER_SA_PASSWORD = \"your-password\"")
    
    success = test_queries()
    sys.exit(0 if success else 1)
