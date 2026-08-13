import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import io

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

# Helper functions - defined first
def load_csv(file):
    """Load CSV file into DataFrame with robust error handling"""
    try:
        df = pd.read_csv(file)
        return df
    except Exception as e:
        st.warning(f"Standard CSV parsing failed: {e}")
        st.info("Trying alternative parsing methods...")
        
        try:
            file.seek(0)
            df = pd.read_csv(file, engine='python')
            st.success("Loaded CSV with Python engine")
            return df
        except Exception as e2:
            st.warning(f"Python engine also failed: {e2}")
        
        try:
            file.seek(0)
            content = file.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            
            lines = content.strip().split('\n')
            header = lines[0].split(',')
            num_cols = len(header)
            
            st.info(f"Header has {num_cols} columns: {header}")
            
            data_rows = []
            skipped = 0
            for i, line in enumerate(lines[1:], 2):
                fields = line.split(',')
                if len(fields) >= num_cols:
                    row_data = fields[:num_cols] if len(fields) > num_cols else fields
                    data_rows.append(row_data)
                else:
                    fields.extend([''] * (num_cols - len(fields)))
                    data_rows.append(fields)
                    skipped += 1
            
            df = pd.DataFrame(data_rows, columns=header)
            st.success(f"Loaded CSV manually: {len(df)} rows ({skipped} rows had issues)")
            return df
            
        except Exception as e3:
            st.error(f"All parsing methods failed: {e3}")
            return None

def find_matching_companies(df_companies, df_trade):
    """Find companies that appear in both datasets by matching company_name with CompanyName"""
    ch_name_col = None
    trade_name_col = None
    
    for col in df_companies.columns:
        if col.lower() in ['company_name', 'companyname', 'name']:
            ch_name_col = col
            break
    
    for col in df_trade.columns:
        if col.lower() in ['companyname', 'company_name', 'name']:
            trade_name_col = col
            break
    
    if not ch_name_col:
        st.error(f"Companies House CSV missing company name column. Found: {list(df_companies.columns)}")
        return None, None
    
    if not trade_name_col:
        st.error(f"UK Trade Importers CSV missing company name column. Found: {list(df_trade.columns)}")
        return None, None
    
    st.info(f"Matching on: '{ch_name_col}' (Companies House) ↔ '{trade_name_col}' (UK Trade)")
    
    companies_set = set(df_companies[ch_name_col].dropna().astype(str).str.strip().str.upper())
    trade_set = set(df_trade[trade_name_col].dropna().astype(str).str.strip().str.upper())
    
    matching_values = companies_set & trade_set
    
    matched_companies = df_companies[
        df_companies[ch_name_col].astype(str).str.strip().str.upper().isin(matching_values)
    ].copy()
    
    return matched_companies, ch_name_col

def get_company_details(company_name, api_key):
    """Fetch company details from Companies House API using company name search"""
    base_url = "https://api.company-information.service.gov.uk"
    
    try:
        st.write(f"🔍 Searching for: {company_name}")
        
        search_url = f"{base_url}/search/companies"
        params = {"q": company_name, "size": 1}
        response = requests.get(search_url, auth=(api_key, ""), params=params)
        
        st.write(f"Search response status: {response.status_code}")
        
        if response.status_code == 200:
            search_data = response.json()
            items = search_data.get("items", [])
            
            st.write(f"Search results: {len(items)} items found")
            
            if not items:
                st.warning(f"No company found for: {company_name}")
                return None
            
            company_data = items[0]
            company_number = company_data.get("company_number")
            matched_name = company_data.get("title", "")
            
            st.write(f"✓ Best match: {matched_name} ({company_number})")
            
            profile_url = f"{base_url}/company/{company_number}"
            profile_response = requests.get(profile_url, auth=(api_key, ""))
            
            st.write(f"Profile response status: {profile_response.status_code}")
            
            if profile_response.status_code != 200:
                st.warning(f"API error for company {company_number}: {profile_response.status_code}")
                return None
            
            company_profile = profile_response.json()
            
            directors_url = f"{base_url}/company/{company_number}/officers"
            directors_response = requests.get(directors_url, auth=(api_key, ""))
            
            st.write(f"Directors response status: {directors_response.status_code}")
            
            directors = []
            if directors_response.status_code == 200:
                directors_data = directors_response.json()
                active_officers = [o for o in directors_data.get("items", []) if o.get("resigned_on") is None]
                st.write(f"Found {len(active_officers)} active directors")
                
                for officer in active_officers:
                    name = officer.get("name", "")
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
                    st.write(f"  - {first_names} {surname}")
            
            result = {
                "company_name": company_profile.get("company_name", ""),
                "incorporation_date": company_profile.get("incorporation_date", ""),
                "directors": directors
            }
            
            st.success(f"✅ Successfully fetched details for {company_name}")
            return result
        else:
            st.warning(f"Search API error for {company_name}: {response.status_code}")
            st.write(f"Response: {response.text[:200]}")
            return None
            
    except Exception as e:
        st.error(f"Error fetching company {company_name}: {e}")
        import traceback
        st.write(traceback.format_exc())
        return None

