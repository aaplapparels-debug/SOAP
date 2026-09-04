"""Stock Position Report"""

import streamlit as st
import pandas as pd
import xlsxwriter
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from config_loader import load_config
import io

@st.cache_resource
def get_engine():
    config = load_config()
    return create_engine(config["postgres"]["connection_string"])


def show_stock_position():
    st.title("📦 Stock Position Report")
    
    engine = get_engine()
    
    # Filters
    col1, col2, col3 = st.columns(3)
    
    with col1:
        divisions = get_divisions(engine)
        selected_divisions = st.multiselect("Divisions", divisions, default=divisions)
    
    with col2:
        style = st.text_input("Style", value="")
        #categories = get_categories(engine)
        selected_categories = ""#st.multiselect("Category", categories, default=categories[:1] if categories else [])
    
    #with col3:
    #stock_filter = st.selectbox(
            #    "Filter By",
            #    ["All", "Low Stock", "High Value", "Zero Stock"]
            #)
    try:
        # Main stock query
        query = """
        SELECT 
            item_code,
            item_desc,
            category_1,
            category_2,
            size,
            stock_qty,
            stock_value,
            mrp,
            current_cost,
            division
        FROM items
        WHERE source_system = 'shoper'
            AND stock_qty > 0
            AND division = ANY(:divisions)
            AND (item_desc ILIKE :style)
        """
        
        params = {"divisions": selected_divisions, "style": f"%{style}%"}
        
        # Apply additional filters
        if selected_categories:
            query += " AND category_1 = ANY(:categories)"
            params["categories"] = selected_categories
        
        #if stock_filter == "Low Stock":
        #    query += " AND stock_qty < (current_cost * 10)"  # Arbitrary low stock threshold
        #elif stock_filter == "High Value":
        #    query += " AND stock_value > (SELECT AVG(stock_value) FROM items WHERE source_system = 'shoper' AND stock_value > 0)"
        #elif stock_filter == "Zero Stock":
        #    query += " AND stock_qty = 0"
        
        query += " ORDER BY stock_value DESC"
        
        with engine.begin() as conn:
            stock_df = pd.read_sql(text(query), conn, params=params)
        
        if stock_df.empty:
            st.warning("No stock items found with selected filters.")
        else:
            # Summary metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Total Items", len(stock_df))
            
            with col2:
                st.metric("Total Qty", f"{stock_df['stock_qty'].sum():,.0f} units")
            
            with col3:
                st.metric("Total Value", f"₹{stock_df['stock_value'].sum():,.0f}")
            
            with col4:
                zero_stock = len(stock_df[stock_df['stock_qty'] == 0])
                st.metric("Zero Stock Items", zero_stock)
            
            with col5:
                avg_value = stock_df['stock_value'].mean()
                st.metric("Avg Item Value", f"₹{avg_value:,.0f}")

            st.markdown("---")
            
            # Detailed stock table
            st.subheader("Detailed Stock Position")
            
            display_df = stock_df[['item_code', 'item_desc', 'stock_qty','size']].copy()
            display_df.sort_values(by='item_desc', ascending=True, inplace=True)
            #display_df['stock_value'] = display_df['stock_value'].apply(lambda x: f"₹{x:,.0f}")
            #display_df['mrp'] = display_df['mrp'].apply(lambda x: f"₹{x:,.0f}")
            #display_df['current_cost'] = display_df['current_cost'].apply(lambda x: f"₹{x:,.0f}")
            
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "item_code": st.column_config.TextColumn("Item Code", width="small"),
                    "item_desc": st.column_config.TextColumn("Description", width="medium"),
                    "category_1": st.column_config.TextColumn("Category", width="small"),
                    "stock_qty": st.column_config.NumberColumn("Qty", format="%d"),
                    "stock_value": st.column_config.TextColumn("Value"),
                    "mrp": st.column_config.TextColumn("MRP"),
                    "division": st.column_config.TextColumn("Division", width="small")
                }
            )
            
            # Export
            #csv = stock_df.to_csv(index=False)
            # 1. Write the DataFrame to an in-memory BytesIO buffer
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                display_df.to_excel(writer, sheet_name="Stock Position", index=False)

            st.download_button(
                label="📥 Download Stock Report",
                data=excel_buffer.getvalue(),
                file_name="stock_position.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )            

            st.markdown("---")
            
        # Stock value by division
            #st.subheader("Stock Distribution by Division")
            #div_stock = stock_df.groupby('division')['stock_value'].sum().sort_values(ascending=False)
            
            #fig_div = go.Figure(data=[
            #    go.Pie(
            #        labels=div_stock.index,
            #        values=div_stock.values,
            #        hole=.3,
            #        text=[f"₹{v/1000000:.1f}M" for v in div_stock.values],
            #        textposition='auto'
            #    )
            #])
            #fig_div.update_layout(title="Stock Value by Division", height=400)
            #st.plotly_chart(fig_div, use_container_width=True)
        
           
            # Stock by category
            st.subheader("Stock by Category")
            cat_stock = stock_df.groupby('category_1').agg({
                'stock_qty': 'sum',
                'stock_value': 'sum'
            }).sort_values('stock_value', ascending=False).head(10)
            
            fig_cat = go.Figure()
            fig_cat.add_trace(go.Bar(
                x=cat_stock.index,
                y=cat_stock['stock_value'],
                name='Stock Value',
                marker_color='#1f77b4',
                text=[f"₹{v/1000000:.1f}M" for v in cat_stock['stock_value']],
                textposition='auto'
            ))
            fig_cat.update_layout(
                title="Top 10 Categories by Stock Value",
                xaxis_title="Category",
                yaxis_title="Stock Value (₹)",
                height=400,
                showlegend=False
            )
            st.plotly_chart(fig_cat, use_container_width=True)
            
   
    except Exception as e:
        st.error(f"Error loading stock data: {e}")


def get_divisions(engine):
    """Get unique divisions"""
    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                "SELECT DISTINCT division FROM items WHERE source_system = 'shoper' ORDER BY division"
            ))
            return [row[0] for row in result]
    except:
        return ["SPM", "SPW", "Thermal", "KTH"]


def get_categories(engine):
    """Get unique categories"""
    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                "SELECT DISTINCT category_1 FROM items WHERE source_system = 'shoper' AND category_1 IS NOT NULL ORDER BY category_1"
            ))
            return [row[0] for row in result]
    except:
        return []


if __name__ == "__main__":
    show_stock_position()
