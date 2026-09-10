"""Owner routes — registration, login, profile."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.owner import Owner
from app.schemas.owner import OwnerCreate, OwnerResponse, OwnerLogin, OwnerTokenResponse
from app.core.security import hash_password, verify_password, create_access_token

router = APIRouter()


@router.post("/register", response_model=OwnerResponse, status_code=status.HTTP_201_CREATED)
async def register_owner(payload: OwnerCreate, db: AsyncSession = Depends(get_db)):
    """Register a new vehicle owner."""
    # Check for duplicate email
    result = await db.execute(select(Owner).where(Owner.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    owner = Owner(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )
    db.add(owner)
    await db.flush()
    await db.refresh(owner)
    return owner


@router.post("/login", response_model=OwnerTokenResponse)
async def login_owner(payload: OwnerLogin, db: AsyncSession = Depends(get_db)):
    """Authenticate an owner and return a JWT token."""
    result = await db.execute(select(Owner).where(Owner.email == payload.email))
    owner = result.scalar_one_or_none()
    if not owner or not verify_password(payload.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": owner.id, "email": owner.email})
    return OwnerTokenResponse(
        access_token=token,
        owner=OwnerResponse.model_validate(owner),
    )


@router.get("/{owner_id}", response_model=OwnerResponse)
async def get_owner(owner_id: str, db: AsyncSession = Depends(get_db)):
    """Get owner profile by ID."""
    result = await db.execute(select(Owner).where(Owner.id == owner_id))
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    return owner
