from pydantic import BaseModel
from modules.model.notifications import NotificationsChannel


class PreferenceUpdate(BaseModel):
    channel: NotificationsChannel
    enabled: bool


class PreferenceResponse(BaseModel):
    channel: NotificationsChannel
    enabled: bool

    class Config:
        from_attributes = True