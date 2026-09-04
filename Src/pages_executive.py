"""Executive Dashboard - High Level Overview"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from config_loader import load_config

@st.cache_resource
def get_engine():
    config = load_config()
    return create_engine(config["postgres"]["connection_string"])


def show_executive_dashboard():
    st.title("👔 Executive Dashboard")
    
    engine = get_engine()
    
    try:
        # 1. Outstanding Debtors (Tally data - investments in receivables)
        outstanding_query = """
        SELECT 
            SUM(pending_amount) as total_outstanding,
            COUNT(DISTINCT customer_name) as customer_count
        FROM outstanding_debtors
        """
        
        # 2. Stock Value (from items table - Shoper inventory)
        stock_query = """
        SELECT 
            SUM(stock_value) as total_stock_value,
            SUM(stock_qty) as total_qty
        FROM items
        WHERE source_system = 'shoper'
        """
        
        # 3. PDCs (Post-Dated Cheques) - from receipts table (Tally)
        pdc_query = """
        SELECT 
            COUNT(*) as pdc_count,
            SUM(amount) as pdc_amount,
            MIN(instrument_date) as earliest_pdc_date
        FROM receipts
        WHERE instrument_date IS NOT NULL
            AND CAST(instrument_date AS DATE) > CURRENT_DATE
        """
        
        # 4. Recent Sales (Shoper sales)
        sales_query = """
        SELECT 
            SUM(net_value) as total_sales,
            COUNT(DISTINCT customer_code) as unique_customers,
            MAX(sale_date) as last_sale_date
        FROM sales
        WHERE source_system = 'shoper'
            AND sale_date >= CURRENT_DATE - INTERVAL '30 days'
        """
        
        with engine.begin() as conn:
            outstanding = pd.read_sql(text(outstanding_query), conn)
            stock = pd.read_sql(text(stock_query), conn)
            pdc = pd.read_sql(text(pdc_query), conn)
            sales = pd.read_sql(text(sales_query), conn)
        
        # Extract values safely
        outstanding_val = outstanding.iloc[0]['total_outstanding'] if not outstanding.empty else 0
        outstanding_val = outstanding_val or 0
        outstanding_customers = outstanding.iloc[0]['customer_count'] if not outstanding.empty else 0
        outstanding_customers = outstanding_customers or 0
        
        stock_value = stock.iloc[0]['total_stock_value'] if not stock.empty else 0
        stock_value = stock_value or 0
        stock_qty = stock.iloc[0]['total_qty'] if not stock.empty else 0
        stock_qty = stock_qty or 0
        
        pdc_count = pdc.iloc[0]['pdc_count'] if not pdc.empty else 0
        pdc_count = pdc_count or 0
        pdc_amount = pdc.iloc[0]['pdc_amount'] if not pdc.empty else 0
        pdc_amount = pdc_amount or 0
        pdc_date = pdc.iloc[0]['earliest_pdc_date'] if not pdc.empty else None
        
        sales_30d = sales.iloc[0]['total_sales'] if not sales.empty else 0
        sales_30d = sales_30d or 0
        sales_customers = sales.iloc[0]['unique_customers'] if not sales.empty else 0
        sales_customers = sales_customers or 0
        
        # Display KPIs
        st.header("Key Performance Indicators")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "💰 Outstanding Amount",
                f"₹{outstanding_val:,.0f}",
                f"{int(outstanding_customers)} customers"
            )
        
        with col2:
            st.metric(
                "📦 Stock Value",
                f"₹{stock_value:,.0f}",
                f"{int(stock_qty):,} units"
            )
        
        with col3:
            st.metric(
                "📄 PDCs",
                f"{int(pdc_count)} cheques",
                f"₹{pdc_amount:,.0f}"
            )
        
        with col4:
            st.metric(
                "📊 Sales (Last 30D)",
                f"₹{sales_30d:,.0f}",
                f"{int(sales_customers)} customers"
            )
        
        st.markdown("---")
        
        # Working Capital Summary
        st.header("Working Capital Analysis")
        
        wc_col1, wc_col2, wc_col3 = st.columns(3)
        
        with wc_col1:
            st.subheader("Receivables (Outstanding)")
            st.metric("", f"₹{outstanding_val/10000000:.1f}Cr", "Amount due from customers")
        
        with wc_col2:
            st.subheader("Inventory")
            st.metric("", f"₹{stock_value/10000000:.1f}Cr", "Stock on hand")
        
        with wc_col3:
            st.subheader("Liquidity (PDCs)")
            st.metric("", f"₹{pdc_amount/1000000:.1f}M", "Post-dated cheques")
        
        # Division Breakdown
        st.markdown("---")
        st.header("Division Breakdown")
        
        div_query = """
        SELECT 
            s.division,
            COALESCE((SELECT SUM(pending_amount) FROM outstanding_debtors WHERE division = s.division), 0) as outstanding,
            COALESCE((SELECT SUM(stock_value) FROM items WHERE division = s.division AND source_system = 'shoper'), 0) as stock_value,
            COALESCE(SUM(s.net_value), 0) as sales_30d
        FROM sales s
        WHERE s.source_system = 'shoper'
            AND s.sale_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY s.division
        ORDER BY s.division
        """
        
        with engine.begin() as conn:
            div_df = pd.read_sql(text(div_query), conn)
        
        if not div_df.empty:
            # Format for display
            div_df['outstanding'] = div_df['outstanding'].apply(lambda x: f"₹{x/10000000:.1f}Cr" if x else "₹0")
            div_df['stock_value'] = div_df['stock_value'].apply(lambda x: f"₹{x/10000000:.1f}Cr" if x else "₹0")
            div_df['sales_30d'] = div_df['sales_30d'].apply(lambda x: f"₹{x/10000000:.1f}Cr" if x else "₹0")
            
            st.dataframe(
                div_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "division": st.column_config.TextColumn("Division"),
                    "outstanding": st.column_config.TextColumn("Outstanding"),
                    "stock_value": st.column_config.TextColumn("Stock Value"),
                    "sales_30d": st.column_config.TextColumn("Sales (30D)")
                }
            )
        
        # Health Check
        st.markdown("---")
        st.header("📊 Business Health Check")
        
        health_col1, health_col2, health_col3 = st.columns(3)
        
        with health_col1:
            if outstanding_val > stock_value * 1.5:
                st.warning("⚠️ High Receivables - Consider accelerating collections")
            else:
                st.success("✅ Receivables in healthy range")
        
        with health_col2:
            if pdc_count > 50:
                st.warning(f"⚠️ High PDC count ({pdc_count}) - Monitor cash flow")
            else:
                st.info(f"ℹ️ {pdc_count} Post-dated cheques in hand")
        
        with health_col3:
            if sales_30d > 0:
                collection_ratio = outstanding_val / (sales_30d / 30)
                st.metric("Collection Ratio", f"{collection_ratio:.1f} days of sales")
    
    except Exception as e:
        st.error(f"Error loading executive data: {e}")
        import traceback
        st.error(traceback.format_exc())


if __name__ == "__main__":
    show_executive_dashboard()
