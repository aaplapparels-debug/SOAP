# AAPL Sales & Operations Dashboard - UI Implementation

## Overview
Complete multi-page Streamlit dashboard with 5 powerful reports for sales, inventory, and customer management.

## Dashboard Structure

### 1. **Outstanding Report** (`pages_outstanding.py`)
**Purpose:** Track and manage outstanding customer invoices

**Features:**
- Filter by division and minimum amount
- View all outstanding debtors with details
- Sort by amount, customer, or date
- Track days outstanding (aging analysis)
- Download data as CSV

**Key Metrics:**
- Total outstanding amount
- Number of invoices
- Number of customers
- Average days outstanding

---

### 2. **Sales Dashboard** (`pages_sales_dashboard.py`)
**Purpose:** Monitor sales performance with trends and analysis

**Features:**
- Time period selector (Today, Month, Quarter, Year, Custom)
- Filter by division(s)
- Sales trend visualization
- Division-wise performance comparison
- Top 10 customers by sales
- Daily average tracking

**Key Metrics:**
- Total sales
- Days with sales
- Average daily sales
- Number of customers

---

### 3. **Executive Dashboard** (`pages_executive.py`)
**Purpose:** High-level business overview for decision makers

**Features:**
- Key Performance Indicators (KPIs)
- Working capital analysis
- Division-wise breakdown
- Business health check
- Investment tracking (Outstanding, Stock, PDCs)
- Collection ratio analysis

**Key Metrics:**
- Outstanding amount
- Stock value (inventory investment)
- PDC count and amount
- 30-day sales performance
- Collection ratio (days of sales outstanding)

---

### 4. **Stock Position** (`pages_stock.py`)
**Purpose:** Inventory management and stock analysis

**Features:**
- Filter by division and category
- Smart filters (All, Low Stock, High Value, Zero Stock)
- Stock distribution visualization
- Category-wise breakdown
- Detailed item-level stock table
- Download stock report

**Key Metrics:**
- Total items
- Total quantity
- Total inventory value
- Zero stock items count
- Average item value

---

### 5. **Sales 360°** (`pages_sales360.py`)
**Purpose:** Complete customer view with all interactions (THE INTERESTING ONE!)

**Features:**
- Customer selector with code and name
- **Sales History:** Complete transaction history with trend visualization
- **Pending Orders:** All outstanding sales orders with expected values
- **Outstanding Invoices:** Aging analysis and collection tracking
- **Payments:** Receipt history showing all customer payments
- **Customer Health Score:** Composite score based on:
  - Credit utilization
  - Payment timeliness
  - Recent activity
  - Order frequency

**Unique Insights:**
- Single view of all customer interactions
- Automatic health scoring system
- Trend analysis for customer behavior
- Complete payment and order history
- Credit limit utilization tracking

---

## Technical Architecture

### Main Entry Point: `dashboard.py`
- Google OAuth authentication (Web Application flow)
- Navigation buttons for all 5 reports
- Session state management
- User info display

### Page Modules
Each page module (`pages_*.py`) contains:
- `@st.cache_resource` for database connection pooling
- SQLAlchemy queries for data retrieval
- Streamlit widgets for filtering and interaction
- Plotly charts for visualization
- CSV export functionality

### Database Integration
- **Connection:** PostgreSQL (Neon) via SQLAlchemy
- **Data Source:** Canonical tables (customers, sales, items, outstanding_debtors, receipts, sales_orders)
- **Row-level Security:** Filters by `source_system = 'shoper'`
- **Performance:** Query caching with `@st.cache_data` for expensive queries

---

## Key Features Implemented

### 1. Multi-Source Safe
All queries filter by `source_system = 'shoper'` to ensure data from other sources (Tally, future adapters) don't interfere.

### 2. Interactive Filters
- Dropdown selectors for divisions and categories
- Date range pickers
- Multi-select for divisions
- Dynamic filtering based on user selection

### 3. Rich Visualizations
- Plotly line charts for trends
- Bar charts for comparisons
- Pie charts for distribution
- Table views with formatted columns

### 4. Export Capabilities
All reports include CSV download buttons for sharing and further analysis.

### 5. Real-time Data
All queries read directly from Postgres, showing live data (no batch exports needed).

### 6. Performance Optimization
- Connection pooling with `@st.cache_resource`
- Efficient SQL queries with aggregations
- Index-friendly queries

---

## How to Run

```bash
cd E:\SOAP\Src

# Set environment variables
$env:SHOPER_SA_PASSWORD = "your-password"
$env:APP_ENV = "dev"

# Run the dashboard
streamlit run dashboard.py
```

The dashboard will open at: `http://localhost:8501`

---

## Data Requirements

For the dashboards to work, ensure:
1. ✅ `canonical_schema.sql` has been applied to Postgres
2. ✅ `load_shoper_to_postgres.py` has run at least once
3. ✅ Tables populated: `customers`, `items`, `sales`, `sales_orders`, `outstanding_debtors`, `receipts`
4. ✅ Google OAuth configured with redirect URI `http://localhost:8501`
5. ✅ User email in `dashboard_users` table with role and `is_active = TRUE`

---

## Sales 360° - The Star Feature

**Sales 360°** is the most comprehensive report, providing:

1. **Customer Profile** - Name, credit terms, credit utilization
2. **Sales History** - All transactions with trend line
3. **Pending Orders** - Orders awaiting fulfillment with values
4. **Outstanding Invoices** - Aging analysis per invoice
5. **Payment Receipts** - All payments received with modes
6. **Health Score** - Automatic scoring based on:
   - Credit utilization rate
   - Payment timeliness
   - Recent sales activity
   - Order frequency

This single view eliminates the need to check multiple reports to understand a customer's status.

---

## Future Enhancements

1. Role-based access control (Admin, Manager, Sales)
2. Print-friendly PDF exports
3. Email delivery of reports
4. Customer segmentation (VIP, Regular, At-Risk)
5. Predictive analytics for defaults
6. Mobile-optimized views

---

## Support

For issues or questions:
- Check `config.dev.yaml` for database connectivity
- Verify user has `is_active = TRUE` in `dashboard_users`
- Check browser console for frontend errors
- Verify Postgres connection string is correct
