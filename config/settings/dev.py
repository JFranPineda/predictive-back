import os

from .base import *  # noqa: F403

DEBUG = True

# The on-premise bench and CI sign with a throwaway key, because ours never
# leaves the issuing machine. Production settings never read this.
LICENSE_PUBLIC_KEY = os.environ.get("LICENSE_PUBLIC_KEY") or LICENSE_PUBLIC_KEY  # noqa: F405
# Lets the bench play another machine. Same rule: production never reads it.
MACHINE_ID_FILE = os.environ.get("MACHINE_ID_FILE") or MACHINE_ID_FILE  # noqa: F405
