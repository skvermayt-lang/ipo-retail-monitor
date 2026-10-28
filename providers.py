"""Public HTML adapters. Missing stays missing; publisher time != fetch time."""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

IST = timezone(timedelta(hours=5, minutes=30), "IST")
IG_GMP = "https://www.investorgain.com/report/ipo-gmp-live/331/"
IG_SUB = "https://www.investorgain.com/report/ipo-subscription-live/333/"
IW_GMP = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"

class DataError(Exception):
    pass

def fetch(url):
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in {"www.investorgain.com", "ipowatch.in"}:
        raise DataError("Unexpected data-source URL")
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
        with urlopen(request, timeout=25) as response:
            return response.read(4_000_000).decode("utf-8")
    except Exception:
        raise DataError(f"Public source unavailable: {urlparse(url).hostname}") from None

def text(node):
    return node.get_text(" ", strip=True)

def number(value):
    cleaned = value.replace(",", "").replace("₹", "").strip()
    match = re.match(r"^(-?\d+(?:\.\d+)?)(?:\s|x|%|$)", cleaned, re.I)
    return float(match[1]) if match else None

def name_key(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())

def dated(value, now, formats):
    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value)
    for fmt in formats:
        candidates = []
        for year in [now.year - 1, now.year, now.year + 1]:
            try:
                candidates.append(datetime.strptime(f"{value} {year}", fmt + " %Y").replace(tzinfo=IST))
            except ValueError:
                pass
        if candidates:
            candidate = min(candidates, key=lambda c: abs((c - now).total_seconds()))
            if abs((candidate.date() - now.date()).days) <= 180:
                return candidate
    return None

def ig_rows(html, required):
    table = BeautifulSoup(html, "html.parser").select_one("#reportTable")
    if not table:
        raise DataError("InvestorGain report table missing; parser needs review")
    rows = []
    for row in table.select("tr"):
        cells = {c.get("data-label"): c for c in row.select("td[data-label]")}
        if not cells:
            continue
        if not required.issubset(cells):
            raise DataError("InvestorGain columns changed; parser needs review")
        rows.append(cells)
    if not rows:
        raise DataError("InvestorGain returned an empty report")
    return rows

def identity(cell):
    link = cell.select_one("a[href]")
    match = re.search(r"/(\d+)/?$", link["href"]) if link else None
    if not match:
        raise DataError("Stable issuer ID missing")
    return "ig:" + match[1], text(link), urljoin(IG_GMP, link["href"])

def parse_ig_gmp(html, now):
    result, seen = [], set()
    for c in ig_rows(html, {"Name", "GMP", "Price (₹)", "Lot", "Close", "Updated-On"}):
        badges = [text(x) for x in c["Name"].select(".badge")]
        if any("SME" in b.upper() for b in badges):
            continue
        if "IPO" not in badges:
            raise DataError("Unrecognized segment; refusing to assume mainboard")
        key, name, url = identity(c["Name"])
        if key in seen:
            raise DataError("Duplicate primary issuer ID")
        seen.add(key)
        close = dated(next(c["Close"].stripped_strings, ""), now, ["%d-%b"])
        if close is None:
            raise DataError("Cannot read mainboard closing date")
        lot = number(text(c["Lot"]))
        result.append(dict(key=key, name=name, close_date=close.date().isoformat(),
                           price=number(text(c["Price (₹)"])), lot=int(lot) if lot and lot.is_integer() else None,
                           gmp=number(text(c["GMP"])), gmp_at=dated(text(c["Updated-On"]), now, ["%d-%b %H:%M"]),
                           gmp_url=url, segment="mainboard"))
    return result

def parse_ig_subscription(html, now):
    result = {}
    for c in ig_rows(html, {"Name", "Total", "QIB", "NII", "RII", "Closing Date", "IPO Price"}):
        key, _, url = identity(c["Name"])
        stamp = c["Total"].select_one("small")
        try:
            close = datetime.strptime(text(c["Closing Date"]), "%d-%m-%Y").date().isoformat()
        except ValueError:
            raise DataError("Cannot read subscription closing date") from None
        value = dict(qib=number(text(c["QIB"])), nii=number(text(c["NII"])), retail=number(text(c["RII"])),
                     total=number(next(c["Total"].stripped_strings, "")),
                     subscription_at=dated(text(stamp), now, ["%d %b %H:%M"]) if stamp else None,
                     subscription_close=close, subscription_price=number(text(c["IPO Price"])), subscription_url=url)
        if key in result and result[key] != value:
            raise DataError("Conflicting subscription rows")
        result[key] = value
    return result

def parse_iw_index(html):
    table = BeautifulSoup(html, "html.parser").select_one("#tablepress-21")
    if not table or "Company" not in text(table) or "GMP" not in text(table):
        raise DataError("IPO Watch mainboard table changed")
    result = {}
    for row in table.select("tr"):
        cells = row.select("td")
        if len(cells) < 6:
            continue
        link = cells[0].select_one("a[href]")
        if link:
            key = name_key(text(link))
            if key in result:
                raise DataError("Duplicate secondary issuer name")
            result[key] = dict(url=urljoin(IW_GMP, link["href"]), price=number(text(cells[3])))
    if not result:
        raise DataError("IPO Watch mainboard list empty")
    return result

def parse_iw_detail(html, now):
    soup = BeautifulSoup(html, "html.parser")
    quotes, close = [], None
    for table in soup.select("table"):
        rows = table.select("tr")
        header = [text(c) for c in rows[0].select("td,th")] if rows else []
        if header[:2] == ["Date", "IPO GMP"]:
            for row in rows[1:]:
                cells = row.select("td")
                if len(cells) < 5:
                    continue
                at = dated(text(cells[0]) + " " + text(cells[4]), now, ["%d %B %H:%M", "%d %b %H:%M"])
                value = number(text(cells[1]))
                if at and value is not None:
                    quotes.append((at, value))
        for row in rows:
            cells = row.select("td")
            if len(cells) == 2 and text(cells[0]) == "IPO Close Date":
                try:
                    close = datetime.strptime(text(cells[1]), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
    quotes.sort(reverse=True)
    latest = quotes[0] if quotes else (None, None)
    prior = next((q for q in quotes[1:] if q[0].date() < latest[0].date()), None) if quotes else None
    return dict(secondary_at=latest[0], secondary_gmp=latest[1], previous_gmp=prior[1] if prior else None,
                previous_at=prior[0] if prior else None, secondary_close=close)

def collect(now, aliases, get=fetch):
    issues = parse_ig_gmp(get(IG_GMP), now)
    today = [i for i in issues if i["close_date"] == now.date().isoformat()]
    if not today:
        return [], []
    errors = []
    try:
        subs = parse_ig_subscription(get(IG_SUB), now)
    except DataError as e:
        subs = {}; errors.append(str(e))
    try:
        index = parse_iw_index(get(IW_GMP))
    except DataError as e:
        index = {}; errors.append(str(e))
    for issue in today:
        issue.update(subs.get(issue["key"], {}))
        secondary = index.get(name_key(aliases.get(issue["name"], issue["name"])))
        if secondary:
            issue["secondary_url"] = secondary["url"]
            issue["secondary_price"] = secondary["price"]
            try:
                issue.update(parse_iw_detail(get(secondary["url"]), now))
            except DataError as e:
                errors.append(str(e))
    return today, errors
