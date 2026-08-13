import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Companies House & UK Trade Data Cross-Reference",
    page_icon="🏢",
    layout="wide"
)

st.title("🏢 Companies House & UK Trade Data Cross-Reference")
st.markdown("""
This app cross-references Companies House data with UK Trade Importers data, 
then enriches matching companies with director information from the Companies House API.
""")

# Sidebar for API key
st.sidebar.header("⚙️ Settings")
api_key = st.sidebar.text_input(
    "Companies House API Key",
    type="password",
    help="Get your API key from https://developer.company-information.service.gov.uk/"
)

# Rate limiting settings
requests_per_second = st.sidebar.slider(
    "API Rate Limit (requests/second)",
    min_value=1,
    max_value=10,
    value=3,
    help="Companies House allows 6 requests per second. Stay conservative to avoid throttling."
)

# File upload section
st.header("1. Upload CSV Files")

col1, col2 = st.columns(2)

with col1:
    companies_file = st.file_uploader(
        "Companies House CSV",
        type=["csv"],
        help="Upload your Companies House data CSV"
    )

with col2:
    trade_file = st.file_uploader(
        "UK Trade Importers CSV",
        type=["csv"],
        help="Upload your UK Trade Importers CSV"
    )

# Helper functions
def load_csv(file):
    """Load CSV file into DataFrame"""
    try:
        df = pd.read_csv(file)
        return df
    except Exception as e:
        st.error(f"Error loading CSV: {e}")
        return None

def find_matching_companies(df_companies, df_trade):
    """Find companies that appear in both datasets"""
    # Try to find common column names for matching
    common_columns = set(df_companies.columns) & set(df_trade.columns)
    
    if not common_columns:
        st.warning("No common column names found between the two CSV files.")
        st.info("Please ensure both CSVs have at least one column with the same name (e.g., 'Company Number', 'Company Name').")
        return None, None
    
    # Let user select the matching column
    match_column = st.selectbox(
        "Select column to match on:",
        options=list(common_columns),
        help="This column must exist in both CSV files"
    )
    
    # Find matches
    companies_set = set(df_companies[match_column].dropna().astype(str).str.strip())
    trade_set = set(df_trade[match_column].dropna().astype(str).str.strip())
    
    matching_values = companies_set & trade_set
    
    # Filter companies that appear in both
    matched_companies = df_companies[df_companies[match_column].astype(str).str.strip().isin(matching_values)].copy()
    
    return matched_companies, match_column

def get_company_details(company_number, api_key):
    """Fetch company details from Companies House API"""
    base_url = "https://api.company-information.service.gov.uk"
    
    try:
        # Get company profile
        profile_url = f"{base_url}/company/{company_number}"
        response = requests.get(profile_url, auth=(api_key, ""))
        
        if response.status_code == 200:
            company_data = response.json()
            
            # Get directors
            directors_url = f"{base_url}/company/{company_number}/officers"
            directors_response = requests.get(directors_url, auth=(api_key, ""))
            
            directors = []
            if directors_response.status_code == 200:
                directors_data = directors_response.json()
                # Filter for active directors only
                for officer in directors_data.get("items", []):
                    if officer.get("resigned_on") is None:  # Only active directors
                        name = officer.get("name", "")
                        # Split name into first and last
                        name_parts = name.split(", ")
                        if len(name_parts) >= 2:
                            surname = name_parts[0]
                            first_names = " ".join(name_parts[1:])
                        else:
                            surname = name
                            first_names = ""
                        
                        directors.append({
                            "first_name": first_names,
                            "surname": surname
                        })
            
            return {
                "company_name": company_data.get("company_name", ""),
                "incorporation_date": company_data.get("incorporation_date", ""),
                "directors": directors
            }
        else:
            st.warning(f"API error for company {company_number}: {response.status_code}")
            return None
            
    except Exception as e:
        st.error(f"Error fetching company {company_number}: {e}")
        return None