def enrich_with_directors(df, api_key):
    """Enrich DataFrame with director information from API using company name"""
    if not api_key:
        st.error("Please enter your Companies House API key in the sidebar.")
        return None
    
    name_col = None
    for col in ["company_name", "Company_Name", "companyname", "CompanyName", "name", "Name"]:
        if col in df.columns:
            name_col = col
            break
    
    if name_col is None:
        st.error(f"Could not find a company name column. Found: {list(df.columns)}")
        return None
    
    st.info(f"Using column '{name_col}' for company name lookups")
    
    total = len(df)
    if total == 0:
        st.warning("No companies to enrich")
        return pd.DataFrame()
    
    st.write(f"📊 Starting enrichment for {total} companies...")
    
    # Show first few company names for debugging
    st.write("Sample company names to search:")
    for i, (_, row) in enumerate(df.head(5).iterrows()):
        st.write(f"{i+1}. {row[name_col]}")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    enriched_data = []
    success_count = 0
    error_count = 0
    
    for idx, row in df.iterrows():
        company_name = str(row[name_col]).strip()
        status_text.text(f"Fetching details for {idx + 1}/{total}: {company_name}")
        
        details = get_company_details(company_name, api_key)
        
        if details:
            success_count += 1
            base_row = {
                "company_name": details["company_name"],
                "incorporation_date": details["incorporation_date"]
            }
            
            directors = details["directors"]
            for i, director in enumerate(directors):
                base_row[f"director_{i+1}_first_name"] = director["first_name"]
                base_row[f"director_{i+1}_surname"] = director["surname"]
            
            for i in range(len(directors), 10):
                base_row[f"director_{i+1}_first_name"] = ""
                base_row[f"director_{i+1}_surname"] = ""
            
            enriched_data.append(base_row)
        else:
            error_count += 1
            base_row = {
                "company_name": "",
                "incorporation_date": ""
            }
            for i in range(1, 11):
                base_row[f"director_{i}_first_name"] = ""
                base_row[f"director_{i}_surname"] = ""
            enriched_data.append(base_row)
        
        progress_value = min((idx + 1) / total, 1.0)
        progress_bar.progress(progress_value)
    
    status_text.text(f"✅ Completed! Success: {success_count}, Errors: {error_count}")
    st.info(f"📈 Results: {success_count} successful, {error_count} failed out of {total} companies")
    
    return pd.DataFrame(enriched_data)

# UI: File upload section
st.header("1. Upload CSV Files")

col1, col2 = st.columns(2)

with col1:
    ch_file = st.file_uploader(
        "Companies House CSV",
        type=["csv"],
        help="Upload your Companies House data CSV",
        key="ch_uploader"
    )

with col2:
    trade_file = st.file_uploader(
        "UK Trade Importers CSV",
        type=["csv"],
        help="Upload your UK Trade Importers CSV",
        key="trade_uploader"
    )

