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
    page_title="IPO Radar – 6-Monats- & 2027-Ausblick",
    page_icon="🔭",
    layout="centered"
)

try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- BEKANNTE DE / EU IPO-KANDIDATEN FÜR 2027 (Jederzeit erweiterbar) ---
# Diese Liste stellt sicher, dass bekannte europäische IPO-Kandidaten für 2027
# genau wie in Tab 1 als echte Unternehmenskarten mit Live-News-Research erscheinen.
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
        "name": "klarna / Revolut (EU-Fintech-Pipeline)",
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
    """Gibt 'n/a' zurück, wenn ein Wert fehlt, ansonsten den formatierten Wert."""
    if pd.isna(val) or str(val).strip().lower() in ["", "-", "n.v.", "n/a", "none", "nan", "0", "0.0", "tbd"]:
        return "n/a"
    if isinstance(val, (int, float)):
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}".strip()
    return f"{str(val).strip()} {suffix}".strip()

def parse_sort_date(raw_val):
    """Wandelt Termine (auch Quartale, Halbjahre oder Jahreszahlen wie 'H1 2027') in sortierbare Daten um."""
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

# --- DATEN-FUNKTIONEN ---

@st.cache_data(ttl=1800)
def get_us_ipos_full(api_key):
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

    # 2. Stock Analysis (Kalender + Unscheduled Filings)
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
                                continue
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
def get_de_eu_ipos_full():
    """Kombiniert akut terminierte DE/EU-Zeichnungen (Web-Tabellen) mit bekannten 2027-Kandidaten."""
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
    
    # 1. Live-Tabellen prüfen auf akut terminierte Zeichnungen
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
                                seen_names.add(cname.lower())
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

    # 2. Bekannte 2027-Kandidaten für DE / Europa einreihen
    for cand in KNOWN_EU_2027_CANDIDATES:
        if cand["name"].lower() in seen_names:
            continue
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

@st.cache_data(ttl=900)
def get_fresh_news(query, max_days=14, max_items=15):
    """
    Holt NUR brandaktuelle Meldungen der letzten `max_days` Tage und sortiert
    sie strikt chronologisch (neueste zuerst), damit keine alten Artikel auftauchen.
    """
    full_query = f"{query} when:{max_days}d"
    encoded_q = urllib.parse.quote(full_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=de&gl=DE&ceid=DE:de"
    
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(days=max_days)
    news_items = []
    
    try:
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall(".//item"):
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"
            
            # Echtes Veröffentlichungsdatum parsen & alles Alte rigoros rauswerfen
            try:
                pub_dt = parsedate_to_datetime(pub_date_raw)
                if pub_dt < cutoff_utc:
                    continue
                date_fmt = pub_dt.strftime("%d.%m.%Y, %H:%M Uhr")
            except Exception:
                pub_dt = now_utc - timedelta(days=max_days)
                date_fmt = pub_date_raw[:16]
                
            news_items.append({
                "title": title,
                "link": link,
                "pub_dt": pub_dt,
                "date_fmt": date_fmt,
                "source": source
            })
            
        # Neueste Schlagzeilen ganz nach oben sortieren
        news_items.sort(key=lambda x: x["pub_dt"], reverse=True)
        return news_items[:max_items]
    except Exception:
        return []

# --- BENUTZEROBERFLÄCHE ---

st.title("🔭 IPO-Radar (Zukunfts-Pipeline)")
horizon_end = (datetime.now() + timedelta(days=180)).strftime("%d.%m.%Y")
st.caption(f"Stand: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')} • Fokus: Nächste 6 Monate & Kandidaten 2027")

if st.button("🔄 Daten aktualisieren", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

tab_us, tab_de, tab_news = st.tabs(["🇺🇸 US-Pipeline (6 Mon.)", "🇩🇪 DE / EU (inkl. 2027)", "📰 Aktuelle News (14 Tage)"])

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
            
        st.caption(f"{len(us_ipos)} geplante US-Börsengänge in der Pipeline (chronologisch sortiert):")
        
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
                    
                    st.markdown(f"**Meldungen der letzten 30 Tage zu {clean_company}:**")
                    company_news = get_fresh_news(f'"{clean_company}" IPO OR Börsengang', max_days=30, max_items=3)
                    if company_news:
                        for n in company_news:
                            st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date_fmt']})*")
                    else:
                        st.caption("Keine deutschsprachigen News in den letzten 30 Tagen – nutze die Links oben für US-Filings.")

# --- TAB 2: DE / EUROPA (KARTEN-DESIGN WIE TAB 1 INKL. 2027-PIPELINE) ---
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
                
                st.markdown(f"**Aktuelle Meldungen (letzte 30 Tage) zu {clean_de_name}:**")
                c_news = get_fresh_news(f'"{clean_de_name}" Börsengang OR IPO', max_days=30, max_items=3)
                if c_news:
                    for n in c_news:
                        st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date_fmt']})*")
                else:
                    st.caption("Keine neuen Meldungen in den letzten 30 Tagen.")

    st.markdown("---")
    st.markdown("**🆕 Frisch entdeckte 2027-Kandidaten aus den News (letzte 14 Tage):**")
    new_2027_news = get_fresh_news('"Börsengang 2027" OR "IPO 2027" OR "Börsenpläne 2027"', max_days=14, max_items=6)
    if new_2027_news:
        for item in new_2027_news:
            with st.container(border=True):
                st.caption(f"🆕 {item['source']} • {item['date_fmt']}")
                st.markdown(f"**[{item['title']}]({item['link']})**")
    else:
        st.caption("In den letzten 14 Tagen wurden keine weiteren neuen 2027-Börsengänge angekündigt.")

# --- TAB 3: MARKTUMFELD & GERÜCHTE (NUR LETZTE 14 TAGE!) ---
with tab_news:
    st.subheader("Aktuelle IPO-Meldungen & Marktstimmung")
    st.caption("Strikter Zeitfilter: Nur Meldungen der letzten 14 Tage (neueste zuerst):")
    
    news = get_fresh_news("Börsengang OR IPO Aktie OR Emissionsmarkt OR Zeichnungsfrist", max_days=14, max_items=15)
    if not news:
        st.info("In den letzten 14 Tagen gab es keine neuen allgemeinen IPO-Schlagzeilen.")
    else:
        for item in news:
            with st.container(border=True):
                st.caption(f"{item['source']} • {item['date_fmt']}")
                st.markdown(f"**[{item['title']}]({item['link']})**")
