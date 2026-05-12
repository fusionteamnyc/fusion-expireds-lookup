"""
Fusion Team Owner Lookup — Engine v6
=====================================

Shared lookup logic for both the Streamlit web app and the Colab notebook.
All the property-type rules, ACRIS lookups, DOS lookups, cross-checks,
caching, and retries live here.
"""

import time
import re
import requests
from datetime import datetime
from typing import Optional, Tuple, List, Dict

# =====================================================================
# PROJECT CONFIG: How to handle each property type
# =====================================================================
PROPERTY_TYPE_BEHAVIOR = {
    # Condominiums
    'Condo':                'condo_unit_lookup',
    'Condominium':          'condo_unit_lookup',
    # Co-ops & Condops (no individual deeds; address-based skip-trace)
    'Co-op':                'coop_no_lookup',
    'Coop':                 'coop_no_lookup',
    'Co-Op':                'coop_no_lookup',
    'Cooperative':          'coop_no_lookup',
    'Condop':               'coop_no_lookup',
    # Buildings (deed at lot level)
    'Townhouse':            'building_lookup',
    'House':                'building_lookup',
    'Two-family home':      'building_lookup',
    'Three-family home':    'building_lookup',
    'Four-family home':     'building_lookup',
    'Five-family home':     'building_lookup',
    'Multi-family home':    'building_lookup',
    'Multifamily home':     'building_lookup',
    'Multi family home':    'building_lookup',
    'Mixed-use Building':   'building_lookup',
    'Mixed-use':            'building_lookup',
    'Rental unit':          'building_lookup',
    'Rental':               'building_lookup',
    # Generic catch-all from the UI dropdown
    'Other':                'building_lookup',
    # Excluded entirely
    'Vacant land':          'excluded',
    'Land':                 'excluded',
}

PROPERTY_TYPE_OPTIONS = [
    'Condo',
    'Coop',
    'House',
    'Multi-Family',
    'Mixed-use',
    'Other',
]

# Maps simplified UI labels back to internal types the engine knows about.
UI_LABEL_TO_INTERNAL = {
    'Condo':        'Condo',
    'Coop':         'Co-op',
    'House':        'House',
    'Multi-Family': 'Multifamily home',
    'Mixed-use':    'Mixed-use Building',
    'Other':        'Other',
}

def get_behavior(property_type):
    if not property_type:
        return 'building_lookup', 'unknown type, defaulted to building_lookup'
    pt = property_type.strip()
    if pt in PROPERTY_TYPE_BEHAVIOR:
        return PROPERTY_TYPE_BEHAVIOR[pt], ''
    for k, v in PROPERTY_TYPE_BEHAVIOR.items():
        if k.lower() == pt.lower():
            return v, ''
    return 'building_lookup', f"unknown type '{pt}', defaulted to building_lookup"

# =====================================================================
# API endpoints (public NYC + NY State data sources)
# =====================================================================
GEOSEARCH_URL        = 'https://geosearch.planninglabs.nyc/v2/search'
ACRIS_LEGALS_URL     = 'https://data.cityofnewyork.us/resource/8h5j-fqxa.json'
ACRIS_MASTER_URL     = 'https://data.cityofnewyork.us/resource/bnx9-e6tj.json'
ACRIS_PARTIES_URL    = 'https://data.cityofnewyork.us/resource/636b-3b5g.json'
DOS_ACTIVE_URL       = 'https://data.ny.gov/resource/n9v6-gdp6.json'
DOS_ALL_FILINGS_URL  = 'https://data.ny.gov/resource/63wc-4exh.json'

HEADERS = {'User-Agent': 'fusion-team-lookup-tool/6.0'}

# Cache: address-string -> geocoder result. Cleared per batch run.
_geocode_cache: Dict[str, Optional[Tuple[str, str, str, str]]] = {}

def clear_cache():
    """Reset the in-memory geocoder cache between runs."""
    _geocode_cache.clear()

LLC_KEYWORDS = re.compile(
    r'\b(LLC|L\.L\.C\.|INC\.?|CORP\.?|CORPORATION|CO\.?|COMPANY|LP|L\.P\.|'
    r'LTD\.?|LIMITED|TRUST|HOLDINGS|GROUP|ASSOCIATES|PARTNERS|REALTY)\b',
    re.IGNORECASE)

def is_entity(name):
    return bool(name and LLC_KEYWORDS.search(name))

# =====================================================================
# Address parsing / unit variants
# =====================================================================

def split_address(raw):
    s = str(raw).strip()
    m = re.split(r'\s+(?:#|Apt\.?|Unit|PH|Ph\.?)\s*', s, maxsplit=1, flags=re.IGNORECASE)
    if len(m) == 2:
        building = m[0].strip()
        unit = m[1].strip().split('&')[0].split('/')[0].strip()
        return building, (unit or None)
    return s, None

