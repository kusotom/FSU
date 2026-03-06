from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FSU Monitoring Platform"
    app_version: str = "0.21"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    secret_key: str = "change_me_to_a_long_random_secret"
    access_token_expire_minutes: int = 60 * 12
    algorithm: str = "HS256"

    database_url: str = "postgresql+psycopg://fsu:fsu123456@127.0.0.1:5432/fsu"
    db_pool_size: int = 60
    db_max_overflow: int = 120
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_pool_pre_ping: bool = True
    ingest_thread_tokens: int = 320
    ingest_mode: str = "queue"
    ingest_queue_maxsize: int = 50000
    ingest_queue_workers: int = 16
    ingest_queue_wait_when_full: bool = True
    ingest_queue_batch_size: int = 200
    ingest_queue_batch_wait_ms: int = 80

    system_rule_eval_enabled: bool = False
    system_rule_eval_interval_seconds: int = 30
    system_rule_inline_enabled: bool = False
    cors_origins: str = "http://localhost:5173"
    auto_create_schema: bool = True
    timescaledb_auto_enable: bool = True

    sms_tencent_enabled: bool = False
    sms_tencent_secret_id: str = ""
    sms_tencent_secret_key: str = ""
    sms_tencent_sdk_app_id: str = ""
    sms_tencent_sign_name: str = ""
    sms_tencent_template_id: str = ""
    sms_tencent_region: str = "ap-guangzhou"
    sms_tencent_template_mode: str = "single_text"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
