set shell := ["bash", "-e", "-o", "pipefail", "-c"]

apple_migration_root := env_var_or_default("APPLE_BOOKS_MIGRATION_ROOT", "/mnt/passport2tb/root/shared_storage/backups/readest/apple-books-library-migration-2026-08-13")
apple_migration_scripts := "apps/readest-app/scripts/apple-books-library-migration"
metadata_cleanup_scripts := "apps/readest-app/scripts/readest-metadata-cleanup"
readest_env := env_var_or_default("READEST_ENV_FILE", "/home/ankit/hroot/devserver/secrets/readest.secrets.env")

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

readest-metadata-cleanup-test:
    cd {{metadata_cleanup_scripts}} && uv run python -m unittest -v test_apply_readest_metadata_cleanup.py

readest-metadata-cleanup-dry-run:
    cd {{metadata_cleanup_scripts}} && uv run --script apply_readest_metadata_cleanup.py
