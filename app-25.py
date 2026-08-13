import streamlit as st
import requests
import os
from datetime import datetime
from typing import List, Dict, Optional
import time
import pandas as pd

# Configuration - Only 1 API key needed (Companies House)
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY")

# API Base URLs
CH_BASE = "https://api.company-information.service.gov.uk"
UK_TRADE_BASE = "https://api.uktradeinfo.com"

# Page config
st.set_page_config(page_title="UK Company Finder", layout="wide")

# Title
st.title("UK Company Finder")
st.markdown("Find UK companies by SIC code and importer status - 100% free")

# Sidebar
with st.sidebar:
    st.header("Filters")
    
    sic_code = st.text_input(
        label="SIC Code (5 digits)",
        placeholder="e.g., 46900",
        max_chars=5,
        help="Standard Industrial Classification code"
    )
    
    incorporation_from = st.date_input(
        label="Incorporated From",
        value=datetime(2000, 1, 1)
    )
    
    incorporation_to = st.date_input(
        label="Incorporated To",
        value=datetime(2022, 12, 31)
    )
    
    company_status = st.selectbox(
        label="Company Status",
        options=["active", "active-proposal-to-strike-off"],
        index=0
    )
    
    check_importer = st.checkbox(
        label="Must be UK Trade importer",
        value=True,
        help="Cross-reference against HMRC importer database"
    )
    
    max_results = st.slider(
        label="Max results to fetch",
        min_value=50,
        max_value=500,
        value=100,
        help="Companies House API limit: 600 requests per 5 minutes"
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
        
        remaining = response.headers.get("X-Ratelimit-Remain", "unknown")
        st.caption(f"Companies House API: {remaining} requests remaining")
        
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Companies House API error: {e}")
        return []

def check_uk_trade_importer_api(company_name: str, postcode: str = None) -> bool:
    """
    Check if company appears as importer via UK Trade Info API
    OPEN ACCESS - No API key required!
    """
    if not company_name or not isinstance(company_name, str):
        return False
    
    session = requests.Session()
    
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
                    return True
            
    except requests.exceptions.RequestException as e:
        st.warning(f"UK Trade API error: {e}")
    
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
    
    # Step 1: Search Companies House
    st.subheader("Step 1: Searching Companies House")
    
    with st.spinner(f"Searching for SIC {sic_code}..."):
        companies = search_companies_by_sic(
            sic_code=sic_code,
            incorporation_from=incorporation_from.strftime("%Y-%m-%d"),
            incorporation_to=incorporation_to.strftime("%Y-%m-%d"),
            company_status=company_status,
            size=max_results
        )
    
    if not companies:
        st.warning("No companies found. Try adjusting your filters.")
        st.stop()
    
    st.success(f"Found {len(companies)} companies")
    
    # Step 2: Check UK Trade importer status
    if check_importer:
        st.subheader("Step 2: Checking Importer Status")
        st.info("Using UK Trade Info API (open access - no API key needed)")
        
        importer_filtered = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, company in enumerate(companies):
            company_number = company.get("company_number")
            company_name = company.get("title")
            
            # Skip if no company name
            if not company_name:
                continue
            
            status_text.text(f"Checking {i+1}/{len(companies)}: {company_name}")
            
            profile = get_company_profile_ch(company_number)
            
            if profile:
                address = profile.get("registered_office_address", {})
                postcode = address.get("postal_code", "")
                
                is_importer = check_uk_trade_importer_api(company_name, postcode)
                
                if is_importer:
                    importer_filtered.append({
                        "company_number": company_number,
                        "company_name": company_name,
                        "profile": profile
                    })
            
            progress_bar.progress((i + 1) / len(companies))
            time.sleep(0.1)
        
        progress_bar.empty()
        status_text.empty()
        final_companies = importer_filtered
        st.success(f"{len(final_companies)} companies are confirmed importers")
    
    else:
        st.subheader("Step 2: Fetching Company Details")
        
        final_companies = []
        progress_bar = st.progress(0)
        
        for i, company in enumerate(companies):
            company_number = company.get("company_number")
            company_name = company.get("title")
            
            profile = get_company_profile_ch(company_number)
            
            if profile:
                final_companies.append({
                    "company_number": company_number,
                    "company_name": company_name,
                    "profile": profile
                })
            
            progress_bar.progress((i + 1) / len(companies))
            time.sleep(0.1)
        
        progress_bar.empty()
        st.success(f"Fetched details for {len(final_companies)} companies")
    
    # Display Results
    if final_companies:
        st.subheader("Results")
        
        results_data = []
        for company_data in final_companies:
            profile = company_data["profile"]
            
            results_data.append({
                "Company Name": company_data["company_name"],
                "Company Number": company_data["company_number"],
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
                profile = company_data["profile"]
                
                st.json({
                    "Company Name": company_data["company_name"],
                    "Company Number": company_data["company_number"],
                    "Status": profile.get("company_status"),
                    "Type": profile.get("company_type"),
                    "Incorporated": profile.get("incorporation_date"),
                    "Address": profile.get("registered_office_address", {}),
                    "SIC Codes": [s.get("description") for s in profile.get("sic_codes", [])]
                })
    else:
        st.warning("No companies matched all criteria.")

# Info Section
with st.expander("Setup Instructions"):
    st.markdown("""
    ### API Keys Required
    
    **Only 1 API key needed:**
    
    #### Companies House API (FREE)
    
    1. Go to https://developer.company-information.service.gov.uk/
    2. Register for free
    3. Generate API key
    4. Add to Streamlit Secrets:
    
    ```toml
    COMPANIES_HOUSE_API_KEY = "your_key_here"
    ```
    
    #### UK Trade Info API (OPEN ACCESS)
    
    **No API key needed!** This API is completely open access.
    
    Documentation: https://www.uktradeinfo.com/api-documentation
    
    ---
    
    ### Rate Limits
    
    - Companies House: 600 requests per 5 minutes
    - UK Trade Info: 60 requests per minute
    """)

# Footer
st.divider()
st.caption("Data: Companies House API, HMRC UK Trade Info API")