# Main workflow
if ch_file and trade_file:
    st.header("2. Cross-Reference Data")
    
    df_companies = load_csv(ch_file)
    df_trade = load_csv(trade_file)
    
    if df_companies is not None and df_trade is not None:
        st.success(f"✅ Loaded {len(df_companies)} companies and {len(df_trade)} trade records")
        
        with st.expander("Preview Companies House Data"):
            st.dataframe(df_companies.head())
        
        with st.expander("Preview UK Trade Data"):
            st.dataframe(df_trade.head())
        
        matched_df, match_column = find_matching_companies(df_companies, df_trade)
        
        if matched_df is not None:
            st.header("3. Matching Companies")
            st.success(f"Found **{len(matched_df)}** companies appearing in both datasets")
            st.dataframe(matched_df.head(10))
            
            csv_matched = matched_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Matched Companies (CSV)",
                csv_matched,
                f"matched_companies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key="download-matched"
            )
            
            st.header("4. Enrich with Director Information")
            
            if st.button("🚀 Fetch Director Details from Companies House API", type="primary"):
                if api_key:
                    enriched_df = enrich_with_directors(matched_df, api_key)
                    
                    if enriched_df is not None and len(enriched_df) > 0:
                        st.success(f"✅ Enriched {len(enriched_df)} companies with director data")
                        st.header("5. Final Results")
                        st.dataframe(enriched_df)
                        
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
Requests are made as fast as possible without artificial delays.
""")        st.info("Trying alternative parsing methods...")
        
        try:
            file.seek(0)
            df = pd.read_csv(file, engine='python')
            st.success("Loaded CSV with Python engine")
            return df
        except Exception as e2:
            st.warning(f"Python engine also failed: {e2}")
        
        try:
            file.seek(0)
            content = file.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            
            lines = content.strip().split('\n')
            header = lines[0].split(',')
            num_cols = len(header)
            
            st.info(f"Header has {num_cols} columns: {header}")
            
            data_rows = []
            skipped = 0
            for i, line in enumerate(lines[1:], 2):
                fields = line.split(',')
                if len(fields) >= num_cols:
                    row_data = fields[:num_cols] if len(fields) > num_cols else fields
                    data_rows.append(row_data)
                else:
                    fields.extend([''] * (num_cols - len(fields)))
                    data_rows.append(fields)
                    skipped += 1
            
            df = pd.DataFrame(data_rows, columns=header)
            st.success(f"Loaded CSV manually: {len(df)} rows ({skipped} rows had issues)")
            return df
            
        except Exception as e3:
            st.error(f"All parsing methods failed: {e3}")
            return None

def find_matching_companies(df_companies, df_trade):
    """Find companies that appear in both datasets by matching company_name with CompanyName"""
    ch_name_col = None
    trade_name_col = None
    
    for col in df_companies.columns:
        if col.lower() in ['company_name', 'companyname', 'name']:
            ch_name_col = col
            break
    
    for col in df_trade.columns:
        if col.lower() in ['companyname', 'company_name', 'name']:
            trade_name_col = col
            break
    
    if not ch_name_col:
        st.error(f"Companies House CSV missing company name column. Found: {list(df_companies.columns)}")
        return None, None
    
    if not trade_name_col:
        st.error(f"UK Trade Importers CSV missing company name column. Found: {list(df_trade.columns)}")
        return None, None
    
    st.info(f"Matching on: '{ch_name_col}' (Companies House) ↔ '{trade_name_col}' (UK Trade)")
    
    companies_set = set(df_companies[ch_name_col].dropna().astype(str).str.strip().str.upper())
    trade_set = set(df_trade[trade_name_col].dropna().astype(str).str.strip().str.upper())
    
    matching_values = companies_set & trade_set
    
    matched_companies = df_companies[
        df_companies[ch_name_col].astype(str).str.strip().str.upper().isin(matching_values)
    ].copy()
    
    return matched_companies, ch_name_col

def get_company_details(company_name, api_key):
    """Fetch company details from Companies House API using company name search"""
    base_url = "https://api.company-information.service.gov.uk"
    
    try:
        st.write(f"🔍 Searching for: {company_name}")
        
        search_url = f"{base_url}/search/companies"
        params = {"q": company_name, "size": 1}
        response = requests.get(search_url, auth=(api_key, ""), params=params)
        
        st.write(f"Search response status: {response.status_code}")
        
        if response.status_code == 200:
            search_data = response.json()
            items = search_data.get("items", [])
            
            st.write(f"Search results: {len(items)} items found")
            
            if not items:
                st.warning(f"No company found for: {company_name}")
                return None
            
            company_data = items[0]
            company_number = company_data.get("company_number")
            matched_name = company_data.get("title", "")
            
            st.write(f"✓ Best match: {matched_name} ({company_number})")
            
            profile_url = f"{base_url}/company/{company_number}"
            profile_response = requests.get(profile_url, auth=(api_key, ""))
            
            st.write(f"Profile response status: {profile_response.status_code}")
            
            if profile_response.status_code != 200:
                st.warning(f"API error for company {company_number}: {profile_response.status_code}")
                return None
            
            company_profile = profile_response.json()
            
            directors_url = f"{base_url}/company/{company_number}/officers"
            directors_response = requests.get(directors_url, auth=(api_key, ""))
            
            st.write(f"Directors response status: {directors_response.status_code}")
            
            directors = []
            if directors_response.status_code == 200:
                directors_data = directors_response.json()
                active_officers = [o for o in directors_data.get("items", []) if o.get("resigned_on") is None]
                st.write(f"Found {len(active_officers)} active directors")
                
                for officer in active_officers:
                    name = officer.get("name", "")
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
                    st.write(f"  - {first_names} {surname}")
            
            result = {
                "company_name": company_profile.get("company_name", ""),
                "incorporation_date": company_profile.get("incorporation_date", ""),
                "directors": directors
            }
            
            st.success(f"✅ Successfully fetched details for {company_name}")
            return result
        else:
            st.warning(f"Search API error for {company_name}: {response.status_code}")
            st.write(f"Response: {response.text[:200]}")
            return None
            
    except Exception as e:
        st.error(f"Error fetching company {company_name}: {e}")
        import traceback
        st.write(traceback.format_exc())
        return None

def enrich_with_directors(df, api_key):
    """Enrich DataFrame with director information from API using company name"""
    if not api_key:
        st.error("Please enter your Companies House API key in the sidebar.")
        return None
    
    name_col = None
    for col in ["company_name", "Company_Name", "companyname", "CompanyName", "name", "Name"]:
        if col in df.columns:
            name_col = col
            break
    
    if name_col is None:
        st.error(f"Could not find a company name column. Found: {list(df.columns)}")
        return None
    
    st.info(f"Using column '{name_col}' for company name lookups")
    
    total = len(df)
    if total == 0:
        st.warning("No companies to enrich")
        return pd.DataFrame()
    
    st.write(f"📊 Starting enrichment for {total} companies...")
    
    # Show first few company names for debugging
    st.write("Sample company names to search:")
    for i, (_, row) in enumerate(df.head(5).iterrows()):
        st.write(f"{i+1}. {row[name_col]}")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    enriched_data = []
    success_count = 0
    error_count = 0
    
    for idx, row in df.iterrows():
        company_name = str(row[name_col]).strip()
        status_text.text(f"Fetching details for {idx + 1}/{total}: {company_name}")
        
        details = get_company_details(company_name, api_key)
        
        if details:
            success_count += 1
            base_row = {
                "company_name": details["company_name"],
                "incorporation_date": details["incorporation_date"]
            }
            
            directors = details["directors"]
            for i, director in enumerate(directors):
                base_row[f"director_{i+1}_first_name"] = director["first_name"]
                base_row[f"director_{i+1}_surname"] = director["surname"]
            
            for i in range(len(directors), 10):
                base_row[f"director_{i+1}_first_name"] = ""
                base_row[f"director_{i+1}_surname"] = ""
            
            enriched_data.append(base_row)
        else:
            error_count += 1
            base_row = {
                "company_name": "",
                "incorporation_date": ""
            }
            for i in range(1, 11):
                base_row[f"director_{i}_first_name"] = ""
                base_row[f"director_{i}_surname"] = ""
            enriched_data.append(base_row)
        
        progress_value = min((idx + 1) / total, 1.0)
        progress_bar.progress(progress_value)
    
    status_text.text(f"✅ Completed! Success: {success_count}, Errors: {error_count}")
    st.info(f"📈 Results: {success_count} successful, {error_count} failed out of {total} companies")
    
    return pd.DataFrame(enriched_data)

# UI: File upload section
st.header("1. Upload CSV Files")

col1, col2 = st.columns(2)

with col1:
    ch_file = st.file_uploader(
        "Companies House CSV",
        type=["csv"],
        help="Upload your Companies House data CSV",
        key="ch_uploader"
    )

with col2:
    trade_file = st.file_uploader(
        "UK Trade Importers CSV",
        type=["csv"],
        help="Upload your UK Trade Importers CSV",
        key="trade_uploader"
    )

# Main workflow
if ch_file and trade_file:
    st.header("2. Cross-Reference Data")
    
    df_companies = load_csv(ch_file)
    df_trade = load_csv(trade_file)
    
    if df_companies is not None and df_trade is not None:
        st.success(f"✅ Loaded {len(df_companies)} companies and {len(df_trade)} trade records")
        
        with st.expander("Preview Companies House Data"):
            st.dataframe(df_companies.head())
        
        with st.expander("Preview UK Trade Data"):
            st.dataframe(df_trade.head())
        
        matched_df, match_column = find_matching_companies(df_companies, df_trade)
        
        if matched_df is not None:
            st.header("3. Matching Companies")
            st.success(f"Found **{len(matched_df)}** companies appearing in both datasets")
            st.dataframe(matched_df.head(10))
            
            csv_matched = matched_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Matched Companies (CSV)",
                csv_matched,
                f"matched_companies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key="download-matched"
            )
            
            st.header("4. Enrich with Director Information")
            
            if st.button("🚀 Fetch Director Details from Companies House API", type="primary"):
                if api_key:
                    enriched_df = enrich_with_directors(matched_df, api_key)
                    
                    if enriched_df is not None and len(enriched_df) > 0:
                        st.success(f"✅ Enriched {len(enriched_df)} companies with director data")
                        st.header("5. Final Results")
                        st.dataframe(enriched_df)
                        
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
Requests are made as fast as possible without artificial delays.
""")        st.info("Trying alternative parsing methods...")
        
        try:
            file.seek(0)
            df = pd.read_csv(file, engine='python')
            st.success("Loaded CSV with Python engine")
            return df
        except Exception as e2:
            st.warning(f"Python engine also failed: {e2}")
        
        try:
            file.seek(0)
            content = file.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            
            lines = content.strip().split('\n')
            header = lines[0].split(',')
            num_cols = len(header)
            
            st.info(f"Header has {num_cols} columns: {header}")
            
            data_rows = []
            skipped = 0
            for i, line in enumerate(lines[1:], 2):
                fields = line.split(',')
                if len(fields) >= num_cols:
                    row_data = fields[:num_cols] if len(fields) > num_cols else fields
                    data_rows.append(row_data)
                else:
                    fields.extend([''] * (num_cols - len(fields)))
                    data_rows.append(fields)
                    skipped += 1
            
            df = pd.DataFrame(data_rows, columns=header)
            st.success(f"Loaded CSV manually: {len(df)} rows ({skipped} rows had issues)")
            return df
            
        except Exception as e3:
            st.error(f"All parsing methods failed: {e3}")
            return None

