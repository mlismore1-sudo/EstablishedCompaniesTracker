import streamlit as st
import requests
import os
from datetime import datetime
from typing import List, Dict, Optional
import time
import pandas as pd
from difflib import SequenceMatcher

# Configuration - Only 1 API key needed (Companies House)
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY")

# API Base URLs
CH_BASE = "https://api.company-information.service.gov.uk"
UK_TRADE_BASE = "https://api.uktradeinfo.com"

# Page config
st.set_page_config(page_title="UK Company Finder", layout="wide")

# Title
st.title("UK Company Finder")
st.markdown("Find UK companies by SIC code - filter by importer status")

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
        label="Show only importers",
        value=False,
        help="Filter to only companies confirmed as importers in HMRC data"
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

def normalize_company_name(name: str) -> str:
    """
    Normalize company name for flexible matching
    Removes common suffixes and standardizes format
    """
    if not name:
        return ""
    
    # Convert to uppercase and strip
    name = name.upper().strip()
    
    # Remove common suffixes
    suffixes = [
        " LIMITED", " LTD", " PLC", " LLP", " CIC",
        " AND COMPANY", " & COMPANY", " AND CO", " & CO",
        " HOLDINGS", " GROUP", " UK", " GB"
    ]
    
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    
    # Remove punctuation and extra spaces
    name = name.replace("&", "AND").replace(".", "").replace(",", "").replace("-", " ")
    name = " ".join(name.split())  # Remove extra spaces
    
    return name

def fuzzy_match_names(name1: str, name2: str, threshold: float = 0.7) -> bool:
    """
    Fuzzy match two company names using multiple strategies
    Returns True if names are similar enough
    """
    if not name1 or not name2:
        return False
    
    # Normalize both names
    norm1 = normalize_company_name(name1)
    norm2 = normalize_company_name(name2)
    
    # Exact match after normalization
    if norm1 == norm2:
        return True
    
    # Check if one contains the other
    if norm1 in norm2 or norm2 in norm1:
        return True
    
    # Check word overlap (at least 50% of words match)
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    if len(words1) > 0 and len(words2) > 0:
        overlap = len(words1 & words2)
        min_words = min(len(words1), len(words2))
        if overlap / min_words >= 0.5:
            return True
    
    # Sequence matching (fuzzy string similarity)
    ratio = SequenceMatcher(None, norm1, norm2).ratio()
    if ratio >= threshold:
        return True
    
    return False

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

