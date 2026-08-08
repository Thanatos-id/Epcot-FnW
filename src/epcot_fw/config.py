from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/epcot_fw"
    test_database_url: str = "postgresql+psycopg://localhost:5432/epcot_fw_test"
    # No default on purpose: the crawler's User-Agent must identify a real,
    # working contact per responsible-scraping etiquette. Set this in your
    # local .env (gitignored) - see .env.example.
    user_agent_contact: str
    log_level: str = "INFO"

    @property
    def user_agent(self) -> str:
        return (
            "EpcotFoodWineResearchBot/0.1 "
            f"(personal, non-commercial research; contact: {self.user_agent_contact})"
        )


settings = Settings()
