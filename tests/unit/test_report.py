import asyncio
import tempfile
from pathlib import Path

from modules.storage import LocalArtifactStore
from services.report import ReportService


def test_generate_report():
    with tempfile.TemporaryDirectory() as directory:
        store = LocalArtifactStore(Path(directory))
        service = ReportService(store)
        result = asyncio.run(service.generate("123e4567-e89b-12d3-a456-426614174000", "QA <Report>", {"score": 96}))
        assert result["filename"] == "report_123e4567-e89b-12d3-a456-426614174000.html"
        assert "QA &lt;Report&gt;" in asyncio.run(store.read(result["filename"])).decode("utf-8")
