#!/bin/bash
# Runs once on first Postgres container startup.
# Creates the brain database and enables pgvector on it.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE votf_brain;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname votf_brain <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
