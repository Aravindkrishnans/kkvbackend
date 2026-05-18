import os
import sqlite3
from datetime import datetime, date, timezone
from typing import Optional, List
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, Session, SQLModel, create_engine, select, col

# ─────────────────────────────────────────
# DB SETUP  (using the provided logic)
# ─────────────────────────────────────────

db_folder = "db"
db_path = os.path.join(db_folder, "user_details.db")

if not os.path.exists(db_folder):
    os.makedirs(db_folder)
    print(f"Folder '{db_folder}' created")

try:
    conn = sqlite3.connect(db_path)
    print(f"Successfully connected to {db_path}")
    conn.close()
except sqlite3.Error as e:
    print(f"An error occurred: {e}")

DATABASE_URL = f"sqlite:///{db_path}"

# ─────────────────────────────────────────
# SQLModel ORM MODELS
# ─────────────────────────────────────────

class UserBase(SQLModel):
    p_username: str = Field(index=True)
    p_age: int
    p_number: int
    p_amount: str
    p_clinic: str


class User(UserBase, table=True):
    """ORM table model — maps to the 'users' table in SQLite."""
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    edited_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserCreate(UserBase):
    """Schema for creating a new appointment."""
    pass


class UserUpdate(SQLModel):
    """Schema for partial updates — all fields optional."""
    p_username: Optional[str] = None
    p_age: Optional[int] = None
    p_number: Optional[int] = None
    p_amount: Optional[str] = None
    p_clinic: Optional[str] = None


class UserRead(UserBase):
    """Schema returned to the client."""
    id: int
    created_at: datetime
    edited_at: datetime


# ─────────────────────────────────────────
# ENGINE & SESSION
# ─────────────────────────────────────────

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    migrate_database()
    print(f"[ORM] Tables created / verified at: {db_path}")


def migrate_database():
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "p_clinic" not in columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN p_clinic TEXT NOT NULL DEFAULT ''"
            )
            conn.commit()


def get_session():
    with Session(engine) as session:
        yield session


# ─────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────

app = FastAPI(
    title="OrthoClinic Appointment API",
    description="Orthopaedic clinic appointment management — backed by SQLModel ORM",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "message": "running",
    }


# ── CREATE ──────────────────────────────
@app.post("/appointments", response_model=UserRead, status_code=201, tags=["Appointments"])
def create_appointment(payload: UserCreate, session: Session = Depends(get_session)):
    """Add a new appointment."""
    now = datetime.now(timezone.utc)
    user = User(
        p_username=payload.p_username,
        p_age=payload.p_age,
        p_number=payload.p_number,
        p_amount=payload.p_amount,
        p_clinic=payload.p_clinic,
        created_at=now,
        edited_at=now,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ── READ ALL ─────────────────────────────
@app.get("/appointments", response_model=List[UserRead], tags=["Appointments"])
def get_all_appointments(session: Session = Depends(get_session)):
    """Return all appointments, newest first."""
    statement = select(User).order_by(col(User.created_at).desc())
    users = session.exec(statement).all()
    return users


# ── READ TODAY ───────────────────────────
@app.get("/appointments/today", response_model=List[UserRead], tags=["Appointments"])
def get_today_appointments(session: Session = Depends(get_session)):
    """Return only today's appointments."""
    # today_str = date.today().isoformat()
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    statement = (
    select(User)
    .where(User.created_at >= today_start)
    .where(User.created_at < tomorrow_start)
)
    # statement = (
    #     select(User)
    #     .where(col(User.created_at).cast(str).startswith(today_str))
    #     .order_by(col(User.created_at).asc())
    # )
    users = session.exec(statement).all()
    return users


# ── READ ONE ─────────────────────────────
@app.get("/appointments/{appointment_id}", response_model=UserRead, tags=["Appointments"])
def get_appointment(appointment_id: int, session: Session = Depends(get_session)):
    """Return a single appointment by ID."""
    user = session.get(User, appointment_id)
    if not user:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return user


# ── UPDATE ───────────────────────────────
@app.put("/appointments/{appointment_id}", response_model=UserRead, tags=["Appointments"])
def update_appointment(
    appointment_id: int,
    payload: UserUpdate,
    session: Session = Depends(get_session),
):
    """Partially update an appointment."""
    user = session.get(User, appointment_id)
    if not user:
        raise HTTPException(status_code=404, detail="Appointment not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    user.edited_at = datetime.now(timezone.utc)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ── DELETE ───────────────────────────────
@app.delete("/appointments/{appointment_id}", tags=["Appointments"])
def delete_appointment(appointment_id: int, session: Session = Depends(get_session)):
    """Delete an appointment by ID."""
    user = session.get(User, appointment_id)
    if not user:
        raise HTTPException(status_code=404, detail="Appointment not found")
    session.delete(user)
    session.commit()
    return {"message": f"Appointment #{appointment_id} deleted successfully"}


# ── STATS ────────────────────────────────
@app.get("/stats/today-count", tags=["Stats"])
def today_count(session: Session = Depends(get_session)):
    """Return count of today's appointments."""
    today_str = date.today().isoformat()
    statement = select(User).where(col(User.created_at).cast(str).startswith(today_str))
    count = len(session.exec(statement).all())
    return {"count": count, "date": today_str}
