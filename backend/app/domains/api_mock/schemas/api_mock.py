"""
API MOCK schemas.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

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
    proxy_base_url: Optional[str] = None
    temp_workspace_path: str
    active_source_version_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiMockProjectUpdate(BaseModel):
    proxy_enabled: Optional[bool] = None
    proxy_base_url: Optional[str] = Field(default=None, max_length=1000)


class ApiMockSourceVersionResponse(BaseModel):
    id: str
    project_id: str
    source_type: ApiMockSourceTypeValue
    source_name: Optional[str] = None
    summary_json: Optional[Dict[str, Any]] = None
    is_active: bool
    creator_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiMockSourceVersionListResponse(BaseModel):
    items: List[ApiMockSourceVersionResponse]
    total: int


class ApiMockEndpointResponse(BaseModel):
    id: str
    project_id: str
    source_version_id: str
    method: str
    path: str
    operation_id: Optional[str] = None
    tag: Optional[str] = None
    summary: Optional[str] = None
    parameters_json: Optional[List[Dict[str, Any]]] = None
    request_schema_json: Optional[Dict[str, Any]] = None
    responses_json: Optional[Dict[str, Any]] = None
    response_schema_json: Optional[Dict[str, Any]] = None
    entity_refs_json: Optional[List[str]] = None
    row_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiMockEndpointListResponse(BaseModel):
    items: List[ApiMockEndpointResponse]
    total: int


class ApiMockEndpointUpdate(BaseModel):
    row_version: int = Field(..., ge=1)
    method: str = Field(..., min_length=1, max_length=16)
    path: str = Field(..., min_length=1, max_length=800)
    operation_id: Optional[str] = Field(default=None, max_length=255)
    tag: Optional[str] = Field(default=None, max_length=255)
    summary: Optional[str] = None
    parameters_json: Optional[List[Dict[str, Any]]] = None
    request_schema_json: Optional[Dict[str, Any]] = None
    responses_json: Optional[Dict[str, Any]] = None
    response_schema_json: Optional[Dict[str, Any]] = None
    entity_refs_json: Optional[List[str]] = None


class ApiMockEntityResponse(BaseModel):
    id: str
    project_id: str
    source_version_id: str
    endpoint_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    schema_data: Dict[str, Any] = Field(validation_alias="schema_json", serialization_alias="schema_json")
    row_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class ApiMockEntityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    schema_data: Dict[str, Any] = Field(default_factory=dict, validation_alias="schema_json")
    endpoint_id: Optional[str] = None


class ApiMockEntityUpdate(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    schema_data: Dict[str, Any] = Field(default_factory=dict, validation_alias="schema_json")
    endpoint_id: Optional[str] = None


class ApiMockEntityListResponse(BaseModel):
    items: List[ApiMockEntityResponse]
    total: int


class ApiMockMockCaseResponse(BaseModel):
    id: str
    project_id: str
    endpoint_id: str
    name: str
    description: Optional[str] = None
    is_default: bool
    sort_order: int
    mode: ApiMockRuleModeValue
    request_path_params_json: Optional[Dict[str, Any]] = None
    request_query_json: Optional[Dict[str, Any]] = None
    request_body_json: Optional[Any] = None
    static_body_json: Optional[Dict[str, Any]] = None
    mockjs_template: Optional[str] = None
    status_code: int
    headers_json: Optional[Dict[str, Any]] = None
    cookies_json: Optional[List[Dict[str, Any]]] = None
    delay_ms: int
    enabled: bool
    updated_by: str
    row_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiMockMockCaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_default: bool = False
    sort_order: Optional[int] = Field(default=None, ge=0)
    mode: ApiMockRuleModeValue = "STATIC"
    request_path_params_json: Optional[Dict[str, Any]] = None
    request_query_json: Optional[Dict[str, Any]] = None
    request_body_json: Optional[Any] = None
    static_body_json: Optional[Dict[str, Any]] = None
    mockjs_template: Optional[str] = None
    status_code: int = Field(default=200, ge=100, le=599)
    headers_json: Optional[Dict[str, Any]] = None
    cookies_json: Optional[List[Dict[str, Any]]] = None
    delay_ms: int = Field(default=0, ge=0, le=60000)
    enabled: bool = True


class ApiMockMockCaseUpdate(BaseModel):
    row_version: Optional[int] = Field(default=None, ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_default: bool = False
    sort_order: Optional[int] = Field(default=None, ge=0)
    mode: ApiMockRuleModeValue = "STATIC"
    request_path_params_json: Optional[Dict[str, Any]] = None
    request_query_json: Optional[Dict[str, Any]] = None
    request_body_json: Optional[Any] = None
    static_body_json: Optional[Dict[str, Any]] = None
    mockjs_template: Optional[str] = None
    status_code: int = Field(default=200, ge=100, le=599)
    headers_json: Optional[Dict[str, Any]] = None
    cookies_json: Optional[List[Dict[str, Any]]] = None
    delay_ms: int = Field(default=0, ge=0, le=60000)
    enabled: bool = True


class ApiMockMockCaseListResponse(BaseModel):
    items: List[ApiMockMockCaseResponse]
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
    source_version_id: Optional[str] = None
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
    message: Optional[str] = None
    result_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiMockJobListResponse(BaseModel):
    items: List[ApiMockJobResponse]
    total: int


class ApiMockSwaggerImportRequest(BaseModel):
    source_name: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[HttpUrl] = None
    raw_content: Optional[str] = None


class ApiMockPreviewRequest(BaseModel):
    endpoint_id: str
    mock_case_id: Optional[str] = None
    method: str = Field(..., min_length=1, max_length=16)
    path: str = Field(..., min_length=1, max_length=800)
    query: Optional[Dict[str, Any]] = None
    body: Optional[Any] = None
    headers: Optional[Dict[str, str]] = None


class ApiMockPreviewResponse(BaseModel):
    mode: ApiMockRuleModeValue
    status_code: int
    headers: Dict[str, Any]
    cookies: List[Dict[str, Any]]
    body: Any
    latency_ms: int
    restc_command: Optional[str] = None


class ApiMockActivateSourceRequest(BaseModel):
    source_version_id: str = Field(..., min_length=1)


class ApiMockDocumentResponse(BaseModel):
    project_id: str
    source_version_id: str
    source_type: ApiMockSourceTypeValue
    source_name: Optional[str] = None
    content: str
    created_at: datetime


class ApiMockDocumentUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class ApiMockCollabEventCreate(BaseModel):
    endpoint_id: Optional[str] = None
    event_type: Literal["DRAFT", "SAVE", "CONFLICT", "PRESENCE"]
    payload: Optional[Dict[str, Any]] = None


class ApiMockCollabEventResponse(BaseModel):
    id: str
    project_id: str
    endpoint_id: Optional[str] = None
    user_id: str
    event_type: Literal["DRAFT", "SAVE", "CONFLICT", "PRESENCE"]
    payload_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiMockCollabEventListResponse(BaseModel):
    items: List[ApiMockCollabEventResponse]
    total: int
