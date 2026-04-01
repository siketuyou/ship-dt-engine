"""全局配置：从环境变量或 .env 文件读取，不硬编码密钥"""
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ── 基础 ──────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    DATA_DIR: Path = BASE_DIR / "data"          # CSV / 媒体文件输出根目录
    STATE_FILE: Path = BASE_DIR / "data" / "state.json"  # 增量时间戳存储
    # ── HTTP ──────────────────────────────────────
    REQUEST_TIMEOUT: int = 30                   # 秒
    REQUEST_DELAY: float = 1.5                  # 请求间隔（礼貌延迟）
    MAX_RETRIES: int = 3
    USER_AGENT: str = (
        "Mozilla/5.0 (compatible; CSIC-Spider/1.0; research-purpose)"
    )

    # ── 采集目标（可按需扩展） ─────────────────────
    CSIC_BASE_URL: str = "http://www.cssc.net.cn"
    GOV_POLICY_BASE_URL: str = "https://www.miit.gov.cn"

    # ── AI / Ollama ────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "deepseek-r1:7b"
    OLLAMA_TIMEOUT: int = 120

    # ── 高德地图 GEO API ───────────────────────────
    AMAP_API_KEY: str = ""                      # 从环境变量注入

    # ── Java 后端接口 ──────────────────────────────
    JAVA_API_BASE_URL: str = "http://localhost:8080"
    JAVA_API_TOKEN: str = ""                    # 从环境变量注入

    # ── 数据库配置 (MySQL) ────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "Yxy201062"
    DB_NAME: str = "ship_digital_db"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


# 全局单例
settings = Settings()

# 确保数据目录存在
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)