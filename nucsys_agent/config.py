from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class OpenAIConfig(BaseSettings):
    api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    timeout_s: float = 60.0

    model_config = SettingsConfigDict(extra="ignore")

class AgentConfig(BaseSettings):
    # Resource overrides (normally not needed; package resources are used)
    ontology_path: str | None = Field(default=None, validation_alias="NUCSYS_ONTOLOGY_PATH")
    cards_dir: str | None = Field(default=None, validation_alias="NUCSYS_CARDS_DIR")

    # Primary loop defaults
    default_primary_deltaT_K: float = 30.0
    default_primary_pressure_MPa: float = 15.5
    default_primary_hot_leg_C: float = 320.0

    # Secondary / Rankine defaults
    default_secondary_pressure_MPa: float = 6.5
    default_condenser_pressure_MPa: float = 0.01
    default_secondary_feedwater_C: float = 220.0
    default_secondary_steam_C: float = 280.0

    # Equipment defaults
    default_turbine_isentropic_efficiency: float = 0.87
    default_pump_efficiency: float = 0.83

    # Optimization weights
    w_pump: float = 1.0
    w_UA: float = 2e-4  # scales UA(W/K) into comparable magnitude with pump power

    # Optional OpenAI parsing config (disabled if api_key missing)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)

    model_config = SettingsConfigDict(extra="ignore")