def check_uk_trade_importer_api(company_name: str, postcode: str = None) -> tuple[bool, Optional[Dict]]:
    """
    Check if company appears as importer via UK Trade Info API
    Returns: (is_importer, trader_data)
    """
    if not company_name or not isinstance(company_name, str):
        return False, None
    
    session = requests.Session()
    
    # Normalize company name for searching
    company_name_clean = normalize_company_name(company_name)
    
    # Strategy 1: Search by exact company name
    filter_query = f"contains(tolower(Name), '{company_name_clean.lower()}')"
    
    try:
        response = session.get(
            f"{UK_TRADE_BASE}/Trader",
            params={
                "$filter": filter_query,
                "$select": "Name,PostCode,ImportEntries,ExportEntries,CommodityCode,HS2Description",
                "$top": 50
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            traders = data.get("value", [])
            
            # Check each trader for import activity and name match
            for trader in traders:
                import_entries = trader.get("ImportEntries", 0)
                trader_name = trader.get("Name", "")
                
                # Check if trader has import activity
                if import_entries and import_entries > 0:
                    # Use fuzzy matching
                    if fuzzy_match_names(company_name, trader_name, threshold=0.6):
                        return True, trader
            
            # Strategy 2: If no exact match, try partial name (first 3 words)
            if len(company_name_clean.split()) >= 3:
                partial_name = " ".join(company_name_clean.split()[:3])
                filter_query2 = f"contains(tolower(Name), '{partial_name.lower()}')"
                
                response2 = session.get(
                    f"{UK_TRADE_BASE}/Trader",
                    params={
                        "$filter": filter_query2,
                        "$select": "Name,PostCode,ImportEntries,ExportEntries",
                        "$top": 50
                    },
                    timeout=15
                )
                
                if response2.status_code == 200:
                    data2 = response2.json()
                    traders2 = data2.get("value", [])
                    
                    for trader in traders2:
                        import_entries = trader.get("ImportEntries", 0)
                        trader_name = trader.get("Name", "")
                        
                        if import_entries and import_entries > 0:
                            if fuzzy_match_names(company_name, trader_name, threshold=0.6):
                                return True, trader
            
    except requests.exceptions.RequestException as e:
        st.warning(f"UK Trade API error: {e}")
    
    return False, None

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
    
    # Step 2: Check UK Trade importer status for all companies
    st.subheader("Step 2: Checking Importer Status")
    st.info("Checking all companies against HMRC UK Trade data")
    
    all_companies_data = []
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
            
            is_importer, trader_data = check_uk_trade_importer_api(company_name, postcode)
            
            all_companies_data.append({
                "company_number": company_number,
                "company_name": company_name,
                "profile": profile,
                "is_importer": is_importer,
                "trader_data": trader_data
            })
        
        progress_bar.progress((i + 1) / len(companies))
        time.sleep(0.05)
    
    progress_bar.empty()
    status_text.empty()
    
    # Count importers vs non-importers
    importers = [c for c in all_companies_data if c["is_importer"]]
    non_importers = [c for c in all_companies_data if not c["is_importer"]]
    
    st.success(f"Checked {len(all_companies_data)} companies: {len(importers)} importers, {len(non_importers)} non-importers")
    
    # Apply filter if requested
    if check_importer:
        final_companies = importers
        st.info("Showing only importers (toggle off to see all companies)")
    else:
        final_companies = all_companies_data
        st.info("Showing all companies (toggle on to see only importers)")
    
    # Display Results
    if final_companies:
        st.subheader("Results")
        
        # Prepare data for display
        results_data = []
        for company_data in final_companies:
            profile = company_data["profile"]
            
            results_data.append({
                "Company Name": company_data["company_name"],
                "Company Number": company_data["company_number"],
                "Importer": "Yes" if company_data["is_importer"] else "No",
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
        
        # Detailed view
        if len(df) > 0:
            selected = st.selectbox("View company details", df["Company Name"].tolist())
            if selected:
                company_data = next(c for c in final_companies if c["company_name"] == selected)
                profile = company_data["profile"]
                
                st.json({
                    "Company Name": company_data["company_name"],
                    "Company Number": company_data["company_number"],
                    "Is Importer": company_data["is_importer"],
                    "Status": profile.get("company_status"),
                    "Type": profile.get("company_type"),
                    "Incorporated": profile.get("incorporation_date"),
                    "Address": profile.get("registered_office_address", {}),
                    "SIC Codes": [s.get("description") for s in profile.get("sic_codes", [])]
                })
                
                # Show trader data if importer
                if company_data["is_importer"] and company_data["trader_data"]:
                    st.subheader("UK Trade Info")
                    trader = company_data["trader_data"]
                    st.json({
                        "Name in HMRC Data": trader.get("Name"),
                        "Import Entries": trader.get("ImportEntries"),
                        "Export Entries": trader.get("ExportEntries"),
                        "Postcode": trader.get("PostCode")
                    })
    
    else:
        st.warning("No companies matched your filter.")
        if check_importer and len(importers) == 0:
            st.info("No importers found for this SIC code. Try a different SIC code or disable the importer filter.")

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
    
    ---
    
    ### How It Works
    
    1. Searches Companies House for companies with your SIC code
    2. Checks each company against HMRC UK Trade database
    3. Uses fuzzy matching to handle name variations
    4. Shows all companies by default, toggle to see only importers
    
    **Note:** Not all companies import/export - many source domestically
    """)

# Footer
st.divider()
st.caption("Data: Companies House API, HMRC UK Trade Info API")
