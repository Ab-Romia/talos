from sqlalchemy import select

from notifications.model import NotificationsChannel, UserNotificationPreference
from notifications.preferences_service import PreferencesService


class TestPreferencesService:

    def test_get_preferences_returns_preferences_for_user(self, db_session, test_user):
        user_id = test_user.id
        preferences = [
            UserNotificationPreference(user_id=user_id, channel=NotificationsChannel.email, enabled=False),
            UserNotificationPreference(user_id=user_id, channel=NotificationsChannel.push, enabled=True),
        ]
        db_session.add_all(preferences)
        db_session.commit()

        result = PreferencesService.get_preferences(db_session, user_id)

        # assert in db
        pref = db_session.scalar(
            select(UserNotificationPreference)
            .where(UserNotificationPreference.user_id == user_id)
        )
        assert len(result) == len(preferences)
        assert pref is not None
        assert pref.user_id == user_id
        assert pref.channel == preferences[0].channel
        assert pref.enabled == preferences[0].enabled

    def test_update_preferences_merges_preferences_and_commits(self, db_session, test_user):
        user_id = test_user.id
        preferences = [
            UserNotificationPreference(user_id=user_id, channel=NotificationsChannel.email, enabled=False),
            UserNotificationPreference(user_id=user_id, channel=NotificationsChannel.push, enabled=True),
        ]

        PreferencesService.update_preferences(db_session, user_id, preferences)

        assert all(pref.user_id == user_id for pref in preferences)
        for pref in preferences:
            db_pref = db_session.scalar(
                select(UserNotificationPreference)
                .where(
                    UserNotificationPreference.user_id == user_id,
                    UserNotificationPreference.channel == pref.channel
                )
            )
            assert db_pref is not None
            assert db_pref.user_id == user_id
            assert db_pref.channel == pref.channel
            assert db_pref.enabled == pref.enabled
