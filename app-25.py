import streamlit as st
import requests
import os
from datetime import datetime
from typing import List, Dict, Optional
import time
import pandas as pd

# Configuration
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY")

# API Base URLs
CH_BASE = "https://api.company-information.service.gov.uk"

# Page config
st.set_page_config(page_title="UK Company Finder", layout="wide")
st.title("UK Company Finder")
st.markdown("Find UK companies by SIC code - matched against HMRC importer data")

# Sidebar
with st.sidebar:
    st.header("Upload Importer Data")
    
    uploaded_file = st.file_uploader(
        label="Upload HMRC Importer CSV",
        type=["csv"],
        help="Download from https://www.uktradeinfo.com/trade-data/latest-bulk-data-sets/"
    )
    
    if uploaded_file is not None:
        st.success("CSV uploaded!")
        # Show file info
        st.write(f"File: {uploaded_file.name}")
        st.write(f"Size: {len(uploaded_file.getvalue()):,} bytes")
    
    st.divider()
    
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
    
    show_only_importers = st.checkbox(
        label="Show only importers",
        value=False,
        help="Filter to only companies in HMRC importer data"
    )
    
    max_results = st.slider(
        label="Max results",
        min_value=50,
        max_value=500,
        value=100
    )
    
    start_search = st.button("Start Search", type="primary", use_container_width=True)

# Helper Functions
def get_ch_session():
    session = requests.Session()
    session.auth = (COMPANIES_HOUSE_API_KEY, "")
    return session

