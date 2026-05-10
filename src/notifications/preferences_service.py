from typing import Iterable

from sqlalchemy.orm import Session

from notifications.model import UserNotificationPreference


class PreferencesService:
    @staticmethod
    def get_preferences(db: Session, user_id):
        prefs = db.query(UserNotificationPreference).filter(
            UserNotificationPreference.user_id == user_id
        ).all()

        return prefs

    @staticmethod
    def update_preferences(db: Session, user_id, preferences: Iterable[UserNotificationPreference]):
        for pref in preferences:
            pref.user_id = user_id
            db.merge(pref)

        db.commit()
