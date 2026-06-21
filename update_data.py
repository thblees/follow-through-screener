#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aktualisiert data.json fuer den Follow-Through-Screener.
Quelle: TradingView Scanner-API (inoffiziell). Laeuft taeglich per GitHub Action.
"""
import json
import sys
import datetime
import requests

SCAN_URL = "https://scanner.tradingview.com/america/scan"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# (Anzeigename, ETF-Kuerzel, ETF-Ticker, [TradingView-Sektor(en) fuer Einzelwerte])
SECTORS = [
    ("Technology", "XLK", "AMEX:XLK", ["Technology Services", "Electronic Technology"]),
    ("Industrials", "XLI", "AMEX:XLI", ["Producer Manufacturing", "Industrial Services", "Transportation", "Commercial Services"]),
    ("Utilities", "XLU", "AMEX:XLU", ["Utilities"]),
    ("Financials", "XLF", "AMEX:XLF", ["Finance"]),
    ("Materials", "XLB", "AMEX:XLB", ["Non-Energy Minerals", "Process Industries"]),
    ("Consumer Discretionary", "XLY", "AMEX:XLY", ["Consumer Durables", "Consumer Services", "Retail Trade"]),
    ("Consumer Staples", "XLP", "AMEX:XLP", ["Consumer Non-Durables"]),
    ("Real Estate", "XLRE", "AMEX:XLRE", ["Finance"]),            # Naeherung: REITs liegen bei TV unter "Finance"
    ("Communication Services", "XLC", "AMEX:XLC", ["Communications"]),  # Naeherung
    ("Health Care", "XLV", "AMEX:XLV", ["Health Technology", "Health Services"]),
    ("Energy", "XLE", "AMEX:XLE", ["Energy Minerals"]),
]

TOP_N = 3
MIN_MCAP = 2_000_000_000
MIN_VOL = 800_000
GOOD_EXCH = {"NASDAQ", "NYSE", "AMEX"}
COLS = ["name", "description", "close", "Perf.W", "Perf.1M", "RSI", "EMA50",
        "market_cap_basic", "volume", "sector"]


def scan(payload):
    r = requests.post(SCAN_URL, headers=HEADERS, data=json.dumps(payload), timeout=25)
    r.raise_for_status()
    return r.json().get("data", [])


def get_sector_perf():
    payload = {
        "symbols": {"tickers": [s[2] for s in SECTORS], "query": {"types": []}},
        "columns": ["Perf.W", "Perf.1M"],
        "range": [0, 20],
        "options": {"lang": "en"},
    }
    perf = {}
    for row in scan(payload):
        d = row["d"]
        perf[row["s"].split(":")[1]] = {"week": d[0], "month": d[1]}
    out = []
    for name, etf, _t, _sec in SECTORS:
        p = perf.get(etf, {})
        out.append({"name": name, "etf": etf,
                    "week": round(p.get("week") or 0.0, 2),
                    "month": round(p.get("month") or 0.0, 2)})
    return out


def base_filters(sectors):
    return [
        {"left": "market_cap_basic", "operation": "egreater", "right": MIN_MCAP},
        {"left": "volume", "operation": "egreater", "right": MIN_VOL},
        {"left": "sector", "operation": "in_range", "right": sectors},
    ]


def parse_rows(rows):
    out = []
    for row in rows:
        exch, _, tk = row["s"].partition(":")
        if exch not in GOOD_EXCH:
            continue
        d = dict(zip(COLS, row["d"]))
        close, ema = d.get("close"), d.get("EMA50")
        out.append({
            "t": tk,
            "n": d.get("description") or tk,
            "p": round(close, 2) if close is not None else 0.0,
            "w": round(d.get("Perf.W") or 0.0, 2),
            "m": round(d.get("Perf.1M") or 0.0, 2),
            "rsi": round(d.get("RSI") or 0.0, 1),
            "a": bool(close is not None and ema is not None and close >= ema),
            "mc": d.get("market_cap_basic") or 0,
        })
    return out


def scan_sector(filters):
    payload = {
        "filter": filters,
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": COLS,
        "sort": {"sortBy": "Perf.W", "sortOrder": "desc"},
        "range": [0, 40],
        "options": {"lang": "en"},
    }
    return parse_rows(scan(payload))


def get_leaders(sectors):
    return scan_sector(base_filters(sectors))[:5]


def get_follow(sectors):
    flt = base_filters(sectors) + [
        {"left": "Perf.W", "operation": "in_range", "right": [1, 9]},
        {"left": "RSI", "operation": "in_range", "right": [48, 67]},
    ]
    return [r for r in scan_sector(flt) if r["a"]][:5]


def fmt_pct(v):
    return ("+" if v > 0 else "") + f"{v:.1f}".replace(".", ",") + " %"


def main():
    sectors = get_sector_perf()
    ranked = sorted(sectors, key=lambda s: s["week"], reverse=True)
    top = ranked[:TOP_N]
    sec_map = {s[0]: s[3] for s in SECTORS}

    deep = []
    for sec in top:
        tv = sec_map[sec["name"]]
        deep.append({
            "name": sec["name"], "etf": sec["etf"], "week": sec["week"],
            "note": ("Leader = staerkste Wochengewinner (oft ausgereizt). "
                     "Follow-Through = liquide Nachzuegler ueber GD50 mit gesundem RSI (48-67)."),
            "leaders": get_leaders(tv),
            "follow": get_follow(tv),
        })

    n_pos = sum(1 for s in sectors if s["week"] > 0)
    t3 = ", ".join(s["name"] for s in top)
    insight = (f"<b>Auto-Ueberblick:</b> Staerkster Sektor der Woche: "
               f"<b>{ranked[0]['name']}</b> ({fmt_pct(ranked[0]['week'])}). "
               f"{n_pos} von 11 Sektoren positiv. Top-Sektoren fuer die Rotation: {t3}.")

    data = {
        "stand": datetime.datetime.utcnow().strftime("%d.%m.%Y") + " (taeglich nach US-Schluss)",
        "quelle": "TradingView (auto)",
        "insight": insight,
        "sectors": sectors,
        "topN": TOP_N,
        "deep": deep,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("data.json geschrieben. Top-3:", t3)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FEHLER:", e, file=sys.stderr)
        sys.exit(1)
