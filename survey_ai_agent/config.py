"""运行期配置。优先级：系统环境变量 > .env > 默认值。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 配置文件固定为项目根目录下的 .env（绝对路径，避免从其他目录启动时读不到）。
CONFIG_FILE = Path(__file__).resolve().with_name(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SURVEY_AI_",
        env_file=str(CONFIG_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "survey-ai-agent"
    host: str = "127.0.0.1"
    port: int = 8790
    log_level: str = "INFO"
    max_questions: int = 500

    # ---- 模型 ----
    llm_mode: Literal["deepseek", "mock", "auto"] = "deepseek"
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SURVEY_AI_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices(
            "SURVEY_AI_DEEPSEEK_BASE_URL",
            "DEEPSEEK_BASE_URL",
        ),
    )
    # 默认是 DeepSeek 的 API 模型别名；如需固定版本，请填服务商提供的版本化模型 ID。
    deepseek_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices(
            "SURVEY_AI_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
        ),
    )
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---- MySQL / MariaDB（默认与 survey_bg_manage 共用）----
    db_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("SURVEY_AI_DB_HOST", "SB_DB_HOST"),
    )
    db_port: int = Field(
        default=3306,
        validation_alias=AliasChoices("SURVEY_AI_DB_PORT", "SB_DB_PORT"),
    )
    db_user: str = Field(
        default="root",
        validation_alias=AliasChoices("SURVEY_AI_DB_USER", "SB_DB_USER"),
    )
    db_password: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("SURVEY_AI_DB_PASSWORD", "SB_DB_PASSWORD"),
    )
    db_name: str = Field(
        default="survey_bg_manage",
        validation_alias=AliasChoices("SURVEY_AI_DB_NAME", "SB_DB_NAME"),
    )
    db_auto_init: bool = True

    @property
    def config_file(self) -> str:
        return str(CONFIG_FILE)

    @property
    def deepseek_key(self) -> str | None:
        if self.deepseek_api_key is None:
            return None
        value = self.deepseek_api_key.get_secret_value().strip()
        return value or None

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_key)

    @property
    def effective_llm_mode(self) -> Literal["deepseek", "mock"]:
        if self.llm_mode == "auto":
            return "deepseek" if self.deepseek_configured else "mock"
        return self.llm_mode
