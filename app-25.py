import streamlit as st
import requests
import os
from datetime import datetime
from typing import List, Dict, Optional
import time
import pandas as pd

# Configuration - All FREE APIs
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY")
CONVERT_IXBRL_API_KEY = os.getenv("CONVERT_IXBRL_API_KEY")  # Free: 25 credits
UK_TRADE_API_KEY = os.getenv("UK_TRADE_API_KEY")  # Free tier

# API Base URLs
CH_BASE = "https://api.company-information.service.gov.uk"
IXBRL_BASE = "https://convert-ixbrl.co.uk/api"
UK_TRADE_BASE = "https://api.uktradeinfo.com"

st.set_page_config(page_title="UK Company Screener (Free)", layout="wide")
st.title("🇬🇧 UK Company Screener - 100% Free APIs")
st.markdown("No paid APIs, no CSV files - all screening via free APIs")

# Sidebar
with st.sidebar:
    st.header("Filter Criteria")
    
    sic_code = st.text_input(
        "SIC Code (5 digits)",
        placeholder="e.g., 46900",
        max_length=5,
        help="Standard Industrial Classification code"
    )
    
    st.info("💷 Revenue: £5m - £30m (via Convert-IXBRL free API)")
    
    incorporation_from = st.date_input(
        "Incorporated From",
        value=datetime(2000, 1, 1)
    )
    
    incorporation_to = st.date_input(
        "Incorporated To",
        value=datetime(2022, 12, 31)
    )
    
    fx_keywords = st.multiselect(
        "FX Exposure Keywords",
        ["foreign exchange", "FX", "currency risk", "hedging", "forex", "exchange rate"],
        default=["foreign exchange", "FX", "currency risk"]
    )
    
    check_importer = st.checkbox(
        "✓ Must be UK Trade importer",
        value=True,
        help="Cross-reference against HMRC importer database"
    )
    
    max_results = st.slider(
        "Max results to process",
        min_value=10,
        max_value=100,
        value=25,
        help="Convert-IXBRL gives 25 free credits. Each company check costs 1 credit."
    )
    
    start_search = st.button("🔍 Start Search", type="primary")

# Helper Functions
def get_ch_session():
    """Companies House authenticated session"""
    session = requests.Session()
    session.auth = (COMPANIES_HOUSE_API_KEY, "")
    return session

def search_companies_by_sic(
    sic_code: str,
    incorporation_from: str,
    incorporation_to: str,
    company_status: str = "active",
    size: int = 100
) -> List[Dict]:
    """
    Step 1: Search Companies House by SIC code and incorporation date
    FREE API - 600 requests per 5 minutes
    Docs: https://developer-specs.company-information.service.gov.uk/advanced-search/companies
    """
    session = get_ch_session()
    
    params = {
        "sic_codes": [sic_code],
        "incorporated_from": incorporation_from,
        "incorporated_to": incorporation_to,
        "company_status": [company_status],
        "company_type": ["ltd"],
        "size": size
    }
    
    try:
        response = session.get(
            f"{CH_BASE}/advanced-search/companies",
            params=params,
            timeout=30
        )
        response.raise_for_status()
        
        # Check rate limit headers
        remaining = response.headers.get("X-Ratelimit-Remain", "unknown")
        st.caption(f"Companies House API: {remaining} requests remaining")
        
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Companies House API error: {e}")
        return []

