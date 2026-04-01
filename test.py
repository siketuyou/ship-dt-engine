
import requests
from bs4 import BeautifulSoup
import re

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

for url in [
    "http://www.cssc.net.cn/n10/n67/index.html",
    "http://www.cssc.net.cn/n5/n18/index.html",
]:
    resp = session.get(url)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")
    
    has_purl = any("purl" in (s.string or "") for s in soup.find_all("script"))
    has_cookie = any("maxPageNum" in (s.string or "") for s in soup.find_all("script"))
    li_count = len(soup.select("ul.olist_list > li"))
    
    print(f"{url}")
    print(f"  has_purl={has_purl}  has_cookie={has_cookie}  li直接可见={li_count}")
    print()
