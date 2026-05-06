from typing import List

from fastapi import APIRouter

from backend.auth.utils.helpers import UserDep
from model import DatabaseDep
from .preferences_service import PreferencesService
from ..model import PreferenceResponse, PreferenceUpdate

router = APIRouter(prefix="/preferences", tags=["Preferences"])


@router.get("/", response_model=List[PreferenceResponse])
def get_preferences(db: DatabaseDep, current_user: UserDep):
    return PreferencesService.get_preferences(db, current_user.id)


@router.put("/")
def update_preferences(preferences: List[PreferenceUpdate], db: DatabaseDep, current_user: UserDep):
    PreferencesService.update_preferences(
        db,
        current_user.id,
        preferences
    )

    return {"status": "updated"}
