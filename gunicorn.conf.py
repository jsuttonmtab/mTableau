# Gunicorn settings, loaded automatically from the app directory (gunicorn's
# default config file is ./gunicorn.conf.py). Options given on the command line
# in the systemd unit (-w, --timeout, log files) still apply alongside these.

# Threads let one worker serve several requests at once, so a long query no
# longer makes every other click (and every other user) wait behind it.
# One process keeps memory as before; each running query may use up to 2 GB
# in DuckDB, so keep this small.
worker_class = "gthread"
threads = 3
