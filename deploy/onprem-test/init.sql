-- The application connects as an ordinary role, the way it will on the
-- customer's server: not a superuser, owner of its two databases only. If
-- something only works as superuser, the bench is where we find out.
CREATE ROLE predictive_app LOGIN PASSWORD 'onprem-test';
CREATE DATABASE predictive_control OWNER predictive_app;
CREATE DATABASE predictive_ipsa_test OWNER predictive_app;
