#!/usr/bin/env python3
"""
MN Architecture & Design RFP Scraper
Scrapes open bid/RFP listings from your bookmarked MN government sites
and saves a filtered report to your desktop.

Usage:
    python3 mn_bid_scraper.py

Requirements:
    pip install requests beautifulsoup4 lxml playwright
    playwright install chromium
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import os
import re

# ── Playwright helper for JS-heavy sites ──────────────────────────────────────

_browser = None

def get_browser():
    """Lazy-load a Playwright browser instance (shared across all JS scrapes)."""
    global _browser
    if _browser is None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            _browser = pw.chromium.launch(headless=True)
            print("  [✓] Playwright browser launched successfully")
        except ImportError:
            print("  [!] Playwright not installed — run: pip install playwright && playwright install chromium")
            return None
        except Exception as e:
            print(f"  [!] Could not launch browser: {e}")
            return None
    return _browser


def fetch_js(url, wait_selector=None, wait_ms=3000):
    """
    Fetch a page using a headless browser (for JS-rendered content).
    Returns BeautifulSoup, or (None, error_string) on failure.
    """
    browser = get_browser()
    if browser is None:
        return None, "Playwright not available"
    try:
        page = browser.new_page()
        page.goto(url, timeout=20000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=8000)
                print(f"    [JS] Found selector '{wait_selector}'")
            except:
                print(f"    [JS] Selector '{wait_selector}' not found, using page as-is")
        else:
            page.wait_for_timeout(wait_ms)
        html = page.content()
        page.close()
        return BeautifulSoup(html, "lxml")
    except Exception as e:
        print(f"    [JS] Error: {e}")
        try:
            page.close()
        except:
            pass
        return None, str(e)

# ── Configuration ──────────────────────────────────────────────────────────────

# Keywords that STRONGLY suggest A/E / architecture work
# A bid must match at least one of these to be flagged
AE_KEYWORDS_STRONG = [
    "architect", "architecture", "architectural",
    "a/e services", "a&e services", "architect/engineer",
    "design services", "design professional",
    "professional design",
    "schematic design", "design development",
    "construction documents", "construction administration",
    "facility design", "building design",
    "interior design",
    "programming and design",
    "feasibility study",
    "space planning",
    "master plan", "masterplan",
    "historic preservation",
    "building assessment", "facility assessment",
    "building condition",
    "renovation design", "remodel design",
    # School-district A/E work
    "facilities assessment",
    "building renovation", "school renovation",
    "roof replacement", "roofing replacement",
    "building envelope",
    "restroom renovation", "restroom remodel",
    "classroom renovation", "classroom addition",
    "building addition",
    "site improvement",
    "long-range facility", "long range facility",
    "facility master plan",
    "capital improvement",
    "ada compliance", "ada upgrade", "accessibility improvement",
    "architect (design)",     # MBID bid type label
    "designer selection",     # SDSB-style postings
    # Facility/infrastructure keywords for Met Council, MnDOT, Hennepin
    "hvac",
    "boiler replacement", "boiler upgrade",
    "elevator replacement", "elevator upgrade",
    "engineering services", "engineering and project management",
    "construction contract administration",
    "design-build", "design build",
    "facility renovation", "station renovation",
    "clinic renovation",
    "fire system upgrade", "fire alarm",
    "lighting upgrade",
    "envelope restoration",
]

# Secondary keywords — only flag if ALSO paired with a strong keyword OR
# the title clearly implies A/E work (used for context scoring)
AE_KEYWORDS_CONTEXT = [
    "professional technical",
    "professional service",
    "design-build",
    "cm/gc",
    "construction management",
    "owner's representative",
]

# Words that disqualify a match even if a keyword appears
# e.g. "engineering" alone usually means civil/utility, not A/E
EXCLUDE_KEYWORDS = [
    "staffing",
    "software",
    "insurance",
    "audit",
    "legal",
    "financial",
    "actuarial",
    "it services",
    "information technology",
    "marketing",
    "printing",
    "janitorial",
    "mowing",
    "snow removal",
    "fuel",
    "food service", "food & beverage", "food items",
    "trash",
    "recycling",
    "curriculum",
    "textbook",
    "school supplies",
    "bus ", "transportation service",
    "copier",
    "medical supplies",
    "athletic equipment",
    "musical instrument",
    "playground equipment",
]

# ── Output paths ──────────────────────────────────────────────────────────────

# GitHub repo folder — the HTML dashboard goes here for GitHub Pages
GITHUB_REPO_DIR = r"W:\AI\GitHub\RFP scrubber"

# Text report — saved next to this script
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mn_bids_report.txt")

# Full browser headers — fixes most 403 blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

TIMEOUT = 15  # seconds per request


# ── Site definitions ───────────────────────────────────────────────────────────

# Each entry: (display_name, url, scraper_function_name)
SITES = [
    # --- CivicEngage cities (all same platform, same scraper) ---
    ("Maplewood, MN",       "https://maplewoodmn.gov/Bids.aspx",                    "civicengage"),
    ("Golden Valley, MN",   "https://www.goldenvalleymn.gov/bids.aspx",             "civicengage"),
    ("Elk River, MN",       "https://www.elkrivermn.gov/bids.aspx",                 "civicengage"),
    ("Lino Lakes, MN",      "https://linolakes.us/bids.aspx",                       "civicengage"),
    ("Hibbing, MN",         "https://hibbingmn.gov/Bids.aspx",                      "civicengage"),
    ("Faribault, MN",       "https://www.ci.faribault.mn.us/Bids.aspx",             "civicengage"),
    ("Forest Lake, MN",     "https://ci.forest-lake.mn.us/Bids.aspx",               "civicengage"),
    ("Woodbury, MN",        "https://woodburywithin.woodburymn.gov/Bids.aspx",       "civicengage"),
    ("St. Cloud, MN",       "https://www.ci.stcloud.mn.us/Bids.aspx",               "civicengage"),
    ("Northfield, MN",      "https://www.northfieldmn.gov/Bids.aspx",               "civicengage"),
    ("Washington County",   "https://www.washingtoncountymn.gov/Bids.aspx",          "civicengage"),
    ("Scott County",        "https://www.scottcountymn.gov/Bids.aspx",               "civicengage"),

    # --- QuestCDN agency portals (same platform, same scraper) ---
    ("Anoka County (QuestCDN)",     "https://qcpi.questcdn.com/cdn/posting/?group=6091&provider=6091&projType=all",   "questcdn"),
    ("Eagan, MN (QuestCDN)",        "https://qcpi.questcdn.com/cdn/posting/?projType=all&provider=7193&group=7193",   "questcdn"),
    ("Moorhead, MN (QuestCDN)",     "https://qcpi.questcdn.com/cdn/posting/?group=7465&provider=7465",                "questcdn"),
    ("MN State (QuestCDN)",         "https://qcpi.questcdn.com/cdn/posting/?projType=&group=70464&provider=70464",    "questcdn"),

    # --- Other platforms ---
    ("MN OSP (State Solicitations)",    "https://osp.admin.mn.gov/PT-auto",                                 "mn_osp"),
    ("MBID (UMN / Public Agencies)",    "https://mbid.ionwave.net/SourcingEvents.aspx?SourceType=1",        "mbid"),
    ("Lino Lakes RFPs",                 "https://linolakes.us/556/Request-for-Proposals",                    "generic"),

    # --- School districts ---
    ("Saint Paul Public Schools",
     "https://erfp.integratise.com/getall/agency_specific_open.asp?c=Saint%20Paul%20Public%20Schools%20ISD",
     "integratise"),
    ("Roseville ISD 623",
     "https://www.isd623.org/services/business-services",
     "finalsite_panels"),
    ("Anoka-Hennepin Schools",
     "https://www.ahschools.us/services/purchasing",
     "finalsite_boards"),
    ("Mounds View Schools",
     "https://www.mvpschools.org/about/finance/bids",
     "finalsite_posts"),
    ("Stillwater ISD 834",
     "https://www.stillwaterschools.org/our-district/departments/business-finance",
     "finalsite_panels"),
    ("Hudson Schools (WI)",
     "https://www.hudsonraiders.org/district/departments",
     "finalsite_boards"),
    ("St. Cloud ISD 742",
     "https://www.isd742.org/departments/business-services/call-for-bids",
     "finalsite_panels"),
    ("Rochester Public Schools (Bonfire)",
     "https://rochesterschools.bonfirehub.com/portal/?tab=openOpportunities",
     "bonfire"),

    # --- High-value regional sources ---
    ("Metropolitan Council",
     "https://metrocouncil.org/About-Us/What-We-Do/DoingBusiness/Contracting-Opportunities.aspx",
     "metcouncil"),
    ("MnDOT P/T Consultant Notices",
     "https://www.dot.state.mn.us/consult/notices.html",
     "mndot_pt"),
    ("Hennepin County (ProcureWare)",
     "https://hennepin.procureware.com/Bids",
     "procureware"),
]

# Sites removed due to persistent 403 blocks — check these manually:
#   St. Louis Park, MN  — https://www.stlouisparkmn.gov/government/legal-notices-248
#   Carver County, MN   — https://www.carvercountymn.gov/government/requests-for-bids-and-proposals


# ── Scrapers ───────────────────────────────────────────────────────────────────

def fetch(url):
    """Fetch a URL and return BeautifulSoup, or None on error."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        return None, str(e)


