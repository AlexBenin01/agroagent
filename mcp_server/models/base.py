from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Tutti i datetime sono TIMESTAMPTZ (UTC) come da schema del piano tecnico
    type_annotation_map = {datetime: DateTime(timezone=True)}