def expand_unit_variants(unit):
    if not unit:
        return []
    u = unit.upper().strip()
    variants = set([u])
    clean = re.sub(r'[-\s]', '', u)
    variants.add(clean)
    for i in range(1, len(clean)):
        if clean[i-1].isdigit() != clean[i].isdigit() or \
           (clean[i-1].isalpha() and clean[i].isalpha() and i == 2 and clean[:2] == 'PH'):
            variants.add(clean[:i] + '-' + clean[i:])
            variants.add(clean[:i] + ' ' + clean[i:])
    m = re.match(r'^(\d+)([A-Z]*)$', clean)
    if m:
        num, letters = m.groups()
        variants.add(num.zfill(3) + letters)
        variants.add(num.zfill(4) + letters)
        variants.add(num.zfill(5) + letters)
        variants.add(num.lstrip('0') + letters)
        if len(letters) >= 2 and letters[-1] == letters[-2]:
            variants.add(num + letters[:-1])
        if len(letters) >= 2 and len(set(letters)) > 1:
            for ch in letters:
                variants.add(num + ch)
    ph_match = re.match(r'^(PH|TH)([\d]*)([A-Z]*)$', clean)
    if ph_match:
        prefix, nums, letters = ph_match.groups()
        if len(letters) >= 2 and letters[-1] == letters[-2]:
            variants.add(prefix + nums + letters[:-1])
        if len(letters) >= 2 and len(set(letters)) > 1:
            for ch in letters:
                variants.add(prefix + nums + ch)
        if nums or letters:
            mid = nums + letters
            variants.add(prefix + '-' + mid)
            variants.add(prefix + ' ' + mid)
    return [v for v in variants if v]

def borough_from_neighborhood(name):
    if not name:
        return None
    n = str(name).lower()
    mn = ['village', 'soho', 'tribeca', 'chelsea', 'midtown', 'upper east',
          'upper west', 'harlem', 'financial district', 'lincoln square',
          'lenox hill', 'murray hill', 'gramercy', 'kips bay', 'flatiron',
          'noho', 'nolita', 'chinatown', 'inwood', 'washington heights',
          'morningside', 'hell', 'roosevelt island', 'battery park',
          'turtle bay', 'sutton place', 'yorkville', 'carnegie hill',
          'manhattan', 'lower east side', 'east village', 'west village',
          'hudson square', 'nomad', 'theater district', 'civic center',
          'two bridges', 'east harlem', 'central harlem',
          'hamilton heights', 'beekman', 'fulton/seaport', 'fulton',
          'seaport', 'midtown south', 'west chelsea']
    bk = ['park slope', 'williamsburg', 'bushwick', 'bedford',
          'crown heights', 'stuyvesant', 'weeksville', 'greenpoint', 'gowanus',
          'red hook', 'sunset park', 'bay ridge', 'flatbush', 'midwood',
          'kensington', 'prospect', 'fort greene', 'clinton hill', 'dumbo',
          'cobble hill', 'carroll gardens', 'boerum hill', 'downtown brooklyn',
          'east new york', 'canarsie', 'ditmas', 'bensonhurst', 'borough park',
          'brooklyn heights', 'brooklyn', 'crown hts', 'bed-stuy', 'bed stuy',
          'bedford-stuyvesant', 'columbia st', 'greenwood', 'ocean hill']
    qn = ['queens', 'astoria', 'lic', 'long island city', 'hunters point',
          'ridgewood', 'sunnyside', 'jackson heights', 'forest hills', 'flushing',
          'rego park', 'kew gardens', 'elmhurst', 'corona', 'maspeth',
          'middle village', 'briarwood', 'whitestone']
    if any(k in n for k in mn): return 'Manhattan, NY'
    if any(k in n for k in bk): return 'Brooklyn, NY'
    if any(k in n for k in qn): return 'Queens, NY'
    if 'bronx' in n or 'riverdale' in n: return 'Bronx, NY'
    if 'staten island' in n: return 'Staten Island, NY'
    return None

# =====================================================================
# Network helpers with retry
# =====================================================================

def _get_with_retry(url, params, max_retries=3, timeout=20):
    """HTTP GET with exponential backoff on failures.
    Returns the parsed JSON, or None if all retries fail.
    """
    delay = 1.0
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            # Rate-limited or server error -> retry
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(delay)
            delay *= 2
    return None

# =====================================================================
# Geocoding (with caching + retry)
# =====================================================================

def geosearch(address, borough_hint=None):
    """Returns (bbl, borough_code, block, lot) or None.
    Results are cached for the duration of the run.
    """
    cache_key = f"{address}||{borough_hint or ''}"
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]
    
    queries = [address]
    if borough_hint:
        queries.insert(0, f'{address}, {borough_hint}')
    
    result = None
    for q in queries:
        data = _get_with_retry(GEOSEARCH_URL, {'text': q, 'size': 1})
        if not data:
            continue
        feats = data.get('features') or []
        if not feats:
            continue
        pad = (feats[0].get('properties', {}).get('addendum') or {}).get('pad') or {}
        bbl = pad.get('bbl')
        if bbl and len(bbl) == 10:
            result = (bbl, bbl[0], bbl[1:6], bbl[6:10])
            break
    
    _geocode_cache[cache_key] = result
    return result

