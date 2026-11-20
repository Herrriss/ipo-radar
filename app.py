import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import io
import urllib.parse
import re

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="IPO Radar – 6-Monats-Ausblick",
    page_icon="🔭",
    layout="centered"
)

try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- HELFER-FUNKTIONEN ---

def clean_val(val, suffix=""):
    """Gibt 'n/a' zurück, wenn ein Wert fehlt, ansonsten den formatierten Wert."""
    if pd.isna(val) or str(val).strip().lower() in ["", "-", "n.v.", "n/a", "none", "nan", "0", "0.0", "tbd"]:
        return "n/a"
    if isinstance(val, (int, float)):
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}".strip()
    return f"{str(val).strip()} {suffix}".strip()

def parse_sort_date(raw_val):
    """
    Erkennt echte Daten (auch wenn Pandas Punkte entfernt hat wie 1092026 -> 01.09.2026)
    und sortiert unbekannte Termine sauber ans Ende des 6-Monats-Horizonts.
    """
    now = datetime.now()
    if pd.isna(raw_val) or str(raw_val).strip().lower() in ["", "-", "offen", "n/a", "none", "nan", "tbd", "unscheduled"]:
        return now + timedelta(days=175), "n/a (Termin offen)"
    
    s = str(raw_val).strip()
    
    # Fix für Pandas-Zahlen ohne Punkte (z. B. 1092026 -> 01.09.2026 oder 30072026 -> 30.07.2026)
    if re.fullmatch(r"\d{7,8}", s):
        s_padded = s.zfill(8)
        s = f"{s_padded[:2]}.{s_padded[2:4]}.{s_padded[4:]}"
        
    # Standard-Datumsformate prüfen (inkl. US-Format wie "Nov 25, 2026")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt, dt.strftime("%d.%m.%Y")
        except ValueError:
            pass
            
    # Quartale erkennen (z. B. Q1 2027)
    s_upper = s.upper()
    year = now.year + 1 if str(now.year + 1) in s_upper else now.year
    for q, (m, d) in [("Q1", (3, 15)), ("Q2", (6, 15)), ("Q3", (9, 15)), ("Q4", (12, 15))]:
        if q in s_upper:
            return datetime(year, m, d), f"~ {s} (geschätzt)"
            
    return now + timedelta(days=170), f"~ {s} (geschätzt)"

# --- DATEN-FUNKTIONEN ---

