import requests
from bs4 import BeautifulSoup
import re

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

url = "http://www.cssc.net.cn/n5/n18/index.html"
resp = session.get(url)
resp.encoding = resp.apparent_encoding
soup = BeautifulSoup(resp.text, "lxml")

# 看 pag_164 原始内容
pag = soup.select_one("#pag_164, td.pages")
print("pag tag:", pag)
print()

# 看所有 script 内容里有没有 totalPage
for s in soup.find_all("script"):
    t = s.string or ""
    if any(k in t for k in ["totalPage", "pageCount", "total_page", "page"]):
        print("script hit:", t[:300])
        print()