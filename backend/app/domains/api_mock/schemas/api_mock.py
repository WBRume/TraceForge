"""
API MOCK schemas.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

ApiMockSourceTypeValue = Literal["CODE_ANALYSIS", "SWAGGER_IMPORT", "CLAUDE_SYNC"]
ApiMockRuleModeValue = Literal["STATIC", "MOCKJS", "PROXY"]
ApiMockJobStatusValue = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]


class ApiMockProjectResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    creator_id: str
    proxy_enabled: bool
    proxy_base_url: str | None = None
    temp_workspace_path: str
    active_source_version_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiMockProjectUpdate(BaseModel):
    proxy_enabled: bool | None = None
    proxy_base_url: str | None = Field(default=None, max_length=1000)


class ApiMockSourceVersionResponse(BaseModel):
    id: str
    project_id: str
    source_type: ApiMockSourceTypeValue
    source_name: str | None = None
    summary_json: dict[str, Any] | None = None
    is_active: bool
    creator_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiMockSourceVersionListResponse(BaseModel):
    items: list[ApiMockSourceVersionResponse]
    total: int


class ApiMockEndpointResponse(BaseModel):
    id: str
    project_id: str
    source_version_id: str
    method: str
    path: str
    operation_id: str | None = None
    tag: str | None = None
    summary: str | None = None
    parameters_json: list[dict[str, Any]] | None = None
    request_schema_json: dict[str, Any] | None = None
    responses_json: dict[str, Any] | None = None
    response_schema_json: dict[str, Any] | None = None
    entity_refs_json: list[str] | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiMockEndpointListResponse(BaseModel):
    items: list[ApiMockEndpointResponse]
    total: int


class ApiMockEndpointUpdate(BaseModel):
    row_version: int = Field(..., ge=1)
    method: str = Field(..., min_length=1, max_length=16)
    path: str = Field(..., min_length=1, max_length=800)
    operation_id: str | None = Field(default=None, max_length=255)
    tag: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    parameters_json: list[dict[str, Any]] | None = None
    request_schema_json: dict[str, Any] | None = None
    responses_json: dict[str, Any] | None = None
    response_schema_json: dict[str, Any] | None = None
    entity_refs_json: list[str] | None = None


class ApiMockEntityResponse(BaseModel):
    id: str
    project_id: str
    source_version_id: str
    endpoint_id: str | None = None
    name: str
    description: str | None = None
    schema_data: dict[str, Any] = Field(validation_alias="schema_json", serialization_alias="schema_json")
    row_version: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class ApiMockEntityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    schema_data: dict[str, Any] = Field(default_factory=dict, validation_alias="schema_json")
    endpoint_id: str | None = None


class ApiMockEntityUpdate(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    schema_data: dict[str, Any] = Field(default_factory=dict, validation_alias="schema_json")
    endpoint_id: str | None = None


class ApiMockEntityListResponse(BaseModel):
    items: list[ApiMockEntityResponse]
    total: int


class ApiMockMockCaseResponse(BaseModel):
    id: str
    project_id: str
    endpoint_id: str
    name: str
    description: str | None = None
    is_default: bool
    sort_order: int
    mode: ApiMockRuleModeValue
    request_path_params_json: dict[str, Any] | None = None
    request_query_json: dict[str, Any] | None = None
    request_body_json: Any | None = None
    static_body_json: dict[str, Any] | None = None
    mockjs_template: str | None = None
    status_code: int
    headers_json: dict[str, Any] | None = None
    cookies_json: list[dict[str, Any]] | None = None
    delay_ms: int
    enabled: bool
    updated_by: str
    row_version: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiMockMockCaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_default: bool = False
    sort_order: int | None = Field(default=None, ge=0)
    mode: ApiMockRuleModeValue = "STATIC"
    request_path_params_json: dict[str, Any] | None = None
    request_query_json: dict[str, Any] | None = None
    request_body_json: Any | None = None
    static_body_json: dict[str, Any] | None = None
    mockjs_template: str | None = None
    status_code: int = Field(default=200, ge=100, le=599)
    headers_json: dict[str, Any] | None = None
    cookies_json: list[dict[str, Any]] | None = None
    delay_ms: int = Field(default=0, ge=0, le=60000)
    enabled: bool = True


class ApiMockMockCaseUpdate(BaseModel):
    row_version: int | None = Field(default=None, ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_default: bool = False
    sort_order: int | None = Field(default=None, ge=0)
    mode: ApiMockRuleModeValue = "STATIC"
    request_path_params_json: dict[str, Any] | None = None
    request_query_json: dict[str, Any] | None = None
    request_body_json: Any | None = None
    static_body_json: dict[str, Any] | None = None
    mockjs_template: str | None = None
    status_code: int = Field(default=200, ge=100, le=599)
    headers_json: dict[str, Any] | None = None
    cookies_json: list[dict[str, Any]] | None = None
    delay_ms: int = Field(default=0, ge=0, le=60000)
    enabled: bool = True


class ApiMockMockCaseListResponse(BaseModel):
    items: list[ApiMockMockCaseResponse]
    total: int


class ApiMockSyncStartResponse(BaseModel):
    job_id: str
    project_id: str
    status: ApiMockJobStatusValue
    message: str


class ApiMockContextResponse(BaseModel):
    project_id: str
    workspace_id: str
    task_id: str
    source_version_id: str | None = None
    mock_base_url: str
    endpoint_count: int
    endpoints_with_mock_cases: int
    endpoints_without_mock_cases: int
    mock_case_count: int


class ApiMockJobResponse(BaseModel):
    id: str
    project_id: str
    creator_id: str
    job_type: str
    status: ApiMockJobStatusValue
    progress: int
    message: str | None = None
    result_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiMockJobListResponse(BaseModel):
    items: list[ApiMockJobResponse]
    total: int


class ApiMockSwaggerImportRequest(BaseModel):
    source_name: str | None = Field(default=None, max_length=500)
    source_url: HttpUrl | None = None
    raw_content: str | None = None


class ApiMockPreviewRequest(BaseModel):
    endpoint_id: str
    mock_case_id: str | None = None
    method: str = Field(..., min_length=1, max_length=16)
    path: str = Field(..., min_length=1, max_length=800)
    query: dict[str, Any] | None = None
    body: Any | None = None
    headers: dict[str, str] | None = None


class ApiMockPreviewResponse(BaseModel):
    mode: ApiMockRuleModeValue
    status_code: int
    headers: dict[str, Any]
    cookies: list[dict[str, Any]]
    body: Any
    latency_ms: int
    restc_command: str | None = None


class ApiMockActivateSourceRequest(BaseModel):
    source_version_id: str = Field(..., min_length=1)


class ApiMockDocumentResponse(BaseModel):
    project_id: str
    source_version_id: str
    source_type: ApiMockSourceTypeValue
    source_name: str | None = None
    content: str
    created_at: datetime


class ApiMockDocumentUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class ApiMockCollabEventCreate(BaseModel):
    endpoint_id: str | None = None
    event_type: Literal["DRAFT", "SAVE", "CONFLICT", "PRESENCE"]
    payload: dict[str, Any] | None = None


class ApiMockCollabEventResponse(BaseModel):
    id: str
    project_id: str
    endpoint_id: str | None = None
    user_id: str
    event_type: Literal["DRAFT", "SAVE", "CONFLICT", "PRESENCE"]
    payload_json: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiMockCollabEventListResponse(BaseModel):
    items: list[ApiMockCollabEventResponse]
    total: int
