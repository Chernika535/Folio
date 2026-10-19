#!/usr/bin/env python3
"""Build Folio's structured article index from publisher pages and sitemaps.

No RSS dependency, no paywall bypass. Only public pages are requested.
"""
import concurrent.futures
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
import trafilatura
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent.parent
html=(ROOT/"index.html").read_text(encoding="utf-8")
sources=[]
for label in ("foreign","russian"):
    match=re.search(r"const "+label+r"=(\[.*?\]);",html,re.S)
    if not match: raise RuntimeError("Missing catalog "+label)
    sources.extend(json.loads(match.group(1)))
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; FolioIndexer/2.0; +https://github.com/Chernika535/Folio)"}
SKIP=re.compile(r"/(?:tag|tags|topic|topics|category|categories|author|authors|search|subscribe|account|login|privacy|terms|video|videos|podcast|newsletter|about|contact|shop|store|events|archive|magazine/backissues)(?:/|$)|\.(?:pdf|jpg|png|gif|webp|svg)$",re.I)
def get(url):
    try:
        r=requests.get(url,headers=HEADERS,timeout=10,allow_redirects=True)
        if r.ok and len(r.content)<3_000_000 and urlparse(r.url).scheme=="https":
            return r.text
    except requests.RequestException: pass
    return ""
def same_host(url,site):
    host=(urlparse(url).hostname or "").lower().removeprefix("www.")
    site=site.lower().removeprefix("www.")
    return host==site or host.endswith("."+site)
def links_from_xml(text,site):
    try: root=ET.fromstring(text)
    except ET.ParseError: return [],[]
    locs=[(x.text or "").strip() for x in root.iter() if x.tag.rsplit("}",1)[-1]=="loc"]
    locs=[u for u in locs if u.startswith("https://") and same_host(u,site)]
    return [u for u in locs if u.endswith(".xml") or "sitemap" in u.lower()], [u for u in locs if not u.endswith(".xml") and not SKIP.search(u)]
def discover(site):
    base="https://"+site
    found=[]
    home=get(base)
    if home:
        soup=BeautifulSoup(home,"html.parser")
        for a in soup.select("main a[href],article a[href],a[href]"):
            u=urljoin(base,a.get("href","")).split("#")[0]
            if u.startswith("https://") and same_host(u,site) and not SKIP.search(u) and len(urlparse(u).path.strip("/").split("/"))>=2:
                found.append(u)
            if len(found)>=35: break
    todo=[base+"/sitemap.xml",base+"/sitemap_index.xml",base+"/news-sitemap.xml"]
    visited=set()
    for _ in range(4):
        if not todo:break
        url=todo.pop(0)
        if url in visited:continue
        visited.add(url)
        xml=get(url)
        nested,urls=links_from_xml(xml,site)
        found.extend(urls[-35:])
        todo.extend(u for u in nested[:4] if u not in visited)
        if len(found)>65:break
    return list(dict.fromkeys(found))[-45:]
def meta_image(soup,url):
    for key in ("og:image","twitter:image"):
        tag=soup.find("meta",attrs={"property":key}) or soup.find("meta",attrs={"name":key})
        if tag and tag.get("content","").startswith("https://"):return tag["content"]
    return ""
def extract_article(url,name):
    page=get(url)
    if not page:return None
    soup=BeautifulSoup(page,"html.parser")
    if soup.find("meta",attrs={"name":"robots","content":re.compile("noindex",re.I)}):return None
    image=meta_image(soup,url)
    try:
        result=trafilatura.extract(page,url=url,output_format="json",with_metadata=True,include_comments=False,include_tables=False,favor_precision=True)
        data=json.loads(result) if result else {}
    except (ValueError,TypeError):return None
    title=(data.get("title") or "").strip()
    body=(data.get("text") or "").strip()
    if len(title)<12 or len(body)<650:return None
    if re.search(r"(subscribe to read|sign in to continue|subscription required|подпишитесь чтобы читать)",body[:900],re.I):return None
    if len(body)>30000:body=body[:30000]
    paras=[p.strip() for p in re.split(r"\n\s*\n|\n",body) if len(p.strip())>25]
    if len(paras)<3:return None
    return {"title":title,"link":url,"mag":name,"description":paras[0][:260],"date":data.get("date") or "","image":image,"author":data.get("author") or "","access":"full","paragraphs":paras,"body":""}
def source_job(source):
    name,site,_=source
    urls=discover(site)
    items=[]
    for u in urls[:10]:
        article=extract_article(u,name)
        if article:items.append(article)
        if len(items)>=5:break
    print(name,":",len(items),"articles from",len(urls),"candidate URLs",flush=True)
    return items
def main():
    items=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        for batch in pool.map(source_job,sources):items.extend(batch)
    seen=set();unique=[]
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"]);unique.append(item)
    old=ROOT/"articles.json"
    if old.exists():
        try:
            previous=json.loads(old.read_text(encoding="utf-8")).get("items",[])
            for x in previous:
                if x.get("link") not in seen and x.get("title"):
                    if not x.get("paragraphs"):x["access"]="preview"
                    unique.append(x);seen.add(x["link"])
        except (ValueError,OSError):pass
    output={"updated":dt.datetime.now(dt.timezone.utc).isoformat(),"engine":"publisher-pages-v2","sources_total":len(sources),"sources_with_articles":len({a["mag"] for a in unique}),"items":unique[:600]}
    old.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Total:",len(unique),"from",output["sources_with_articles"],"publishers")
if __name__=="__main__":main()