# =====================================================================
# ACRIS lookups
# =====================================================================

def deeds_for_lot(boro, block, lot):
    where = f"borough='{boro}' AND block='{block}' AND lot='{lot}'"
    data = _get_with_retry(ACRIS_LEGALS_URL,
                           {'$where': where, '$limit': 500,
                            '$select': 'document_id,lot,unit'},
                           timeout=30)
    return data or []

def deeds_for_condo_unit(boro, block, unit_variants):
    if not unit_variants:
        return []
    all_legals = []
    for i in range(0, len(unit_variants), 30):
        chunk = unit_variants[i:i+30]
        quoted = ','.join(f"'{v}'" for v in chunk)
        where = f"borough='{boro}' AND block='{block}' AND unit in ({quoted})"
        data = _get_with_retry(ACRIS_LEGALS_URL,
                               {'$where': where, '$limit': 200,
                                '$select': 'document_id,lot,unit'},
                               timeout=30)
        if data:
            all_legals.extend(data)
    return all_legals

def newest_deed(legals_rows):
    doc_ids = list({r['document_id'] for r in legals_rows if r.get('document_id')})
    if not doc_ids:
        return None
    masters = []
    for i in range(0, len(doc_ids), 100):
        chunk = doc_ids[i:i+100]
        quoted = ','.join(f"'{d}'" for d in chunk)
        where = f"document_id in ({quoted}) AND starts_with(doc_type, 'DEED')"
        data = _get_with_retry(ACRIS_MASTER_URL,
                               {'$where': where, '$limit': 200,
                                '$order': 'document_date DESC',
                                '$select': 'document_id,doc_type,document_date,recorded_datetime'},
                               timeout=30)
        if data:
            masters.extend(data)
    if not masters:
        return None
    masters.sort(key=lambda m: m.get('document_date') or m.get('recorded_datetime') or '',
                 reverse=True)
    return masters[0]

def grantees(doc_id):
    data = _get_with_retry(ACRIS_PARTIES_URL,
                           {'document_id': doc_id, 'party_type': '2',
                            '$limit': 20,
                            '$select': 'name,address_1,address_2,city,state,zip'},
                           timeout=30)
    return data or []

# =====================================================================
# NY Department of State lookups
# =====================================================================

def lookup_dos_active(entity_name):
    if not entity_name:
        return None
    name = re.sub(r'\s+', ' ', entity_name).strip().upper().rstrip('.,')
    for params in (
        {'current_entity_name': name, '$limit': 5},
        {'current_entity_name': name.rstrip('.'), '$limit': 5},
        {'$where': f"starts_with(current_entity_name, '{name.rstrip(chr(46)).replace(chr(39), chr(39)+chr(39))}')", '$limit': 5},
    ):
        rows = _get_with_retry(DOS_ACTIVE_URL, params, timeout=30)
        if rows:
            row = rows[0]
            addr = ', '.join([p for p in [row.get('dos_process_address_1'),
                              row.get('dos_process_address_2'),
                              row.get('dos_process_city'),
                              row.get('dos_process_state'),
                              row.get('dos_process_zip')] if p])
            return {
                'dos_id': row.get('dos_id'),
                'dos_entity_name': row.get('current_entity_name'),
                'dos_jurisdiction': row.get('jurisdiction'),
                'dos_initial_date': row.get('initial_dos_filing_date'),
                'dos_process_name': row.get('dos_process_name'),
                'dos_process_address': addr,
                'dos_status_note': 'Active',
            }
    return None

def lookup_dos_all_filings(entity_name):
    if not entity_name:
        return None
    name = re.sub(r'\s+', ' ', entity_name).strip().upper()
    for v in [name, name.rstrip('.'), name.replace('.', '').strip()]:
        filings = _get_with_retry(DOS_ALL_FILINGS_URL,
                                  {'corp_name': v, '$limit': 100},
                                  timeout=30)
        if filings:
            base = filings[0]
            dissolved = any('DISSOLUTION' in (f.get('documenttype') or '').upper()
                            or 'SURRENDER' in (f.get('documenttype') or '').upper()
                            for f in filings)
            return {
                'dos_id': base.get('corpid_num'),
                'dos_entity_name': base.get('corp_name'),
                'dos_jurisdiction': base.get('juris'),
                'dos_initial_date': base.get('date_filed'),
                'dos_process_name': None,
                'dos_process_address': None,
                'dos_status_note': 'Dissolved/Inactive' if dissolved else 'Active or unknown',
            }
    return None

