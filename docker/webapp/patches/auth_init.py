import logging
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import exceptions as exc
from papermerge.core import types
from papermerge.core.config import get_settings
from papermerge.core.features.users.db import api as usr_dbapi
from papermerge.core.features.users import schema as users_schema
from papermerge.core.features.auth.remote_scheme import RemoteUserScheme
from papermerge.core.features.auth import scopes
from papermerge.core.db import exceptions as db_exc
from papermerge.core.utils import base64
from papermerge.core.db.engine import get_db

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/token/",
    auto_error=False,
    scopes=scopes.SCOPES,
)

remote_user_scheme = RemoteUserScheme()

logger = logging.getLogger(__name__)

settings = get_settings()


def extract_token_data(token: str = Depends(oauth2_scheme)) -> types.TokenData | None:
    if "." in token:
        _, payload, _ = token.split(".")
        data = base64.decode(payload)
        user_id: str = data.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is missing `sub` field",
            )
        token_scopes = data.get("scopes", [])
        groups = data.get("groups", [])
        roles = data.get("roles", [])
        username = data.get("preferred_username", None)
        email = data.get("email", None)

        return types.TokenData(
            scopes=token_scopes,
            user_id=user_id,
            username=username,
            email=email,
            groups=groups,
            roles=roles,
        )


async def get_current_user(
    security_scopes: SecurityScopes,
    remote_user: users_schema.RemoteUser | None = Depends(remote_user_scheme),
    token: str | None = Depends(oauth2_scheme),
    db_session: AsyncSession = Depends(get_db),
) -> users_schema.User:
    user = None
    total_scopes = []
    if token:  # token found
        token_data: types.TokenData = extract_token_data(token)

        if token_data is not None:
            try:
                user = await usr_dbapi.get_user(db_session, token_data.username)
            except db_exc.UserNotFound:
                # create normal user
                # Upstream bug fixed here: create_user() returns a
                # (user, error) tuple, but this used to assign it directly
                # to `user`, so the very next `user.is_superuser` check
                # below raised AttributeError on a tuple -- first-time
                # login always 500'd once UserNotFound was actually
                # reachable (see the get_user() fix in users/db/api.py).
                user, create_err = await usr_dbapi.create_user(
                    db_session,
                    username=token_data.username,
                    email=token_data.email,
                    user_id=UUID(token_data.user_id),
                    password="-",
                )
                if create_err is not None:
                    raise exc.HTTP401Unauthorized() from None
        total_scopes = token_data.scopes
        # superusers have all privileges
        if user.is_superuser:
            total_scopes.extend(scopes.SCOPES.keys())
        # Map OIDC/JWT `groups` and `roles` claims onto local Papermerge
        # Roles by name (case-insensitive, via get_user_scopes_from_roles).
        # Permissions only ever attach to Roles in this schema -- there is
        # no Group-level permission concept -- so both claims are resolved
        # the same way. Upstream bug fixed here: this used to call
        # `usr_dbapi.get_user_scopes_from_groups`, which does not exist
        # anywhere in the codebase and raised AttributeError on any token
        # carrying a non-empty `groups` claim.
        claimed_role_names = list(token_data.groups) + list(token_data.roles)
        if len(claimed_role_names) > 0:
            s = await usr_dbapi.get_user_scopes_from_roles(
                db_session,
                user_id=UUID(token_data.user_id),
                roles=claimed_role_names,
            )
            total_scopes.extend(s)

        # Flat low-privilege fallback: a JWT-authenticated non-superuser who
        # matched no role/group claim would otherwise end up with zero
        # scopes on first SSO login. If PAPERMERGE__AUTH__OIDC_DEFAULT_ROLE
        # names an existing Role, grant its permissions as a baseline.
        default_role_name = settings.papermerge__auth__oidc_default_role
        if not user.is_superuser and not total_scopes and default_role_name:
            s = await usr_dbapi.get_user_scopes_from_roles(
                db_session,
                user_id=UUID(token_data.user_id),
                roles=[default_role_name],
            )
            total_scopes.extend(s)

    elif remote_user:  # get user from headers
        # Using here external identity provider i.e.
        # user management is done in external application
        # If remote_user is not present in our DB then just create it
        # (with its home folder ID, inbox folder ID etc)
        try:
            user = await usr_dbapi.get_user(db_session, remote_user.username)
        except db_exc.UserNotFound:
            # create normal user
            # Upstream bugs fixed here: this was missing `await` entirely
            # (create_user() is async, so `user` was a bare coroutine, never
            # actually run) and, like the token branch above, didn't unpack
            # the (user, error) tuple create_user() returns.
            user, create_err = await usr_dbapi.create_user(
                db_session,
                username=remote_user.username,
                email=remote_user.email,
                password="-",
            )
            if create_err is not None:
                raise HTTPException(
                    status_code=401, detail="No credentials provided"
                ) from None
        # superusers have all privileges
        if user.is_superuser:
            total_scopes.extend(scopes.SCOPES.keys())
        # augment user scopes with permissions associated to local roles
        if len(remote_user.roles) > 0:
            s = await usr_dbapi.get_user_scopes_from_roles(
                db_session, user_id=user.id, roles=remote_user.roles
            )
            total_scopes.extend(s)

        if user is None:
            raise HTTPException(status_code=401, detail="No credentials provided")

    if user is None:
        raise exc.HTTP401Unauthorized()

    # User is authenticated.
    # But does he/she has enough permissions?
    for scope in security_scopes.scopes:
        if scope not in total_scopes:
            raise exc.HTTP403Forbidden()

    user.scopes = total_scopes  # is this required?

    return user
