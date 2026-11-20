import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import io

# --- SEITEN-KONFIGURATION (Optimal für Smartphone & Desktop) ---
st.set_page_config(
    page_title="IPO Radar",
    page_icon="📈",
    layout="centered"
)

# API Key sicher aus Streamlit Secrets laden
try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- HELFER-FUNKTIONEN ---

def format_de_number(val, suffix=""):
    """Formatiert Zahlen sauber ins deutsche Format (z. B. 1.234,56 €)."""
    if pd.isna(val) or str(val).strip() in ["", "-", "n.v.", "None"]:
        return "Offen"
    if isinstance(val, (int, float)):
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}".strip()
    return f"{val} {suffix}".strip()

# --- DATEN-FUNKTIONEN ---

@st.cache_data(ttl=1800)
def get_us_ipos(api_key):
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={today}&to={future}&token={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json().get("ipoCalendar", [])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df = df.sort_values(by="date", ascending=True)
        return df
    except Exception as e:
        st.error(f"Fehler beim Laden der US-IPOs: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_de_ipos():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Referer": "https://www.google.de/"
    }
    
    ipo_headers = ["wkn", "isin", "termin", "emissions", "zeichnungs", "erstnotiz", "status", "preisspanne"]
    sources = [
        ("boerse.de", "https://www.boerse.de/ipos/"),
        ("finanzen.net", "https://www.finanzen.net/ipo/")
    ]
    
    for source_name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                tables = pd.read_html(io.StringIO(resp.text), decimal=",", thousands=".")
                for t in tables:
                    cols_str = " ".join([str(c).lower() for c in t.columns])
                    if any(h in cols_str for h in ipo_headers) and len(t) > 0:
                        return t, source_name
        except Exception:
            continue

    return pd.DataFrame(), None

@st.cache_data(ttl=900)
def get_ipo_news(query="B%C3%B6rsengang+OR+IPO+Aktie"):
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de"
    news_items = []
    
    try:
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall(".//item")[:20]:
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "Börsen-News"
            
            news_items.append({
                "title": title,
                "link": link,
                "date": pub_date[:22],
                "source": source
            })
        return news_items
    except Exception as e:
        st.error(f"News-Feed konnte nicht geladen werden: {e}")
        return []

# --- BENUTZEROBERFLÄCHE (EINHEITLICHES KARTEN-DESIGN) ---

st.title("📈 Mein IPO-Radar")
st.caption(f"Stand: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')}")

if st.button("🔄 Daten aktualisieren", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

tab_us, tab_de, tab_news = st.tabs(["🇺🇸 US-IPOs", "🇩🇪 DE / Europa", "📰 IPO-News"])

# --- TAB 1: US-IPOs (KARTEN-DESIGN) ---
with tab_us:
    st.subheader("Anstehende US-Börsengänge")
    df_us = get_us_ipos(FINNHUB_API_KEY)
    
    if df_us.empty:
        st.info("Aktuell keine terminierten US-IPOs in den nächsten 45 Tagen gefunden.")
    else:
        status_options = ["Alle"] + sorted(df_us["status"].dropna().unique().tolist())
        selected_status = st.selectbox("Status filtern:", status_options)
        
        if selected_status != "Alle":
            df_us = df_us[df_us["status"] == selected_status]
            
        for _, row in df_us.iterrows():
            name = row.get("name", "Unbekannt")
            symbol = row.get("symbol", "-")
            date_str = row.get("date", "Offen")
            exchange = row.get("exchange", "-")
            price = row.get("price", "")
            shares = row.get("numberOfShares", 0)
            status = row.get("status", "-")
            
            try:
                date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_fmt = date_str

            with st.container(border=True):
                # Kopfzeile: Name, Ticker & Datum
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{name}** (`{symbol}`)")
                with col2:
                    st.markdown(f"📅 **{date_fmt}**")
                
                # Detail-Infos
                st.markdown(f"🏛️ **Börse:** {exchange}  |  🏷️ **Status:** `{status}`")
                
                vol_str = f"{int(shares):,} Stück".replace(",", ".") if (pd.notna(shares) and shares > 0) else "Offen"
                price_str = f"{price} $" if price else "Offen"
                st.markdown(f"💵 **Preisspanne:** {price_str}  |  📊 **Volumen:** {vol_str}")
                
                # Direktlink für Underwriters / Konsortialbanken
                if symbol and symbol != "-":
                    sa_url = f"https://stockanalysis.com/stocks/{symbol.lower()}/"
                    st.markdown(f"🏦 [Konsortialbanken & Details auf Stock Analysis prüfen ↗]({sa_url})")

# --- TAB 2: DE / EUROPA (KARTEN-DESIGN MIT VOLLEM INFORMATIONSGEHALT) ---
with tab_de:
    st.subheader("Börsengänge (DE / Europa)")
    st.markdown("🔗 [Onvista IPO-Übersicht ↗](https://www.onvista.de/aktien/ipos)  |  [Börse Frankfurt Neuemissionen ↗](https://live.deutsche-boerse.com/aktien/neuemissionen)")
    
    df_de, source_name = get_de_ipos()
    if not df_de.empty:
        st.caption(f"Quelle: {source_name}")
        
        for _, row in df_de.iterrows():
            name = row.get("Name", "Unbekannt")
            wkn = row.get("WKN", "-")
            erstnotiz = row.get("Erstnotiz", "Offen")
            emission = format_de_number(row.get("Emission"), "Mio. €")
            kurs = format_de_number(row.get("Aktueller Kurs"), "€")
            perf = str(row.get("Performance", "-")).strip()
            
            # Performance farblich hervorheben
            if perf.startswith("-"):
                perf_display = f"📉 :red[**{perf}**]"
            elif perf not in ["-", "n.v.", "0,00%", "0,00 %"]:
                perf_display = f"📈 :green[**+{perf}**]" if not perf.startswith("+") else f"📈 :green[**{perf}**]"
            else:
                perf_display = f"➖ **{perf}**"

            with st.container(border=True):
                # Kopfzeile: Name, WKN & Erstnotiz-Datum
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{name}** (`WKN: {wkn}`)")
                with col2:
                    st.markdown(f"📅 **{erstnotiz}**")
                
                # Kennzahlen aus Tab 2 sauber aufbereitet
                st.markdown(f"💰 **Emissionsvolumen:** {emission}")
                st.markdown(f"💶 **Aktueller Kurs:** {kurs}  |  {perf_display}")
                
                # Direktlink zu Onvista über die WKN
                if wkn and str(wkn) != "-":
                    onvista_search_url = f"https://www.onvista.de/suche/{wkn}"
                    st.markdown(f"🔍 [Kurs, Chart & Handelsplätze auf Onvista prüfen ↗]({onvista_search_url})")
    else:
        st.info("Aktuell keine Tabellendaten verfügbar.")
    
    st.markdown("---")
    st.markdown("**🇩🇪 Aktuelle Meldungen zu deutschen & europäischen Börsengängen:**")
    de_news = get_ipo_news(query="B%C3%B6rsengang+Frankfurt+OR+Zeichnungsfrist+Aktie+OR+IPO+Deutschland")
    for item in de_news[:8]:
        with st.container(border=True):
            st.caption(f"{item['source']} • {item['date']}")
            st.markdown(f"**[{item['title']}]({item['link']})**")

# --- TAB 3: NEWS-TICKER ---
with tab_news:
    st.subheader("Aktuelle IPO-Meldungen")
    news = get_ipo_news()
    if not news:
        st.info("Aktuell keine spezifischen IPO-Schlagzeilen gefunden.")
    else:
        for item in news:
            with st.container(border=True):
                st.caption(f"{item['source']} • {item['date']}")
                st.markdown(f"**[{item['title']}]({item['link']})**")