def scrape_civicengage(url):
    """
    CivicEngage Bids.aspx pages — used by Maplewood, Golden Valley,
    Elk River, Lino Lakes, Hibbing, Faribault, Forest Lake, etc.

    Structure (confirmed via browser inspection):
      div.bidItems.listItems
        div.bidsHeader.listHeader        ← column headers (skip)
        div.listItemsRow.bid             ← one per bid
          div.bidTitle
            span > a[href*=bidID]        ← title + link
            span                         ← description / "Read on" link
          div.bidStatus
            div (labels)
            div (values: status + close date)
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    base = "/".join(url.split("/")[:3])

    # Primary: CivicEngage bid rows (div.listItemsRow.bid)
    for row in soup.select("div.listItemsRow"):
        title_div = row.select_one("div.bidTitle")
        status_div = row.select_one("div.bidStatus")
        if not title_div:
            continue

        # Title is the first <a> inside bidTitle
        link_tag = title_div.find("a", href=True)
        if not link_tag:
            continue

        title = link_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        href = link_tag["href"]
        if not href.startswith("http"):
            href = base + "/" + href.lstrip("/")

        # Description: second <span> in bidTitle (if present)
        spans = title_div.find_all("span")
        detail = spans[1].get_text(strip=True) if len(spans) > 1 else ""

        # Status / close date from bidStatus div
        if status_div:
            status_text = status_div.get_text(" ", strip=True)
            if detail:
                detail = detail + " | " + status_text
            else:
                detail = status_text

        bids.append({"title": title, "detail": detail[:200], "url": href})

    # Fallback: look for any <a> tags that look like bid listings
    if not bids:
        for a in soup.select("a[href]"):
            t = a.get_text(strip=True)
            if len(t) > 10 and any(k in t.lower() for k in ["bid", "rfp", "proposal", "contract"]):
                href = a["href"]
                if not href.startswith("http"):
                    href = base + "/" + href.lstrip("/")
                bids.append({"title": t, "detail": "", "url": href})

    return bids, None


def scrape_questcdn(url):
    """
    QuestCDN agency portal pages (?group=XXXX).
    Uses Playwright (headless browser) because the DataTables content
    is loaded via JavaScript AJAX after page load.

    Structure (confirmed via browser inspection):
      table#table_id.datatable (DataTables jQuery plugin)
        thead > tr > th  (columns vary by portal)
        tbody > tr
          td[0]  Post Date
          td[1]  Quest Number
          td[2]  Category Code
          td[3]  Bid/Request Name      ← title (contains <a> link)
          td[4]  Bid Closing Date
          td[5]  City
          ...more columns...
    """
    # Use Playwright to render JS-loaded DataTable
    result = fetch_js(url, wait_selector="table#table_id tbody tr", wait_ms=5000)
    if isinstance(result, tuple):
        # Fallback to requests if Playwright unavailable
        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            session.get("https://qcpi.questcdn.com/", timeout=TIMEOUT)
            time.sleep(0.5)
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            return [], str(e)
    else:
        soup = result

    bids = []

    # Find the DataTables table (id="table_id") or fall back to any table with data rows
    table = soup.find("table", id="table_id") or soup.find("table", class_="datatable")
    if not table:
        # Fallback: try any table with enough columns
        for t in soup.find_all("table"):
            if t.find("tbody") and len(t.select("tbody tr")) > 0:
                table = t
                break
    if not table:
        return [], None

    tbody = table.find("tbody")
    if not tbody:
        return [], None

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Skip "No postings found" rows
        first_text = cells[0].get_text(strip=True)
        if "no postings" in first_text.lower():
            continue

        # Extract fields based on known column positions
        quest_number = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        category = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        title = cells[3].get_text(strip=True) if len(cells) > 3 else first_text
        close_date = cells[4].get_text(strip=True) if len(cells) > 4 else ""
        city = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        owner = cells[8].get_text(strip=True) if len(cells) > 8 else ""
        posting_type = cells[10].get_text(strip=True) if len(cells) > 10 else ""

        if not title or len(title) < 3:
            continue

        # Build detail URL from quest number (onclick="prevnext(ID)")
        detail_url = ""
        link_tag = row.find("a")
        if link_tag:
            onclick = link_tag.get("onclick", "")
            match = re.search(r"prevnext\((\d+)\)", onclick)
            if match:
                detail_url = f"https://qcpi.questcdn.com/cdn/posting/?id={match.group(1)}"

        detail_parts = [p for p in [category, owner, city, close_date, posting_type] if p]
        detail = " | ".join(detail_parts)

        bids.append({"title": title, "detail": detail[:200], "url": detail_url})

    return bids, None


def scrape_mn_osp(url):
    """
    MN Office of State Procurement — PT Solicitation Postings.
    Drupal Views page (not a table).

    Structure (confirmed via browser inspection):
      div.view-content
        div.item-list
          ul
            li                                        ← one per solicitation
              span.views-field-field-solicitation-number
                span.views-label + span.field-content ← "REFERENCE NUMBER: PTxxxx"
              span.views-field-field-agency-name
                span.views-label + span.field-content ← agency name
              span.views-field-title
                span.views-label + span.field-content ← solicitation title
              span.views-field-field-due-date
                span.views-label + span.field-content ← due date
              (and other fields: swift event id, version, contact phone, etc.)
    No per-listing detail links — the portal link is generic (mn.gov/supplier).
    """
    # Try requests first (Drupal should render server-side)
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []

    # Find all listing items in the Drupal views list
    items = soup.select(".item-list ul li")

    # If requests returned no items, try Playwright
    if not items:
        result2 = fetch_js(url, wait_selector=".item-list ul li", wait_ms=4000)
        if not isinstance(result2, tuple):
            soup = result2
            items = soup.select(".item-list ul li")
    if not items:
        # Fallback: try views-row divs
        items = soup.select(".views-row")

    for item in items:
        # Extract key fields via their views-field class names
        ref_el = item.select_one(".views-field-field-solicitation-number .field-content")
        title_el = item.select_one(".views-field-title .field-content")
        agency_el = item.select_one(".views-field-field-agency-name .field-content")
        due_el = item.select_one(".views-field-field-due-date .field-content")

        title = title_el.get_text(strip=True) if title_el else ""
        if not title or len(title) < 5:
            continue

        ref_num = ref_el.get_text(strip=True) if ref_el else ""
        agency = agency_el.get_text(strip=True) if agency_el else ""
        due_date = due_el.get_text(strip=True) if due_el else ""

        detail_parts = [p for p in [ref_num, agency, due_date] if p]
        detail = " | ".join(detail_parts)

        # No per-listing URL; link to the OSP page itself
        bids.append({"title": title, "detail": detail[:200], "url": url})

    return bids, None


def scrape_mbid(url):
    """
    MBID / Ionwave — UMN and other public agency bids.
    Public current-bids page: SourcingEvents.aspx?SourceType=1
    Uses Playwright because the Telerik RadGrid is rendered via ASP.NET postbacks.

    Structure (confirmed via browser inspection):
      Telerik RadGrid (ASP.NET) rendered as a standard HTML table
      table#ctl00_mainContent_rgBidList_ctl00
        thead > tr > th   (columns: [template], BidNumber, Title, TypeTitle,
                           WorkGroupName(hidden), OpenDate, CloseDate)
        tbody > tr.rgRow / tr.rgAltRow  ← data rows (skip pager rows)
          td[0]  (empty template column)
          td[1]  Bid Number
          td[2]  Bid Title
          td[3]  Bid Type (RFP, RFB, RFI, Construction, Architect (Design), etc.)
          td[4]  Organization
          td[5]  Open Date
          td[6]  Close Date/Time
    """
    # Use Playwright to render ASP.NET content
    result = fetch_js(url, wait_selector="tr.rgRow", wait_ms=5000)
    if isinstance(result, tuple):
        # Fallback to requests
        result2 = fetch(url)
        if isinstance(result2, tuple):
            return [], result2[1]
        soup = result2
    else:
        soup = result

    bids = []

    # Find the RadGrid table — try specific ID first, then any data table
    table = (
        soup.find("table", id=re.compile(r"rgBidList"))
        or soup.find("table", class_=re.compile(r"rgMasterTable"))
    )
    if not table:
        # Fallback: find any table with multiple columns of data
        for t in soup.find_all("table"):
            tbody = t.find("tbody")
            if tbody and len(tbody.find_all("tr")) > 0:
                first_row = tbody.find("tr")
                if first_row and len(first_row.find_all("td")) >= 5:
                    table = t
                    break
    if not table:
        return [], None

    # IMPORTANT: use recursive=False to get the direct-child <tbody>, not a
    # nested tbody buried inside the TFOOT pager controls.
    tbody = table.find("tbody", recursive=False)
    if not tbody:
        tbody = table.find("tbody")
    if not tbody:
        return [], None

    for row in tbody.find_all("tr", recursive=False):
        # Only process actual data rows (rgRow / rgAltRow), skip pager and control rows
        row_class = row.get("class", [])
        cells = row.find_all("td")

        # Skip rows with too few cells (pager rows, control rows)
        if len(cells) < 5:
            continue

        # Skip pager/control rows that don't have rgRow or rgAltRow class
        # (if Playwright rendered the page, data rows have these classes)
        if row_class and not any(c in ["rgRow", "rgAltRow"] for c in row_class):
            # But if no rows have rgRow class (requests fallback), process all 7-cell rows
            if tbody.find("tr", class_="rgRow"):
                continue

        # Extract fields — column order: [template], BidNumber, Title, Type, Org, OpenDate, CloseDate
        bid_number = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        title = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        bid_type = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        org = cells[4].get_text(strip=True) if len(cells) > 4 else ""
        open_date = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        close_date = cells[6].get_text(strip=True) if len(cells) > 6 else ""

        if not title or len(title) < 3:
            continue

        detail_parts = [p for p in [bid_number, bid_type, org, close_date] if p]
        detail = " | ".join(detail_parts)

        # Link back to the public bids page (rows require JS click, no direct URL)
        bids.append({"title": title, "detail": detail[:200], "url": url})

    return bids, None


def scrape_integratise(url):
    """
    Integratise / GetAll procurement portal — used by SPPS and other districts.
    Embeds as an iframe on the district page; we hit the iframe URL directly.

    Structure (confirmed via browser inspection):
      table#myTable1.tbl1
        thead > tr > th  (7 cols: Sol Name, Type, Buyer, Synopsis,
                          Closing Date & Time, Pre-Conf. Date & Time, Link)
        tbody > tr       ← one per solicitation (absent when no open bids)
          td[0]  Solicitation Name
          td[1]  Type (RFP, IFB, etc.)
          td[2]  Buyer
          td[3]  Synopsis
          td[4]  Closing Date & Time
          td[5]  Pre-Conference Date & Time
          td[6]  Link (contains <a>)
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []

    table = soup.find("table", id="myTable1") or soup.find("table", class_="tbl1")
    if not table:
        # Fallback: any table with a thead
        for t in soup.find_all("table"):
            if t.find("thead"):
                table = t
                break
    if not table:
        return [], None

    tbody = table.find("tbody")
    if not tbody:
        return [], None  # no open bids

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        title = cells[0].get_text(strip=True)
        if not title or len(title) < 3:
            continue

        sol_type = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        buyer = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        synopsis = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        close_date = cells[4].get_text(strip=True) if len(cells) > 4 else ""

        # Link is in the last column
        link_tag = row.find("a", href=True)
        href = ""
        if link_tag:
            href = link_tag["href"]
            if not href.startswith("http"):
                href = "https://erfp.integratise.com" + href

        detail_parts = [p for p in [sol_type, buyer, synopsis[:80], close_date] if p]
        detail = " | ".join(detail_parts)

        bids.append({"title": title, "detail": detail[:200], "url": href})

    return bids, None


