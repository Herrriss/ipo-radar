import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import io
import urllib.parse
import re

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="IPO Radar – Zukunfts-Pipeline",
    page_icon="🔭",
    layout="centered"
)

try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- BEKANNTE DE / EU IPO-KANDIDATEN FÜR 2027 ---
KNOWN_EU_2027_CANDIDATES = [
    {
        "name": "KNDS (Krauss-Maffei Wegmann + Nexter)",
        "wkn": "n/a",
        "est_date": "H1 2027",
        "exchange": "Frankfurt / Paris",
        "sector": "Rüstung & Verteidigung",
        "banks": "n/a (Dual-Listing geplant)",
        "status": "Vorbereitung (2027)"
    },
    {
        "name": "AUTODOC SE",
        "wkn": "n/a",
        "est_date": "H1 2027",
        "exchange": "Frankfurt (Prime Standard)",
        "sector": "E-Commerce / Kfz-Teile",
        "banks": "Goldman Sachs, J.P. Morgan, Deutsche Bank",
        "status": "Börsenreif / Kandidat 2027"
    },
    {
        "name": "Flix SE (FlixBus / FlixTrain)",
        "wkn": "n/a",
        "est_date": "2027",
        "exchange": "Frankfurt",
        "sector": "Mobilität & Transport",
        "banks": "J.P. Morgan, Goldman Sachs, BNP Paribas",
        "status": "Kandidat (Marktfenster 2027)"
    },
    {
        "name": "DKV Mobility",
        "wkn": "n/a",
        "est_date": "2027",
        "exchange": "Frankfurt",
        "sector": "B2B-Mobilitätsdienstleister",
        "banks": "n/a",
        "status": "Kandidat (2027)"
    },
    {
        "name": "Klarna / Revolut (EU-FinTech-Pipeline)",
        "wkn": "n/a",
        "est_date": "2027",
        "exchange": "London / EU / US-Dual",
        "sector": "FinTech & Banking",
        "banks": "n/a",
        "status": "Beobachtungsliste 2027"
    },
    {
        "name": "Stada Arzneimittel",
        "wkn": "n/a",
        "est_date": "H1 2027",
        "exchange": "Frankfurt",
        "sector": "Pharma & Healthcare",
        "banks": "J.P. Morgan, Morgan Stanley, Goldman Sachs",
        "status": "Börsenrückkehr geplant"
    }
]

# --- HELFER-FUNKTIONEN ---

def clean_val(val, suffix=""):
    if pd.isna(val) or str(val).strip().lower() in ["", "-", "n.v.", "n/a", "none", "nan", "0", "0.0", "tbd"]:
        return "n/a"
    if isinstance(val, (int, float)):
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}".strip()
    return f"{str(val).strip()} {suffix}".strip()

