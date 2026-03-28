"""
Pydantic 数据模型：流水线每一步输入/输出的统一契约。
RawArticle  → 采集器输出的原始条目
CleanedItem → 清洗+去重后的标准条目
EnrichedItem → AI结构化提取后的完整条目（可直接写CSV/推送Java）
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class RawArticle(BaseModel):
    """采集器输出的原始条目，字段宽松，允许None"""
    source: str                          # 来源标识，如 "csic" / "gov_policy"
    url: str
    title: Optional[str] = None
    content: Optional[str] = None       # 正文（可能很长）
    pub_time: Optional[datetime] = None
    img_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    raw_location: Optional[str] = None  # 文本中识别到的地名，待编码
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


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
    """AI提取后的完整条目，对应数据库字段"""
    # 基础信息（来自 CleanedItem）
    source: str
    url: str
    title: str
    pub_time: Optional[datetime] = None
    fetched_at: datetime

    # AI 结构化提取字段（对应 device 表）
    company_name: Optional[str] = None      # 企业名称
    country: Optional[str] = None           # 国家/地区
    level1_category: Optional[str] = None   # 1级分类（行业动态/基础设施/典型案例）
    level2_category: Optional[str] = None   # 2级分类
    level3_category: Optional[str] = None   # 3级具体方向
    invest_cost: Optional[str] = None       # 投入成本
    use_year: Optional[int] = None          # 投产/实施年份
    effect_description: Optional[str] = None  # 转型效果描述
    tech_keywords: list[str] = Field(default_factory=list)  # 技术关键词

    # 地理编码
    location_name: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None

    # 媒体文件（本地路径，下载后填写）
    local_img_paths: list[str] = Field(default_factory=list)
    local_video_paths: list[str] = Field(default_factory=list)

    # 内容
    content_summary: Optional[str] = None  # AI摘要（200字以内）
    original_url: str = ""