def scrape_finalsite_panels(url):
    """
    Finalsite CMS pages with accordion panels (.fsPanel).
    Used by Roseville ISD 623, Stillwater ISD 834, St. Cloud ISD 742, etc.

    Structure (confirmed via browser inspection):
      section.fsPanelGroup.fsAccordion
        div.fsPanel
          h2.fsPanelTitle / button   ← panel header
          div.fsPanelBody
            a[href]                  ← links to documents / external bid portals

    Scrapes ALL links from panels whose titles contain bid/RFP keywords,
    and also picks up any inline links on the page that look like bids.
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    base = "/".join(url.split("/")[:3])
    seen_urls = set()

    bid_panel_words = [
        "bid", "rfp", "rfq", "proposal", "request for", "solicitation",
        "procurement", "opportunity", "call for",
    ]

    # 1) Scan panels for bid-related content
    for panel in soup.select(".fsPanel"):
        title_el = (
            panel.select_one(".fsPanelTitle")
            or panel.select_one("h2")
            or panel.select_one("h3")
            or panel.select_one("button")
        )
        panel_title = title_el.get_text(strip=True).lower() if title_el else ""

        # Only harvest links from panels whose title suggests bids/RFPs
        if not any(w in panel_title for w in bid_panel_words):
            continue

        for a in panel.select("a[href]"):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            # Skip self-anchors and navigation
            if href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = base + "/" + href.lstrip("/")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            bids.append({"title": text, "detail": "", "url": href})

    # 2) Also scan page-level links that look like bids (outside panels)
    bid_words = ["bid", "rfp", "rfq", "proposal", "solicitation", "request for",
                 "design services", "architect", "renovation", "construction"]
    for a in soup.select("#fsPageContent a[href]"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if href.startswith("#") or not text or len(text) < 10:
            continue
        if not any(w in text.lower() for w in bid_words):
            continue
        if not href.startswith("http"):
            href = base + "/" + href.lstrip("/")
        if href in seen_urls:
            continue
        seen_urls.add(href)
        bids.append({"title": text, "detail": "", "url": href})

    return bids, None


def scrape_finalsite_boards(url):
    """
    Finalsite CMS pages with board-post articles.
    Used by Anoka-Hennepin Schools, Hudson Schools, etc.

    Structure (confirmed via browser inspection):
      article.fsBoard-NNN   ← NNN varies per category (e.g. 460=RFQ, 461=RFB, 462=RFP)
        h3 or a[href]       ← title + link to individual post
        ...detail text...

    Individual post URLs look like:
      /services/purchasing/individual/~board/services-purchasing-request-for-bids/post/title-slug
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    base = "/".join(url.split("/")[:3])
    seen_urls = set()

    # Collect all board articles — each has class "fsBoard-NNN"
    for article in soup.select("article[class*='fsBoard-']"):
        # Skip the homepage news carousel (fsBoard-78 etc.) by checking
        # if the article links to a bid-like path or has bid-like text
        link_tag = article.find("a", href=True)
        if not link_tag:
            continue

        text = link_tag.get_text(strip=True)
        href = link_tag["href"]
        if not text or len(text) < 5:
            continue

        # Filter: only keep articles whose link path or text suggests bids/RFPs
        combined = (text + " " + href).lower()
        bid_signals = [
            "bid", "rfp", "rfq", "rfb", "proposal", "quote",
            "purchasing", "procurement", "solicitation",
            "renovation", "remodel", "construction", "design",
            "request-for-bids", "request-for-proposals", "request-for-quotes",
        ]
        if not any(sig in combined for sig in bid_signals):
            continue

        if not href.startswith("http"):
            href = base + href if href.startswith("/") else base + "/" + href
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Try to get any description text from the article
        detail = ""
        desc_el = article.select_one("p, .fsBody, .fsSummary")
        if desc_el:
            detail = desc_el.get_text(strip=True)

        bids.append({"title": text, "detail": detail[:200], "url": href})

    # Fallback: also check for post elements (.fsPostElement lists)
    for post_section in soup.select(".fsPostElement"):
        for a in post_section.select("article a[href], a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if not text or len(text) < 10 or href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = base + "/" + href.lstrip("/")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            bids.append({"title": text, "detail": "", "url": href})

    return bids, None


def scrape_finalsite_posts(url):
    """
    Finalsite CMS pages with post-feed sections (.fsPostElement).
    Used by Mounds View Schools.

    Structure (confirmed via browser inspection):
      div.fsPostElement.fsList
        h2 (section title: "Bids", "Proposals", "Quotes")
        article or div.fsPostItem
          a[href]   ← link to individual post
          ...
        (or "No post to display." when empty)
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    base = "/".join(url.split("/")[:3])
    seen_urls = set()

    for section in soup.select(".fsPostElement"):
        for a in section.select("a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if not text or len(text) < 10 or href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = base + "/" + href.lstrip("/")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            bids.append({"title": text, "detail": "", "url": href})

    # Fallback: also check board articles (some Finalsite sites use both)
    if not bids:
        for article in soup.select("article[class*='fsBoard-'] a[href]"):
            text = article.get_text(strip=True)
            href = article.get("href", "")
            if not text or len(text) < 10 or href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = base + "/" + href.lstrip("/")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            bids.append({"title": text, "detail": "", "url": href})

    return bids, None


def scrape_bonfire(url):
    """
    Bonfire Hub procurement portal — used by Rochester Public Schools.

    Structure (confirmed via browser inspection):
      Two table.dataTable elements on the page:
        Table 0: duplicate header (ignore)
        Table 1: actual data rows
          thead > tr > th  (Status, Ref. #, Project, Close Date, Days Left, Action)
          tbody > tr
            td[0]  Status  (OPEN / CLOSED)
            td[1]  Ref. #
            td[2]  Project name
            td[3]  Close Date
            td[4]  Days Left
            td[5]  Action  (contains <a href="/opportunities/ID">)
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    base_url = "/".join(url.split("/")[:3])  # https://rochesterschools.bonfirehub.com

    # Find the data table with actual rows (the second dataTable, or any with tbody rows)
    tables = soup.select("table.dataTable")
    table = None
    for t in tables:
        tbody = t.find("tbody")
        if tbody and tbody.find("tr"):
            first_row = tbody.find("tr")
            if first_row and len(first_row.find_all("td")) >= 4:
                table = t
                break
    # Fallback: any table with enough data
    if not table:
        for t in soup.find_all("table"):
            tbody = t.find("tbody")
            if tbody:
                rows = tbody.find_all("tr")
                if len(rows) > 0 and len(rows[0].find_all("td")) >= 4:
                    table = t
                    break
    if not table:
        return [], None

    tbody = table.find("tbody")
    if not tbody:
        return [], None

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        status = cells[0].get_text(strip=True)
        ref_num = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        title = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        close_date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        days_left = cells[4].get_text(strip=True) if len(cells) > 4 else ""

        if not title or len(title) < 3:
            continue

        # Get the "View Opportunity" link
        link_tag = row.find("a", href=True)
        href = ""
        if link_tag:
            href = link_tag["href"]
            if not href.startswith("http"):
                href = base_url + href

        detail_parts = [p for p in [ref_num, status, close_date, days_left + " days left"] if p]
        detail = " | ".join(detail_parts)

        bids.append({"title": title, "detail": detail[:200], "url": href})

    return bids, None


def scrape_generic(url):
    """
    Generic fallback — grab any links that look like bids/RFPs
    from pages with no consistent structure.
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    bid_words = ["bid", "rfp", "proposal", "contract", "solicitation", "request for"]
    for a in soup.select("a[href]"):
        t = a.get_text(strip=True)
        if len(t) > 15 and any(w in t.lower() for w in bid_words):
            href = a["href"]
            if not href.startswith("http"):
                base = "/".join(url.split("/")[:3])
                href = base + "/" + href.lstrip("/")
            bids.append({"title": t, "detail": "", "url": href})

    return bids, None


def scrape_metcouncil(url):
    """
    Metropolitan Council contracting opportunities.
    Structure: table.table-sort with columns:
      Division | Number | Title/General Description | Issue Date | Due Date | Type
    Multiple tables on page (with/without small-biz goals); we scrape all.
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    for table in soup.find_all("table", class_="table-sort"):
        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            # Single-cell "no opportunities" placeholder row
            if len(cells) == 1:
                continue
            division = cells[0].get_text(strip=True) if len(cells) > 0 else ""
            number = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            title = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            issue_date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            due_date = cells[4].get_text(strip=True) if len(cells) > 4 else ""
            bid_type = cells[5].get_text(strip=True) if len(cells) > 5 else ""

            if not title or len(title) < 3:
                continue

            detail_parts = [p for p in [number, bid_type, division, f"Due: {due_date}"] if p]
            detail = " | ".join(detail_parts)

            bids.append({"title": title, "detail": detail[:200], "url": url})

    return bids, None


def scrape_mndot_pt(url):
    """
    MnDOT Professional/Technical Consultant Notices.
    Structure: h3 headings for each notice under the
    'Notices Open To All Consultants' section, followed by <p> with description
    and <p> with dates. Also scrapes 'pre-qualified' section.
    """
    result = fetch(url)
    if isinstance(result, tuple):
        return [], result[1]
    soup = result

    bids = []
    # Find all h2 sections that contain notices
    target_sections = [
        "Notices Open To All Consultants",
        "Notices open only to pre-qualified consultants",
    ]

    for h2 in soup.find_all("h2"):
        h2_text = h2.get_text(strip=True)
        if not any(target.lower() in h2_text.lower() for target in target_sections):
            continue

        # Walk siblings until next h2
        el = h2.find_next_sibling()
        while el and el.name != "h2":
            if el.name == "h3":
                title = el.get_text(strip=True)
                # Gather description and dates from following <p> elements
                detail_parts = []
                sib = el.find_next_sibling()
                while sib and sib.name not in ("h2", "h3"):
                    if sib.name == "p":
                        text = sib.get_text(strip=True)
                        if text and len(text) > 5:
                            detail_parts.append(text)
                    sib = sib.find_next_sibling()

                detail = " | ".join(detail_parts)
                if title and len(title) > 3:
                    bids.append({"title": title, "detail": detail[:300], "url": url})

            el = el.find_next_sibling()

    return bids, None


def scrape_procureware(url):
    """
    Hennepin County ProcureWare — JS-rendered grid of bids.
    Uses Playwright because the grid is loaded via AJAX.
    We look for rows in the grid table that are 'Open for Bidding'.
    """
    # ProcureWare uses a Kendo UI grid — the data table is inside .k-grid-content,
    # separate from the header table in .k-grid-header-wrap.
    result = fetch_js(url, wait_selector=".k-grid-content table tr", wait_ms=8000)
    if isinstance(result, tuple):
        # Fallback to requests (will likely get empty grid)
        result2 = fetch(url)
        if isinstance(result2, tuple):
            return [], result2[1]
        soup = result2
    else:
        soup = result

    bids = []
    # Find the Kendo data table (inside .k-grid-content), not the header table
    grid = soup.select_one(".k-grid-content table")
    if not grid:
        # Fallback: largest table on the page
        for t in soup.find_all("table"):
            if len(t.find_all("tr")) > 5:
                grid = t
                break
    if not grid:
        return [], None

    rows = grid.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 8:
            continue

        # Column order from page: Id, Guid, Number, Title, Description, Status,
        #   Bid Type, Contact, Available Date, Clarification Deadline,
        #   Due Date, Cancel Date, Award Date, Awardee, Process, Categories, Plans, Location
        number = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        title = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        status = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        bid_type = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        due_date = cells[10].get_text(strip=True) if len(cells) > 10 else ""

        if not title or len(title) < 3:
            continue

        # Only include open bids (skip awarded, cancelled, closed)
        if status.lower() not in ("open for bidding", ""):
            continue

        detail_parts = [p for p in [number, bid_type, f"Due: {due_date}"] if p]
        detail = " | ".join(detail_parts)

        bid_url = url  # ProcureWare doesn't have simple per-bid URLs
        bids.append({"title": title, "detail": detail[:200], "url": bid_url})

    return bids, None


SCRAPER_MAP = {
    "civicengage":      scrape_civicengage,
    "questcdn":         scrape_questcdn,
    "mn_osp":           scrape_mn_osp,
    "mbid":             scrape_mbid,
    "integratise":      scrape_integratise,
    "finalsite_panels": scrape_finalsite_panels,
    "finalsite_boards": scrape_finalsite_boards,
    "finalsite_posts":  scrape_finalsite_posts,
    "bonfire":          scrape_bonfire,
    "metcouncil":       scrape_metcouncil,
    "mndot_pt":         scrape_mndot_pt,
    "procureware":      scrape_procureware,
    "generic":          scrape_generic,
}


# ── Keyword matching ───────────────────────────────────────────────────────────

def is_architecture_related(title, detail):
    """
    Return True if this bid is likely relevant to architecture/design work.
    Uses a tiered system:
      - Must match at least one STRONG keyword
      - Must NOT match any EXCLUDE keyword (whole-word boundary matching)
    """
    text = (title + " " + detail).lower()
    # Immediately disqualify if an exclusion keyword appears (word-boundary match)
    # Uses \b to prevent "audit" from matching inside "auditorium", etc.
    for ex in EXCLUDE_KEYWORDS:
        # Keywords ending with space (like "bus ") already handle boundaries
        if ex.endswith(" "):
            if ex in text:
                return False
        else:
            if re.search(r'\b' + re.escape(ex) + r'\b', text):
                return False
    # Must have at least one strong A/E keyword
    return any(kw in text for kw in AE_KEYWORDS_STRONG)


# ── HTML dashboard generation ─────────────────────────────────────────────────

import html as html_mod   # rename to avoid clash with local vars
import json as json_mod

def build_html_dashboard(all_results, flagged, timestamp):
    """
    Build a single self-contained HTML dashboard file.
    all_results: list of (site_name, url, bids_list, error_or_None)
    flagged:     list of flagged bid dicts
    timestamp:   string like "2026-04-08 07:30"
    Returns the HTML string.
    """
    total_bids = sum(len(r[2]) for r in all_results)
    sites_ok = sum(1 for r in all_results if r[3] is None)
    sites_err = sum(1 for r in all_results if r[3] is not None)

    # Build flat row data for the table
    rows_json = []
    for site_name, site_url, bids, error in all_results:
        if error:
            rows_json.append({
                "site": site_name,
                "title": f"ERROR: {error[:100]}",
                "detail": "",
                "url": site_url,
                "flagged": False,
                "error": True,
            })
            continue
        if not bids:
            rows_json.append({
                "site": site_name,
                "title": "(no open bids)",
                "detail": "",
                "url": site_url,
                "flagged": False,
                "error": False,
            })
            continue
        for b in bids:
            rows_json.append({
                "site": site_name,
                "title": b["title"],
                "detail": b.get("detail", ""),
                "url": b.get("url", ""),
                "flagged": is_architecture_related(b["title"], b.get("detail", "")),
                "error": False,
            })

    data_js = json_mod.dumps(rows_json, ensure_ascii=False)

    # Manual-check sites
    manual_sites = [
        ("St. Louis Park, MN", "https://www.stlouisparkmn.gov/government/legal-notices-248"),
        ("Carver County, MN", "https://www.carvercountymn.gov/government/requests-for-bids-and-proposals"),
    ]

    manual_html = "".join(
        f'<a href="{url}" target="_blank" rel="noopener">{name}</a>'
        for name, url in manual_sites
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MN A/E Bid Dashboard</title>
<style>
  :root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --surface2: #334155;
    --border: #475569;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #3b82f6;
    --flag: #f59e0b;
    --flag-bg: rgba(245, 158, 11, 0.08);
    --error: #ef4444;
    --green: #22c55e;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  .header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
  }}
  .header h1 {{
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 4px;
  }}
  .header .subtitle {{
    color: var(--text-dim);
    font-size: 13px;
  }}
  .stats {{
    display: flex;
    gap: 24px;
    padding: 16px 32px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .stat {{
    display: flex;
    flex-direction: column;
  }}
  .stat-value {{
    font-size: 24px;
    font-weight: 700;
  }}
  .stat-value.flag {{ color: var(--flag); }}
  .stat-value.green {{ color: var(--green); }}
  .stat-value.error {{ color: var(--error); }}
  .stat-label {{
    font-size: 11px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .controls {{
    display: flex;
    gap: 12px;
    padding: 16px 32px;
    align-items: center;
    flex-wrap: wrap;
  }}
  .controls input, .controls select {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 14px;
  }}
  .controls input {{ flex: 1; min-width: 200px; }}
  .controls select {{ min-width: 150px; }}
  .controls label {{
    font-size: 13px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }}
  .controls input[type="checkbox"] {{
    flex: unset;
    min-width: unset;
    width: 16px;
    height: 16px;
    accent-color: var(--flag);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  thead th {{
    background: var(--surface);
    padding: 10px 16px;
    text-align: left;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-dim);
    border-bottom: 2px solid var(--border);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}
  thead th:hover {{ color: var(--text); }}
  thead th .arrow {{ margin-left: 4px; opacity: 0.4; }}
  thead th.sorted .arrow {{ opacity: 1; color: var(--accent); }}
  tbody td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--surface2);
    vertical-align: top;
  }}
  tbody tr:hover {{ background: var(--surface); }}
  tbody tr.flagged {{ background: var(--flag-bg); }}
  tbody tr.flagged td:first-child {{
    border-left: 3px solid var(--flag);
    padding-left: 13px;
  }}
  tbody tr.error-row td {{ color: var(--error); opacity: 0.7; }}
  tbody tr.empty-row td {{ color: var(--text-dim); font-style: italic; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }}
  .tag-flag {{ background: rgba(245,158,11,0.15); color: var(--flag); }}
  .detail {{ color: var(--text-dim); font-size: 12px; margin-top: 2px; }}
  .manual-check {{
    padding: 12px 32px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-dim);
  }}
  .manual-check a {{ margin: 0 8px; }}
  .count-info {{
    padding: 0 32px 8px;
    font-size: 12px;
    color: var(--text-dim);
  }}
</style>
</head>
<body>

<div class="header">
  <h1>MN Architecture &amp; Engineering Bid Dashboard</h1>
  <div class="subtitle">Last updated: {timestamp} &nbsp;|&nbsp; The Adkins Association</div>
</div>

<div class="stats">
  <div class="stat">
    <span class="stat-value flag">{len(flagged)}</span>
    <span class="stat-label">A/E Flagged</span>
  </div>
  <div class="stat">
    <span class="stat-value">{total_bids}</span>
    <span class="stat-label">Total Listings</span>
  </div>
  <div class="stat">
    <span class="stat-value green">{sites_ok}</span>
    <span class="stat-label">Sites OK</span>
  </div>
  <div class="stat">
    <span class="stat-value error">{sites_err}</span>
    <span class="stat-label">Sites Error</span>
  </div>
  <div class="stat">
    <span class="stat-value">{len(SITES)}</span>
    <span class="stat-label">Sites Checked</span>
  </div>
</div>

<div class="controls">
  <input type="text" id="search" placeholder="Filter by keyword..." />
  <select id="siteFilter">
    <option value="">All sites</option>
  </select>
  <label><input type="checkbox" id="flaggedOnly" /> Flagged only</label>
</div>
<div class="count-info" id="countInfo"></div>

<table>
  <thead>
    <tr>
      <th data-col="site">Site <span class="arrow">&#x25B4;</span></th>
      <th data-col="title">Title <span class="arrow">&#x25B4;</span></th>
      <th data-col="detail">Detail <span class="arrow">&#x25B4;</span></th>
    </tr>
  </thead>
  <tbody id="tbody"></tbody>
</table>

<div class="manual-check">
  Manual check (403 blocked): {manual_html}
</div>

<script>
const DATA = {data_js};

// Populate site filter dropdown
const sites = [...new Set(DATA.map(r => r.site))].sort();
const sel = document.getElementById("siteFilter");
sites.forEach(s => {{
  const o = document.createElement("option");
  o.value = s; o.textContent = s;
  sel.appendChild(o);
}});

let sortCol = "site", sortAsc = true;

function render() {{
  const q = document.getElementById("search").value.toLowerCase();
  const site = sel.value;
  const flagOnly = document.getElementById("flaggedOnly").checked;

  let rows = DATA.filter(r => {{
    if (flagOnly && !r.flagged) return false;
    if (site && r.site !== site) return false;
    if (q) {{
      const hay = (r.site + " " + r.title + " " + r.detail).toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  // Sort
  rows.sort((a, b) => {{
    let va = a[sortCol] || "", vb = b[sortCol] || "";
    // Flagged items always first
    if (a.flagged !== b.flagged) return a.flagged ? -1 : 1;
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  }});

  const tbody = document.getElementById("tbody");
  tbody.innerHTML = rows.map(r => {{
    const cls = r.error ? "error-row" :
                r.title === "(no open bids)" ? "empty-row" :
                r.flagged ? "flagged" : "";
    const tag = r.flagged ? ' <span class="tag tag-flag">A/E</span>' : "";
    const titleCell = r.url && !r.error && r.title !== "(no open bids)"
      ? `<a href="${{r.url}}" target="_blank" rel="noopener">${{esc(r.title)}}</a>${{tag}}`
      : esc(r.title) + tag;
    const detailHtml = r.detail ? `<div class="detail">${{esc(r.detail)}}</div>` : "";
    return `<tr class="${{cls}}"><td>${{esc(r.site)}}</td><td>${{titleCell}}</td><td>${{detailHtml || "&mdash;"}}</td></tr>`;
  }}).join("");

  const flagCount = rows.filter(r => r.flagged).length;
  document.getElementById("countInfo").textContent =
    `Showing ${{rows.length}} of ${{DATA.length}} listings` +
    (flagCount ? ` (${{flagCount}} flagged)` : "");
}}

function esc(s) {{
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}}

// Sort on header click
document.querySelectorAll("thead th").forEach(th => {{
  th.addEventListener("click", () => {{
    const col = th.dataset.col;
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = true; }}
    document.querySelectorAll("thead th").forEach(h => h.classList.remove("sorted"));
    th.classList.add("sorted");
    th.querySelector(".arrow").innerHTML = sortAsc ? "&#x25B4;" : "&#x25BE;";
    render();
  }});
}});

document.getElementById("search").addEventListener("input", render);
sel.addEventListener("change", render);
document.getElementById("flaggedOnly").addEventListener("change", render);

render();
</script>
</body>
</html>'''


# ── Report generation ──────────────────────────────────────────────────────────

def run():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  MN Architecture RFP Scraper")
    print(f"  {timestamp}")
    print(f"{'='*60}\n")

    all_results = []   # (site_name, bids, error)
    flagged = []       # architecture-related bids across all sites

    for site_name, url, scraper_key in SITES:
        print(f"Checking: {site_name}...")
        scraper = SCRAPER_MAP.get(scraper_key, scrape_generic)
        bids, error = scraper(url)

        if error:
            print(f"  !! Error: {error[:80]}")
            all_results.append((site_name, url, [], error))
            time.sleep(1)
            continue

        # Flag architecture-relevant ones
        for bid in bids:
            if is_architecture_related(bid["title"], bid.get("detail", "")):
                bid["site"] = site_name
                bid["site_url"] = url
                flagged.append(bid)

        print(f"  Found {len(bids)} listings, {sum(1 for b in bids if is_architecture_related(b['title'], b.get('detail',''))) } flagged")
        all_results.append((site_name, url, bids, None))
        time.sleep(1)  # be polite — don't hammer servers

    # ── Build report ──────────────────────────────────────────────────────────

    lines = []
    lines.append("=" * 70)
    lines.append("  MN ARCHITECTURE & DESIGN BID REPORT")
    lines.append(f"  Generated: {timestamp}")
    lines.append("=" * 70)
    lines.append("")

    # Section 1: Flagged / likely relevant bids
    lines.append(f"FLAGGED AS LIKELY RELEVANT ({len(flagged)} total)")
    lines.append("-" * 70)
    if flagged:
        for b in flagged:
            lines.append(f"  [{b['site']}]")
            lines.append(f"  {b['title']}")
            if b.get("detail"):
                lines.append(f"  {b['detail'][:120]}")
            if b.get("url"):
                lines.append(f"  --> {b['url']}")
            lines.append("")
    else:
        lines.append("  No architecture-related bids found today.\n")

    # Section 2: All bids by site
    lines.append("")
    lines.append("ALL LISTINGS BY SITE")
    lines.append("=" * 70)

    for site_name, url, bids, error in all_results:
        lines.append(f"\n[ {site_name} ]")
        lines.append(f"  {url}")
        if error:
            lines.append(f"  ERROR: {error[:100]}")
            continue
        if not bids:
            lines.append("  No open bids found (site may require login or be empty)")
            continue
        for b in bids:
            marker = " ** " if is_architecture_related(b["title"], b.get("detail","")) else "    "
            lines.append(f"{marker}{b['title']}")
            if b.get("url") and b["url"] != url:
                lines.append(f"      {b['url']}")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  Checked {len(SITES)} sites | {sum(len(r[2]) for r in all_results)} total listings")
    lines.append(f"  {len(flagged)} flagged as architecture/design related")
    lines.append("=" * 70)

    report = "\n".join(lines)

    # ── Save text report ─────────────────────────────────────────────────────
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nText report saved to: {OUTPUT_FILE}")
    except Exception as e:
        print(f"\nCould not save text report: {e}")
        fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mn_bids_report.txt")
        with open(fallback, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Saved to: {fallback}")

    # ── Save HTML dashboard to GitHub repo ───────────────────────────────────
    html_dashboard = build_html_dashboard(all_results, flagged, timestamp)
    html_path = os.path.join(GITHUB_REPO_DIR, "index.html")
    try:
        os.makedirs(GITHUB_REPO_DIR, exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_dashboard)
        print(f"Dashboard saved to: {html_path}")
        print(f"\n  >> Open GitHub Desktop and commit to publish your dashboard.")
    except Exception as e:
        # Fallback: save next to script
        fallback_html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        try:
            with open(fallback_html, "w", encoding="utf-8") as f:
                f.write(html_dashboard)
            print(f"Could not save to GitHub repo ({e})")
            print(f"Dashboard saved locally to: {fallback_html}")
        except Exception as e2:
            print(f"Could not save dashboard: {e2}")

    # ── Print flagged summary to terminal ────────────────────────────────────
    print("\n" + "=" * 60)
    print("FLAGGED BIDS (architecture/design related):")
    print("=" * 60)
    if flagged:
        for b in flagged:
            print(f"\n  [{b['site']}]  {b['title']}")
            if b.get("url"):
                print(f"  {b['url']}")
    else:
        print("  None found today.")
    print()


if __name__ == "__main__":
    try:
        run()
    finally:
        # Clean up Playwright browser if it was started
        if _browser is not None:
            try:
                _browser.close()
            except:
                pass
