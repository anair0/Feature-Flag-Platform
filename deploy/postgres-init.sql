-- Runs once, as the postgres superuser, when the database volume is first created.
-- flags_owner owns the schema and runs migrations; flags_app is what the API connects as.
-- flags_app is NOT a superuser and not the table owner, so row-level security applies to it.
CREATE ROLE flags_owner LOGIN PASSWORD 'flags_owner';
CREATE ROLE flags_app LOGIN PASSWORD 'flags_app';
CREATE DATABASE flags OWNER flags_owner;
