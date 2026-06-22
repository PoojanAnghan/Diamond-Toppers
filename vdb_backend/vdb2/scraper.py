#!/usr/bin/env python3
"""
Excel-Driven VDB Diamond API Scraper with Excel Enrichment (vdb2)
=================================================================
Reads search queries row-by-row from Input VDB.xlsx, maps criteria
to VDB API filters, paginates through all matches, extracts the top 10
cheapest distinct prices with their occurrence counts, and writes them
directly back into Input VDB.xlsx.
"""

import os
import sys
import json
import time
import httpx
import pandas as pd
import random

# ── Configuration & Paths ───────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "session_config.json")
EXCEL_PATH = os.path.join(BASE_DIR, "Input VDB (1).xlsx")
DATA_JSON_PATH = os.path.join(BASE_DIR, "data.json")

# Dry-run mode: use data.json instead of real API calls, skip all sleeps
# Used only when running as a standalone script
_CLI_DRY_RUN = "--dry-run" in sys.argv


def sleep_interruptible(seconds: float, cancel_event=None):
    """Sleep in 0.1-second increments, checking for cancellation event to allow instant interrupts."""
    if not cancel_event:
        time.sleep(seconds)
        return
    ticks = int(seconds / 0.1)
    for _ in range(ticks):
        if cancel_event.is_set():
            raise InterruptedError("Scraper execution was cancelled by user request.")
        time.sleep(0.1)
    rem = seconds % 0.1
    if rem > 0 and not cancel_event.is_set():
        time.sleep(rem)


def call_time_sleep(dry_run=False, cancel_event=None):
    if dry_run:
        print("   ⏱️ [DRY-RUN] Skipping page sleep.")
        return
    sleep_seconds = random.randint(20, 40)
    print(f"   ⏱️ Rate Limit Throttling: sleeping {sleep_seconds}s...")
    sleep_interruptible(sleep_seconds, cancel_event)


def filter_call_time_sleep(dry_run=False, cancel_event=None):
    if dry_run:
        print("   ⏱️ [DRY-RUN] Skipping filter row sleep.")
        return
    sleep_seconds = random.randint(300, 500)
    print(f"   ⏱️ Rate Limit Throttling: sleeping {sleep_seconds}s...")
    sleep_interruptible(sleep_seconds, cancel_event)


MAX_PAGES_PER_QUERY = 25       # Hard limit of 600 diamonds per row to prevent locks
PAGE_SIZE = 24                 # API chunk size


# ── Mapping Helpers ─────────────────────────────────────────────────────────

def map_shape(shape):
    """Normalize Excel shapes to VDB shape standards."""
    if not shape or pd.isna(shape):
        return None
    s = str(shape).strip().upper()
    if s == "ROUND": return "Round"
    if s == "PRINCESS": return "Princess"
    if s == "EMERALD": return "Emerald"
    if s == "RADIANT": return "Radiant"
    if s == "MARQUISE": return "Marquise"
    if s == "PEAR": return "Pear"
    if s in ["OVAL", "OVAL BRILLIANT"]: return "Oval"
    if s == "HEART": return "Heart"
    return str(shape).strip().title()


QUALITY_MAPPING = {
    "EX": "Excellent",
    "VG": "Very Good",
    "G": "Good",
    "FR": "Fair",
    "ID": "Ideal",
    "8X": "8X",
}


def map_quality(q):
    """Normalize Excel quality grades (Cut, Polish, Sym) using QUALITY_MAPPING."""
    if not q or pd.isna(q):
        return None
    
    q_str = str(q).strip()
    
    # 1. Match against keys (case-insensitive)
    for key, val in QUALITY_MAPPING.items():
        if q_str.upper() == key.upper():
            return val
            
    # 2. Match against values (case-insensitive)
    for key, val in QUALITY_MAPPING.items():
        if q_str.lower() == val.lower():
            return val
            
    # 3. Otherwise use as is
    return q_str



# ── Configuration Loader ───────────────────────────────────────────────────

