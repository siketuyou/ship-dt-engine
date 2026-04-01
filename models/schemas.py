"""
Pydantic 数据模型：流水线每一步输入/输出的统一契约。
RawArticle  → 采集器输出的原始条目
CleanedItem → 清洗+去重后的标准条目
EnrichedItem → AI结构化提取后的完整条目（可直接写CSV/推送Java）
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl

# --- 新增：对应表 10 关键词表 ---
class KeywordConfig(BaseModel):
    keyword_id: int
    model_id: int
    keyword_name: str
    incremental_spider_time: Optional[datetime] = None
    use_flag: int = 1

# --- 新增：对应表 9 爬虫模型表 ---
class CrawlModel(BaseModel):
    model_id: int
    model_name: str
    target_url: str
    keywords: List[str]
    keyword_ids: List[int]
    watermark: datetime  # 最小水位线
    watermark_id: Optional[int] = None
    
class RawArticle(BaseModel):
    """
    轻量化原始条目：仅记录元数据与指向详情的引用。
    对齐数据库表 9 与表 10。
    """
    model_id: int          # 对应表 9: m_reptile_model_id
    keyword_id: Optional[int] = None
    source: str            # 对应表 9: m_reptile_model_name
    
    url: str               # 列表页中发现的原始跳转链接
    title: Optional[str] = None
    content: Optional[str] = None
    content_url: Optional[str] = None  # 降维后的正文引用地址（通常与 url 一致，或为 API 地址）
    
    pub_time: Optional[datetime] = None
    img_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    
    raw_location: Optional[str] = None  # 文本中初步识别的地名
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    
class FilteredItem(BaseModel):
    """
    一篇通过过滤的文章 + 命中的关键词 id 列表。
    keyword_ids: 在该文章 title/content 中被 AC 自动机命中的关键词 id，
                 可能是模型关键词的子集（部分命中）。
    """
    article: RawArticle
    content: str                       
    matched_keyword_ids: List[int]
 

class CleanedItem(BaseModel):
    """清洗+去重后，字段更收敛"""
    source: str
    url: str
    url_fingerprint: str                # sha256(url)，用于去重
    title: str
    content: str
    pub_time: Optional[datetime] = None
    img_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    raw_location: Optional[str] = None
    fetched_at: datetime


class EnrichedItem(BaseModel):
    """AI提取后的完整条目，深度适配数据库 device 表"""
    # 基础元数据
    source: str
    url: str = Field(..., alias="device_news_link")
    title: str = Field(..., alias="device_news_title")
    pub_time: Optional[datetime] = Field(None, alias="device_news_time")
    fetched_at: datetime = Field(default_factory=datetime.utcnow, alias="device_insql_time")

    # AI 结构化字段 -> 对应 device 表核心字段
    company_name: Optional[str] = Field(None, alias="device_using_unit") # 使用单位
    device_name: Optional[str] = None                                    # 对应 device_name (通常取 title 或主体)
    
    # 映射外键名称 (L8 逻辑中需根据名称查询 ID 或由 AI 直接分类)
    level1_category: str = "行业动态数据"  # 对应 device_class_id 的名称
    level2_category: Optional[str] = None # 对应 device_style_id 的名称
    level3_category: Optional[str] = None # 对应 device_type_id 的名称
    
    country: str = Field("中国", alias="country_name") # 对应 device_country_id 的名称
    
    invest_cost: Optional[str] = Field(None, alias="device_price")
    use_year: Optional[int] = Field(None, alias="device_use_year")
    effect_description: Optional[str] = Field(None, alias="device_introduce") # 详情介绍
    
    # 地理信息
    location_name: Optional[str] = Field(None, alias="device_location")
    longitude: Optional[str] = Field(None, alias="device_longitude")
    latitude: Optional[str] = Field(None, alias="device_latitude")

    # 媒体文件处理后的 URL (由 L8 上传后获得)
    device_img: Optional[str] = None 
    device_video: Optional[str] = None

    class Config:
        populate_by_name = True # 允许使用别名或原始字段名赋值