import streamlit as st
import requests
import os
from datetime import datetime
from typing import List, Dict, Optional
import time
import pandas as pd

# Configuration - All FREE APIs
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY")
CONVERT_IXBRL_API_KEY = os.getenv("CONVERT_IXBRL_API_KEY")
UK_TRADE_API_KEY = os.getenv("UK_TRADE_API_KEY")

# API Base URLs
CH_BASE = "https://api.company-information.service.gov.uk"
IXBRL_BASE = "https://convert-ixbrl.co.uk/api"
UK_TRADE_BASE = "https://api.uktradeinfo.com"

# Page config
st.set_page_config(page_title="UK Company Screener", layout="wide")

# Title
st.title("UK Company Screener")
st.markdown("Find UK companies by revenue, FX exposure, and importer status")

# Sidebar - all inputs here
with st.sidebar:
    st.header("Filters")
    
    sic_code = st.text_input(
        label="SIC Code (5 digits)",
        placeholder="e.g., 46900",
        max_chars=5,
        help="Standard Industrial Classification code"
    )
    
    st.write("Revenue: GBP 5m-30m")
    
    incorporation_from = st.date_input(
        label="Incorporated From",
        value=datetime(2000, 1, 1)
    )
    
    incorporation_to = st.date_input(
        label="Incorporated To",
        value=datetime(2022, 12, 31)
    )
    
    fx_keywords = st.multiselect(
        label="FX Keywords",
        options=["foreign exchange", "FX", "currency risk", "hedging", "forex", "exchange rate"],
        default=["foreign exchange", "FX", "currency risk"]
    )
    
    check_importer = st.checkbox(
        label="Must be UK Trade importer",
        value=True,
        help="Cross-reference against HMRC importer database"
    )
    
    max_results = st.slider(
        label="Max results",
        min_value=10,
        max_value=100,
        value=25,
        help="Convert-IXBRL gives 25 free credits"
    )
    
    start_search = st.button("Start Search", type="primary", use_container_width=True)

# Helper Functions
def get_ch_session():
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
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Companies House API error: {e}")
        return []

def get_company_financials_ixbrl(company_number: str) -> Optional[Dict]:
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
    if not financials:
        return False
    
    try:
        company_financials = financials.get("company_financial_list", [])
        
        if not company_financials:
            return False
        
        latest = company_financials[0]
        profit_loss = latest.get("profit_loss", {})
        
        turnover_str = profit_loss.get("turnover", "0")
        turnover = float(turnover_str.replace(",", "")) if turnover_str else 0
        
        return min_revenue <= turnover <= max_revenue
    except (ValueError, KeyError, IndexError):
        return False

def search_fx_exposure_in_financials(financials: Dict, fx_keywords: List[str]) -> bool:
    if not financials:
        return False
    
    financial_text = str(financials).lower()
    
    for keyword in fx_keywords:
        if keyword.lower() in financial_text:
            return True
    
    return False

def check_uk_trade_importer_api(company_name: str, postcode: str = None) -> bool:
    if not UK_TRADE_API_KEY:
        return True
    
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {UK_TRADE_API_KEY}"})
    
    company_name_clean = company_name.upper().replace(" LIMITED", "").replace(" LTD", "")
    filter_query = f"contains(tolower(Name), '{company_name_clean.lower()}')"
    
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
                    return True
            
    except requests.exceptions.RequestException:
        pass
    
    return False

