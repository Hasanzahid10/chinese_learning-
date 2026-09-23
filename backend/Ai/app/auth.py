from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

import jwt

from .config import settings


def verify_access_token(
    credentials: HTTPAuthorizationCredentials,
):
    token = credentials.credentials

    try:

        payload = jwt.decode(
            token,
            settings.django_jwt_secret_key,
            algorithms=["HS256"],
        )

    except jwt.ExpiredSignatureError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )

    except jwt.InvalidTokenError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    token_type = payload.get("token_type")

    if token_type != "access":

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required.",
        )

    user_id = payload.get("user_id")

    if user_id is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user_id.",
        )

    return payload

