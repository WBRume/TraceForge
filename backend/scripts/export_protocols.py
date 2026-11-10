"""Generate shared JSON Schema and the DSH tool manifest from Python contracts."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import TypeAdapter

from app.domains.ai.schemas.job_result import JobCompletion
from app.domains.ai.schemas.queue import QueueJobActionResponse, QueueJobCommand
from app.domains.api_mock.schemas.api_mock import ApiMockJobResponse
from app.domains.diagnosis_playbook.tool_server import TOOLS
from app.protocols.agent_events import AGENT_EVENT
from app.protocols.base import JSON_SCHEMA_DIALECT
from app.protocols.messages import APPLICATION_MESSAGE, RoomEnvelope, TerminalRecord
from app.protocols.resources import RESOURCE_COMMAND, RESOURCE_RESULTS, RESULT_ACTIONS, OperationReceipt
from app.protocols.tools import SUBMISSION_REPLY, WORKSPACE_REPLY


def schemas():
    adapters = {
        "applicationMessage": APPLICATION_MESSAGE,
        "roomEnvelope": TypeAdapter(RoomEnvelope),
        "terminalRecord": TypeAdapter(TerminalRecord),
        "jobCompletion": TypeAdapter(JobCompletion),
        "apiMockJob": TypeAdapter(ApiMockJobResponse),
        "queueJobCommand": TypeAdapter(QueueJobCommand),
        "queueJobActionResponse": TypeAdapter(QueueJobActionResponse),
        "agentEvent": AGENT_EVENT,
        "resourceCommand": RESOURCE_COMMAND,
        "operationReceipt": TypeAdapter(OperationReceipt),
        "submissionReply": SUBMISSION_REPLY,
        "workspaceReply": WORKSPACE_REPLY,
        **{
            "resourceResult_" + key.replace(":", "_"): TypeAdapter(value)
            for key, value in (RESOURCE_RESULTS | RESULT_ACTIONS).items()
        },
    }
    return {name: {"$schema": JSON_SCHEMA_DIALECT, **adapter.json_schema()} for name, adapter in adapters.items()}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    destination = root / "frontend/shared/contracts/schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (destination / (name + ".json")).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    dsh_tools = root / "integrations/dsh-playbook/tools.json"
    dsh_tools.write_text(json.dumps(TOOLS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
