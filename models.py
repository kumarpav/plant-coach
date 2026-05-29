from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime, timezone
from database import Base


class Plant(Base):
    __tablename__ = "plants"

    id           = Column(Integer, primary_key=True, index=True)
    token        = Column(String(64), index=True, default="", server_default="")
    name         = Column(String(120))
    species      = Column(String(120))
    location     = Column(String(120), default="")
    light_level  = Column(String(50), default="")
    acquired     = Column(String(20), default="")
    notes        = Column(Text, default="")
    photo_data   = Column(Text, default="")
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Observation(Base):
    __tablename__ = "observations"

    id            = Column(Integer, primary_key=True, index=True)
    token         = Column(String(64), index=True, default="", server_default="")
    plant_id      = Column(Integer, index=True)
    timestamp     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    obs_type      = Column(String(50), default="note")
    notes         = Column(Text, default="")
    health_rating = Column(Integer, default=3)
    advice        = Column(Text, default="")


class UserConfig(Base):
    __tablename__ = "plant_user_config"

    id    = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), index=True, default="")
    key   = Column(String(50))
    value = Column(Text)
