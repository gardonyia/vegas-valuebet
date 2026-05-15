import streamlit as st
import requests
import time
from datetime import datetime

# ── Konfiguráció ──────────────────────────────────────────
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
CHAT_ID        = st.secrets["CHAT_ID"]
REMEMBER_TOKEN = st.secrets["REMEMBER_TOKEN"]
SSTOKEN        = st.secrets["SSTOKEN"]
STOKEN         = st.secrets["STOKEN"]

SUREBET_URL = "https://en.surebet.com/by/bookie/vegas/valuebets"

COOKIES = {
    "remember_user_token": REMEMBER_TOKEN,
    "sstoken":             SSTOKEN,
    "stoken":              STOKEN,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer":    "https://en.surebet.com/valuebets",
}

# ── Állapot ───────────────────────────────────────────────
if "sent_ids"    not in st.session_state: st.session_state.sent_ids    = set()
if "all_bets"    not in st.session_state: st.session_state.all_bets    = []
if "last_update" not in st.session_state: st.session_state.last_update = None
if "running"     not in st.session_state: st.session_state.running     = False
if "log"         not in st.session_state: st.session_state.log         = []

# ── Segédfüggvények ───────────────────────────────────────

def safe_float(val) -> float:
    try:
        return float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


def fetch_valuebets(min_ov: float, min_odds: float, max_odds: float) -> list:
    from bs4 import BeautifulSoup
    import re, json, html
    try:
        r = requests.get(SUREBET_URL, cookies=COOKIES, headers=HEADERS, timeout=15)
        st.session_state.log.append(f"🌐 HTTP: {r.status_code} | méret: {len(r.text)} karakter")
        if r.status_code != 200:
            st.session_state.log.append(f"⚠️ Hiba: {r.text[:200]}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        bets = []

        rows = soup.select("tbody tr")
        st.session_state.log.append(f"📋 Talált sorok: {len(rows)}")

        for row in rows:
            try:
                # Overvalue kinyerése
                ov_el = row.select_one(".overvalue-box, [class*='overvalue']")
                if not ov_el:
                    continue
                ov = safe_float(re.sub(r'[^0-9.]', '', ov_el.get_text(strip=True)))

                # data-comb-json attribútumból az adatok
                comb_el = row.select_one("[data-comb-json]")
                if comb_el:
                    raw = html.unescape(comb_el["data-comb-json"])
                    data = json.loads(raw)
                    if isinstance(data, str):
                        data = json.loads(data)
                    # Debug: első sor struktúráját logoljuk
                    if len(bets) == 0 and len(rows) > 1:
                        st.session_state.log.append(f"🔍 JSON típus: {type(data).__name__} | tartalom: {str(data)[:300]}")
                    prongs = data.get("prongs", [])
                    p = prongs[0] if prongs else {}
                    # Ha a prong elem string, parse-oljuk
                    if isinstance(p, str):
                        try:
                            p = json.loads(p)
                        except Exception:
                            p = {}
                    teams = data.get("teams", [])
                    event = " – ".join(teams) if teams else str(data.get("synonym_id", ""))
                    market = p.get("market_name", p.get("market", ""))
                    # initial_value lehet dict {"datetime":..., "value":1.87} vagy szám
                    iv = p.get("initial_value", p.get("value", 0))
                    if isinstance(iv, dict):
                        odds = safe_float(iv.get("value", 0))
                    else:
                        odds = safe_float(iv)
                    prob = round(1 / odds * 100, 1) if odds > 0 else 0
                    tournament = data.get("tournament", "")
                    start_time = ""
                    iv2 = p.get("initial_value", {})
                    if isinstance(iv2, dict):
                        start_time = iv2.get("datetime", "")[:16]
                else:
                    # Fallback: cellákból
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue
                    event  = cells[2].get_text(strip=True)[:80]
                    market = cells[3].get_text(strip=True)[:60]
                    odds_text = cells[4].get_text(strip=True) if len(cells) > 4 else "0"
                    odds   = safe_float(re.sub(r'[^0-9.]', '', odds_text))
                    prob   = 0
                    tournament = ""
                    start_time = ""

                if ov >= min_ov and min_odds <= odds <= max_odds:
                    bets.append({
                        "overvalue":   ov,
                        "event":       event,
                        "market":      market,
                        "odds":        odds,
                        "probability": prob,
                        "time":        start_time,
                        "tournament":  tournament,
                    })

            except Exception as e:
                st.session_state.log.append(f"⚠️ Sor hiba: {e}")
                continue

        st.session_state.log.append(f"✅ Szűrés után: {len(bets)} bet")
        return bets

    except Exception as e:
        st.session_state.log.append(f"❌ Lekérési hiba: {e}")
        return []


def bet_id(bet: dict) -> str:
    return f"{bet.get('event','')}__{bet.get('market','')}__{bet.get('odds','')}"


def send_telegram(msg: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        st.session_state.log.append(f"❌ Telegram hiba: {e}")
        return False


def format_msg(bet: dict) -> str:
    ov    = bet.get("overvalue", 0)
    odds  = bet.get("odds", 0)
    prob  = bet.get("probability", 0)
    event = bet.get("event", "–")
    mkt   = bet.get("market", "–")
    start = bet.get("time", "–")
    emoji = "🔥🔥🔥" if ov >= 20 else ("🔥🔥" if ov >= 10 else "🔥")
    return (
        f"{emoji} *VEGAS.HU VALUEBET*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏟 *Esemény:* {event}\n"
        f"📊 *Piac:* {mkt}\n"
        f"⏰ *Kezdés:* {start}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Odds:* `{odds}`\n"
        f"📈 *Overvalue:* `+{ov}%`\n"
        f"🎯 *Valószínűség:* `{prob}%`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [Vegas.hu](https://vegas.hu)\n"
        f"_{datetime.now().strftime('%H:%M:%S')}_"
    )

# ── UI ────────────────────────────────────────────────────

st.set_page_config(page_title="Vegas Valuebet Riasztó", page_icon="🔥", layout="centered")
st.title("🔥 Vegas.hu Valuebet Riasztó")
st.caption("Surebet.com → Telegram értesítő")

with st.sidebar:
    st.header("⚙️ Beállítások")
    min_ov   = st.slider("Min. overvalue (%)", 1, 30, 5)
    min_odds = st.number_input("Min. odds", value=1.50, step=0.05)
    max_odds = st.number_input("Max. odds", value=10.0, step=0.5)
    interval = st.slider("Frissítési időköz (mp)", 60, 600, 300)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Indít", use_container_width=True):
            st.session_state.running = True
            send_telegram(
                "🤖 *Vegas Valuebet Bot elindult!*\n"
                f"• Min overvalue: `{min_ov}%`\n"
                f"• Odds: `{min_odds} – {max_odds}`\n"
                f"• Frissítés: `{interval}mp`"
            )
    with col2:
        if st.button("⏹ Leállít", use_container_width=True):
            st.session_state.running = False

# ── Fő panel ──────────────────────────────────────────────

status_box  = st.empty()
metrics_row = st.empty()
table_box   = st.empty()
log_box     = st.empty()

if st.session_state.running:
    status_box.success(f"✅ Figyelés aktív – {interval}mp-ként frissül")
else:
    status_box.info("⏸ Leállítva – nyomj Indít gombot")

# Metrikák
if st.session_state.last_update:
    with metrics_row.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Talált valuebetek", len(st.session_state.all_bets))
        c2.metric("Elküldött riasztások", len(st.session_state.sent_ids))
        c3.metric("Utolsó frissítés", st.session_state.last_update)

# Táblázat
if st.session_state.all_bets:
    import pandas as pd
    df = pd.DataFrame(st.session_state.all_bets)
    cols = [c for c in ["event","market","odds","overvalue","probability","time"] if c in df.columns]
    table_box.dataframe(df[cols], use_container_width=True, hide_index=True)

# Log
if st.session_state.log:
    with log_box.expander("📋 Log", expanded=False):
        for entry in st.session_state.log[-20:]:
            st.text(entry)

# ── Fő ciklus ─────────────────────────────────────────────

if st.session_state.running:
    bets = fetch_valuebets(min_ov, min_odds, max_odds)
    st.session_state.all_bets    = bets
    st.session_state.last_update = datetime.now().strftime("%H:%M:%S")

    new_count = 0
    for bet in bets:
        uid = bet_id(bet)
        if uid not in st.session_state.sent_ids:
            if send_telegram(format_msg(bet)):
                st.session_state.sent_ids.add(uid)
                new_count += 1
                time.sleep(0.5)

    log_entry = f"[{st.session_state.last_update}] {len(bets)} bet találva, {new_count} új riasztás elküldve"
    st.session_state.log.append(log_entry)

    # Memória tisztítás
    if len(st.session_state.sent_ids) > 1000:
        st.session_state.sent_ids = set(list(st.session_state.sent_ids)[-500:])

    time.sleep(interval)
    st.rerun()
