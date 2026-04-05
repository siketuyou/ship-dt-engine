import httpx

KEY = "f19a6e08495d1c7f82c76a8e55914a4d"
resp = httpx.get(
    "https://restapi.amap.com/v3/geocode/geo",
    params={"key": KEY, "address": "长城电子", "output": "JSON"}
)
print(resp.json())
# 正常返回: {"status": "1", "geocodes": [{"location": "121.47...,31.23..."}]}