def load_config():
    """Load session headers and tokens from session_config.json."""
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ Configuration file not found at: {CONFIG_PATH}")
        print("💡 Make sure session_config.json is populated with active cookies/tokens.")
        return None

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error reading session_config.json: {e}")
        return None


# ── Main Scraper Loop ───────────────────────────────────────────────────────

def run_scraper(excel_path=None, dry_run=None, cancel_event=None, on_row_completed=None):
    """
    Main scraper function.

    Args:
        excel_path: Path to the .xlsx file to process. Defaults to EXCEL_PATH.
        dry_run: If True, use data.json instead of real API calls. Defaults to CLI flag.
    """
    if excel_path is None:
        excel_path = EXCEL_PATH
    if dry_run is None:
        dry_run = _CLI_DRY_RUN

    print("=" * 60)
    print("  Excel-Driven VDB API Scraper (vdb2 - Enriched)")
    if dry_run:
        print("  🧪 MODE: DRY-RUN (using data.json, no API calls)")
    print("=" * 60)

    # 1. Load Session Config
    config = load_config()
    if not config:
        return

    api_url = config.get("api_url")
    auth_token = config.get("authorization")
    cookies = config.get("cookie")
    user_agent = config.get("user_agent")

    if not all([api_url, auth_token, cookies]):
        print("❌ Missing required keys in session_config.json (api_url, authorization, cookie).")
        return

    # 2. Load Excel File
    if not os.path.exists(excel_path):
        print(f"❌ Excel input file not found at: {excel_path}")
        return

    try:
        df_input = pd.read_excel(excel_path)
        print(f"📊 Loaded Excel sheet with {len(df_input)} rows.")
    except Exception as e:
        print(f"❌ Error reading Excel file: {e}")
        return

    # Set up HTTP headers
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en,ta;q=0.9",
        "authorization": auth_token,
        "content-type": "application/json",
        "cookie": cookies,
        "origin": "https://app.vdbapp.com",
        "referer": (
            "https://app.vdbapp.com/webapp/lab-grown-diamonds/search"
            "?priceMode=1&productType=lab_grown_diamond"
            "&fromNewFilterScreen=false&filterSplitStep=1"
            "&sectionName=Single%20Stones&breadCrumbLabel=Stone%20Search"
            "&enterSecondFlow=false"
        ),
        "user-agent": user_agent or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    }

    # Iterate over Excel rows
    with httpx.Client() as client:
        for idx, row in df_input.iterrows():
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Scraper execution was cancelled by user request.")
            # Check if row is already completed in a previous attempt
            if "Scrape_Status" in df_input.columns and df_input.loc[idx, "Scrape_Status"] == "COMPLETED":
                print(f"\n⚙️  Processing Excel Row {idx+1}/{len(df_input)}...")
                print(f"   ⏭️ Row already processed successfully in a previous run. Skipping.")
                continue

            print(f"\n⚙️  Processing Excel Row {idx+1}/{len(df_input)}...")
            
            # Map Excel row to VDB search API filter payload
            vdb_payload = {
                "page_size": PAGE_SIZE,
                "price_mode": 1,
                "lab_grown": True,
                "preference": ["total_price ASC"],
                "pair": "other",
                "vdb_setting": "true",
                "results_view_type": "grid",
                "with_available_items": False,
            }

            # Map filters
            shape_mapped = map_shape(row.get("Shape"))
            if shape_mapped:
                vdb_payload["shapes"] = [shape_mapped]

            carat = row.get("Carat")
            if carat and not pd.isna(carat):
                vdb_payload["size_from"] = str(carat)
                vdb_payload["size_to"] = str(carat)

            color = row.get("Color")
            if color and not pd.isna(color):
                vdb_payload["color_from"] = str(color).strip()
                vdb_payload["color_to"] = str(color).strip()

            clarity = row.get("Clarity")
            if clarity and not pd.isna(clarity):
                vdb_payload["clarity_from"] = str(clarity).strip()
                vdb_payload["clarity_to"] = str(clarity).strip()

            cut = map_quality(row.get("Cut"))
            polish = map_quality(row.get("Polish"))
            sym = map_quality(row.get("Sym"))

            if cut:
                vdb_payload["cut_from"] = cut
                vdb_payload["cut_to"] = cut
            if polish:
                vdb_payload["polish_from"] = polish
                vdb_payload["polish_to"] = polish
            if sym:
                vdb_payload["symmetry_from"] = sym
                vdb_payload["symmetry_to"] = sym

            # Fluorescence filter (from Flo column)
            flo = row.get("Flo")
            if flo and not pd.isna(flo):
                vdb_payload["fluorescence_intensities"] = [str(flo).strip()]
            else:
                vdb_payload["fluorescence_intensities"] = ["None"]

            growth = row.get("growth_type")
            if growth and not pd.isna(growth):
                vdb_payload["growth_type"] = [str(growth).strip().upper()]

            row_diamonds = []
            seen_ids = set()
            page_number = 1

            print(f"   Filters: Shape={shape_mapped}, Carat={carat}, Color={color}, Clarity={clarity}, Growth={growth}")

            # Nested Pagination Loop
            if dry_run:
                # ── DRY-RUN: Load diamonds from data.json instead of API ──
                print(f"   🧪 [DRY-RUN] Loading diamonds from data.json...")
                try:
                    with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
                        mock_data = json.load(f)
                    diamonds = mock_data.get("response", {}).get("body", {}).get("diamonds", [])
                    row_diamonds = diamonds
                    print(f"   📥 [DRY-RUN] Loaded {len(row_diamonds)} diamonds from data.json.")
                except Exception as e:
                    print(f"   ❌ [DRY-RUN] Failed to load data.json: {e}")
            else:
                # ── LIVE: Paginate through the real API ──
                while page_number <= MAX_PAGES_PER_QUERY:
                    if cancel_event and cancel_event.is_set():
                        raise InterruptedError("Scraper execution was cancelled by user request.")
                    vdb_payload["page_number"] = page_number
                    payload = {"vdb": vdb_payload}
                    
                    # Simulating human click/think delay before the request (2 to 5 seconds)
                    click_delay = random.uniform(2.0, 5.0)
                    sleep_interruptible(click_delay, cancel_event)

                    response = None
                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        print(f"   📡 Querying Page {page_number} (Attempt {attempt}/{max_retries})...")
                        try:
                            response = client.post(
                                api_url,
                                json=payload,
                                headers=headers,
                                timeout=30.0
                            )
                            if response.status_code == 200:
                                break
                            elif response.status_code in [401, 403]:
                                # Auth expired or bot blocked (immediate break, no retry)
                                break
                            else:
                                print(f"   ⚠️ Server returned status {response.status_code}.")
                        except Exception as e:
                            print(f"   ⚠️ Connection error: {e}")
                        
                        if attempt < max_retries:
                            retry_delay = random.randint(10, 20)
                            print(f"      ⏱️ Retrying in {retry_delay}s...")
                            sleep_interruptible(float(retry_delay), cancel_event)

                    if response is None or response.status_code != 200:
                        if response and response.status_code == 401:
                            raise PermissionError("VDB session expired (401). Please update session_config.json with active cookies/tokens.")
                        elif response and response.status_code == 403:
                            raise PermissionError("VDB access denied (403). Bot block triggered. Please update session_config.json.")
                        else:
                            raise RuntimeError(f"Failed to fetch page after maximum retries (Status Code: {response.status_code if response else 'Unknown'}).")

                    try:
                        res_data = response.json()
                    except Exception:
                        print("   ❌ Failed to parse JSON response.")
                        break

                    diamonds = res_data.get("response", {}).get("body", {}).get("diamonds", [])
                    if not diamonds:
                        print("   ✅ End of results reached.")
                        break

                    # Safety check for duplicates (infinite loop guard)
                    new_diamonds = [d for d in diamonds if d.get("id") not in seen_ids]
                    if not new_diamonds:
                        print("   ⚠️ No new diamond IDs on this page. Stopping query.")
                        break

                    # Add to dataset
                    for d in new_diamonds:
                        seen_ids.add(d.get("id"))
                        row_diamonds.append(d)

                    print(f"   📥 Retrieved {len(diamonds)} diamonds (Added {len(new_diamonds)} unique).")

                    # If returned records are fewer than PAGE_SIZE, it's the last page
                    if len(diamonds) < PAGE_SIZE:
                        break

                    page_number += 1
                    
                    # Apply rate limiting delay between page requests
                    call_time_sleep(dry_run=dry_run, cancel_event=cancel_event)

            print(f"   🏁 Fetch complete for this row. Total matching diamonds: {len(row_diamonds)}")

            # 3. Sort & Extract Top 10 Cheapest Distinct Rounded Prices & Counts
            if row_diamonds:
                # Group by rounded integer price and count occurrences
                price_counts = {}
                for d in row_diamonds:
                    price_val = d.get("total_sales_price")
                    if price_val is not None:
                        try:
                            price_float = float(price_val)
                            # Round mathematically (half up): e.g. 42.3 -> 42, 42.5 -> 43
                            price_int = int(price_float + 0.5)
                            price_counts[price_int] = price_counts.get(price_int, 0) + 1
                        except ValueError:
                            pass
                
                # Sort distinct rounded prices ascending
                sorted_distinct_prices = sorted(price_counts.keys())
                
                # Extract top 10 cheapest distinct rounded prices and write back
                for rank in range(1, 11):
                    if rank <= len(sorted_distinct_prices):
                        p = sorted_distinct_prices[rank - 1]
                        c = price_counts[p]
                        df_input.loc[idx, f"Price {rank}"] = int(p)
                        df_input.loc[idx, f"Count {rank}"] = int(c)
                    else:
                        df_input.loc[idx, f"Price {rank}"] = None
                        df_input.loc[idx, f"Count {rank}"] = None

            # Mark this row as completed in the sheet
            df_input.loc[idx, "Scrape_Status"] = "COMPLETED"

            # Overwrite the spreadsheet immediately to capture partial progress
            try:
                df_input.to_excel(excel_path, index=False)
                print(f"   💾 Saved partial progress to Excel file.")
                if on_row_completed:
                    try:
                        on_row_completed()
                    except Exception as cb_err:
                        print(f"   ⚠️ Callback warning: {cb_err}")
            except Exception as e:
                print(f"   ⚠️ Warning: failed to save partial progress: {e}")

            # Check if there are future unprocessed rows to decide if we should sleep
            remaining_unprocessed = False
            for future_idx in range(idx + 1, len(df_input)):
                if "Scrape_Status" not in df_input.columns or df_input.loc[future_idx, "Scrape_Status"] != "COMPLETED":
                    remaining_unprocessed = True
                    break

            # Delay before starting next row's query loop
            if remaining_unprocessed:
                filter_call_time_sleep(dry_run=dry_run, cancel_event=cancel_event)

    # 4. Overwrite Spreadsheet
    try:
        df_input.to_excel(excel_path, index=False)
        print("\n" + "=" * 60)
        print("✅ SUCCESS: Enriched search criteria written back directly.")
        print(f"📂 Modified File: {excel_path}")
        print("=" * 60)
        if on_row_completed:
            try:
                on_row_completed()
            except Exception as cb_err:
                print(f"   ⚠️ Callback warning: {cb_err}")
    except Exception as e:
        print(f"❌ Error overwriting Excel file: {e}")


def run_scraper_for_file(excel_path: str, dry_run: bool = False, cancel_event=None, on_row_completed=None) -> str:
    """
    API-callable wrapper. Runs the scraper on the given file.

    Args:
        excel_path: Absolute path to the .xlsx file.
        dry_run: If True, use cached data.json instead of real API calls.
        cancel_event: threading.Event to cooperatively interrupt execution.
        on_row_completed: callback triggered after each row/final save.

    Returns:
        The path to the enriched .xlsx file (same as input, overwritten in place).

    Raises:
        FileNotFoundError: If the input file doesn't exist.
        Exception: If the scraper encounters a fatal error.
    """
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Input file not found: {excel_path}")

    run_scraper(excel_path=excel_path, dry_run=dry_run, cancel_event=cancel_event, on_row_completed=on_row_completed)
    return excel_path


if __name__ == "__main__":
    run_scraper()
