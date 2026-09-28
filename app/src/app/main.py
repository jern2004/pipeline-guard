from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Incident, utc_now
from app.schemas import IncidentCreate, IncidentResponse

# Dependency injection: a route parameter typed DbSession receives a database Session
# that FastAPI creates by calling get_db for each request (and closes afterwards).
DbSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts: create any tables that do not exist yet.
    # Fine for this project; a production service would use schema migrations (e.g. Alembic).
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="PipelineGuard", lifespan=lifespan)


@app.get("/health")
def health():
    # Liveness check: the pipeline's smoke test calls this after starting the container.
    return {"status": "ok"}


@app.post("/incidents", response_model=IncidentResponse, status_code=201)
def create_incident(incident_in: IncidentCreate, db: DbSession):
    incident = Incident(**incident_in.model_dump())
    db.add(incident)
    db.commit()
    db.refresh(incident)  # load the saved row back, including the generated id and defaults
    return incident


@app.get("/incidents", response_model=list[IncidentResponse])
def list_incidents(db: DbSession):
    return db.scalars(select(Incident).order_by(Incident.id)).all()


@app.patch("/incidents/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(incident_id: int, db: DbSession):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Idempotent: resolving an already-resolved incident changes nothing
    # and keeps the original resolved_at timestamp.
    if incident.status != "resolved":
        incident.status = "resolved"
        incident.resolved_at = utc_now()
        db.commit()
        db.refresh(incident)
    return incident
