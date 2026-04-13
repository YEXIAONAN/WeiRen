from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from weiren.models import AppSetting, ChangeLog
from weiren.utils.text import dumps_json


class SettingsService:
    def get(self, session: Session) -> AppSetting:
        setting = session.exec(select(AppSetting)).first()
        if setting is None:
            setting = AppSetting(id=1)
            session.add(setting)
            session.commit()
            session.refresh(setting)
        return setting

    def update(self, session: Session, **values: bool) -> AppSetting:
        setting = self.get(session)
        before = setting.model_dump()
        for key, value in values.items():
            if hasattr(setting, key):
                setattr(setting, key, bool(value))
        setting.updated_at = datetime.utcnow()
        session.add(setting)
        session.add(
            ChangeLog(
                entity_type="app_settings",
                entity_id=setting.id or 1,
                action="update",
                before_json=dumps_json(before),
                after_json=dumps_json(setting.model_dump()),
                note="更新隐私与演示模式设置",
            )
        )
        session.commit()
        session.refresh(setting)
        return setting
