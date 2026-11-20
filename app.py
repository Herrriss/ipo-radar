import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import io
import urllib.parse

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="IPO Radar – 6-Monats-Ausblick",
    page_icon="🔭",
    layout="centered"
)

# API Key sicher aus Streamlit Secrets laden
try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- HELFER-FUNKTIONEN ---

def clean_val(val, suffix=""):
    """Gibt 'n/a' zurück, wenn ein Wert fehlt, ansonsten den formatierten Wert."""
    if pd.isna(val) or str(val).strip() in ["", "-", "n.v.", "None", "nan", "0", "0.0"]:
        return "n/a"
    if isinstance(val, (int, float)):
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}".strip()
    return f"{str(val).strip()} {suffix}".strip()

def parse_sort_date(date_str):
    """
    Wandelt bekannte Daten in ein echtes Datum um.
    Fehlt ein genaues Datum (z. B. nur Quartal oder 'n/a'), wird ein geschätztes Datum
    in der Zukunft vergeben, damit die chronologische Sortierung erhalten bleibt.
    """
    now = datetime.now()
    if not date_str or str(date_str).strip().lower() in ["", "-", "offen", "n/a", "none", "nan"]:
        # Ohne Datum -> geschätzt ans Ende des 6-Monats-Horizonts sortieren
        return now + timedelta(days=175), "n/a (Zeitpunkt offen)"
    
    s = str(date_str).strip()
    # Standard-Formate prüfen (YYYY-MM-DD oder DD.MM.YYYY)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt, dt.strftime("%d.%m.%Y")
        except ValueError:
            pass
            
    # Falls nur ein Quartal angegeben ist (z. B. "Q1 2027" oder "Q2")
    s_upper = s.upper()
    year = now.year + 1 if str(now.year + 1) in s_upper else now.year
    if "Q1" in s_upper:
        return datetime(year, 3, 15), f"~ {s} (geschätzt)"
    if "Q2" in s_upper:
        return datetime(year, 6, 15), f"~ {s} (geschätzt)"
    if "Q3" in s_upper:
        return datetime(year, 9, 15), f"~ {s} (geschätzt)"
    if "Q4" in s_upper:
        return datetime(year, 12, 15), f"~ {s} (geschätzt)"
        
    return now + timedelta(days=170), f"~ {s} (geschätzt)"

# --- DATEN-FUNKTIONEN ---