def find_matching_companies(df_companies, df_trade):
    """Find companies that appear in both datasets by matching company_name with CompanyName"""
    ch_name_col = None
    trade_name_col = None
    
    for col in df_companies.columns:
        if col.lower() in ['company_name', 'companyname', 'name']:
            ch_name_col = col
            break
    
    for col in df_trade.columns:
        if col.lower() in ['companyname', 'company_name', 'name']:
            trade_name_col = col
            break
    
    if not ch_name_col:
        st.error(f"Companies House CSV missing company name column. Found: {list(df_companies.columns)}")
        return None, None
    
    if not trade_name_col:
        st.error(f"UK Trade Importers CSV missing company name column. Found: {list(df_trade.columns)}")
        return None, None
    
    st.info(f"Matching on: '{ch_name_col}' (Companies House) ↔ '{trade_name_col}' (UK Trade)")
    
    companies_set = set(df_companies[ch_name_col].dropna().astype(str).str.strip().str.upper())
    trade_set = set(df_trade[trade_name_col].dropna().astype(str).str.strip().str.upper())
    
    matching_values = companies_set & trade_set
    
    matched_companies = df_companies[
        df_companies[ch_name_col].astype(str).str.strip().str.upper().isin(matching_values)
    ].copy()
    
    return matched_companies, ch_name_col

