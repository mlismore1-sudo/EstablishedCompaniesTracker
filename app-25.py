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

# Filters section
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
