from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Municipality Address Check"
    db_url: str = "sqlite:///./municipality_check.db"

    municipalities_dir: str = "./data/municipalities"
    nsc_regions_dir: str = "./data/nsc_regions"
    mpr_regions_dir: str = "./data/mpr_regions"
    custom_regions_dir: str = "./data/custom_regions"

    # Live refresh security
    # If empty, admin refresh endpoints are disabled.
    admin_token: str = ""

    # Optional ArcGIS layer URLs (used by scripts.fetch_datasets and /api/admin/refresh-datasets).
    # Provide FULL layer endpoints (ending in /<layerId>), e.g.
    #   https://.../FeatureServer/0
    #   https://.../MapServer/28
    ethekwini_municipal_layer_url: str = ""
    ethekwini_nsc_layer_url: str = ""
    ethekwini_mpr_layer_url: str = ""

    # Geocoding (optional)
    allow_nominatim: bool = True
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "municipality-address-check/1.0 (contact: you@example.com)"
    request_timeout_s: float = 20.0

    model_config = SettingsConfigDict(env_prefix="MAC_", env_file=".env", extra="ignore")


settings = Settings()
