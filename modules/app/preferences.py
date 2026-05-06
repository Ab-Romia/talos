from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from modules.app.auth import (
    db_dependency,
    user_dependency
)

from modules.app.preferences_service import PreferencesService

from modules.model.preferences import (
    PreferenceUpdate,
    PreferenceResponse
)

router = APIRouter(
    prefix="/preferences",
    tags=["Preferences"]
)


@router.get(
    "/",
    response_model=List[PreferenceResponse]
)
def get_preferences(
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):

    return PreferencesService.get_preferences(
        db,
        current_user.id
    )


@router.put("/")
def update_preferences(
    preferences: List[PreferenceUpdate],
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):

    PreferencesService.update_preferences(
        db,
        current_user.id,
        preferences
    )

    return {"status": "updated"}