def get_company_financials_ixbrl(company_number: str) -> Optional[Dict]:
    """
    Get company financials from Convert-IXBRL API
    FREE: 25 credits on signup, then ~3p per company
    Docs: https://convert-ixbrl.co.uk/Documentation/v2/Financials
    """
    if not CONVERT_IXBRL_API_KEY:
        return None
    
    try:
        response = requests.get(
            f"{IXBRL_BASE}/financials",
            params={
                "companynumber": company_number,
                "apiVersion": "2"
            },
            headers={"Authorization": f"Bearer {CONVERT_IXBRL_API_KEY}"},
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "Ok":
                return data.get("result", {})
    except requests.exceptions.RequestException:
        pass
    
    return None

def check_revenue_range(financials: Dict, min_revenue: int = 5_000_000, max_revenue: int = 30_000_000) -> bool:
    """
    Check if company turnover is within £5m-€30m range
    Uses Convert-IXBRL financial data
    """
    if not financials:
        return False
    
    try:
        # Get latest financial period
        company_financials = financials.get("company_financial_list", [])
        
        if not company_financials:
            return False
        
        # Get most recent period
        latest = company_financials[0]
        profit_loss = latest.get("profit_loss", {})
        
        turnover_str = profit_loss.get("turnover", "0")
        turnover = float(turnover_str.replace(",", "")) if turnover_str else 0
        
        return min_revenue <= turnover <= max_revenue
    except (ValueError, KeyError, IndexError):
        return False

def search_fx_exposure_in_financials(financials: Dict, fx_keywords: List[str]) -> bool:
    """
    Search for FX exposure mentions in company accounts
    Convert-IXBRL returns full iXBRL-extracted text including notes
    """
    if not financials:
        return False
    
    # Search in all financial text fields
    # Convert-IXBRL includes notes, director reports, accounting policies
    financial_text = str(financials).lower()
    
    for keyword in fx_keywords:
        if keyword.lower() in financial_text:
            return True
    
    return False

def check_uk_trade_importer_api(company_name: str, postcode: str = None) -> bool:
    """
    Step 3: Check if company appears as importer via UK Trade Info API
    FREE API with registration
    Docs: https://www.uktradeinfo.com/api-documentation
    """
    if not UK_TRADE_API_KEY:
        st.warning("⚠️ UK Trade API key not set. Skipping importer check.")
        return True  # Skip check if no API key
    
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {UK_TRADE_API_KEY}"})
    
    # OData filter: search by company name
    company_name_clean = company_name.upper().replace(" LIMITED", "").replace(" LTD", "")
    filter_query = f"contains(tolower(Name), '{company_name_clean.lower()}')"
    
    # Add postcode filter if provided
    if postcode:
        postcode_prefix = postcode.replace(" ", "")[:3].upper()
        filter_query += f" and startswith(replace(PostCode, ' ', ''), '{postcode_prefix}')"
    
    try:
        response = session.get(
            f"{UK_TRADE_BASE}/Trader",
            params={
                "$filter": filter_query,
                "$select": "Name,PostCode,ImportEntries,ExportEntries",
                "$top": 10
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            traders = data.get("value", [])
            
            for trader in traders:
                import_entries = trader.get("ImportEntries", 0)
                
                if import_entries > 0:
                    st.success(f"✓ {company_name} confirmed as importer ({import_entries} import entries)")
                    return True
            
            if traders:
                st.info(f"ℹ️ {company_name} found but no import activity (only exports)")
            
    except requests.exceptions.RequestException as e:
        st.warning(f"UK Trade API error: {e}")
    
    return False

def get_company_profile_ch(company_number: str) -> Optional[Dict]:
    """Get full company profile from Companies House"""
    session = get_ch_session()
    
    try:
        response = session.get(
            f"{CH_BASE}/company/{company_number}",
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
    except:
        pass
    
    return None

# Main Search Logic
if start_search:
    if not sic_code or len(sic_code) != 5:
        st.error("Please enter a valid 5-digit SIC code")
        st.stop()
    
    if not COMPANIES_HOUSE_API_KEY:
        st.error("⚠️ Companies House API key not set")
        st.info("""
        **Get your FREE API key:**
        1. Go to https://developer.company-information.service.gov.uk/
        2. Register for free account
        3. Generate API key
        4. Add to Streamlit Secrets as `COMPANIES_HOUSE_API_KEY`
        """)
        st.stop()
    
    if not CONVERT_IXBRL_API_KEY:
        st.error("⚠️ Convert-IXBRL API key not set")
        st.info("""
        **Get your FREE API key (25 credits):**
        1. Go to https://convert-ixbrl.co.uk/
        2. Register for free account
        3. Check email for activation code
        4. Add to Streamlit Secrets as `CONVERT_IXBRL_API_KEY`
        
        **Note:** 25 free credits = ~25 company checks. Each check costs 1 credit.
        """)
        st.stop()
    
    # Step 1: Search Companies House by SIC and incorporation date
    st.subheader("📊 Step 1: Searching Companies House")
    
    with st.spinner(f"Searching for SIC {sic_code}, incorporated {incorporation_from.year}-{incorporation_to.year}..."):
        companies = search_companies_by_sic(
            sic_code=sic_code,
            incorporation_from=incorporation_from.strftime("%Y-%m-%d"),
            incorporation_to=incorporation_to.strftime("%Y-%m-%d"),
            size=max_results
        )
    
    if not companies:
        st.warning("No companies found. Try adjusting your filters.")
        st.stop()
    
    st.success(f"Found {len(companies)} companies. Processing financials...")
    
    # Step 2: Filter by revenue (£5m-€30m) and FX exposure
    st.subheader("💷 Step 2: Filtering by Revenue & FX Exposure")
    st.info(f"⚠️ This will use {min(len(companies), max_results)} Convert-IXBRL credits (1 per company)")
    
    filtered_companies = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    credits_used = 0
    
    for i, company in enumerate(companies[:max_results]):
        company_number = company.get("company_number")
        company_name = company.get("title")
        
        status_text.text(f"Processing {i+1}/{min(len(companies), max_results)}: {company_name}")
        
        # Get financials from Convert-IXBRL (costs 1 credit)
        financials = get_company_financials_ixbrl(company_number)
        
        if financials:
            credits_used += 1
            
            # Check revenue range
            in_revenue_range = check_revenue_range(financials, 5_000_000, 30_000_000)
            
            if in_revenue_range:
                # Check FX exposure
                has_fx = search_fx_exposure_in_financials(financials, fx_keywords)
                
                if has_fx:
                    # Get full profile for address
                    profile = get_company_profile_ch(company_number)
                    
                    if profile:
                        filtered_companies.append({
                            "company_number": company_number,
                            "company_name": company_name,
                            "profile": profile,
                            "financials": financials
                        })
        
        progress_bar.progress((i + 1) / min(len(companies), max_results))
        time.sleep(0.1)  # Rate limiting
    
    progress_bar.empty()
    status_text.empty()
    
    st.success(f"✅ {len(filtered_companies)} companies match revenue + FX criteria (used {credits_used} credits)")
    
    if not filtered_companies:
        st.warning("No companies matched revenue and FX criteria.")
        st.info("""
        **Tips:**
        - Try different SIC codes
        - Widen incorporation date range
        - Add more FX keywords
        - Check Convert-IXBRL dashboard for available credits
        """)
        st.stop()
    
    # Step 3: Check UK Trade importer status
    if check_importer:
        st.subheader("🚢 Step 3: Verifying UK Trade Importer Status")
        
        importer_filtered = []
        progress_bar = st.progress(0)
        
        for i, company_data in enumerate(filtered_companies):
            company_name = company_data["company_name"]
            profile = company_data["profile"]
            
            # Get postcode from registered office
            address = profile.get("registered_office_address", {})
            postcode = address.get("postal_code", "")
            
            # Check importer status
            is_importer = check_uk_trade_importer_api(company_name, postcode)
            
            if is_importer:
                importer_filtered.append(company_data)
            
            progress_bar.progress((i + 1) / len(filtered_companies))
            time.sleep(0.1)  # Rate limiting
        
        progress_bar.empty()
        final_companies = importer_filtered
        st.success(f"✅ {len(final_companies)} companies match ALL criteria")
    
    else:
        final_companies = filtered_companies
    
    # Display Results
    if final_companies:
        st.subheader("📋 Results")
        
        # Prepare data for display
        results_data = []
        for company_data in final_companies:
            profile = company_data["profile"]
            financials = company_data["financials"]
            
            # Extract turnover from financials
            turnover = "N/A"
            try:
                company_financials = financials.get("company_financial_list", [])
                if company_financials:
                    turnover_str = company_financials[0].get("profit_loss", {}).get("turnover", "0")
                    turnover = f"€{float(turnover_str.replace(',', '')):,.0f}"
            except:
                pass
            
            results_data.append({
                "Company Name": company_data["company_name"],
                "Company Number": company_data["company_number"],
                "Turnover": turnover,
                "Status": profile.get("company_status", "active"),
                "Incorporated": profile.get("incorporation_date", ""),
                "SIC Code": sic_code
            })
        
        df = pd.DataFrame(results_data)
        
        # Download button
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download Results (CSV)",
            csv,
            file_name=f"uk_companies_free_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
        
        # Display table
        st.dataframe(df, use_container_width=True)
        
        # Detailed view
        selected = st.selectbox("View company details", df["Company Name"].tolist())
        if selected:
            company_data = next(c for c in final_companies if c["company_name"] == selected)
            st.json({
                "Company Name": company_data["company_name"],
                "Company Number": company_data["company_number"],
                "Status": company_data["profile"].get("company_status"),
                "Address": company_data["profile"].get("registered_office_address", {}),
                "SIC Codes": [s.get("description") for s in company_data["profile"].get("sic_codes", [])]
            })
            
            # Show financials
            st.subheader("Financial Summary")
            try:
                financials = company_data["financials"]
                company_financials = financials.get("company_financial_list", [])
                if company_financials:
                    latest = company_financials[0]
                    st.json({
                        "Period End": latest.get("end_date"),
                        "Turnover": latest.get("profit_loss", {}).get("turnover"),
                        "Profit/Loss": latest.get("profit_loss", {}).get("profit_loss")
                    })
            except:
                pass
    
    else:
        st.warning("No companies matched all criteria.")

# Info Section
with st.expander("ℹ️ Free API Setup Instructions"):
    st.markdown("""
    ### 1. Companies House API (FREE, Unlimited)
    
    **Register:** https://developer.company-information.service.gov.uk/
    
    **Rate Limit:** 600 requests per 5 minutes
    
    **Setup in Streamlit Secrets:**
    ```toml
    COMPANIES_HOUSE_API_KEY = "your_api_key_here"
    ```
    
    ---
    
    ### 2. Convert-IXBRL API (FREE: 25 credits)
    
    **Register:** https://convert-ixbrl.co.uk/
    
    **Free Credits:** 25 on signup, then ~3p per company
    
    **What it provides:**
    - Turnover/revenue filtering
    - Full iXBRL accounts text (for FX keyword search)
    - Balance sheet, P&L, cashflow data
    
    **Setup in Streamlit Secrets:**
    ```toml
    CONVERT_IXBRL_API_KEY = "your_api_key_here"
    ```
    
    **API Docs:** https://convert-ixbrl.co.uk/Documentation/v2
    
    ---
    
    ### 3. UK Trade Info API (FREE)
    
    **Register:** https://www.uktradeinfo.com/api-documentation
    
    **What it provides:**
    - Importer/exporter status
    - Number of import entries
    - Commodity codes traded
    
    **Setup in Streamlit Secrets:**
    ```toml
    UK_TRADE_API_KEY = "your_api_key_here"
    ```
    
    **Swagger UI:** https://api.uktradeinfo.com/swagger/ui/index
    
    ---
    
    ### Cost Breakdown
    
    For screening 25 companies:
    - Companies House: **FREE** (unlimited)
    - Convert-IXBRL: **FREE** (uses 25 of your welcome credits)
    - UK Trade Info: **FREE** (unlimited on free tier)
    
    **Total: £0.00** (for first 25 companies)
    
    After 25 companies:
    - Convert-IXBRL: ~3p per company
    - Example: 100 companies = £3.00
    
    ---
    
    ### Rate Limits
    
    | API | Limit | Reset |
    |-----|-------|-------|
    | Companies House | 600 req | 5 minutes |
    | Convert-IXBRL | Pay-per-result | N/A |
    | UK Trade Info | 1000 req/hour | 1 hour |
    
    ---
    
    ### Alternative: Truly Unlimited Free
    
    If you want to avoid Convert-IXBRL costs after 25 credits:
    
    1. Download bulk iXBRL data from Companies House (free)
    2. Process locally with Python
    3. Upload filtered CSV to your app
    
    This is more complex but completely free for unlimited searches.
    """)

# Credits tracker
if CONVERT_IXBRL_API_KEY:
    with st.sidebar:
        st.divider()
        st.caption("ℹ️ Convert-IXBRL credits are consumed at 1 credit per company financial check.")
        st.caption("Free tier: 25 credits. Check your dashboard at https://convert-ixbrl.co.uk/myaccount")