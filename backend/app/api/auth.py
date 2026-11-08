from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.security import create_token, hash_password, verify_password
from app.db.session import get_db, set_tenant
from app.models import Membership, Organization, User
from app.schemas.common import LoginIn, MeOut, OrgOut, SignupIn, TokenOut
from app.services.orgs import create_org

router = APIRouter(prefix="/api", tags=["auth"])

# Compare against a real hash when the email is unknown, so response time doesn't reveal
# which emails have accounts.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/auth/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)) -> TokenOut:
    if db.execute(select(User.id).where(User.email == body.email)).first():
        raise HTTPException(409, "an account with this email already exists")
    user = User(
        id=uuid.uuid4(),
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    set_tenant(db, user_id=user.id)
    org = create_org(db, user, body.org_name)
    db.commit()
    return TokenOut(token=create_token(user.id), user_id=user.id, org_id=org.id)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        raise HTTPException(401, "invalid email or password")
    return TokenOut(token=create_token(user.id), user_id=user.id)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> MeOut:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.created_at)
    ).all()
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        orgs=[OrgOut(id=o.id, name=o.name, role=r) for o, r in rows],
    )