@st.cache_data(ttl=1800)
def get_us_ipos_future(api_key):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    future_str = (now + timedelta(days=180)).strftime("%Y-%m-%d")
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={today_str}&to={future_str}&token={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json().get("ipoCalendar", [])
        if not data:
            return []
        
        processed = []
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        for item in data:
            sort_dt, display_date = parse_sort_date(item.get("date"))
            # Nur zukünftige oder heutige Termine behalten (keine Vergangenheit!)
            if sort_dt < today_start:
                continue
                
            item["sort_dt"] = sort_dt
            item["display_date"] = display_date
            processed.append(item)
            
        # Chronologisch aufsteigend sortieren (nächste Termine zuerst, geschätzte danach)
        processed.sort(key=lambda x: x["sort_dt"])
        return processed
    except Exception as e:
        st.error(f"Fehler beim Laden der US-IPOs: {e}")
        return []

@st.cache_data(ttl=3600)
def get_de_ipos_future():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
                tables = pd.read_html(io.StringIO(resp.text), decimal=",", thousands=".")
                for t in tables:
                    cols_str = " ".join([str(c).lower() for c in t.columns])
                    if any(h in cols_str for h in ipo_headers) and len(t) > 0:
                        for _, row in t.iterrows():
                            raw_date = row.get("Erstnotiz") or row.get("Termin") or ""
                            sort_dt, display_date = parse_sort_date(raw_date)
                            # Strikter Filter: Alles aus der Vergangenheit ignorieren!
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

# --- TAB 1: US-IPOs (NUR ZUKUNFT, CHRONOLOGISCH + RESEARCH-BOX) ---
with tab_us:
    st.subheader("Kommende US-Börsengänge")
    us_ipos = get_us_ipos_future(FINNHUB_API_KEY)
    
    if not us_ipos:
        st.info("Aktuell keine zukünftigen US-IPOs im 6-Monats-Fenster gemeldet.")
    else:
        # Filter nach Status (z. B. expected = terminiert, filed = Prospekt eingereicht)
        all_statuses = sorted(list({item.get("status", "n/a") for item in us_ipos if item.get("status")}))
        selected_status = st.selectbox("Phase / Status filtern:", ["Alle"] + all_statuses)
        
        if selected_status != "Alle":
            us_ipos = [i for i in us_ipos if i.get("status") == selected_status]
            
        st.caption(f"{len(us_ipos)} geplante Börsengänge gefunden (nächste Termine zuerst):")
        
        for item in us_ipos:
            name = item.get("name") or "n/a"
            symbol = clean_val(item.get("symbol"))
            display_date = item.get("display_date", "n/a")
            exchange = clean_val(item.get("exchange"))
            status = clean_val(item.get("status"))
            price = clean_val(item.get("price"), "$")
            
            shares_raw = item.get("numberOfShares", 0)
            shares = f"{int(shares_raw):,} Stück".replace(",", ".") if (pd.notna(shares_raw) and shares_raw > 0) else "n/a"
            
            with st.container(border=True):
                col1, col2 = st.columns([3, 1.3])
                with col1:
                    st.markdown(f"**{name}** (`{symbol}`)")
                with col2:
                    st.markdown(f"📅 **{display_date}**")
                
                st.markdown(f"🏛️ **Börse:** {exchange}  |  🏷️ **Status:** `{status}`")
                st.markdown(f"💵 **Preisspanne:** {price}  |  📊 **Volumen:** {shares}")
                
                # Aufklappbare Research-Box für Investment-Entscheidung
                with st.expander("🔍 Unternehmens- & Markt-Research"):
                    clean_company = name.replace("Inc.", "").replace("Corp.", "").replace("Ltd.", "").strip()
                    
                    # Direkt-Links zu Primärquellen
                    links = []
                    if symbol != "n/a":
                        links.append(f"[Stock Analysis (Finanzen & Underwriters) ↗](https://stockanalysis.com/stocks/{symbol.lower()}/)")
                        links.append(f"[SEC-Börsenprospekt (S-1 Filings) ↗](https://www.sec.gov/edgar/searchedgar/companysearch?q={urllib.parse.quote(clean_company)})")
                    links.append(f"[Google News Suche ↗](https://news.google.com/search?q={urllib.parse.quote(clean_company + ' IPO')})")
                    st.markdown(" • ".join(links))
                    
                    # Live-News speziell zu diesem Unternehmen
                    st.markdown(f"**Aktuelle Meldungen zu {clean_company}:**")
                    company_news = get_news_feed(f'"{clean_company}" IPO OR Börsengang', max_items=3)
                    if company_news:
                        for n in company_news:
                            st.markdown(f"- [{n['title']}]({n['link']}) *({n['source']}, {n['date'][:16]})*")
                    else:
                        st.caption("Keine aktuellen deutschsprachigen Schlagzeilen – nutze den Google News / Stock Analysis Link oben.")

# --- TAB 2: DE / EUROPA (NUR ZUKUNFT + KANDIDATEN-PIPELINE) ---
with tab_de:
    st.subheader("Geplante Börsengänge (DE / Europa)")
    st.markdown("🔗 [Onvista IPO-Kandidaten ↗](https://www.onvista.de/aktien/ipos)  |  [Börse Frankfurt Zeichnungen ↗](https://live.deutsche-boerse.com/aktien/neuemissionen)")
    
    de_ipos = get_de_ipos_future()
    if de_ipos:
        for item in de_ipos:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1.3])
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
        st.info("In den öffentlichen Kalendertabellen steht heute noch kein neuer deutscher Börsengang mit festem Datum. Unten siehst du aktuelle Ankündigungen und Kandidaten in der Vorbereitung:")
    
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
