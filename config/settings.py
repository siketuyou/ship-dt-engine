"""全局配置：从环境变量或 .env 文件读取，不硬编码密钥"""
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ── 基础 ──────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    DATA_DIR: Path = BASE_DIR / "data"
    STATE_FILE: Path = BASE_DIR / "data" / "state.json"

    # ── HTTP ──────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    REQUEST_DELAY: float = 1.5
    MAX_RETRIES: int = 3
    USER_AGENT: str = (
        "Mozilla/5.0 (compatible; CSIC-Spider/1.0; research-purpose)"
    )

    # ── 采集目标 ───────────────────────────────────
    CSIC_BASE_URL: str = "http://www.cssc.net.cn"
    GOV_POLICY_BASE_URL: str = "https://www.miit.gov.cn"

    # ── AI / Ollama ────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "deepseek-r1:8b"
    OLLAMA_TIMEOUT: int = 120

    # ── 高德地图（必须从.env读取，无默认值） ──────────
    AMAP_KEY: str = ""                        # 无默认值，强制从.env读取
    AMAP_URL: str = "https://restapi.amap.com/v3/geocode/geo"
    # ── Java 后端接口 ──────────────────────────────
    JAVA_API_BASE_URL: str = "http://localhost:8080"
    JAVA_API_TOKEN: str = ""

    # ── 数据库（密码必须从.env读取，无默认值） ────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""                        # 无默认值，强制从.env读取
    DB_NAME: str = "ship_digital_db"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


# 全局单例
settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
# 启动时校验，而不是依赖pydantic强制
if not settings.DB_PASSWORD:
    raise ValueError("DB_PASSWORD未配置，请检查.env文件")
if not settings.AMAP_KEY:
    raise ValueError("AMAP_KEY未配置，请检查.env文件")