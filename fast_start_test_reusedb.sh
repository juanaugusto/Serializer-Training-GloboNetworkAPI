#!/bin/bash
if [ ! -d test_venv ]; then
    virtualenv test_venv
fi

source test_venv/bin/activate

echo "exporting NETWORKAPI_DEBUG"
export NETWORKAPI_DEBUG='DEBUG'

echo "exporting DJANGO_SETTINGS_MODULE"
export DJANGO_SETTINGS_MODULE='networkapi.settings_ci'

# Updates the SDN controller ip address
export REMOTE_CTRL_IP=$(nslookup netapi_odl | grep Address | tail -1 | awk '{print $2}')

echo "Starting tests.."
REUSE_DB=1 python manage.py test "$@"