def get_company_profile_ch(company_number: str) -> Optional[Dict]:
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
        st.error("Companies House API key not set")
        st.info("Add COMPANIES_HOUSE_API_KEY to Streamlit Secrets")
        st.stop()
    
    if not CONVERT_IXBRL_API_KEY:
        st.error("Convert-IXBRL API key not set")
        st.info("Add CONVERT_IXBRL_API_KEY to Streamlit Secrets")
        st.stop()
    
    st.subheader("Step 1: Searching Companies House")
    
    with st.spinner(f"Searching for SIC {sic_code}..."):
        companies = search_companies_by_sic(
            sic_code=sic_code,
            incorporation_from=incorporation_from.strftime("%Y-%m-%d"),
            incorporation_to=incorporation_to.strftime("%Y-%m-%d"),
            size=max_results
        )
    
    if not companies:
        st.warning("No companies found. Try adjusting your filters.")
        st.stop()
    
    st.success(f"Found {len(companies)} companies")
    
    st.subheader("Step 2: Filtering by Revenue and FX")
    
    filtered_companies = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    credits_used = 0
    
    for i, company in enumerate(companies[:max_results]):
        company_number = company.get("company_number")
        company_name = company.get("title")
        
        status_text.text(f"Processing {i+1}/{min(len(companies), max_results)}: {company_name}")
        
        financials = get_company_financials_ixbrl(company_number)
        
        if financials:
            credits_used += 1
            
            in_revenue_range = check_revenue_range(financials, 5_000_000, 30_000_000)
            
            if in_revenue_range:
                has_fx = search_fx_exposure_in_financials(financials, fx_keywords)
                
                if has_fx:
                    profile = get_company_profile_ch(company_number)
                    
                    if profile:
                        filtered_companies.append({
                            "company_number": company_number,
                            "company_name": company_name,
                            "profile": profile,
                            "financials": financials
                        })
        
        progress_bar.progress((i + 1) / min(len(companies), max_results))
        time.sleep(0.1)
    
    progress_bar.empty()
    status_text.empty()
    
    st.success(f"{len(filtered_companies)} companies match criteria (used {credits_used} credits)")
    
    if not filtered_companies:
        st.warning("No companies matched revenue and FX criteria.")
        st.stop()
    
    if check_importer:
        st.subheader("Step 3: Checking Importer Status")
        
        importer_filtered = []
        progress_bar = st.progress(0)
        
        for i, company_data in enumerate(filtered_companies):
            company_name = company_data["company_name"]
            profile = company_data["profile"]
            
            address = profile.get("registered_office_address", {})
            postcode = address.get("postal_code", "")
            
            is_importer = check_uk_trade_importer_api(company_name, postcode)
            
            if is_importer:
                importer_filtered.append(company_data)
            
            progress_bar.progress((i + 1) / len(filtered_companies))
            time.sleep(0.1)
        
        progress_bar.empty()
        final_companies = importer_filtered
        st.success(f"{len(final_companies)} companies match ALL criteria")
    
    else:
        final_companies = filtered_companies
    
    if final_companies:
        st.subheader("Results")
        
        results_data = []
        for company_data in final_companies:
            profile = company_data["profile"]
            financials = company_data["financials"]
            
            turnover = "N/A"
            try:
                company_financials = financials.get("company_financial_list", [])
                if company_financials:
                    turnover_str = company_financials[0].get("profit_loss", {}).get("turnover", "0")
                    turnover = f"GBP {float(turnover_str.replace(',', '')):,.0f}"
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
        
        csv = df.to_csv(index=False)
        st.download_button(
            label="Download Results (CSV)",
            data=csv,
            file_name=f"uk_companies_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
        
        st.dataframe(df, use_container_width=True)
        
        if len(df) > 0:
            selected = st.selectbox("View company details", df["Company Name"].tolist())
            if selected:
                company_data = next(c for c in final_companies if c["company_name"] == selected)
                st.json({
                    "Company Name": company_data["company_name"],
                    "Company Number": company_data["company_number"],
                    "Status": company_data["profile"].get("company_status"),
                    "Address": company_data["profile"].get("registered_office_address", {}),
                })
    else:
        st.warning("No companies matched all criteria.")

# Info Section
with st.expander("API Setup Instructions"):
    st.markdown("""
    ### Required API Keys (All FREE)
    
    1. **Companies House**: https://developer.company-information.service.gov.uk/
    2. **Convert-IXBRL**: https://convert-ixbrl.co.uk/ (25 free credits)
    3. **UK Trade Info**: https://www.uktradeinfo.com/api-documentation
    
    Add to Streamlit Secrets:
    ```toml
    COMPANIES_HOUSE_API_KEY = "your_key"
    CONVERT_IXBRL_API_KEY = "your_key"
    UK_TRADE_API_KEY = "your_key"
    ```
    """)
