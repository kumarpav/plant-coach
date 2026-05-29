from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os
import anthropic

from database import engine, get_db, Base
from models import Plant, Observation, UserConfig

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plant Daddy")
app.mount("/static", StaticFiles(directory="public"), name="static")

_anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

COACH_SYSTEM_PROMPT = """\
You are a knowledgeable, friendly plant care coach helping plant parents keep their plants healthy and thriving.
You understand plant biology, common houseplant species, soil science, and how to diagnose issues from symptoms.

Key diagnostic principles:
- Always tailor advice to the specific species — a succulent and a fern have completely different needs.
- Yellow leaves from the bottom up = usually overwatering or natural ageing.
- Yellow leaves at the top = underwatering, nutrient deficiency, or too much direct sun.
- Brown crispy tips = low humidity, underwatering, or fluoride in tap water.
- Brown mushy leaves or stem = overwatering or root rot. Act fast.
- Drooping with wet soil = overwatering. Drooping with dry soil = underwatering.
- Leggy, stretched growth = insufficient light. Move closer to a window.
- White crusty deposits on soil = mineral buildup from tap water. Flush with distilled water.
- Pests: check leaf undersides. Spider mites = fine webbing + stippled leaves. Mealybugs = white fluff.
  Fungus gnats = tiny flies around soil, larvae damage roots. Scale = brown bumps on stems.

If previous observations are provided, reference them explicitly — acknowledge what changed, whether
previous advice seemed to help, and build on that trajectory.

Always give 2–3 numbered, specific action items with reasons. Be encouraging but honest about severity.
Keep total response under 180 words."""


def generate_advice(plant: Plant, obs: Observation, recent: list) -> str:
    history = ""
    if recent:
        history = "\n\nRecent history (newest first):\n"
        for r in recent:
            history += (
                f"- [{r.obs_type}] {r.timestamp.strftime('%b %d')}: "
                f"{r.notes or 'no notes'} (health {r.health_rating}/5)\n"
            )

    user_msg = f"""Plant: {plant.name} ({plant.species})
Location: {plant.location or 'not specified'}
Light: {plant.light_level or 'not specified'}
Plant notes: {plant.notes or 'none'}

Current observation:
- Type: {obs.obs_type}
- Health rating: {obs.health_rating}/5
- Notes: {obs.notes or 'none provided'}{history}

What should I know or do for this plant?"""

    try:
        response = _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=320,
            system=[{"type": "text", "text": COACH_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}
        )
        return response.content[0].text
    except Exception:
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_token(x_user_token: str = Header(default="")) -> str:
    return x_user_token

def get_config(db: Session, token: str, key: str, default: str = "") -> str:
    row = db.query(UserConfig).filter(UserConfig.token == token, UserConfig.key == key).first()
    return row.value if row else default


# ── Schemas ───────────────────────────────────────────────────────────────────

class PlantIn(BaseModel):
    name: str
    species: str
    location: Optional[str] = ""
    light_level: Optional[str] = ""
    acquired: Optional[str] = ""
    notes: Optional[str] = ""
    photo_data: Optional[str] = ""

class LastObs(BaseModel):
    timestamp: datetime
    obs_type: str
    health_rating: int
    class Config:
        from_attributes = True

class PlantOut(BaseModel):
    id: int
    name: str
    species: str
    location: str
    light_level: str
    acquired: str
    notes: str
    photo_data: str
    created_at: datetime
    last_observation: Optional[LastObs] = None
    class Config:
        from_attributes = True

class ObsIn(BaseModel):
    obs_type: str
    health_rating: int
    notes: Optional[str] = ""

class ObsOut(BaseModel):
    id: int
    plant_id: int
    timestamp: datetime
    obs_type: str
    health_rating: int
    notes: str
    advice: str
    class Config:
        from_attributes = True

class ConfigIn(BaseModel):
    display_name: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("public/index.html")


# Plants
@app.post("/plants", response_model=PlantOut)
def create_plant(plant: PlantIn, db: Session = Depends(get_db), token: str = Depends(get_token)):
    row = Plant(**plant.model_dump(), token=token)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

