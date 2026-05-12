"""
Fusion Team — Expired Listings Lookup Tool
============================================

Streamlit web app. Imports lookup logic from engine.py so the same
code is used by both this app and the Colab notebook.

Built by Beatriz Moitinho.
"""

import streamlit as st
import pandas as pd
import time
from pathlib import Path

from engine import (
    PROPERTY_TYPE_OPTIONS, UI_LABEL_TO_INTERNAL,
    process_row, build_idi_export, df_to_csv_with_title,
    load_csv_smart, clear_cache, is_entity,
)

# =====================================================================
# Page config & theme
# =====================================================================
st.set_page_config(
    page_title="Fusion Team — Expired Listings Lookup",
    page_icon="🏛️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* === DARK THEME === */
    
    /* Hide Streamlit chrome */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Force dark background app-wide */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], .main {
        background-color: #0a0a0a !important;
    }
    
    /* Body text default */
    html, body, [class*="css"], .stMarkdown, p, span, div, label {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: #e8e8e8 !important;
    }
    
    /* Serif headings - white */
    h1, h2, h3, h4 {
        font-family: 'Playfair Display', Georgia, serif !important;
        font-weight: 600 !important;
        color: #ffffff !important;
        letter-spacing: -0.02em !important;
    }
    
    /* Muted secondary text */
    .muted, p {
        color: #999 !important;
    }
    
    /* Section dividers - subtle white line */
    .section-divider {
        border-top: 1px solid #2a2a2a;
        margin: 3rem 0 2rem 0;
    }
    
    /* Result card - dark with subtle border */
    .result-card {
        background: #1a1a1a;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        padding: 1.5rem 2rem;
        margin: 1rem 0;
    }
    .result-card .label {
        color: #777 !important;
        font-size: 0.78rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        margin-bottom: 0.2rem !important;
    }
    .result-card .value {
        color: #f5f5f5 !important;
        font-size: 1.05rem !important;
        margin-bottom: 1rem !important;
        font-weight: 500 !important;
    }
    
    /* Primary buttons - white on black */
    .stButton > button {
        background-color: #ffffff !important;
        color: #0a0a0a !important;
        border: none !important;
        border-radius: 4px !important;
        padding: 0.7rem 2rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        font-size: 0.85rem !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        background-color: #b8932f !important;
        color: #ffffff !important;
    }
    .stButton > button:disabled {
        background-color: #2a2a2a !important;
        color: #555 !important;
    }
    
    /* Download buttons - outlined white */
    .stDownloadButton > button {
        background-color: transparent !important;
        color: #ffffff !important;
        border: 1px solid #ffffff !important;
        border-radius: 4px !important;
        padding: 0.7rem 2rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        font-size: 0.85rem !important;
    }
    .stDownloadButton > button:hover {
        background-color: #ffffff !important;
        color: #0a0a0a !important;
    }
    
    /* Form inputs - dark fields */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #1a1a1a !important;
        color: #f5f5f5 !important;
        border: 1px solid #2a2a2a !important;
    }
    .stTextInput input::placeholder {
        color: #666 !important;
    }
    
    /* File uploader - dark dashed */
    [data-testid="stFileUploader"] {
        background: #1a1a1a !important;
        border: 2px dashed #444 !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    [data-testid="stFileUploader"] section, 
    [data-testid="stFileUploader"] label {
        background-color: transparent !important;
        color: #ccc !important;
    }
    
    /* Expander - dark */
    [data-testid="stExpander"], .stExpander {
        background-color: #1a1a1a !important;
        border: 1px solid #2a2a2a !important;
        border-radius: 8px !important;
    }
    [data-testid="stExpander"] summary {
        color: #ccc !important;
    }
    
    /* Progress bar - gold accent */
    .stProgress > div > div > div > div {
        background-color: #b8932f !important;
    }
    .stProgress > div > div > div {
        background-color: #2a2a2a !important;
    }
    
    /* Alerts (warning, success) - dark styled */
    .stAlert {
        background-color: #1a1a1a !important;
        border: 1px solid #2a2a2a !important;
        color: #e8e8e8 !important;
    }
    
    /* Metric cards */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
        color: #f5f5f5 !important;
    }
    [data-testid="stMetric"] {
        background-color: #1a1a1a !important;
        border: 1px solid #2a2a2a !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    
    /* Footer */
    .footer-credit {
        text-align: center;
        color: #555 !important;
        font-size: 0.8rem;
        margin-top: 4rem;
        padding-top: 1.5rem;
        border-top: 1px solid #2a2a2a;
        letter-spacing: 0.05em;
    }
    
    /* Status pills */
    .status-pill {
        display: inline-block;
        padding: 0.3rem 0.9rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .pill-found    { background: #1b3a1b; color: #7ed27e !important; }
    .pill-coop     { background: #3a2f1b; color: #d4b27e !important; }
    .pill-sponsor  { background: #3a1b2a; color: #d47ea0 !important; }
    .pill-missing  { background: #2a2a2a; color: #999 !important; }
    .pill-mismatch { background: #3a2a1b; color: #d49d5a !important; }
    .pill-match    { background: #1b2a3a; color: #7eb0d4 !important; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# HEADER
# =====================================================================
logo_path = Path(__file__).parent / "static" / "logo.png"
if logo_path.exists():
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        st.image(str(logo_path), use_container_width=True)

st.markdown(
    "<h1 style='text-align:center; margin-top: 2rem;'>Expired Listings Lookup</h1>",
    unsafe_allow_html=True
)
st.markdown(
    "<p style='text-align:center; color:#888; font-size:1rem; margin-top:-0.5rem;'>"
    "Find the owner of record for any NYC property — instantly or in bulk."
    "</p>",
    unsafe_allow_html=True
)

# =====================================================================
# SECTION 1: SINGLE SEARCH
# =====================================================================
st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.markdown("## Single Search")
st.markdown(
    "<p style='color:#666; font-size:0.95rem;'>"
    "Quick lookup for one property. Results appear below in seconds."
    "</p>",
    unsafe_allow_html=True
)

with st.form("single_search_form"):
    col1, col2 = st.columns([1, 2])
    with col1:
        single_type = st.selectbox(
            "Property Type",
            options=PROPERTY_TYPE_OPTIONS,
            index=0,
        )
    with col2:
        single_address = st.text_input(
            "Address",
            placeholder="e.g., 125 Greenwich Street #63G",
        )
    
    with st.expander("Optional fields (improves accuracy)"):
        col3, col4 = st.columns(2)
        with col3:
            single_area = st.text_input("Area / Neighborhood", placeholder="e.g., Financial District")
        with col4:
            single_check_name = st.text_input("Owner name to cross-check (optional)", placeholder="e.g., John Smith or Smith LLC")
    
    single_submit = st.form_submit_button("Look up owner")

if single_submit and single_address:
    clear_cache()
    # Translate the user-friendly dropdown label to the internal type the engine knows
    internal_type = UI_LABEL_TO_INTERNAL.get(single_type, single_type)
    with st.spinner("Looking up owner information..."):
        row = {
            'Property Type': internal_type,
            'Address': single_address,
            'Area': single_area or '',
            'Check Owner Name 1': single_check_name or '',
            'Check Owner Name 2': '',
        }
        result = process_row(row)
    
    # Determine status pill
    status = result.get('lookup_status', '')
    match_check = result.get('name_match_check', '')
    owner = result.get('owner_names')
    
    if result.get('is_sponsor_unit'):
        pill = '<span class="status-pill pill-sponsor">Sponsor Unit</span>'
    elif 'no individual deed' in (status or ''):
        pill = '<span class="status-pill pill-coop">Co-op / Condop</span>'
    elif owner:
        pill = '<span class="status-pill pill-found">Owner Found</span>'
    else:
        pill = '<span class="status-pill pill-missing">No Owner Found</span>'
    
    # Match pill (only show if user provided a name)
    match_pill = ''
    if single_check_name:
        if 'match (verified)' in match_check:
            match_pill = '&nbsp;<span class="status-pill pill-match">Name Verified</span>'
        elif 'mismatch' in match_check:
            match_pill = '&nbsp;<span class="status-pill pill-mismatch">Name Mismatch</span>'
        elif 'your name only' in match_check:
            match_pill = '&nbsp;<span class="status-pill pill-mismatch">ACRIS Empty - Using Your Name</span>'
    
    st.markdown(f"### Result &nbsp; {pill}{match_pill}", unsafe_allow_html=True)
    
    card_html = ['<div class="result-card">']
    
    def field(label, value):
        if value and str(value).strip() and str(value).lower() != 'nan':
            return (f'<div class="label">{label}</div>'
                    f'<div class="value">{value}</div>')
        return ''
    
    card_html.append(field("Property", single_address))
    card_html.append(field("Type", single_type))
    if owner:
        card_html.append(field("Owner (ACRIS)", owner))
        if result.get('owner_is_entity'):
            card_html.append(field("Owner Is", "Business entity (LLC / Corp / Trust)"))
        if result.get('owner_mailing_address'):
            card_html.append(field("Mailing Address", result['owner_mailing_address']))
        if result.get('deed_date'):
            card_html.append(field("Deed Date", str(result['deed_date'])[:10]))
        if result.get('dos_process_name'):
            card_html.append(field("Registered Agent", result['dos_process_name']))
        if result.get('dos_process_address'):
            card_html.append(field("Agent Address", result['dos_process_address']))
        if result.get('dos_status_note'):
            card_html.append(field("Entity Status", result['dos_status_note']))
    
    if single_check_name:
        card_html.append(field("Your Provided Name", single_check_name))
        card_html.append(field("Name Match Check", match_check))
    
    if result.get('is_sponsor_unit'):
        card_html.append(field("Note", "This unit appears to be sponsor-owned (no buyer deed on record yet)."))
    elif 'no individual deed' in (status or ''):
        card_html.append(field("Note", "Co-ops and condops do not have individual unit deeds in public records. Use a property-address reverse lookup to find the resident shareholder."))
    elif not owner:
        card_html.append(field("Note", "No deed found on file. May require manual review or address-based lookup."))
    
    card_html.append(field("Lookup Status", status))
    card_html.append('</div>')
    
    st.markdown(''.join(card_html), unsafe_allow_html=True)

elif single_submit and not single_address:
    st.warning("Please enter an address.")


# =====================================================================
# SECTION 2: BATCH SEARCH
# =====================================================================
st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.markdown("## Batch Search")
st.markdown(
    "<p style='color:#666; font-size:0.95rem;'>"
    "Upload your full list of properties and receive two enriched files: "
    "a complete data file and a skip-trace-ready upload file."
    "</p>",
    unsafe_allow_html=True
)

st.markdown(
    "<p style='font-size:0.85rem; color:#666;'>"
    "<strong>Expected columns:</strong> Property Type, Area, Address, Notes, Price, Bed, Bath, "
    "(optional) Check Owner Name 1, Check Owner Name 2"
    "</p>",
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader("Upload your CSV file", type=['csv'], label_visibility="collapsed")

run_batch = st.button("Run batch lookup", disabled=(uploaded_file is None))

if run_batch and uploaded_file:
    clear_cache()
    
    try:
        df = load_csv_smart(uploaded_file)
    except Exception as e:
        st.error(f"Could not read the CSV: {e}")
        st.stop()
    
    n = len(df)
    st.success(f"Loaded {n} properties.")
    
    progress = st.progress(0.0)
    status_box = st.empty()
    
    enriched_rows = []
    consecutive_failures = 0
    early_warning_shown = False
    
    for i, row in df.iterrows():
        addr = str(row.get('Address', '')).strip()
        if not addr:
            continue
        status_box.markdown(
            f"<p style='color:#666; font-size:0.9rem;'>"
            f"Processing {i+1} of {n} &nbsp;·&nbsp; "
            f"{row.get('Property Type', '?')} &nbsp;·&nbsp; {addr}"
            f"</p>",
            unsafe_allow_html=True
        )
        enrichment = process_row(row)
        enriched_rows.append({**row.to_dict(), **enrichment})
        
        # Early-failure detection
        if enrichment.get('lookup_status') == 'address not found':
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        
        if consecutive_failures >= 10 and not early_warning_shown:
            st.warning(
                "⚠️ Many addresses failing to geocode. This may indicate the "
                "NYC mapping service is rate-limited. Results will continue but "
                "may include false 'address not found' results — please re-run if needed."
            )
            early_warning_shown = True
        
        progress.progress((i + 1) / n)
        time.sleep(1.5)
    
    out_df = pd.DataFrame(enriched_rows)
    idi_df = build_idi_export(out_df)
    
    progress.empty()
    status_box.empty()
    
    # ----- Results summary -----
    owners_found = (out_df['owner_names'].notna() & (out_df['owner_names'] != '')).sum()
    llc_count = int(out_df['owner_is_entity'].sum())
    sponsor_count = int(out_df['is_sponsor_unit'].sum())
    coop_count = out_df['lookup_status'].str.contains('no individual deed', na=False).sum()
    
    # Name-check stats
    matches = (out_df['name_match_check'] == 'match (verified)').sum()
    mismatches = (out_df['name_match_check'] == 'mismatch -- investigate').sum()
    
    st.markdown("### Results")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total processed", n)
    m2.metric("Owners found", int(owners_found))
    m3.metric("Co-ops (address-only)", int(coop_count))
    m4.metric("Sponsor units excluded", sponsor_count)
    
    if matches or mismatches:
        st.markdown(
            f"<p style='color:#666; font-size:0.9rem; margin-top:1rem;'>"
            f"<strong>Name cross-check:</strong> "
            f"<span style='color:#1565c0;'>{matches} verified</span>, "
            f"<span style='color:#bf6a02;'>{mismatches} mismatches to investigate</span>"
            f"</p>",
            unsafe_allow_html=True
        )
    
    st.markdown(
        f"<p style='color:#666; font-size:0.9rem;'>"
        f"Of the owners found, <strong>{llc_count}</strong> are business entities. "
        f"Skip-trace file contains <strong>{len(idi_df)}</strong> rows ready for upload."
        f"</p>",
        unsafe_allow_html=True
    )
    
    # ----- Build the two output CSVs with title rows -----
    full_csv = df_to_csv_with_title(out_df).encode('utf-8')
    idi_csv = df_to_csv_with_title(idi_df).encode('utf-8')
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            label="⬇  Full Data File",
            data=full_csv,
            file_name="fusion_owners_full.csv",
            mime="text/csv",
        )
    with col_dl2:
        st.download_button(
            label="⬇  Skip-Trace Upload File",
            data=idi_csv,
            file_name="fusion_owners_for_skiptrace.csv",
            mime="text/csv",
        )


# =====================================================================
# FOOTER
# =====================================================================
st.markdown(
    '<div class="footer-credit">'
    'Built by Beatriz Moitinho &nbsp;·&nbsp; Fusion Team'
    '</div>',
    unsafe_allow_html=True
)
