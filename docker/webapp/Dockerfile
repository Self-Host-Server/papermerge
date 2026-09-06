ARG PAPERMERGE_VERSION=3.5.3

FROM docker.io/papermerge/papermerge:${PAPERMERGE_VERSION}

# core_app patches -- see docker/webapp/patches/*.py for the diff against
# upstream and why each change exists. Both files are full replacements of
# the corresponding upstream file, not partial patches, so a version bump
# requires re-diffing against the new upstream file rather than expecting
# these to apply cleanly.
COPY patches/config.py /core_app/papermerge/core/config.py
COPY patches/auth_init.py /core_app/papermerge/core/features/auth/__init__.py
COPY patches/users_db_api.py /core_app/papermerge/core/features/users/db/api.py