def normalize_name(name: str) -> str:
    """Normalize company name for matching"""
    if not name:
        return ""
    name = str(name).upper().strip()
    # Remove common suffixes
    for suffix in [" LIMITED", " LTD", " PLC", " LLP", " AND COMPANY", " & COMPANY", " AND CO", " & CO", " HOLDINGS", " GROUP"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    name = name.replace("&", "AND").replace(".", "").replace(",", "").replace("-", " ")
    return " ".join(name.split())

def load_importer_csv(file) -> Optional[pd.DataFrame]:
    """Load HMRC importer data from uploaded CSV file"""
    try:
        df = pd.read_csv(file)
        
        # Show column info for debugging
        st.info(f"CSV loaded: {len(df):,} rows, columns: {list(df.columns)}")
        
        # Standardize column names
        df.columns = df.columns.str.strip().str.upper().str.replace(" ", "_").str.replace("-", "_")
        
        st.info(f"After standardization: {list(df.columns)}")
        
        # Check for required columns
        required_cols = ["COMPANYNAME", "POSTCODE"]
        if not all(col in df.columns for col in required_cols):
            # Try alternative column names
            alternatives = {
                "COMPANY_NAME": "COMPANYNAME",
                "COMPANY NAME": "COMPANYNAME",
                "NAME": "COMPANYNAME",
                "POST_CODE": "POSTCODE",
                "POST CODE": "POSTCODE"
            }
            
            for alt, standard in alternatives.items():
                if alt in df.columns:
                    df.rename(columns={alt: standard}, inplace=True)
                    st.write(f"Renamed {alt} → {standard}")
        
        # Check again after renaming
        if "COMPANYNAME" not in df.columns or "POSTCODE" not in df.columns:
            st.error(f"CSV missing required columns. Found: {list(df.columns)}")
            st.error("""
            **Expected columns:**
            - CompanyName (or Company Name, NAME)
            - PostCode (or Post Code, POST_CODE)
            
            Please download the CSV from:
            https://www.uktradeinfo.com/trade-data/latest-bulk-data-sets/
            """)
            return None
        
        # Create normalized name column for matching
        df["COMPANYNAME_NORM"] = df["COMPANYNAME"].apply(normalize_name)
        
        # Filter to only importers (if TradeType column exists)
        if "TRADETYPEDESCRIPTION" in df.columns:
            original_count = len(df)
            df = df[df["TRADETYPEDESCRIPTION"].str.upper() == "IMPORT"]
            st.write(f"Filtered to IMPORT only: {original_count:,} → {len(df):,} rows")
        
        # Show sample data
        st.write("Sample data:")
        st.dataframe(df[["COMPANYNAME", "POSTCODE"] + ([c for c in df.columns if "TRADETYPE" in c][:1])].head(5))
        
        return df
        
    except Exception as e:
        st.error(f"Error loading CSV: {e}")
        import traceback
        st.error(traceback.format_exc())
        return None

def match_company_to_importer(company_name: str, postcode: str, importer_df: pd.DataFrame) -> tuple[bool, Optional[Dict]]:
    """Match a company to the importer CSV"""
    if importer_df is None or len(importer_df) == 0:
        return False, None
    
    company_name_norm = normalize_name(company_name)
    
    if not company_name_norm:
        return False, None
    
    # Strategy 1: Exact match on normalized name
    matches = importer_df[importer_df["COMPANYNAME_NORM"] == company_name_norm]
    
    if len(matches) > 0:
        # If we have postcode, filter by that too
        if postcode:
            postcode_prefix = postcode.replace(" ", "")[:4].upper()
            matches_postcode = matches[matches["POSTCODE"].str.replace(" ", "").str.startswith(postcode_prefix, na=False)]
            if len(matches_postcode) > 0:
                return True, matches_postcode.iloc[0].to_dict()
        # Return first match even without postcode match
        return True, matches.iloc[0].to_dict()
    
    # Strategy 2: Contains match (company name in CSV name or vice versa)
    for idx, row in importer_df.head(1000).iterrows():  # Limit search for speed
        csv_name_norm = row["COMPANYNAME_NORM"]
        
        if not csv_name_norm:
            continue
        
        # Check if one contains the other
        if company_name_norm in csv_name_norm or csv_name_norm in company_name_norm:
            # Postcode check if available
            if postcode and "POSTCODE" in row:
                csv_postcode = str(row["POSTCODE"])
                postcode_prefix = postcode.replace(" ", "")[:4].upper()
                if csv_postcode.replace(" ", "").startswith(postcode_prefix):
                    return True, row.to_dict()
            else:
                return True, row.to_dict()
    
    return False, None

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
        st.error(f"Companies House error: {e}")
        return []

def get_company_profile_ch(company_number: str) -> Optional[Dict]:
    session = get_ch_session()
    try:
        response = session.get(f"{CH_BASE}/company/{company_number}", timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

# Main Search Logic
if start_search:
    if not sic_code or len(sic_code) != 5:
        st.error("Please enter a 5-digit SIC code")
        st.stop()
    
    if not COMPANIES_HOUSE_API_KEY:
        st.error("Companies House API key not set")
        st.stop()
    
    if uploaded_file is None:
        st.error("Please upload the HMRC Importer CSV first!")
        st.stop()
    
    # Load importer CSV
    st.subheader("Loading Importer Data")
    
    with st.spinner("Loading HMRC importer data..."):
        importer_df = load_importer_csv(uploaded_file)
    
    if importer_df is None:
        st.error("Failed to load CSV. Please check the file format.")
        st.stop()
    
    st.success(f"Loaded {len(importer_df):,} importer records")
    
    # Step 1: Search Companies House
    st.subheader("Step 1: Searching Companies House")
    
    with st.spinner(f"Searching SIC {sic_code}..."):
        companies = search_companies_by_sic(
            sic_code=sic_code,
            incorporation_from=incorporation_from.strftime("%Y-%m-%d"),
            incorporation_to=incorporation_to.strftime("%Y-%m-%d"),
            company_status=company_status,
            size=max_results
        )
    
    if not companies:
        st.warning("No companies found")
        st.stop()
    
    st.success(f"Found {len(companies)} companies")
    
    # Show first few companies for debugging
    with st.expander("Preview Companies House results"):
        for i, company in enumerate(companies[:5]):
            st.write(f"{i+1}. {company.get('title')} ({company.get('company_number')})")
    
    # Step 2: Match against importer data
    st.subheader("Step 2: Matching Against Importer Data")
    
    all_companies = []
    progress_bar = st.progress(0)
    match_count = 0
    
    for i, company in enumerate(companies):
        company_number = company.get("company_number")
        company_name = company.get("title")
        
        if not company_name:
            continue
        
        profile = get_company_profile_ch(company_number)
        
        if profile:
            address = profile.get("registered_office_address", {})
            postcode = address.get("postal_code", "")
            
            is_importer, match_data = match_company_to_importer(company_name, postcode, importer_df)
            
            if is_importer:
                match_count += 1
                if match_count <= 5:
                    st.success(f"✓ Match found: {company_name}")
            
            all_companies.append({
                "company_number": company_number,
                "company_name": company_name,
                "profile": profile,
                "is_importer": is_importer,
                "match_data": match_data,
                "postcode": postcode
            })
        
        progress_bar.progress((i + 1) / len(companies))
        time.sleep(0.02)
    
    progress_bar.empty()
    
    # Count results
    importers = [c for c in all_companies if c["is_importer"]]
    non_importers = [c for c in all_companies if not c["is_importer"]]
    
    st.write(f"**Results:** {len(importers)} importers, {len(non_importers)} non-importers")
    
    # Apply filter
    if show_only_importers:
        display_companies = importers
        st.info("Showing only importers")
    else:
        display_companies = all_companies
        st.info("Showing all companies")
    
    # Display Results
    if display_companies:
        st.subheader("Results")
        
        results_data = []
        for c in display_companies:
            profile = c["profile"]
            results_data.append({
                "Company Name": c["company_name"],
                "Company Number": c["company_number"],
                "Importer": "Yes" if c["is_importer"] else "No",
                "Postcode": c["postcode"],
                "Status": profile.get("company_status", "active"),
                "Incorporated": profile.get("incorporation_date", "")
            })
        
        df = pd.DataFrame(results_data)
        
        # Download
        csv = df.to_csv(index=False)
        st.download_button(
            label="Download Results CSV",
            data=csv,
            file_name=f"uk_companies_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
        
        st.dataframe(df, use_container_width=True)
        
        # Detail view
        if len(df) > 0:
            selected = st.selectbox("View details", df["Company Name"].tolist())
            if selected:
                c = next(x for x in display_companies if x["company_name"] == selected)
                profile = c["profile"]
                
                st.json({
                    "Company": c["company_name"],
                    "Number": c["company_number"],
                    "Importer": c["is_importer"],
                    "Postcode": c["postcode"],
                    "Status": profile.get("company_status"),
                    "Address": profile.get("registered_office_address", {})
                })
                
                if c["is_importer"] and c["match_data"]:
                    st.subheader("HMRC Importer Data")
                    match = c["match_data"]
                    st.json({
                        "Name in HMRC": match.get("COMPANYNAME"),
                        "Postcode": match.get("POSTCODE"),
                        "Commodity Code": match.get("COMMODITYCODE"),
                        "Description": match.get("HS2DESCRIPTION"),
                        "Trade Type": match.get("TRADETYPEDESCRIPTION"),
                    })
    else:
        st.warning("No companies match your filter")

# Info
with st.expander("Setup Instructions"):
    st.markdown("""
    ### Step 1: Get Companies House API Key
    
    1. Go to https://developer.company-information.service.gov.uk/
    2. Register for free
    3. Generate API key
    4. Add to Streamlit Secrets:
    
    ```toml
    COMPANIES_HOUSE_API_KEY = "your_key"
    ```
    
    ### Step 2: Download Importer CSV
    
    1. Go to https://www.uktradeinfo.com/trade-data/latest-bulk-data-sets/
    2. Download "Importer details: May 2026 (ZIP, 4.4 MB)"
    3. Extract the ZIP file
    4. Upload the CSV in the sidebar
    
    ### Expected CSV Format
    
    Columns should include:
    - CompanyName
    - PostCode
    - TradeTypeDescription (should be "Import")
    """)

# Footer
st.divider()
st.caption("Data: Companies House API, HMRC UK Trade Info (CSV upload)")
