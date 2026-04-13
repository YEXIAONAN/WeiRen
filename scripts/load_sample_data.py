from __future__ import annotations

from pathlib import Path
import sys

from fastapi import UploadFile
from sqlmodel import Session

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weiren.config import settings
from weiren.db import engine, init_db
from weiren.services.import_service import ImportService


async def main() -> None:
    init_db()
    service = ImportService()
    sample_dir = Path(__file__).resolve().parent.parent / "sample_data"
    files = []
    for path in sorted(sample_dir.iterdir()):
        if path.is_file():
            files.append(UploadFile(filename=path.name, file=path.open("rb")))
    with Session(engine) as session:
        await service.import_uploads(session, files=files, subject_name="林栖")
    for upload in files:
        if upload.file:
            upload.file.close()
    print("Sample data imported.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