def get_company_details(company_name, api_key):
    """Fetch company details from Companies House API using company name search"""
    base_url = "https://api.company-information.service.gov.uk"
    
    try:
        search_url = f"{base_url}/search/companies"
        params = {"q": company_name, "size": 1}
        response = requests.get(search_url, auth=(api_key, ""), params=params)
        
        if response.status_code == 200:
            search_data = response.json()
            items = search_data.get("items", [])
            
            if not items:
                st.warning(f"No company found for: {company_name}")
                return None
            
            company_data = items[0]
            company_number = company_data.get("company_number")
            
            profile_url = f"{base_url}/company/{company_number}"
            profile_response = requests.get(profile_url, auth=(api_key, ""))
            
            if profile_response.status_code != 200:
                st.warning(f"API error for company {company_number}: {profile_response.status_code}")
                return None
            
            company_profile = profile_response.json()
            
            directors_url = f"{base_url}/company/{company_number}/officers"
            directors_response = requests.get(directors_url, auth=(api_key, ""))
            
            directors = []
            if directors_response.status_code == 200:
                directors_data = directors_response.json()
                for officer in directors_data.get("items", []):
                    if officer.get("resigned_on") is None:
                        name = officer.get("name", "")
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
                "company_name": company_profile.get("company_name", ""),
                "incorporation_date": company_profile.get("incorporation_date", ""),
                "directors": directors
            }
        else:
            st.warning(f"Search API error for {company_name}: {response.status_code}")
            return None
            
    except Exception as e:
        st.error(f"Error fetching company {company_name}: {e}")
        return None

