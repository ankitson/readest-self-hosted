set shell := ["bash", "-e", "-o", "pipefail", "-c"]

apple_migration_root := env_var_or_default("APPLE_BOOKS_MIGRATION_ROOT", "./tmp/apple-books-library-migration")
apple_migration_scripts := "apps/readest-app/scripts/apple-books-library-migration"
metadata_cleanup_scripts := "apps/readest-app/scripts/readest-metadata-cleanup"
cover_backfill_scripts := "apps/readest-app/scripts/readest-cover-backfill"
calibre_migration_scripts := "apps/readest-app/scripts/calibre-library-migration"
calibre_migration_root := env_var_or_default("CALIBRE_BOOK_MIGRATION_ROOT", "./tmp/calibre-book-stage-migration")
metadata_cleanup_root := env_var_or_default("READEST_METADATA_CLEANUP_ROOT", "./tmp/readest-metadata-cleanup")
readest_env := env_var_or_default("READEST_ENV_FILE", "./secrets/readest.secrets.env")

default:
    @just --list

apple-books-migration-test:
    cd {{apple_migration_scripts}} && uv run --with 'boto3>=1.40,<2' python -m unittest -v test_apply_apple_books_library.py

apple-books-migration-plan:
    APPLE_BOOKS_MIGRATION_MANIFEST={{apple_migration_root}}/library-manifest.json \
    APPLE_BOOKS_MIGRATION_STAGE_DIR={{apple_migration_root}}/source-files \
    APPLE_BOOKS_MIGRATION_ANNOTATIONS_DIR={{apple_migration_root}}/annotation-exports \
    APPLE_BOOKS_MIGRATION_OUTPUT_DIR={{apple_migration_root}}/plan \
    pnpm --filter @readest/readest-app exec vitest run \
      scripts/apple-books-library-migration/apple-books-library-plan.test.ts --reporter=verbose

apple-books-migration-dry-run:
    cd {{apple_migration_scripts}} && uv run --script apply_apple_books_library.py \
      --plan {{apple_migration_root}}/plan/migration-plan.json \
      --stage-dir {{apple_migration_root}}/source-files \
      --covers-dir {{apple_migration_root}}/plan/covers \
      --env-file {{readest_env}}

apple-books-migration-verify:
    cd {{apple_migration_scripts}} && uv run --script verify_apple_books_library.py \
      --plan {{apple_migration_root}}/plan/migration-plan.json \
      --env-file {{readest_env}}

calibre-book-migration-plan:
    CALIBRE_BOOK_STAGE_ROOT={{calibre_migration_root}}/stage \
    CALIBRE_LIVE_BOOKS_JSON={{calibre_migration_root}}/pre-import/live-books.json \
    CALIBRE_BOOK_PLAN_OUTPUT={{calibre_migration_root}}/plan \
    pnpm --filter @readest/readest-app exec vitest run \
      scripts/calibre-library-migration/calibre-book-plan.test.ts --reporter=verbose

calibre-book-migration-dry-run:
    uv run --script {{calibre_migration_scripts}}/apply_calibre_book_stage.py \
      --plan {{calibre_migration_root}}/plan/calibre-book-plan.json \
      --stage-dir {{calibre_migration_root}}/stage \
      --output-dir {{calibre_migration_root}}/apply \
      --env-file {{readest_env}}

calibre-book-migration-verify:
    uv run --script {{calibre_migration_scripts}}/verify_calibre_book_stage.py \
      --plan {{calibre_migration_root}}/plan/calibre-book-plan.json \
      --covers-dir {{calibre_migration_root}}/apply/covers \
      --pre-state {{calibre_migration_root}}/pre-import/state.json \
      --env-file {{readest_env}} \
      --output {{calibre_migration_root}}/apply/verification-report.json

readest-metadata-cleanup-test:
    cd {{metadata_cleanup_scripts}} && uv run python -m unittest -v test_apply_readest_metadata_cleanup.py

readest-metadata-cleanup-dry-run:
    cd {{metadata_cleanup_scripts}} && uv run --script apply_readest_metadata_cleanup.py

readest-cover-backfill-test:
    cd {{cover_backfill_scripts}} && uv run --with 'boto3>=1.40,<2' --with 'httpx>=0.28,<1' --with 'pillow>=11,<12' --with 'pymupdf>=1.26,<2' python -m unittest -v test_backfill_readest_covers.py

readest-cover-backfill-prepare:
    cd {{cover_backfill_scripts}} && uv run --script backfill_readest_covers.py \
      --output-dir {{metadata_cleanup_root}}/covers \
      --env-file {{readest_env}}
