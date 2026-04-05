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

class LLMExtractResult(BaseModel):
    is_target_info: bool = Field(default=True)
    device_name: Optional[str] = None
    device_use_year: Optional[int] = None
    device_price: Optional[str] = None
    device_using_unit: Optional[str] = None
    device_location: Optional[str] = None
    device_introduce: Optional[str] = None
    dim1_id: Optional[int] = None
    dim1_name: Optional[str] = None
    dim2_id: Optional[int] = None
    dim2_name: Optional[str] = None
    dim3_id: Optional[int] = None          
    dim3_name: Optional[str] = None
    device_keywords: Optional[str] = None  # 新增：具体技术关键词，逗号分隔
    country_name: Optional[str] = None


class EnrichedItem(BaseModel):
    device_name: str
    device_class_id: Optional[int] = None
    device_style_id: Optional[int] = None
    device_type_id: Optional[int] = None
    device_use_year: Optional[int] = None
    device_price: Optional[str] = None
    device_using_unit: Optional[str] = None
    device_country_id: Optional[int] = None
    device_location: Optional[str] = None
    device_longitude: Optional[str] = None
    device_latitude: Optional[str] = None
    device_img: Optional[str] = None
    device_video: Optional[str] = None
    device_introduce: Optional[str] = None
    device_keywords: Optional[str] = None  # 新增
    device_news_link: str
    device_news_title: str
    device_news_time: Optional[datetime] = None
    device_insql_time: datetime = Field(default_factory=datetime.now)
    device_changesql_time: datetime = Field(default_factory=datetime.now)
    audit_flag: int = Field(default=0)
    deleted: int = Field(default=0)