def normalize_company_name(name):
    if not name:
        return ""
    s = str(name).lower()
    s = re.sub(r"\b(inc|corp|corporation|ltd|limited|llc|plc|se|ag|gmbh|holdings|group|co)\b\.?", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s

def parse_sort_date(raw_val):
    now = datetime.now()
    if pd.isna(raw_val) or str(raw_val).strip().lower() in ["", "-", "offen", "n/a", "none", "nan", "tbd", "unscheduled"]:
        return now + timedelta(days=360), "n/a (Termin offen)"
    
    s = str(raw_val).strip()
    if re.fullmatch(r"\d{7,8}", s):
        s_padded = s.zfill(8)
        s = f"{s_padded[:2]}.{s_padded[2:4]}.{s_padded[4:]}"
        
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt, dt.strftime("%d.%m.%Y")
        except ValueError:
            pass
            
    s_upper = s.upper()
    year = 2027 if "2027" in s_upper else (2028 if "2028" in s_upper else now.year)
    
    if "H1" in s_upper:
        return datetime(year, 4, 15), f"~ {s} (geschätzt)"
    if "H2" in s_upper:
        return datetime(year, 10, 15), f"~ {s} (geschätzt)"
    for q, (m, d) in [("Q1", (2, 15)), ("Q2", (5, 15)), ("Q3", (8, 15)), ("Q4", (11, 15))]:
        if q in s_upper:
            return datetime(year, m, d), f"~ {s} (geschätzt)"
    if s_upper in ["2027", "2028"]:
        return datetime(int(s_upper), 6, 30), f"~ {s} (geschätzt)"
            
    return now + timedelta(days=300), f"~ {s} (geschätzt)"

# --- DATEN-FUNKTIONEN (TAB 1 & TAB 2) ---

@st.cache_data(ttl=1800)
def get_us_ipos_full(api_key):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_end = now + timedelta(days=180)
    
    items = []
    seen_symbols = set()
    seen_names = set()
    
    url_fh = f"https://finnhub.io/api/v1/calendar/ipo?from={now.strftime('%Y-%m-%d')}&to={horizon_end.strftime('%Y-%m-%d')}&token={api_key}"
    try:
        resp = requests.get(url_fh, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("ipoCalendar", []):
                sort_dt, display_date = parse_sort_date(item.get("date"))
                if sort_dt < today_start:
                    continue
                    
                raw_name = item.get("name") or "n/a"
                norm_name = normalize_company_name(raw_name)
                sym = clean_val(item.get("symbol"))
                
                if (norm_name and norm_name in seen_names) or (sym != "n/a" and sym in seen_symbols):
                    continue
                    
                if norm_name:
                    seen_names.add(norm_name)
                if sym != "n/a":
                    seen_symbols.add(sym)
                    if sym.endswith("U") and len(sym) == 5:
                        seen_symbols.add(sym[:-1])
                        
                shares_raw = item.get("numberOfShares", 0)
                shares = f"{int(shares_raw):,} Stück".replace(",", ".") if (pd.notna(shares_raw) and shares_raw > 0) else "n/a"
                
                items.append({
                    "name": raw_name,
                    "symbol": sym,
                    "sort_dt": sort_dt,
                    "display_date": display_date,
                    "exchange": clean_val(item.get("exchange")),
                    "price": clean_val(item.get("price"), "$"),
                    "shares": shares,
                    "status": clean_val(item.get("status", "Terminiert"))
                })
    except Exception:
        pass

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for sa_url, default_status in [
        ("https://stockanalysis.com/ipos/calendar/", "Terminiert"),
        ("https://stockanalysis.com/ipos/filings/", "Prospekt eingereicht (S-1)")
    ]:
        try:
            resp = requests.get(sa_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                tables = pd.read_html(io.StringIO(resp.text))
                for t in tables:
                    cols = {str(c).lower(): c for c in t.columns}
                    if "symbol" in cols and ("company name" in cols or "name" in cols):
                        name_col = cols.get("company name") or cols.get("name")
                        date_col = cols.get("ipo date") or cols.get("filing date")
                        price_col = cols.get("price range")
                        shares_col = cols.get("shares")
                        
                        for _, row in t.head(30).iterrows():
                            raw_name = clean_val(row.get(name_col))
                            norm_name = normalize_company_name(raw_name)
                            sym = clean_val(row.get(cols["symbol"]))
                            
                            if (norm_name and norm_name in seen_names) or (sym != "n/a" and sym in seen_symbols):
                                continue
                                
                            raw_d = row.get(date_col) if "ipo date" in cols else "n/a"
                            sort_dt, display_date = parse_sort_date(raw_d)
                            if sort_dt < today_start:
                                continue
                                
                            if norm_name:
                                seen_names.add(norm_name)
                            if sym != "n/a":
                                seen_symbols.add(sym)
                                
                            items.append({
                                "name": raw_name,
                                "symbol": sym,
                                "sort_dt": sort_dt,
                                "display_date": display_date,
                                "exchange": "NASDAQ / NYSE",
                                "price": clean_val(row.get(price_col)),
                                "shares": clean_val(row.get(shares_col), "Stück"),
                                "status": default_status
                            })
        except Exception:
            pass

    items.sort(key=lambda x: x["sort_dt"])
    return items

@st.cache_data(ttl=3600)
def get_de_eu_ipos_full():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }
    ipo_headers = ["wkn", "isin", "termin", "emissions", "zeichnungs", "erstnotiz", "status", "preisspanne"]
    sources = [
        ("boerse.de", "https://www.boerse.de/ipos/"),
        ("finanzen.net", "https://www.finanzen.net/ipo/")
    ]
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    items = []
    seen_names = set()
    
    for source_name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                tables = pd.read_html(io.StringIO(resp.text))
                for t in tables:
                    cols_str = " ".join([str(c).lower() for c in t.columns])
                    if any(h in cols_str for h in ipo_headers) and len(t) > 0:
                        for _, row in t.iterrows():
                            raw_date = row.get("Erstnotiz") or row.get("Termin") or ""
                            sort_dt, display_date = parse_sort_date(raw_date)
                            if sort_dt >= today_start:
                                cname = clean_val(row.get("Name") or row.get("Unternehmen"))
                                norm_c = normalize_company_name(cname)
                                if norm_c in seen_names:
                                    continue
                                seen_names.add(norm_c)
                                items.append({
                                    "name": cname,
                                    "wkn": clean_val(row.get("WKN")),
                                    "sort_dt": sort_dt,
                                    "display_date": display_date,
                                    "exchange": "Frankfurt / Xetra",
                                    "sector": "n/a",
                                    "banks": "n/a",
                                    "emission": clean_val(row.get("Emission"), "Mio. €"),
                                    "status": clean_val(row.get("Status", "Terminiert"))
                                })
        except Exception:
            continue

    for cand in KNOWN_EU_2027_CANDIDATES:
        norm_c = normalize_company_name(cand["name"])
        if norm_c in seen_names:
            continue
        seen_names.add(norm_c)
        sort_dt, display_date = parse_sort_date(cand["est_date"])
        items.append({
            "name": cand["name"],
            "wkn": cand["wkn"],
            "sort_dt": sort_dt,
            "display_date": display_date,
            "exchange": cand["exchange"],
            "sector": cand["sector"],
            "banks": cand["banks"],
            "emission": "n/a",
            "status": cand["status"]
        })

    items.sort(key=lambda x: x["sort_dt"])
    return items

# --- MULTI-QUELLEN NEWS-AGGREGATOR (TAB 3 & RESEARCH) ---

def parse_rss_feed(url, source_label, cutoff_utc, filter_keywords=None, headers=None):
    """Liest einen beliebigen RSS-Feed aus und filtert optional nach IPO-Begriffen."""
    results = []
    try:
        resp = requests.get(url, headers=headers or {"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            desc = item.find("description").text if item.find("description") is not None else ""
            
            # Wenn ein eigener <source>-Tag im Feed existiert (z. B. Google News), diesen nutzen
            src_tag = item.find("source")
            actual_source = src_tag.text if (src_tag is not None and src_tag.text) else source_label
            
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff_utc:
                    continue
                date_fmt = pub_dt.strftime("%d.%m.%Y, %H:%M Uhr")
            except Exception:
                continue
                
            if filter_keywords:
                text_blob = f"{title} {desc}".lower()
                if not any(kw in text_blob for kw in filter_keywords):
                    continue
                    
            results.append({
                "title": title.strip(),
                "link": link.strip(),
                "pub_dt": pub_dt,
                "date_fmt": date_fmt,
                "source": actual_source,
                "category": source_label
            })
    except Exception:
        pass
    return results

@st.cache_data(ttl=900)
def get_multi_source_ipo_news(max_days=5):
    """
    Kombiniert 4 hochwertige Wirtschafts- & Primärquellen für die letzten 5 Tage:
    1. Finnhub Market News (Reuters, Bloomberg-Zusammenfassungen, CNBC, Seeking Alpha)
    2. Handelsblatt & manager magazin (Direkte Wirtschafts-RSS-Feeds)
    3. CNBC & MarketWatch (Direkte US-Finanz-RSS-Feeds)
    4. Streng gefiltertes Google News (nur Qualitätsmedien + intitle:IPO/Börsengang)
    """
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(days=max_days)
    all_news = []
    
    ipo_keywords = [
        "ipo", "börsengang", "börsenpläne", "börsendebüt", "erstnotiz",
        "zeichnungsfrist", "emissionspreis", "s-1", "going public", "float"
    ]
    
    # 1. Finnhub General Market News API (englische Top-Finanzmedien)
    try:
        fh_url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_API_KEY}"
        resp = requests.get(fh_url, timeout=8)
        if resp.status_code == 200:
            for art in resp.json():
                ts = art.get("datetime", 0)
                pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if pub_dt < cutoff_utc:
                    continue
                headline = art.get("headline", "")
                summary = art.get("summary", "")
                if any(kw in f"{headline} {summary}".lower() for kw in ipo_keywords):
                    all_news.append({
                        "title": headline,
                        "link": art.get("url", ""),
                        "pub_dt": pub_dt,
                        "date_fmt": pub_dt.strftime("%d.%m.%Y, %H:%M Uhr"),
                        "source": art.get("source", "Finnhub Wire"),
                        "category": "Finnhub (US/Global)"
                    })
    except Exception:
        pass

    # 2. Direkte Wirtschafts-RSS-Feeds (DE & US)
    direct_feeds = [
        ("Handelsblatt", "https://www.handelsblatt.com/contentexport/feed/finanzen"),
        ("manager magazin", "https://www.manager-magazin.de/unternehmen/index.rss"),
        ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories")
    ]
    for label, feed_url in direct_feeds:
        all_news.extend(parse_rss_feed(feed_url, label, cutoff_utc, filter_keywords=ipo_keywords))

    # 3. Streng gefiltertes Google News (Whitelist seriöser Medien + intitle-Zwang)
    whitelist_query = (
        '(intitle:Börsengang OR intitle:IPO) '
        '(site:handelsblatt.com OR site:wiwo.de OR site:manager-magazin.de OR site:boersen-zeitung.de OR site:faz.net OR site:finanzen.net) '
        '-Ratgeber -Rückblick '
        f'when:{max_days}d'
    )
    gn_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(whitelist_query)}&hl=de&gl=DE&ceid=DE:de"
    all_news.extend(parse_rss_feed(gn_url, "Wirtschaftspresse (DE)", cutoff_utc))

    # Deduplizierung über bereinigten Titel-Anfang & chronologische Sortierung
    unique_news = []
    seen_prefixes = set()
    all_news.sort(key=lambda x: x["pub_dt"], reverse=True)
    
    for item in all_news:
        clean_t = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß ]", "", item["title"].lower())
        prefix = clean_t[:42]
        if prefix and prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            unique_news.append(item)
            
    return unique_news[:30]

@st.cache_data(ttl=900)
def get_company_specific_news(company_name, max_days=14):
    """Gezielte Unternehmens-News für die Research-Boxen in Tab 1 & Tab 2."""
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(days=max_days)
    q = f'"{company_name}" (IPO OR Börsengang) when:{max_days}d'
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=de&gl=DE&ceid=DE:de"
    return parse_rss_feed(url, "News", cutoff_utc)[:3]

# --- BENUTZEROBERFLÄCHE ---

st.title("🔭 IPO-Radar (Zukunfts-Pipeline)")
st.caption(f"Stand: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')} • Fokus: Nächste 6 Monate & Kandidaten 2027")

if st.button("🔄 Daten aktualisieren", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

tab_us, tab_de, tab_news = st.tabs(["🇺🇸 US-Pipeline (6 Mon.)", "🇩🇪 DE / EU (inkl. 2027)", "📰 Wirtschafts-News (5 Tage)"])

# --- TAB 1: US-IPOs ---
with tab_us:
    st.subheader("Kommende US-Börsengänge")
    us_ipos = get_us_ipos_full(FINNHUB_API_KEY)
    
    if not us_ipos:
        st.info("Aktuell keine zukünftigen US-IPOs im 6-Monats-Fenster gemeldet.")
    else:
        all_statuses = sorted(list({item.get("status", "n/a") for item in us_ipos if item.get("status")}))
        selected_status = st.selectbox("Phase / Status filtern:", ["Alle"] + all_statuses, key="us_filter")
        
        if selected_status != "Alle":
            us_ipos = [i for i in us_ipos if i.get("status") == selected_status]
            
        st.caption(f"{len(us_ipos)} geplante US-Börsengänge in der Pipeline (chronologisch & ohne Duplikate):")
        
        for item in us_ipos:
            name = item["name"]
            symbol = item["symbol"]
            display_date = item["display_date"]
            exchange = item["exchange"]
            status = item["status"]
            price = item["price"]
            shares = item["shares"]
            
            with st.container(border=True):
                col1, col2 = st.columns([2.8, 1.4])
                with col1:
                    st.markdown(f"**{name}** (`{symbol}`)")
                with col2:
                    st.markdown(f"📅 **{display_date}**")
                
                st.markdown(f"🏛️ **Börse:** {exchange}  |  🏷️ **Status:** `{status}`")
                st.markdown(f"💵 **Preisspanne:** {price}  |  📊 **Volumen:** {shares}")
                
                with st.expander("🔍 Unternehmens- & Markt-Research"):
                    clean_company = name.replace("Inc.", "").replace("Corp.", "").replace("Ltd.", "").strip()
                    links = []
                    if symbol != "n/a":
                        links.append(f"[Stock Analysis (Finanzen & Underwriters) ↗](https://stockanalysis.com/stocks/{symbol.lower()}/)")
                        links.append(f"[SEC-Börsenprospekt (S-1) ↗](https://www.sec.gov/edgar/searchedgar/companysearch?q={urllib.parse.quote(clean_company)})")
                    links.append(f"[Google News ↗](https://news.google.com/search?q={urllib.parse.quote(clean_company + ' IPO')})")
                    st.markdown(" • ".join(links))
                    
                    st.markdown(f"**Meldungen der letzten 14 Tage zu {clean_company}:**")
                    company_news = get_company_specific_news(clean_company, max_days=14)
                    if company_news:
                        for n in company_news:
                            st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date_fmt']})*")
                    else:
                        st.caption("Keine deutschsprachigen News in den letzten 14 Tagen – nutze die Links oben für US-Filings.")

# --- TAB 2: DE / EUROPA ---
with tab_de:
    st.subheader("Geplante Börsengänge (DE / Europa)")
    st.markdown("🔗 [Onvista IPO-Kandidaten ↗](https://www.onvista.de/aktien/ipos)  |  [Börse Frankfurt Zeichnungen ↗](https://live.deutsche-boerse.com/aktien/neuemissionen)")
    
    de_ipos = get_de_eu_ipos_full()
    st.caption(f"{len(de_ipos)} geplante bzw. bekannte DE/EU-Börsenkandidaten (chronologisch nach erwartetem Fenster):")
    
    for item in de_ipos:
        with st.container(border=True):
            col1, col2 = st.columns([2.8, 1.4])
            with col1:
                st.markdown(f"**{item['name']}** (`WKN: {item['wkn']}`)")
            with col2:
                st.markdown(f"📅 **{item['display_date']}**")
                
            st.markdown(f"🏛️ **Börse:** {item['exchange']}  |  🏷️ **Status:** `{item['status']}`")
            st.markdown(f"🏭 **Branche:** {item['sector']}  |  🏦 **Banken:** {item['banks']}")
            
            with st.expander("🔍 Unternehmens- & Markt-Research"):
                clean_de_name = item["name"].split("(")[0].strip()
                links = []
                if item["wkn"] != "n/a":
                    links.append(f"[Onvista Zeichnungsdetails ↗](https://www.onvista.de/suche/{item['wkn']})")
                links.append(f"[Aktuelle News suchen ↗](https://news.google.com/search?q={urllib.parse.quote(clean_de_name + ' Börsengang')})")
                st.markdown(" • ".join(links))
                
                st.markdown(f"**Aktuelle Meldungen (letzte 14 Tage) zu {clean_de_name}:**")
                c_news = get_company_specific_news(clean_de_name, max_days=14)
                if c_news:
                    for n in c_news:
                        st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date_fmt']})*")
                else:
                    st.caption("Keine neuen Meldungen in den letzten 14 Tagen.")

# --- TAB 3: MULTI-QUELLEN WIRTSCHAFTS-NEWS (LETZTE 5 TAGE) ---
with tab_news:
    st.subheader("Wirtschafts-News & IPO-Pläne (letzte 5 Tage)")
    st.caption("Quellen: Finnhub (Reuters/Bloomberg), Handelsblatt, manager magazin, CNBC, MarketWatch & gefilterte Wirtschaftspresse:")
    
    all_news = get_multi_source_ipo_news(max_days=5)
    
    if not all_news:
        st.info("In den letzten 5 Tagen gab es keine neuen IPO-Meldungen in den angeschlossenen Wirtschaftsmedien.")
    else:
        # Quellen-Filter direkt über den Nachrichten
        categories = ["Alle Quellen"] + sorted(list({n["category"] for n in all_news}))
        selected_cat = st.selectbox("Quelle filtern:", categories, key="news_source_filter")
        
        filtered_news = all_news if selected_cat == "Alle Quellen" else [n for n in all_news if n["category"] == selected_cat]
        
        for item in filtered_news:
            with st.container(border=True):
                st.caption(f"📰 **{item['source']}** ({item['category']}) • {item['date_fmt']}")
                st.markdown(f"**[{item['title']}]({item['link']})**")
