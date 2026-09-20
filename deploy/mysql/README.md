# Platform MySQL (production-preferred). Replaces Postgres as the primary
# application database. Trusted-claims holdout MySQL remains a separate service.
#
# Apply versioned migrations after first boot:
#   DATABASE_URL=mysql+pymysql://idp:...@mysql:3306/idp \
#     python3 scripts/apply_mysql_migrations.py
#
# Restore drill (blocker #4 close-out):
#   mysqldump -u idp -p idp > /backup/idp-$(date -u +%Y%m%dT%H%M%SZ).sql
#   mysql -u idp -p idp < /backup/....sql

MYSQL_DATABASE=idp
MYSQL_USER=idp
MYSQL_PASSWORD=change-me-in-secret-manager
MYSQL_ROOT_PASSWORD=change-me-root-in-secret-manager
