# Fusion Team — Expired Listings Lookup Tool

A web app that takes NYC property addresses and returns owner of record info — supports single ad-hoc lookups (for agents) and bulk CSV processing (for skip-trace prep).

**Built by Beatriz Moitinho.**

## What's in v6

- **Name cross-check**: if you provide a "Check Owner Name 1" or "Check Owner Name 2" column, the tool compares your name against the ACRIS owner and flags matches/mismatches
- **Fallback to your name**: if ACRIS finds nothing but you provided a name, that name is used in the skip-trace export
- **Title row in outputs**: every output file is auto-stamped with `Fusion Team - Expired Listings - YYYY-MM-DD HH:MM` so files don't get mixed up
- **Geocoder retries**: each API call retries up to 3 times with exponential backoff on rate limits
- **Address caching**: same building geocoded once per batch, not per row (much faster, fewer API hits)
- **Early-failure warning**: if 10+ addresses fail in a row, the app warns you to re-run later
- **Smart name matching**: handles `BEATRIZ M` ↔ `MOITINHO, BEATRIZ` and `Suydam Realty Inc.` ↔ `SUYDAM REALTY, INC.`

## Property type handling

| Property Type | Behavior |
|---|---|
| Condo / Condominium | Unit-level deed lookup with full variant matrix |
| Co-op / Condop | No deed lookup (impossible by design); flagged for address-based search |
| Townhouse / House / N-family home / Multifamily home / Mixed-use / Rental unit | Strip unit, search building-level deed |
| Vacant land | Excluded entirely |

Edit `PROPERTY_TYPE_BEHAVIOR` in `engine.py` for different projects.

## Local development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deployment to Streamlit Community Cloud

1. Push this repo to GitHub
2. Go to share.streamlit.io, sign in with GitHub
3. New app → point at this repo → main file is `app.py`
4. Click Deploy

Uses only free public APIs. No keys required.

## Files

```
fusion_app/
├── app.py                  # Streamlit web app UI
├── engine.py               # Shared lookup logic (used by app & Colab)
├── requirements.txt        # Python dependencies
├── .streamlit/
│   └── config.toml         # Theme config
└── static/
    └── logo.png            # Fusion Team logo
```
