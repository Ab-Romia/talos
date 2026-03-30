import uuid
from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

UUID = Annotated[uuid.UUID, PlainSerializer(lambda v: v.hex if v else None)]
DATETIME = Annotated[datetime, PlainSerializer(lambda v: v.timestamp())]
