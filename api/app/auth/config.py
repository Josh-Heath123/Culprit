import os

JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))

#: A single hardcoded operator credential, not a users table — this is a
#: small-team internal tool (CLAUDE.md's own framing: "on-call engineers
#: who are also the founders"), not a multi-tenant product. Same "fixed,
#: not a general onboarding flow" scope decision Phase 3 already made for
#: the demo-service API keys. Only the argon2 hash is ever stored here,
#: never the plaintext password.
OPERATOR_USERNAME = os.environ["OPERATOR_USERNAME"]
OPERATOR_PASSWORD_HASH = os.environ["OPERATOR_PASSWORD_HASH"]
