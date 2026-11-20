import streamlit as st
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# --- SEITEN-KONFIGURATION (Mobilfreundlich) ---
st.set_page_config(
    page_title="IPO Radar",
    page_icon="📈",
    layout="centered"
)

# API Key sicher aus Streamlit Secrets laden (oder Fallback für lokalen Start)
try:
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except Exception:
    FINNHUB_API_KEY = "dc03iq1r01qgh2a7ms80dc03iq1r01qgh2a7ms8g"

# --- DATEN-FUNKTIONEN (Mit Caching für schnelle Ladezeiten auf dem Handy) ---

@st.cache_data(ttl=1800)  # Cache für 30 Minuten
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
        # Chronologisch sortieren (früheste zuerst)
        if "date" in df.columns:
            df = df.sort_values(by="date", ascending=True)
        return df
    except Exception as e:
        st.error(f"Fehler beim Laden der US-IPOs: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)  # Cache für 1 Stunde
def get_onvista_ipos():
    url = "https://www.onvista.de/aktien/ipos"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        # Tabellen direkt mit pandas auslesen
        tables = pd.read_html(response.text)
        if tables:
            return tables[0]
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame({"Hinweis": [f"Onvista-Tabelle aktuell nicht direkt abrufbar ({e}). Bitte Link nutzen."]})

@st.cache_data(ttl=900)  # Cache für 15 Minuten
def get_ipo_news():
    # Onvista RSS-Feed für aktuelle Markt-News
    rss_url = "https://www.onvista.de/news/feed/rss.xml"
    keywords = ["ipo", "börsengang", "börsendebüt", "erstnotiz", "zeichnungsfrist", "emission", "aktienplatzierung"]
    news_items = []
    
    try:
        response = requests.get(rss_url, timeout=10)
        root = ET.fromstring(response.content)
        for item in root.findall(".//item"):
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            desc = item.find("description").text if item.find("description") is not None else ""
            
            combined_text = (title + " " + desc).lower()
            if any(kw in combined_text for kw in keywords):
                news_items.append({
                    "title": title,
                    "link": link,
                    "date": pub_date[:22]
                })
        return news_items
    except Exception as e:
        st.error(f"News-Feed konnte nicht geladen werden: {e}")
        return []

# --- BENUTZEROBERFLÄCHE (MOBILE-FIRST) ---

st.title("📈 Mein IPO-Radar")
st.caption(f"Stand: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')}")

if st.button("🔄 Daten aktualisieren", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

tab_us, tab_de, tab_news = st.tabs(["🇺🇸 US-IPOs", "🇩🇪 DE / Europa", "📰 IPO-News"])

# --- TAB 1: US-IPOs ---
with tab_us:
    st.subheader("Anstehende US-Börsengänge")
    df_us = get_us_ipos(FINNHUB_API_KEY)
    
    if df_us.empty:
        st.info("Aktuell keine terminierten US-IPOs in den nächsten 45 Tagen gefunden.")
    else:
        # Filter nach Status
        status_options = ["Alle"] + sorted(df_us["status"].dropna().unique().tolist())
        selected_status = st.selectbox("Status filtern:", status_options)
        
        if selected_status != "Alle":
            df_us = df_us[df_us["status"] == selected_status]
            
        for _, row in df_us.iterrows():
            name = row.get("name", "Unbekannt")
            symbol = row.get("symbol", "-")
            date_str = row.get("date", "Offen")
            exchange = row.get("exchange", "-")
            price = row.get("price", "Keine Angabe")
            shares = row.get("numberOfShares", 0)
            status = row.get("status", "-")
            
            # Datum schön formatieren
            try:
                date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_fmt = date_str

            # Karten-Ansicht für das Smartphone
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{name}** (`{symbol}`)")
                with col2:
                    st.markdown(f"📅 **{date_fmt}**")
                
                st.markdown(f"🏛️ **Börse:** {exchange} | 🏷️ **Status:** `{status}`")
                st.markdown(f"💵 **Preisspanne:** {price if price else 'Offen'} $")
                
                if pd.notna(shares) and shares > 0:
                    st.markdown(f"📊 **Aktienvolumen:** {int(shares):,} Stück".replace(",", "."))
                
                # Direkter Link zu Stock Analysis für Underwriters / Konsortialbanken
                if symbol and symbol != "-":
                    sa_url = f"https://stockanalysis.com/stocks/{symbol.lower()}/"
                    st.markdown(f"🏦 [Konsortialbanken & Details auf Stock Analysis prüfen ↗]({sa_url})")

# --- TAB 2: DE / EUROPA (ONVISTA) ---
with tab_de:
    st.subheader("Geplante Börsengänge (Onvista)")
    st.markdown("🔗 [Direkt zur Onvista IPO-Übersicht ↗](https://www.onvista.de/aktien/ipos)")
    
    df_onvista = get_onvista_ipos()
    if not df_onvista.empty:
        st.dataframe(df_onvista, use_container_width=True, hide_index=True)
    else:
        st.warning("Keine Tabellendaten gefunden.")

# --- TAB 3: NEWS-TICKER ---
with tab_news:
    st.subheader("Aktuelle IPO-Meldungen")
    news = get_ipo_news()
    if not news:
        st.info("Aktuell keine spezifischen IPO-Schlagzeilen im dpa-AFX-Feed.")
    else:
        for item in news:
            with st.container(border=True):
                st.caption(item["date"])
                st.markdown(f"**[{item['title']}]({item['link']})**")
