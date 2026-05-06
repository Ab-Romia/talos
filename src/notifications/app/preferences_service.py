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
    def update_preferences(
            db: Session,
            user_id,
            preferences
    ):

        existing = db.query(UserNotificationPreference).filter(
            UserNotificationPreference.user_id == user_id
        ).all()

        existing_map = {
            p.channel: p for p in existing
        }

        for pref in preferences:

            if pref.channel in existing_map:

                existing_map[pref.channel].enabled = pref.enabled

            else:

                db.add(
                    UserNotificationPreference(
                        user_id=user_id,
                        channel=pref.channel,
                        enabled=pref.enabled
                    )
                )

        db.commit()
