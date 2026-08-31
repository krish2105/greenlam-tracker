#!/bin/sh
# Creates the database pytest uses, on first container start.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE greenlam_test OWNER $POSTGRES_USER;
EOSQL