def verify_sponsor(boro, block, lot):
    for parent_lot in ['7501', '7502', '7503']:
        legals = deeds_for_lot(boro, block, parent_lot)
        deed = newest_deed(legals)
        if not deed:
            continue
        parties = grantees(deed['document_id'])
        if not parties:
            continue
        names = [p['name'] for p in parties if p.get('name')]
        if not names:
            continue
        sponsor_name = names[0]
        p0 = parties[0]
        addr = ', '.join([x for x in [p0.get('address_1'), p0.get('address_2'),
                          p0.get('city'), p0.get('state'), p0.get('zip')] if x])
        return {
            'sponsor_name': sponsor_name,
            'sponsor_mailing_address': addr,
        }
    return None

# =====================================================================
# Name normalization + smart matching (for cross-check)
# =====================================================================

NAME_NOISE = re.compile(r'\b(LLC|L\.L\.C\.|INC\.?|CORP\.?|CORPORATION|CO\.?|COMPANY|'
                        r'LP|L\.P\.|LTD\.?|LIMITED|THE)\b\.?',
                        re.IGNORECASE)

def normalize_name(name):
    """Lowercase, strip punctuation, normalize whitespace, drop entity suffixes."""
    if not name:
        return ''
    s = str(name).strip().lower()
    # Remove punctuation except spaces and hyphens
    s = re.sub(r"[.,'\"`*]", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def name_tokens(name):
    """Returns a SET of word tokens after normalization (entity words stripped)."""
    if not name:
        return set()
    s = normalize_name(name)
    s = NAME_NOISE.sub(' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Filter out 1-char tokens (initials we can't reliably match)
    return set(t for t in s.split() if len(t) >= 2)

def names_match(name_a, name_b):
    """Smart match: returns True if any meaningful name part overlaps.
    
    Examples that should match:
      'BEATRIZ M' <-> 'MOITINHO, BEATRIZ'        (beatriz)
      'John Smith' <-> 'SMITH, JOHN A'           (john + smith)
      'Suydam Realty Inc.' <-> 'SUYDAM REALTY, INC.'  (suydam + realty)
      'Greenwich Owner LLC' <-> 'GREENWICH OWNER LLC' (greenwich + owner)
    
    Examples that should NOT match:
      'John Smith' <-> 'Mary Johnson'
      'Greenwich Owner LLC' <-> 'Tribeca Holdings LLC'
    """
    if not name_a or not name_b:
        return False
    ta = name_tokens(name_a)
    tb = name_tokens(name_b)
    if not ta or not tb:
        return False
    # Require at least one meaningful token overlap.
    # For very short names, that's enough; for longer names, also helpful.
    overlap = ta & tb
    return len(overlap) >= 1

def cross_check_names(user_names, acris_names):
    """Compare your pre-existing names against ACRIS results.
    
    user_names: list of names you provided (may be empty list)
    acris_names: list of grantee names from ACRIS (may be empty list)
    
    Returns one of:
      'match (verified)'                - your name(s) match ACRIS
      'mismatch -- investigate'         - both have names, none match
      'your name only - using as fallback' - you have name, ACRIS empty
      'acris only'                       - ACRIS has name, you didn't
      'no name on file'                  - neither has a name
    """
    u = [n for n in (user_names or []) if n and str(n).strip()]
    a = [n for n in (acris_names or []) if n and str(n).strip()]
    if not u and not a:
        return 'no name on file'
    if u and not a:
        return 'your name only - using as fallback'
    if a and not u:
        return 'acris only'
    # Both populated -- check for any match
    for un in u:
        for an in a:
            if names_match(un, an):
                return 'match (verified)'
    return 'mismatch -- investigate'

# =====================================================================
# The main per-row processor
# =====================================================================

def process_row(row, user_name_columns=("Check Owner Name 1", "Check Owner Name 2",
                                         "Potential Owner's Name", "Potential Owner's Name ",
                                         "Owner Name", "Owner's Name 1", "Owner's Name 2",
                                         "Owner Name 1", "Owner Name 2", "Notes.1")):
    """Process a single property row.
    
    Args:
      row: dict-like with at least 'Address' and 'Property Type'.
            May also include 'Area' and any of the user_name_columns for cross-check.
      user_name_columns: tuple of column names that may contain a researcher-
                         provided owner name (for cross-checking). We accept
                         several common variants so files with different
                         column names still work.
    
    Returns:
      dict of new/enriched columns. Caller should merge this with the
      original row to build the output row.
    """
    address = str(row.get('Address', '')).strip()
    property_type = str(row.get('Property Type', '')).strip()
    area = str(row.get('Area', '')).strip()
    
    # Collect names from any of the recognized columns
    user_names = []
    seen = set()
    for col in user_name_columns:
        val = str(row.get(col, '')).strip()
        # Skip if empty, or looks like a URL/note (very long, contains http)
        if not val or val.lower() in ('nan', 'no contact'):
            continue
        if 'http' in val.lower() or len(val) > 200:
            continue
        if val.lower() in seen:
            continue
        seen.add(val.lower())
        user_names.append(val)
    
    behavior, behavior_note = get_behavior(property_type)
    
    out = {
        'lookup_behavior_applied': behavior,
        'behavior_note': behavior_note,
        'cleaned_address': None, 'unit_searched': None, 'bbl': None,
        'owner_names': None, 'owner_mailing_address': None,
        'owner_is_entity': False, 'deed_date': None, 'deed_type': None,
        'dos_id': None, 'dos_entity_name': None, 'dos_jurisdiction': None,
        'dos_initial_date': None, 'dos_process_name': None,
        'dos_process_address': None, 'dos_status_note': None,
        'is_sponsor_unit': False, 'sponsor_name': None,
        'sponsor_mailing_address': None,
        'lookup_status': '', 'skip_trace_strategy': '',
        'name_match_check': '',
        'final_owner_name_for_idi': '',
    }
    
    if not address:
        out['lookup_status'] = 'no address provided'
        out['name_match_check'] = cross_check_names(user_names, [])
        if user_names:
            out['final_owner_name_for_idi'] = user_names[0]
        return out
    
    if behavior == 'excluded':
        out['lookup_status'] = f'{property_type} (excluded from skip-trace)'
        out['skip_trace_strategy'] = 'EXCLUDE'
        out['name_match_check'] = cross_check_names(user_names, [])
        return out
    
    building, raw_unit = split_address(address)
    out['cleaned_address'] = building
    
    # Co-ops: no deed lookup possible
    if behavior == 'coop_no_lookup':
        out['lookup_status'] = f'{property_type} (no individual deed by design)'
        out['skip_trace_strategy'] = 'address-only (reverse-search resident)'
        boro_hint = borough_from_neighborhood(area)
        bbl_info = geosearch(building, boro_hint)
        if bbl_info:
            out['bbl'] = bbl_info[0]
        out['name_match_check'] = cross_check_names(user_names, [])
        # For co-ops, if user has a name, that's the best we have for IDI
        if user_names:
            out['final_owner_name_for_idi'] = user_names[0]
        return out
    
    if behavior == 'condo_unit_lookup':
        effective_unit = raw_unit
    else:
        effective_unit = None
    out['unit_searched'] = effective_unit
    
    boro_hint = borough_from_neighborhood(area)
    bbl_info = geosearch(building, boro_hint)
    if not bbl_info:
        out['lookup_status'] = 'address not found'
        out['name_match_check'] = cross_check_names(user_names, [])
        if user_names:
            out['final_owner_name_for_idi'] = user_names[0]
        return out
    bbl, boro, block, lot = bbl_info
    out['bbl'] = bbl
    
    legals = []
    if effective_unit:
        variants = expand_unit_variants(effective_unit)
        legals = deeds_for_condo_unit(boro, block, variants)
        if not legals:
            legals = deeds_for_lot(boro, block, lot)
    else:
        legals = deeds_for_lot(boro, block, lot)
    
    deed = newest_deed(legals)
    acris_names = []
    
    if deed:
        parties = grantees(deed['document_id'])
        if parties:
            out['deed_date'] = deed.get('document_date')
            out['deed_type'] = deed.get('doc_type')
            acris_names = [p['name'] for p in parties if p.get('name')]
            out['owner_names'] = ' | '.join(acris_names)
            p0 = parties[0]
            out['owner_mailing_address'] = ', '.join([x for x in [p0.get('address_1'),
                                                       p0.get('address_2'), p0.get('city'),
                                                       p0.get('state'), p0.get('zip')] if x])
            out['lookup_status'] = 'ok'
            out['skip_trace_strategy'] = 'by owner name'
            if acris_names and is_entity(acris_names[0]):
                out['owner_is_entity'] = True
                dos = lookup_dos_active(acris_names[0]) or lookup_dos_all_filings(acris_names[0])
                if dos:
                    for k, v in dos.items():
                        out[k] = v
                    out['lookup_status'] = 'ok (LLC, DOS found)'
                else:
                    out['lookup_status'] = 'ok (LLC, DOS not found)'
            out['name_match_check'] = cross_check_names(user_names, acris_names)
            out['final_owner_name_for_idi'] = acris_names[0]
            return out
    
    # No deed found - try sponsor check for condos
    if behavior == 'condo_unit_lookup' and effective_unit:
        sponsor = verify_sponsor(boro, block, lot)
        if sponsor:
            out['is_sponsor_unit'] = True
            out['sponsor_name'] = sponsor['sponsor_name']
            out['sponsor_mailing_address'] = sponsor['sponsor_mailing_address']
            out['owner_names'] = sponsor['sponsor_name']
            out['owner_mailing_address'] = sponsor['sponsor_mailing_address']
            out['owner_is_entity'] = True
            out['lookup_status'] = 'Sponsor Unit (no buyer deed; building owned by sponsor)'
            out['skip_trace_strategy'] = 'EXCLUDE - sponsor inventory'
            dos = lookup_dos_active(sponsor['sponsor_name']) or lookup_dos_all_filings(sponsor['sponsor_name'])
            if dos:
                for k, v in dos.items():
                    out[k] = v
            out['name_match_check'] = cross_check_names(user_names, [sponsor['sponsor_name']])
            out['final_owner_name_for_idi'] = sponsor['sponsor_name']
            return out
    
    # Final fallback: no deed, no sponsor, use user name if available
    out['lookup_status'] = 'no deed found'
    out['skip_trace_strategy'] = 'address-only (manual review recommended)'
    out['name_match_check'] = cross_check_names(user_names, [])
    if user_names:
        out['final_owner_name_for_idi'] = user_names[0]
    return out

# =====================================================================
# Output file builders
# =====================================================================

def make_title_row(num_columns, requester=None):
    """Generate the timestamped title row. Returns a list of `num_columns`
    items where the first is the title text and the rest are blank.
    
    If `requester` is provided, includes it in the title.
    """
    base = f"Fusion Team - Expired Listings - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if requester:
        title = f"{base} - Requested by: {requester}"
    else:
        title = base
    return [title] + [''] * (num_columns - 1)

def _safe_str(value):
    """Coerce any value (NaN, None, float, missing) to a clean string."""
    if value is None:
        return ''
    s = str(value).strip()
    if s.lower() == 'nan':
        return ''
    return s

def flag_bulk_owner_sponsors(out_df, min_units=3):
    """Post-process: detect LLCs that own 3+ units in the same building.
    
    These are very likely sponsors (developers selling new construction).
    Updates the is_sponsor_unit flag on those rows IN PLACE.
    
    Args:
      out_df: enriched DataFrame from a batch run
      min_units: minimum number of units to qualify as bulk-owning sponsor
    """
    import pandas as pd
    if out_df.empty:
        return out_df
    
    # Group by (BBL prefix = building) + LLC name
    # BBL is 10 chars: borough(1) + block(5) + lot(4)
    # Same building = same borough+block; same LLC = same owner_names
    
    bulk_signatures = set()  # (borough+block, llc_name)
    bbl_to_building = {}
    
    for idx, r in out_df.iterrows():
        bbl = _safe_str(r.get('bbl'))
        owner = _safe_str(r.get('owner_names'))
        if not bbl or len(bbl) < 10 or not owner:
            continue
        # Use first owner if multiple
        first_owner = owner.split('|')[0].strip()
        if not is_entity(first_owner):
            continue
        building_key = bbl[:6]  # borough + block
        sig = (building_key, first_owner.upper())
        bbl_to_building[idx] = sig
    
    # Count occurrences of each (building, llc) signature
    from collections import Counter
    counts = Counter(bbl_to_building.values())
    
    # Any signature with >= min_units is a bulk-owner sponsor
    bulk_signatures = {sig for sig, count in counts.items() if count >= min_units}
    
    if not bulk_signatures:
        return out_df
    
    # Update is_sponsor_unit for matching rows
    # Add the columns if they don't exist
    if 'is_sponsor_unit' not in out_df.columns:
        out_df['is_sponsor_unit'] = False
    if 'sponsor_name' not in out_df.columns:
        out_df['sponsor_name'] = ''
    
    for idx, sig in bbl_to_building.items():
        if sig in bulk_signatures:
            out_df.at[idx, 'is_sponsor_unit'] = True
            existing = _safe_str(out_df.at[idx, 'sponsor_name'])
            if not existing:
                out_df.at[idx, 'sponsor_name'] = sig[1]
    
    return out_df


def _addresses_match(a, b):
    """Return True if two addresses appear to be the same building.
    
    Compares just the number+street portion of each (ignoring unit, city, state, zip).
    Examples that match:
      '125 Greenwich St #63G' == '125 Greenwich Street'
      '125 Bond Street, Brooklyn, NY, 11217' == '125 Bond Street'
      '670a Greene Avenue' == '670A Greene Ave'
    """
    if not a or not b:
        return False
    
    def normalize(s):
        s = str(s).lower().strip()
        # Take everything before the FIRST comma (drops city/state/zip)
        s = s.split(',')[0].strip()
        # Take everything before unit/apt/floor indicators
        s = re.split(r'\s+(?:#|apt\.?|unit|fl\.?|floor|suite|ste\.?)\s*', s, maxsplit=1)[0]
        # Normalize street type abbreviations
        s = re.sub(r'\b(street|st\.?)\b', 'st', s)
        s = re.sub(r'\b(avenue|ave\.?)\b', 'ave', s)
        s = re.sub(r'\b(boulevard|blvd\.?)\b', 'blvd', s)
        s = re.sub(r'\b(place|pl\.?)\b', 'pl', s)
        s = re.sub(r'\b(road|rd\.?)\b', 'rd', s)
        s = re.sub(r'\b(drive|dr\.?)\b', 'dr', s)
        s = re.sub(r'\b(north|n\.?)\b', 'n', s)
        s = re.sub(r'\b(south|s\.?)\b', 's', s)
        s = re.sub(r'\b(east|e\.?)\b', 'e', s)
        s = re.sub(r'\b(west|w\.?)\b', 'w', s)
        s = re.sub(r'[.,\']', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s
    
    return normalize(a) == normalize(b)

def build_idi_export(out_df):
    """Build the IDI skip-trace export with the Fusion Team format.
    
    Column order:
      1. Owner First Name
      2. Owner Last Name
      3. LLC Name
      4. Property Address (full)
      5. Area
      6. Property Type (may be flagged as "Sponsor Condo" / "Sponsor Coop")
      7. Owner Mailing Address (blank if same building as property)
      8. Property Status
      9. Name Check (blank unless mismatch; shows USER's original name for comparison)
    
    Sort order:
      1. Individual owners A-Z by last name
      2. LLC owners A-Z by LLC name
      3. Sponsor units at the bottom
    """
    import pandas as pd
    individuals = []
    llcs = []
    sponsors = []
    
    for _, r in out_df.iterrows():
        behavior = _safe_str(r.get('lookup_behavior_applied'))
        original_property_type = _safe_str(r.get('Property Type'))
        is_sponsor_val = _safe_str(r.get('is_sponsor_unit'))
        is_sponsor = is_sponsor_val.lower() in ('true', '1', 'yes')
        is_coop = behavior == 'coop_no_lookup'
        property_address = _safe_str(r.get('Address'))
        area = _safe_str(r.get('Area'))
        property_status = _safe_str(r.get('Notes.1'))
        
        # Skip vacant land and other 'excluded' types entirely
        if behavior == 'excluded':
            continue
        
        # ACRIS findings
        acris_names_str = _safe_str(r.get('owner_names'))
        acris_first_name = acris_names_str.split('|')[0].strip() if acris_names_str else ''
        
        # User's original name (for cross-check column)
        user_name = ''
        for col in ['Check Owner Name 1', 'Check Owner Name 2',
                    "Potential Owner's Name", "Potential Owner's Name ",
                    'Owner Name', "Owner's Name 1", "Owner's Name 2"]:
            v = _safe_str(r.get(col))
            if v and 'http' not in v.lower() and len(v) < 200:
                user_name = v
                break
        
        name_check_value = _safe_str(r.get('name_match_check'))
        
        # Build the cross-check column: only fill if mismatch, show USER's name
        if name_check_value == 'mismatch -- investigate' and user_name:
            name_check_display = user_name
        else:
            name_check_display = ''
        
        # Determine the "final" name and whether it's an entity
        final_name = _safe_str(r.get('final_owner_name_for_idi'))
        owner_is_entity = bool(r.get('owner_is_entity')) and \
                          _safe_str(r.get('owner_is_entity')).lower() in ('true', '1', 'yes')
        # Fall back to detecting entity from the name itself
        if not owner_is_entity and final_name and is_entity(final_name):
            owner_is_entity = True
        
        # Build name fields
        first_name = ''
        last_name = ''
        llc_name = ''
        
        if final_name:
            if owner_is_entity:
                llc_name = final_name
            else:
                if ',' in final_name:
                    last_name, rest = final_name.split(',', 1)
                    last_name = last_name.strip()
                    first_name = rest.strip()
                else:
                    parts = final_name.split()
                    if len(parts) >= 2:
                        first_name = parts[0]
                        last_name = ' '.join(parts[1:])
                    else:
                        last_name = final_name
        
        # Build owner mailing address
        mailing_address = (_safe_str(r.get('dos_process_address'))
                           or _safe_str(r.get('owner_mailing_address')))
        
        # If mailing address is at the same building as the property, leave blank
        if mailing_address and _addresses_match(mailing_address, property_address):
            mailing_address = ''
        
        # Sponsor unit: relabel property type
        property_type_label = original_property_type
        if is_sponsor:
            if 'condo' in original_property_type.lower():
                property_type_label = 'Sponsor Condo'
            elif 'co-op' in original_property_type.lower() or 'coop' in original_property_type.lower():
                property_type_label = 'Sponsor Coop'
            elif 'condop' in original_property_type.lower():
                property_type_label = 'Sponsor Condop'
            else:
                property_type_label = f'Sponsor {original_property_type}'
        
        row_data = {
            'Owner First Name': first_name,
            'Owner Last Name': last_name,
            'LLC Name': llc_name,
            'Property Address': property_address,
            'Area': area,
            'Property Type': property_type_label,
            'Owner Mailing Address': mailing_address,
            'Property Status': property_status,
            'Name Check': name_check_display,
        }
        
        # Route to the right tier for sorting
        if is_sponsor:
            sponsors.append(row_data)
        elif llc_name:
            llcs.append(row_data)
        else:
            individuals.append(row_data)
    
    # Sort each tier
    individuals.sort(key=lambda x: (x.get('Owner Last Name', '').upper(),
                                     x.get('Owner First Name', '').upper()))
    llcs.sort(key=lambda x: x.get('LLC Name', '').upper())
    sponsors.sort(key=lambda x: x.get('LLC Name', '').upper())
    
    # Concatenate: individuals first, then LLCs, then sponsors
    all_rows = individuals + llcs + sponsors
    
    if not all_rows:
        # Return empty DataFrame with the right columns
        return pd.DataFrame(columns=[
            'Owner First Name', 'Owner Last Name', 'LLC Name', 'Property Address',
            'Area', 'Property Type', 'Owner Mailing Address', 'Property Status',
            'Name Check'
        ])
    
    return pd.DataFrame(all_rows)

def sort_full_export(out_df):
    """Sort the full enriched DataFrame in the same 3-tier order as IDI:
    1. Individual owners A-Z by last name
    2. LLC owners A-Z by LLC name
    3. Sponsor units at the bottom
    
    Returns a NEW sorted DataFrame; does not modify input.
    """
    import pandas as pd
    if out_df.empty:
        return out_df
    
    def sort_key(row):
        # Tier: 0=individual, 1=LLC, 2=sponsor
        is_sponsor = _safe_str(row.get('is_sponsor_unit')).lower() in ('true', '1', 'yes')
        owner_name = _safe_str(row.get('owner_names'))
        first_owner = owner_name.split('|')[0].strip() if owner_name else ''
        
        if is_sponsor:
            tier = 2
        elif first_owner and is_entity(first_owner):
            tier = 1
        else:
            tier = 0
        
        # Within tier, sort by the owner name (or empty -> last)
        # For individuals: parse out last name for proper alpha sort
        if tier == 0 and first_owner:
            if ',' in first_owner:
                # Already "LAST, FIRST" - sort by full string
                sort_name = first_owner.upper()
            else:
                # "FIRST LAST" - sort by last word
                parts = first_owner.upper().split()
                sort_name = parts[-1] if parts else ''
        else:
            sort_name = first_owner.upper() if first_owner else 'ZZZZZ'
        
        return (tier, sort_name)
    
    # Build a sort key column, sort, then drop it
    out_df = out_df.copy()
    out_df['_sort_key'] = out_df.apply(sort_key, axis=1)
    out_df = out_df.sort_values('_sort_key').reset_index(drop=True)
    out_df = out_df.drop(columns=['_sort_key'])
    return out_df


    """Convert DataFrame to a CSV string with a title row at the very top.
    Returns a string. Caller can encode to bytes for download.
    
    If `requester` is provided, includes it in the title row.
    """
    import io
    import csv as csvmod
    
    if num_columns is None:
        num_columns = len(df.columns)
    title_row = make_title_row(num_columns, requester=requester)
    
    buf = io.StringIO()
    writer = csvmod.writer(buf)
    writer.writerow(title_row)
    # Header
    writer.writerow(list(df.columns))
    # Data rows
    for _, r in df.iterrows():
        writer.writerow([r[c] for c in df.columns])
    return buf.getvalue()

# =====================================================================
# Smart CSV loader (handles title row)
# =====================================================================

def load_csv_smart(file_obj):
    """Read a CSV, auto-detecting a title row if present.
    
    Strategy:
      1. Try reading normally. If it parses cleanly AND row 0 looks like real
         headers (contains 'Address' or 'Property Type'), use as-is.
      2. If parsing fails OR row 0 doesn't look like headers, try skipping
         the first row (treating it as a title) and re-read.
      3. If that also fails, raise the error.
    """
    import pandas as pd
    
    def _seek(f):
        try:
            f.seek(0)
        except Exception:
            pass
    
    # Strategy 1: read normally
    _seek(file_obj)
    try:
        df = pd.read_csv(file_obj, dtype=str, keep_default_na=False)
        cols_lower = [str(c).lower().strip() for c in df.columns]
        if 'address' in cols_lower or 'property type' in cols_lower:
            return df
    except Exception:
        pass
    
    # Strategy 2: skip first row (title), try again
    _seek(file_obj)
    try:
        df = pd.read_csv(file_obj, skiprows=1, dtype=str, keep_default_na=False)
        cols_lower = [str(c).lower().strip() for c in df.columns]
        if 'address' in cols_lower or 'property type' in cols_lower:
            return df
    except Exception:
        pass
    
    # Strategy 3: maybe headerless 8-column file (legacy StreetEasy export)
    _seek(file_obj)
    try:
        df = pd.read_csv(file_obj, header=None, dtype=str, keep_default_na=False,
                         names=['Property Type', 'Area', 'Address', 'Notes',
                                'Price', 'Bed', 'Bath', 'Status'])
        return df
    except Exception:
        pass
    
    # Strategy 4: try reading with the python engine (more forgiving)
    _seek(file_obj)
    try:
        df = pd.read_csv(file_obj, dtype=str, keep_default_na=False,
                         engine='python', on_bad_lines='skip')
        cols_lower = [str(c).lower().strip() for c in df.columns]
        if 'address' in cols_lower or 'property type' in cols_lower:
            return df
    except Exception:
        pass
    
    # Strategy 5: python engine + skip first row
    _seek(file_obj)
    df = pd.read_csv(file_obj, skiprows=1, dtype=str, keep_default_na=False,
                     engine='python', on_bad_lines='skip')
    return df