def enrich_with_directors(df, api_key):
    """Enrich DataFrame with director information from API using company name"""
    if not api_key:
        st.error("Please enter your Companies House API key in the sidebar.")
        return None
    
    name_col = None
    for col in ["company_name", "Company_Name", "companyname", "CompanyName", "name", "Name"]:
        if col in df.columns:
            name_col = col
            break
    
    if name_col is None:
        st.error(f"Could not find a company name column. Found: {list(df.columns)}")
        return None
    
    st.info(f"Using column '{name_col}' for company name lookups")
    
    total = len(df)
    if total == 0:
        st.warning("No companies to enrich")
        return pd.DataFrame()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    enriched_data = []
    
    for idx, row in df.iterrows():
        company_name = str(row[name_col]).strip()
        status_text.text(f"Fetching details for {idx + 1}/{total}: {company_name}")
        
        details = get_company_details(company_name, api_key)
        
        if details:
            base_row = {
                "company_name": details["company_name"],
                "incorporation_date": details["incorporation_date"]
            }
            
            directors = details["directors"]
            for i, director in enumerate(directors):
                base_row[f"director_{i+1}_first_name"] = director["first_name"]
                base_row[f"director_{i+1}_surname"] = director["surname"]
            
            for i in range(len(directors), 10):
                base_row[f"director_{i+1}_first_name"] = ""
                base_row[f"director_{i+1}_surname"] = ""
            
            enriched_data.append(base_row)
        else:
            base_row = {
                "company_name": "",
                "incorporation_date": ""
            }
            for i in range(1, 11):
                base_row[f"director_{i}_first_name"] = ""
                base_row[f"director_{i}_surname"] = ""
            enriched_data.append(base_row)
        
        # Update progress (ensure value is between 0 and 1)
        progress_value = min((idx + 1) / total, 1.0)
        progress_bar.progress(progress_value)
    
    status_text.text("✅ Completed!")
    return pd.DataFrame(enriched_data)

# UI: File upload section
st.header("1. Upload CSV Files")

col1, col2 = st.columns(2)

with col1:
    ch_file = st.file_uploader(
        "Companies House CSV",
        type=["csv"],
        help="Upload your Companies House data CSV",
        key="ch_uploader"
    )

with col2:
    trade_file = st.file_uploader(
        "UK Trade Importers CSV",
        type=["csv"],
        help="Upload your UK Trade Importers CSV",
        key="trade_uploader"
    )

# Main workflow
if ch_file and trade_file:
    st.header("2. Cross-Reference Data")
    
    df_companies = load_csv(ch_file)
    df_trade = load_csv(trade_file)
    
    if df_companies is not None and df_trade is not None:
        st.success(f"✅ Loaded {len(df_companies)} companies and {len(df_trade)} trade records")
        
        with st.expander("Preview Companies House Data"):
            st.dataframe(df_companies.head())
        
        with st.expander("Preview UK Trade Data"):
            st.dataframe(df_trade.head())
        
        matched_df, match_column = find_matching_companies(df_companies, df_trade)
        
        if matched_df is not None:
            st.header("3. Matching Companies")
            st.success(f"Found **{len(matched_df)}** companies appearing in both datasets")
            st.dataframe(matched_df.head(10))
            
            csv_matched = matched_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Matched Companies (CSV)",
                csv_matched,
                f"matched_companies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key="download-matched"
            )
            
            st.header("4. Enrich with Director Information")
            
            if st.button("🚀 Fetch Director Details from Companies House API", type="primary"):
                if api_key:
                    enriched_df = enrich_with_directors(matched_df, api_key)
                    
                    if enriched_df is not None and len(enriched_df) > 0:
                        st.success(f"✅ Enriched {len(enriched_df)} companies with director data")
                        st.header("5. Final Results")
                        st.dataframe(enriched_df)
                        
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
Requests are made as fast as possible without artificial delays.
""")
