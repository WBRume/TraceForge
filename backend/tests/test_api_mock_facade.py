import os
import sys
import unittest
import asyncio
from contextlib import asynccontextmanager
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.services import api_mock_service
import app.domains.api_mock.services.api_mock.auto_mock_service
import app.domains.api_mock.services.api_mock.cli_sync_service

class ApiMockFacadeTest(unittest.TestCase):
    def test_facade_exports(self):
        # We verify that standard functions from sub-modules are successfully imported and exported from the facade
        self.assertTrue(hasattr(api_mock_service, "list_endpoints"))
        self.assertTrue(hasattr(api_mock_service, "get_project_by_task"))
        self.assertTrue(hasattr(api_mock_service, "list_mock_cases_for_endpoint"))
        self.assertTrue(hasattr(api_mock_service, "ensure_project"))
        self.assertTrue(hasattr(api_mock_service, "run_auto_mock_job_background"))
        self.assertTrue(hasattr(api_mock_service, "run_sync_job_background"))
        self.assertTrue(hasattr(api_mock_service, "run_import_job_background"))
        self.assertTrue(hasattr(api_mock_service, "execute_gateway"))
        self.assertTrue(hasattr(api_mock_service, "save_active_document"))
        self.assertTrue(hasattr(api_mock_service, "list_collab_events"))
        
    @mock.patch("app.domains.api_mock.services.api_mock_service.SessionLocal")
    @mock.patch("app.domains.api_mock.services.api_mock_service._clear_cancel_event")
    @mock.patch("app.domains.api_mock.services.api_mock_service.ensure_project")
    def test_run_auto_mock_job_background_wrapper(self, mock_ensure_project, mock_clear_cancel, mock_session_local):
        mock_db = mock.MagicMock()
        mock_session_local.return_value = mock_db
        mock_project = mock.MagicMock()
        mock_ensure_project.return_value = mock_project
        
        with mock.patch("app.domains.api_mock.services.api_mock.auto_mock_service.auto_generate_mock_cases_for_endpoint") as mock_auto:
            api_mock_service.run_auto_mock_job_background(
                job_id="job123",
                workspace_id="ws456",
                task_id="task789",
                user_id="user001",
                endpoint_id="ep0"
            )
            
            mock_auto.assert_called_once_with(
                mock_db,
                mock_project,
                job_id="job123",
                endpoint_id="ep0",
                creator_id="user001"
            )
        
        mock_clear_cancel.assert_called_once_with("job123")
        mock_db.close.assert_called_once()
        
    @mock.patch("app.domains.api_mock.services.api_mock_service.SessionLocal")
    @mock.patch("app.domains.api_mock.services.api_mock_service._clear_cancel_event")
    @mock.patch("app.domains.api_mock.services.api_mock_service.ensure_project")
    def test_run_import_job_background_wrapper(self, mock_ensure_project, mock_clear_cancel, mock_session_local):
        mock_db = mock.MagicMock()
        mock_session_local.return_value = mock_db
        mock_project = mock.MagicMock()
        mock_ensure_project.return_value = mock_project
        
        with mock.patch("app.domains.api_mock.services.api_mock.cli_sync_service.run_import_job_internal") as mock_import:
            api_mock_service.run_import_job_background(
                job_id="job123",
                workspace_id="ws456",
                task_id="task789",
                user_id="user001",
                source_name="My Import",
                source_url="http://test",
                raw_content="swagger: '2.0'"
            )
            
            mock_import.assert_called_once_with(
                mock_db,
                mock_project,
                job_id="job123",
                source_name="My Import",
                source_url="http://test",
                raw_content="swagger: '2.0'",
                creator_id="user001"
            )
            
        mock_clear_cancel.assert_called_once_with("job123")
        mock_db.close.assert_called_once()

    @mock.patch("app.domains.api_mock.services.api_mock_service._mark_job_queue_failed")
    def test_run_with_api_mock_queue_runs_job_in_worker_thread(self, mock_mark_job_failed):
        @asynccontextmanager
        async def _fake_queue_api_mock_jobs(*_args, **_kwargs):
            yield

        with mock.patch("app.domains.api_mock.services.api_mock_service.queue_api_mock_jobs", _fake_queue_api_mock_jobs):
            called = {"ok": False}

            def _job_with_asyncio_run() -> None:
                # This would fail with "asyncio.run() cannot be called from a running event loop"
                # if executed directly inside the queue guard coroutine.
                asyncio.run(asyncio.sleep(0))
                called["ok"] = True

            api_mock_service._run_with_api_mock_queue("job123", _job_with_asyncio_run)

        self.assertTrue(called["ok"])
        mock_mark_job_failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
