from pydantic import BaseModel, ConfigDict

CONTRACT_VERSION = 2
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
