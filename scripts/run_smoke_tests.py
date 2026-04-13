from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from fastapi import UploadFile
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_sample_assets import main as generate_sample_assets
from weiren.db import engine, init_db
from weiren.main import create_app
from weiren.models import ExportRecord, Memory, QARecord, Quote, Source
from weiren.services.dedupe_service import DedupeService
from weiren.services.export_service import ExportService
from weiren.services.import_service import ImportService


async def ensure_sample_data() -> None:
    generate_sample_assets()
    init_db()
    service = ImportService()
    sample_dir = ROOT / "sample_data"
    files = []
    for path in sorted(sample_dir.iterdir()):
        if path.is_file():
            files.append(UploadFile(filename=path.name, file=path.open("rb")))
    with Session(engine) as session:
        await service.import_uploads(session, files=files, subject_name="林栖")
    for upload in files:
        if upload.file:
            upload.file.close()


def run_checks() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/review").status_code == 200
    assert client.get("/dedupe?refresh=1").status_code == 200
    assert client.get("/export").status_code == 200
    assert client.get("/settings").status_code == 200
    with Session(engine) as session:
        quote = session.exec(select(Quote).order_by(Quote.id.asc())).first()
        memory = session.exec(select(Memory).order_by(Memory.id.asc())).first()
        if quote is not None:
            assert client.get(f"/evidence/quote/{quote.id}").status_code == 200
        response = client.post("/qa", data={"subject_name": "林栖", "question": "她喜欢吃什么？"})
        assert response.status_code == 200
        assert session.exec(select(QARecord)).first() is not None
        export_path = ExportService().export_profile_markdown(session, "林栖", include_evidence=True, masked=True, confirmed_only=False)
        assert export_path.exists()
        DedupeService().scan(session)
        assert session.exec(select(Source)).first() is not None
        assert session.exec(select(ExportRecord)).first() is not None
    print("Smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(ensure_sample_data())
    run_checks()
