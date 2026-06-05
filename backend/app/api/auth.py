from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.database import get_db
from app.models.user import User
from app.schemas.user import CaptchaOut, Token, UserCreate, UserOut
from app.services import auth_service, captcha


router = APIRouter(prefix="/auth", tags=["auth"])


def _require_captcha(captcha_id: str | None, captcha_code: str | None) -> None:
    if not captcha.verify_captcha(captcha_id, captcha_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")


@router.get("/captcha", response_model=CaptchaOut)
def captcha_image():
    return captcha.create_captcha()


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    _require_captcha(payload.captcha_id, payload.captcha_code)
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名已被占用")
    return auth_service.create_user(db, payload)


@router.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    captcha_id: str = Form(...),
    captcha_code: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_captcha(captcha_id, captcha_code)
    user = auth_service.authenticate(db, form.username, form.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return Token(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
