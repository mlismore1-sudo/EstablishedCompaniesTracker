import streamlit as st
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(page_title="Companies House & UK Trade Data", page_icon="🏢", layout="wide")

st.title("🏢 Companies House & UK Trade Data Cross-Reference")

st.sidebar.header("⚙️ Settings")
api_key = st.sidebar.text_input("Companies House API Key", type="password")

def load_csv(file):
    try:
        df = pd.read_csv(file)
        return df
    except Exception as e:
        st.warning(f"CSV error: {e}")
        try:
            file.seek(0)
            df = pd.read_csv(file, engine='python')
            return df
        except:
            st.error("Could not parse CSV")
            return None

def find_matches(df1, df2):
    col1 = col2 = None
    for c in df1.columns:
        if c.lower() in ['company_name', 'companyname', 'name']:
            col1 = c
            break
    for c in df2.columns:
        if c.lower() in ['companyname', 'company_name', 'name']:
            col2 = c
            break
    if not col1 or not col2:
        return None, None
    set1 = set(df1[col1].dropna().astype(str).str.strip().str.upper())
    set2 = set(df2[col2].dropna().astype(str).str.strip().str.upper())
    matches = set1 & set2
    result = df1[df1[col1].astype(str).str.strip().str.upper().isin(matches)].copy()
    return result, col1

def get_details(name, key):
    base = "https://api.company-information.service.gov.uk"
    try:
        r = requests.get(f"{base}/search/companies", auth=(key,""), params={"q":name,"size":1})
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        num = items[0].get("company_number")
        p = requests.get(f"{base}/company/{num}", auth=(key,""))
        if p.status_code != 200:
            return None
        prof = p.json()
        d = requests.get(f"{base}/company/{num}/officers", auth=(key,""))
        dirs = []
        if d.status_code == 200:
            for o in d.json().get("items", []):
                if o.get("resigned_on") is None:
                    nm = o.get("name","")
                    parts = nm.split(", ")
                    if len(parts) >= 2:
                        dirs.append({"first": " ".join(parts[1:]), "last": parts[0]})
                    else:
                        dirs.append({"first": "", "last": nm})
        return {"name": prof.get("company_name",""), "inc": prof.get("incorporation_date",""), "dirs": dirs}
    except:
        return None

def enrich(df, key):
    if not key:
        st.error("No API key")
        return None
    col = None
    for c in ["company_name","Company_Name","companyname","CompanyName","name","Name"]:
        if c in df.columns:
            col = c
            break
    if not col:
        st.error("No name column")
        return None
    total = len(df)
    if total == 0:
        return pd.DataFrame()
    prog = st.progress(0)
    data = []
    for i, (_, row) in enumerate(df.iterrows()):
        nm = str(row[col]).strip()
        det = get_details(nm, key)
        if det:
            r = {"company_name": det["name"], "incorporation_date": det["inc"]}
            for j, d in enumerate(det["dirs"]):
                r[f"director_{j+1}_first_name"] = d["first"]
                r[f"director_{j+1}_surname"] = d["last"]
            for j in range(len(det["dirs"]), 10):
                r[f"director_{j+1}_first_name"] = ""
                r[f"director_{j+1}_surname"] = ""
            data.append(r)
        else:
            r = {"company_name": "", "incorporation_date": ""}
            for j in range(1, 11):
                r[f"director_{j}_first_name"] = ""
                r[f"director_{j}_surname"] = ""
            data.append(r)
        prog.progress(min((i+1)/total, 1.0))
    return pd.DataFrame(data)

st.header("1. Upload CSV Files")
c1, c2 = st.columns(2)
with c1:
    f1 = st.file_uploader("Companies House CSV", type=["csv"], key="u1")
with c2:
    f2 = st.file_uploader("UK Trade CSV", type=["csv"], key="u2")

if f1 and f2:
    st.header("2. Cross-Reference")
    df1 = load_csv(f1)
    df2 = load_csv(f2)
    if df1 is not None and df2 is not None:
        st.success(f"Loaded {len(df1)} + {len(df2)} records")
        with st.expander("Preview CH"):
            st.dataframe(df1.head())
        with st.expander("Preview Trade"):
            st.dataframe(df2.head())
        matched, col = find_matches(df1, df2)
        if matched is not None:
            st.header("3. Matches")
            st.success(f"Found {len(matched)} matches")
            st.dataframe(matched.head(10))
            csv = matched.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download Matches", csv, f"matches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "text/csv", key="d1")
            st.header("4. Enrich")
            if st.button("🚀 Fetch Directors", type="primary"):
                if api_key:
                    enriched = enrich(matched, api_key)
                    if enriched is not None and len(enriched) > 0:
                        st.success(f"Enriched {len(enriched)} companies")
                        st.header("5. Results")
                        st.dataframe(enriched)
                        csv2 = enriched.to_csv(index=False).encode("utf-8")
                        st.download_button("📥 Download Enriched", csv2, f"enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "text/csv", key="d2")
else:
    st.info("Upload both files")

st.markdown("---")
st.caption("Companies House API")
