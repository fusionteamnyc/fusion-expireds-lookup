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
    PROPERTY_TYPE_OPTIONS,
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
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: #1a1a1a;
    }
    
    h1, h2, h3 {
        font-family: 'Playfair Display', Georgia, serif;
        font-weight: 600;
        color: #0a0a0a;
        letter-spacing: -0.02em;
    }
    
    .section-divider {
        border-top: 1px solid #e5e5e5;
        margin: 3rem 0 2rem 0;
    }
    
    .result-card {
        background: #fafafa;
        border: 1px solid #e5e5e5;
        border-radius: 8px;
        padding: 1.5rem 2rem;
        margin: 1rem 0;
    }
    .result-card .label {
        color: #888;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.2rem;
    }
    .result-card .value {
        color: #1a1a1a;
        font-size: 1.05rem;
        margin-bottom: 1rem;
        font-weight: 500;
    }
    
    .stButton > button {
        background-color: #1a1a1a;
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 0.7rem 2rem;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.85rem;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #b8932f;
        color: #ffffff;
    }
    
    .stDownloadButton > button {
        background-color: #ffffff;
        color: #1a1a1a;
        border: 1px solid #1a1a1a;
        border-radius: 4px;
        padding: 0.7rem 2rem;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.85rem;
    }
    .stDownloadButton > button:hover {
        background-color: #1a1a1a;
        color: #ffffff;
    }
    
    [data-testid="stFileUploader"] {
        background: #fafafa;
        border: 2px dashed #cccccc;
        border-radius: 8px;
        padding: 1rem;
    }
    
    .stProgress > div > div > div > div {
        background-color: #b8932f;
    }
    
    .footer-credit {
        text-align: center;
        color: #999;
        font-size: 0.8rem;
        margin-top: 4rem;
        padding-top: 1.5rem;
        border-top: 1px solid #eeeeee;
        letter-spacing: 0.05em;
    }
    
    .status-pill {
        display: inline-block;
        padding: 0.3rem 0.9rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .pill-found   { background: #e8f5e9; color: #2e7d32; }
    .pill-coop    { background: #fff8e1; color: #8a6d3b; }
    .pill-sponsor { background: #fce4ec; color: #ad1457; }
    .pill-missing { background: #f5f5f5; color: #757575; }
    .pill-mismatch { background: #fff3e0; color: #bf6a02; }
    .pill-match    { background: #e3f2fd; color: #1565c0; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# HEADER
# =====================================================================
logo_path = Path(__file__).parent / "static" / "logo.png"
col_logo, _ = st.columns([3, 1])
with col_logo:
    if logo_path.exists():
        st.image(str(logo_path), width=280)

st.markdown("# Expired Listings Lookup")
st.markdown(
    "<p style='color:#666; font-size:1rem; margin-top:-0.5rem;'>"
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
    with st.spinner("Looking up owner information..."):
        row = {
            'Property Type': single_type,
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
