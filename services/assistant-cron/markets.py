"""The Markets table of the office briefing. Numbers come from code-fetched sources only, never the model.

Each item has a chain of sources tried in order; an item whose sources all fail is dropped from the
table. Items are fetched concurrently with short timeouts. Currency rows (USD, EUR) use Vietcombank's
sell rate, whose day change is computed against the value stored on the state volume; with no earlier
value the change is None and the table shows a dash.
"""

import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

log = logging.getLogger("markets")

TIMEOUT = 8
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}
VCB_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
DEFAULT_ITEMS = ["gold", "bitcoin", "sp500", "vnindex", "usd", "eur"]


def get(url, **kw):
    r = requests.get(url, timeout=TIMEOUT, headers=UA, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------- sources
# Each returns {"price": float, "pct": float | None, "key": optional state key for a stored change}.

def yahoo(symbol):
    def fetch():
        meta = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                   params={"interval": "1d", "range": "1d"}).json()["chart"]["result"][0]["meta"]
        price, pct = float(meta["regularMarketPrice"]), meta.get("regularMarketChangePercent")
        if pct is None and meta.get("chartPreviousClose"):
            pct = (price / float(meta["chartPreviousClose"]) - 1) * 100
        return {"price": price, "pct": None if pct is None else float(pct)}
    return fetch


def coingecko(coin):
    def fetch():
        d = get("https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin, "vs_currencies": "usd", "include_24hr_change": "true"}).json()[coin]
        return {"price": float(d["usd"]), "pct": float(d["usd_24h_change"])}
    return fetch


def binance(symbol):
    def fetch():
        d = get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": symbol}).json()
        return {"price": float(d["lastPrice"]), "pct": float(d["priceChangePercent"])}
    return fetch


def vietcombank(code):
    def fetch():
        root = ET.fromstring(get(VCB_URL).content.decode("utf-8", "replace").split("-->", 1)[-1].strip())
        for e in root.iter("Exrate"):
            if e.get("CurrencyCode") == code:
                return {"price": float(e.get("Sell").replace(",", "")), "pct": None, "key": f"{code}:vcb"}
        raise ValueError(f"{code} not in the Vietcombank list")
    return fetch


def er_api(code):
    def fetch():
        rate = get(f"https://open.er-api.com/v6/latest/{code}").json()["rates"]["VND"]
        return {"price": float(rate), "pct": None, "key": f"{code}:erapi"}
    return fetch


# name, price format, sources in order
ITEMS = {
    "gold": ("Gold", "${:,.0f}/oz", [yahoo("GC=F"), coingecko("pax-gold")]),
    "bitcoin": ("BTC", "${:,.0f}", [binance("BTCUSDT"), coingecko("bitcoin")]),
    "ethereum": ("ETH", "${:,.0f}", [binance("ETHUSDT"), coingecko("ethereum")]),
    "solana": ("SOL", "${:,.2f}", [binance("SOLUSDT"), coingecko("solana")]),
    "chainlink": ("LINK", "${:,.2f}", [binance("LINKUSDT"), coingecko("chainlink")]),
    "sp500": ("S&P 500", "{:,.0f}", [yahoo("^GSPC")]),
    "nasdaq100": ("Nasdaq 100", "{:,.0f}", [yahoo("^NDX")]),
    "vnindex": ("VN-Index", "{:,.0f}", [yahoo("^VNINDEX.VN")]),
    "usd": ("USD", "{:,.0f} ₫", [vietcombank("USD"), yahoo("VND=X"), er_api("USD")]),
    "eur": ("EUR", "{:,.0f} ₫", [vietcombank("EUR"), yahoo("EURVND=X"), er_api("EUR")]),
}


def fetch_item(item):
    """First source that answers, or None."""
    for src in ITEMS[item][2]:
        try:
            return src()
        except Exception as e:
            log.warning("markets: %s source failed: %s", item, str(e)[:100])
    return None


def stored_change(res, state, today):
    """Day change against the last value stored on an earlier day; None when there is none."""
    store = state.setdefault("fx", {})
    s = store.get(res["key"])
    prev = None
    if s:
        prev = s.get("prev") if s["date"] == today else s["rate"]
    store[res["key"]] = {"rate": res["price"], "date": today, "prev": prev}
    return (res["price"] / prev - 1) * 100 if prev else None


def fetch_all(cfg, state, today):
    """Raw results {item: {"price", "pct"} or None}, in config order. `state` is updated for currencies."""
    items = [i for i in (cfg.get("market_items") or DEFAULT_ITEMS) if i in ITEMS]
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        results = list(pool.map(fetch_item, items))
    out = {}
    for item, res in zip(items, results):
        if res and res.get("key"):
            res["pct"] = stored_change(res, state, today)
        out[item] = res
    return out


# ---------------------------------------------------------------------------- table

def arrow(pct) -> str:
    if pct is None:
        return "—"
    return f"{'▲' if pct >= 0 else '▼'} {abs(pct):.1f}%"


def table(raw) -> str:
    """Markdown table from raw results; "" when every row failed."""
    rows = [(ITEMS[k][0], ITEMS[k][1].format(r["price"]), arrow(r["pct"])) for k, r in raw.items() if r and k in ITEMS]
    if not rows:
        return ""
    out = ["**Markets** (last close)", "|          | Price      | Day    |", "|----------|-----------:|-------:|"]
    out += [f"| {n} | {p} | {d} |" for n, p, d in rows]
    return "\n".join(out)
