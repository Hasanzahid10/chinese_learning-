from pathlib import  Path
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,

)

App_dir = Path(__file__).resolve().parent
BACKEND_DIR = App_dir.parent.parent
ENV_FILE =BACKEND_DIR / '.env'

class Settings(BaseSettings):

    ollama_url: str = (
        "http://127.0.0.1:11434"
    )

    ollama_model: str = "qwen2.5vl:3b"

    django_url: str = (
        "http://127.0.0.1:8000"
    )

    ai_internal_key: str
    django_jwt_secret_key: str

    model_config = SettingsConfigDict(
        env_file= ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
