from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class AuthConfig(BaseSettings):
    google_client_id: str = ""
    google_client_secret: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""

    yaml_file: str = "config/auth.yaml"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="ignore",  # TODO: change to "forbid" in prod
    )

    auth_config: AuthConfig = AuthConfig()

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings, file_secret_settings):
        return (
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
            init_settings,
        )


@lru_cache
def get_config() -> Config:
    return Config()
