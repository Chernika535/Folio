#!/usr/bin/env python3
"""Build a static, best-effort article index from publishers' public RSS feeds."""
import concurrent.futures, datetime, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests, feedparser
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent.parent
html=(ROOT/"index.html").read_text(encoding="utf-8")
sources=[]
for label,country in (("foreign","Зарубежные"),("russian","Российские")):
    match=re.search(r"const "+label+r"=(\[.*?\]);",html,re.S)
    if not match: raise RuntimeError("Catalog missing: "+label)
    for name,site,cat in json.loads(match.group(1)):
        sources.append((name,site,country))
session=requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (compatible; FolioFeedIndex/1.0; +https://github.com/Chernika535/Folio)","Accept":"application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
OVERRIDES={
 "theatlantic.com":["https://www.theatlantic.com/feed/all/"],
 "wired.com":["https://www.wired.com/feed/rss"],
 "aeon.co":["https://aeon.co/feed.rss"],
 "thenewhumanitarian.org":["https://www.thenewhumanitarian.org/rss.xml"],
 "daily.afisha.ru":["https://daily.afisha.ru/rss/"],
 "theblueprint.ru":["https://theblueprint.ru/rss"],
 "knife.media":["https://knife.media/feed/"],
 "snob.ru":["https://snob.ru/rss/"],
 "gq.com":["https://www.gq.com/feed/rss"],
 "rollingstone.com":["https://www.rollingstone.com/feed/"],
 "vulture.com":["https://www.vulture.com/rss/index.xml"],
 "variety.com":["https://variety.com/feed/"],
 "hollywoodreporter.com":["https://www.hollywoodreporter.com/feed/"],
 "technologyreview.com":["https://www.technologyreview.com/feed/"],
 "frieze.com":["https://www.frieze.com/rss.xml"],
 "hypebeast.com":["https://hypebeast.com/feed"],
 "highsnobiety.com":["https://www.highsnobiety.com/feed/"],
 "mel.fm":["https://mel.fm/rss"],
 "reminder.media":["https://reminder.media/rss"],
 "sobaka.ru":["https://www.sobaka.ru/rss"],
}
def text(html):
    return BeautifulSoup(str(html or ""),"html.parser").get_text(" ",strip=True)[:320]
def fetch_one(src):
    name,site,country=src
    host="https://"+site
    candidates=OVERRIDES.get(site,[])+[host+"/feed/",host+"/rss/",host+"/rss.xml",host+"/feed",host+"/atom.xml"]
    seen=set()
    for url in candidates:
        if url in seen: continue
        seen.add(url)
        try:
            response=session.get(url,timeout=9,allow_redirects=True)
            if response.status_code!=200 or len(response.content)>3_000_000: continue
            parsed=feedparser.parse(response.content)
            if not parsed.entries: continue
            rows=[]
            for entry in parsed.entries[:12]:
                link=entry.get("link","")
                if not link.startswith("https://") and not link.startswith("http://"): continue
                title=text(entry.get("title",""))
                if not title: continue
                img=""
                media=entry.get("media_thumbnail") or entry.get("media_content") or []
                if media: img=media[0].get("url","")
                if not img:
                    for l in entry.get("links",[]):
                        if l.get("type","").startswith("image/"): img=l.get("href","");break
                desc=text(entry.get("summary",""))
                rows.append({"title":title,"link":link,"mag":name,"description":desc,"date":entry.get("published",entry.get("updated","")),"image":img if img.startswith("https://") else "","access":"unknown"})
            if rows: return rows
        except (requests.RequestException,ValueError,Exception):
            continue
    return []
def main():
    items=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for batch in pool.map(fetch_one,sources):
            items.extend(batch)
    seen=set();unique=[]
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"]);unique.append(item)
    payload={"updated":datetime.datetime.now(datetime.timezone.utc).isoformat(),"sources_total":len(sources),"sources_with_articles":len(set(x["mag"] for x in unique)),"items":unique}
    (ROOT/"articles.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Indexed",len(unique),"articles from",payload["sources_with_articles"],"of",len(sources),"sources")
if __name__=="__main__":main()