@st.cache_data(ttl=1800)
def get_us_ipos_full(api_key):
    """Kombiniert terminierte US-IPOs (Finnhub) + unbestätigte S-1 Filings (Stock Analysis)."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_end = now + timedelta(days=180)
    
    combined = {}
    
    # 1. Finnhub API (fest terminierte IPOs)
    url_fh = f"https://finnhub.io/api/v1/calendar/ipo?from={now.strftime('%Y-%m-%d')}&to={horizon_end.strftime('%Y-%m-%d')}&token={api_key}"
    try:
        resp = requests.get(url_fh, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("ipoCalendar", []):
                sort_dt, display_date = parse_sort_date(item.get("date"))
                if sort_dt >= today_start:
                    sym = clean_val(item.get("symbol"))
                    key = sym if sym != "n/a" else item.get("name", "")
                    shares_raw = item.get("numberOfShares", 0)
                    shares = f"{int(shares_raw):,} Stück".replace(",", ".") if (pd.notna(shares_raw) and shares_raw > 0) else "n/a"
                    combined[key] = {
                        "name": item.get("name") or "n/a",
                        "symbol": sym,
                        "sort_dt": sort_dt,
                        "display_date": display_date,
                        "exchange": clean_val(item.get("exchange")),
                        "price": clean_val(item.get("price"), "$"),
                        "shares": shares,
                        "status": clean_val(item.get("status", "Terminiert"))
                    }
    except Exception:
        pass

    # 2. Stock Analysis (Kalender + Unscheduled Filings für die volle 6-Monats-Pipeline)
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
                        
                        for _, row in t.head(25).iterrows():
                            sym = clean_val(row.get(cols["symbol"]))
                            if sym in combined:
                                continue  # Bereits über Finnhub geladen
                            
                            raw_d = row.get(date_col) if "ipo date" in cols else "n/a"
                            sort_dt, display_date = parse_sort_date(raw_d)
                            if sort_dt < today_start:
                                continue
                                
                            combined[sym] = {
                                "name": clean_val(row.get(name_col)),
                                "symbol": sym,
                                "sort_dt": sort_dt,
                                "display_date": display_date,
                                "exchange": "NASDAQ / NYSE",
                                "price": clean_val(row.get(price_col)),
                                "shares": clean_val(row.get(shares_col), "Stück"),
                                "status": default_status
                            }
        except Exception:
            pass

    result = list(combined.values())
    result.sort(key=lambda x: x["sort_dt"])
    return result

@st.cache_data(ttl=3600)
def get_de_ipos_future():
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
    future_items = []
    
    for source_name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # Wichtig: KEIN thousands="." hier, damit Datums-Punkte nicht zerstört werden!
                tables = pd.read_html(io.StringIO(resp.text))
                for t in tables:
                    cols_str = " ".join([str(c).lower() for c in t.columns])
                    if any(h in cols_str for h in ipo_headers) and len(t) > 0:
                        for _, row in t.iterrows():
                            raw_date = row.get("Erstnotiz") or row.get("Termin") or ""
                            sort_dt, display_date = parse_sort_date(raw_date)
                            # Jetzt greift der Vergangenheitsfilter sauber!
                            if sort_dt >= today_start:
                                future_items.append({
                                    "name": row.get("Name") or row.get("Unternehmen") or "n/a",
                                    "wkn": clean_val(row.get("WKN")),
                                    "sort_dt": sort_dt,
                                    "display_date": display_date,
                                    "emission": clean_val(row.get("Emission"), "Mio. €"),
                                    "status": clean_val(row.get("Status", "Geplant")),
                                    "source": source_name
                                })
        except Exception:
            continue
            
    future_items.sort(key=lambda x: x["sort_dt"])
    return future_items

@st.cache_data(ttl=900)
def get_news_feed(query, max_items=15):
    encoded_q = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=de&gl=DE&ceid=DE:de"
    news_items = []
    
    try:
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall(".//item")[:max_items]:
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"
            
            news_items.append({
                "title": title,
                "link": link,
                "date": pub_date[:22],
                "source": source
            })
        return news_items
    except Exception:
        return []

# --- BENUTZEROBERFLÄCHE ---

st.title("🔭 IPO-Radar (6-Monats-Ausblick)")
horizon_end = (datetime.now() + timedelta(days=180)).strftime("%d.%m.%Y")
st.caption(f"Zeitraum: Heute ({datetime.now().strftime('%d.%m.%Y')}) bis {horizon_end} • Chronologisch sortiert")

if st.button("🔄 Daten aktualisieren", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

tab_us, tab_de, tab_news = st.tabs(["🇺🇸 US-Pipeline (6 Mon.)", "🇩🇪 DE / EU-Ausblick", "📰 Markt & Gerüchte"])

# --- TAB 1: US-IPOs ---
with tab_us:
    st.subheader("Kommende US-Börsengänge")
    us_ipos = get_us_ipos_full(FINNHUB_API_KEY)
    
    if not us_ipos:
        st.info("Aktuell keine zukünftigen US-IPOs im 6-Monats-Fenster gemeldet.")
    else:
        all_statuses = sorted(list({item.get("status", "n/a") for item in us_ipos if item.get("status")}))
        selected_status = st.selectbox("Phase / Status filtern:", ["Alle"] + all_statuses)
        
        if selected_status != "Alle":
            us_ipos = [i for i in us_ipos if i.get("status") == selected_status]
            
        st.caption(f"{len(us_ipos)} geplante Börsengänge in der Pipeline (chronologisch sortiert):")
        
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
                    
                    st.markdown(f"**Aktuelle Meldungen zu {clean_company}:**")
                    company_news = get_news_feed(f'"{clean_company}" IPO OR Börsengang', max_items=3)
                    if company_news:
                        for n in company_news:
                            st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date'][:16]})*")
                    else:
                        st.caption("Keine aktuellen deutschsprachigen Schlagzeilen – nutze die Links oben für US-Analysen.")

# --- TAB 2: DE / EUROPA ---
with tab_de:
    st.subheader("Geplante Börsengänge (DE / Europa)")
    st.markdown("🔗 [Onvista IPO-Kandidaten ↗](https://www.onvista.de/aktien/ipos)  |  [Börse Frankfurt Zeichnungen ↗](https://live.deutsche-boerse.com/aktien/neuemissionen)")
    
    de_ipos = get_de_ipos_future()
    if de_ipos:
        for item in de_ipos:
            with st.container(border=True):
                col1, col2 = st.columns([2.8, 1.4])
                with col1:
                    st.markdown(f"**{item['name']}** (`WKN: {item['wkn']}`)")
                with col2:
                    st.markdown(f"📅 **{item['display_date']}**")
                st.markdown(f"💰 **Emissionsvolumen:** {item['emission']}  |  🏷️ **Status:** `{item['status']}`")
                
                with st.expander("🔍 Unternehmens- & Markt-Research"):
                    if item['wkn'] != "n/a":
                        st.markdown(f"🔍 [Details & Zeichnungsinfos auf Onvista ↗](https://www.onvista.de/suche/{item['wkn']})")
                    c_news = get_news_feed(f'"{item["name"]}" Börsengang OR IPO', max_items=3)
                    for n in c_news:
                        st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']})*")
    else:
        st.info("In den öffentlichen Kalendertabellen steht aktuell noch kein neuer deutscher Börsengang mit festem zukünftigen Datum. Unten siehst du aktuelle Ankündigungen und Kandidaten in der Vorbereitung:")
    
    st.markdown("---")
    st.markdown("**🇩🇪 Pipeline & Ankündigungen (DE / Europa):**")
    de_pipeline = get_news_feed("Börsengang geplant Deutschland OR Europa OR Frankfurt IPO 2026 OR 2027", max_items=10)
    for item in de_pipeline:
        with st.container(border=True):
            st.caption(f"{item['source']} • {item['date']}")
            st.markdown(f"**[{item['title']}]({item['link']})**")

# --- TAB 3: MARKTUMFELD & GERÜCHTE ---
with tab_news:
    st.subheader("IPO-Marktumfeld & Gerüchte")
    st.caption("Hintergründe zu Stimmung am Emissionsmarkt, verschobenen IPOs und großen Kandidaten:")
    news = get_news_feed("Börsengang OR IPO Markt OR Emissionsmarkt OR Börsenpläne", max_items=15)
    if not news:
        st.info("Aktuell keine Meldungen gefunden.")
    else:
        for item in news:
            with st.container(border=True):
                st.caption(f"{item['source']} • {item['date']}")
                st.markdown(f"**[{item['title']}]({item['link']})**")
