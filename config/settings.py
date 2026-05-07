"""全局配置：从环境变量或 .env 文件读取，不硬编码密钥"""
from pydantic_settings import BaseSettings
from pathlib import Path
import consul

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
    AMAP_KEY: str = ""
    AMAP_URL: str = "https://restapi.amap.com/v3/geocode/geo"

    # ── Java 后端接口 ──────────────────────────────
    JAVA_API_BASE_URL: str = "http://localhost:8080"
    JAVA_API_TOKEN: str = ""

    # ── 数据库（密码必须从.env读取，无默认值） ────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "ship_digital_db"

    # ── 服务自身 ───────────────────────────────────
    SERVICE_HOST: str = "localhost"   # 注册到 Consul 的对外 IP/域名
    SERVICE_PORT: int = 8000

    # ── CORS（逗号分隔的允许来源列表） ────────────────
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # ── 存储路径 ───────────────────────────────────
    OUTPUT_DIR: str = "data/output"
    UPLOAD_DIR: str = "data/upload"

    # ── Consul ────────────────────────────────────
    CONSUL_HOST: str = "localhost"
    CONSUL_PORT: int = 8500
    CONSUL_KV_PREFIX: str = "config/database"
    USE_CONSUL_CONFIG: bool = False   # 云端默认关闭，使用环境变量直接配置

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def load_from_consul(self):
        """从 Consul KV 加载数据库配置并覆盖当前值"""
        if not self.USE_CONSUL_CONFIG:
            return
        try:
            c = consul.Consul(host=self.CONSUL_HOST, port=self.CONSUL_PORT)
            for key in ["host", "port", "username", "password", "dbname"]:
                full_key = f"{self.CONSUL_KV_PREFIX}/{key}"
                index, data = c.kv.get(full_key)
                if data and data['Value']:
                    value = data['Value'].decode('utf-8')
                    if key == "host":
                        self.DB_HOST = value
                    elif key == "port":
                        self.DB_PORT = int(value)
                    elif key == "username":
                        self.DB_USER = value
                    elif key == "password":
                        self.DB_PASSWORD = value
                    elif key == "dbname":
                        self.DB_NAME = value
            print(f"✓ 从 Consul 加载数据库配置: {self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}")
        except Exception as e:
            print(f"⚠️ 从 Consul 加载配置失败（将使用本地配置）: {e}")


# 全局单例
settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

if not settings.DB_PASSWORD:
    raise ValueError("DB_PASSWORD 未配置，请检查 .env 文件或环境变量")
if not settings.AMAP_KEY:
    raise ValueError("AMAP_KEY 未配置，请检查 .env 文件或环境变量")