def enrich_with_directors(df, api_key, rate_limit):
    """Enrich DataFrame with director information from API"""
    if api_key is None or api_key == "":
        st.error("Please enter your Companies House API key in the sidebar.")
        return None
    
    # Assume company number column exists
    company_col = None
    for col in ["Company Number", "company_number", "CompanyNumber", "company no", "reg_no"]:
        if col in df.columns:
            company_col = col
            break
    
    if company_col is None:
        st.error("Could not find a company number column. Please ensure your CSV has a column named 'Company Number' or similar.")
        return None
    
    # Progress bar
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    enriched_data = []
    total = len(df)
    
    for idx, row in df.iterrows():
        company_number = str(row[company_col]).strip()
        
        status_text.text(f"Fetching details for {idx + 1}/{total}: {company_number}")
        
        details = get_company_details(company_number, api_key)
        
        if details:
            base_row = {
                "company_number": company_number,
                "company_name": details["company_name"],
                "incorporation_date": details["incorporation_date"]
            }
            
            # Add directors as separate columns
            directors = details["directors"]
            max_directors = len(directors)
            
            for i, director in enumerate(directors):
                base_row[f"director_{i+1}_first_name"] = director["first_name"]
                base_row[f"director_{i+1}_surname"] = director["surname"]
            
            # Pad with empty strings if fewer directors
            for i in range(len(directors), 10):  # Support up to 10 directors
                base_row[f"director_{i+1}_first_name"] = ""
                base_row[f"director_{i+1}_surname"] = ""
            
            enriched_data.append(base_row)
        else:
            # Add row with empty director data
            base_row = {
                "company_number": company_number,
                "company_name": "",
                "incorporation_date": ""
            }
            for i in range(1, 11):
                base_row[f"director_{i}_first_name"] = ""
                base_row[f"director_{i}_surname"] = ""
            enriched_data.append(base_row)
        
        # Rate limiting
        time.sleep(1 / rate_limit)
        progress_bar.progress((idx + 1) / total)
    
    status_text.text("✅ Completed!")
    return pd.DataFrame(enriched_data)

# Main workflow
if companies_file and trade_file:
    st.header("2. Cross-Reference Data")
    
    # Load CSVs
    df_companies = load_csv(companies_file)
    df_trade = load_csv(trade_file)
    
    if df_companies is not None and df_trade is not None:
        st.success(f"✅ Loaded {len(df_companies)} companies and {len(df_trade)} trade records")
        
        # Show previews
        with st.expander("Preview Companies House Data"):
            st.dataframe(df_companies.head())
        
        with st.expander("Preview UK Trade Data"):
            st.dataframe(df_trade.head())
        
        # Find matches
        matched_df, match_column = find_matching_companies(df_companies, df_trade)
        
        if matched_df is not None:
            st.header("3. Matching Companies")
            st.success(f"Found **{len(matched_df)}** companies appearing in both datasets")
            
            st.dataframe(matched_df.head(10))
            
            # Download matched data
            csv_matched = matched_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Matched Companies (CSV)",
                csv_matched,
                f"matched_companies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key="download-matched"
            )
            
            # Enrich with API data
            st.header("4. Enrich with Director Information")
            
            if st.button("🚀 Fetch Director Details from Companies House API", type="primary"):
                if api_key:
                    enriched_df = enrich_with_directors(matched_df, api_key, requests_per_second)
                    
                    if enriched_df is not None:
                        st.success(f"✅ Enriched {len(enriched_df)} companies with director data")
                        
                        # Display enriched data
                        st.header("5. Final Results")
                        st.dataframe(enriched_df)
                        
                        # Download enriched data
                        csv_enriched = enriched_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "📥 Download Enriched Data (CSV)",
                            csv_enriched,
                            f"enriched_companies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            "text/csv",
                            key="download-enriched"
                        )
                else:
                    st.error("Please enter your Companies House API key in the sidebar first.")
else:
    st.info("👆 Please upload both CSV files to begin.")

# Footer
st.markdown("---")
st.markdown("""
**Note:** Companies House API has a rate limit of 6 requests per second. 
This app includes built-in rate limiting to avoid throttling. 
For large datasets, consider running during off-peak hours.
""")    
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
