#!/bin/bash
pkill -HUP -f gunicorn
echo "RELOAD_SUCCESS_$(date +%s)" > /home/hanban-api/htdocs/api.hanban.site/reload_status.txt