@app.get("/plants", response_model=list[PlantOut])
def list_plants(db: Session = Depends(get_db), token: str = Depends(get_token)):
    plants = db.query(Plant).filter(Plant.token == token).order_by(Plant.created_at.desc()).all()
    result = []
    for p in plants:
        last = (
            db.query(Observation)
            .filter(Observation.plant_id == p.id)
            .order_by(Observation.timestamp.desc())
            .first()
        )
        out = PlantOut.model_validate(p)
        if last:
            out.last_observation = LastObs.model_validate(last)
        result.append(out)
    return result

@app.get("/plants/{plant_id}", response_model=PlantOut)
def get_plant(plant_id: int, db: Session = Depends(get_db), token: str = Depends(get_token)):
    p = db.query(Plant).filter(Plant.id == plant_id, Plant.token == token).first()
    if not p:
        raise HTTPException(404, "Plant not found")
    return p

@app.patch("/plants/{plant_id}", response_model=PlantOut)
def update_plant(plant_id: int, plant: PlantIn, db: Session = Depends(get_db), token: str = Depends(get_token)):
    row = db.query(Plant).filter(Plant.id == plant_id, Plant.token == token).first()
    if not row:
        raise HTTPException(404, "Plant not found")
    for k, v in plant.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row

@app.delete("/plants/{plant_id}")
def delete_plant(plant_id: int, db: Session = Depends(get_db), token: str = Depends(get_token)):
    row = db.query(Plant).filter(Plant.id == plant_id, Plant.token == token).first()
    if not row:
        raise HTTPException(404, "Plant not found")
    db.query(Observation).filter(Observation.plant_id == plant_id).delete()
    db.delete(row)
    db.commit()
    return {"ok": True}


# Observations
@app.post("/plants/{plant_id}/observations", response_model=ObsOut)
def log_observation(plant_id: int, obs: ObsIn, db: Session = Depends(get_db), token: str = Depends(get_token)):
    plant = db.query(Plant).filter(Plant.id == plant_id, Plant.token == token).first()
    if not plant:
        raise HTTPException(404, "Plant not found")
    row = Observation(**obs.model_dump(), plant_id=plant_id, token=token)
    db.add(row)
    db.commit()
    db.refresh(row)
    recent = (
        db.query(Observation)
        .filter(Observation.plant_id == plant_id, Observation.id != row.id)
        .order_by(Observation.timestamp.desc())
        .limit(5).all()
    )
    row.advice = generate_advice(plant, row, recent)
    db.commit()
    db.refresh(row)
    return row

@app.get("/plants/{plant_id}/observations", response_model=list[ObsOut])
def list_observations(plant_id: int, db: Session = Depends(get_db), token: str = Depends(get_token)):
    plant = db.query(Plant).filter(Plant.id == plant_id, Plant.token == token).first()
    if not plant:
        raise HTTPException(404, "Plant not found")
    return db.query(Observation).filter(Observation.plant_id == plant_id).order_by(Observation.timestamp.desc()).all()

@app.delete("/observations/{obs_id}")
def delete_observation(obs_id: int, db: Session = Depends(get_db), token: str = Depends(get_token)):
    obs = db.query(Observation).filter(Observation.id == obs_id, Observation.token == token).first()
    if not obs:
        raise HTTPException(404, "Observation not found")
    db.delete(obs)
    db.commit()
    return {"ok": True}


# Stats
@app.get("/stats")
def stats(db: Session = Depends(get_db), token: str = Depends(get_token)):
    plant_count = db.query(func.count(Plant.id)).filter(Plant.token == token).scalar()
    obs_count = db.query(func.count(Observation.id)).filter(Observation.token == token).scalar()
    return {"plants": plant_count, "observations": obs_count}


# Config
@app.patch("/api/config")
def update_config(body: ConfigIn, db: Session = Depends(get_db), token: str = Depends(get_token)):
    if body.display_name is not None:
        row = db.query(UserConfig).filter(UserConfig.token == token, UserConfig.key == "display_name").first()
        if row:
            row.value = body.display_name
        else:
            db.add(UserConfig(token=token, key="display_name", value=body.display_name))
        db.commit()
    return {"ok": True}

@app.get("/api/profile")
def api_profile(token: str = "", db: Session = Depends(get_db)):
    display_name = get_config(db, token, "display_name", "My Plant Collection")
    return {"display_name": display_name}
