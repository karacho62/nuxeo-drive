#!/bin/sh -ex
#
# Launch several QA tests. Sync with SonarCloud.
#
# Warning: do not execute this script manually but from Jenkins.
#

main() {
    echo ">>> [QA] Setting up the virtualenv"
    virtualenv -p python2 venv
    . venv/bin/activate
    pip install coverage pylint

    echo ">>> [QA] Code coverage"
    coverage combine .coverage_*
    coverage xml

    echo ">>> [QA] Code quality"
    pylint nuxeo-drive-client/nxdrive > pylint_report.txt

    echo ">>> [QA] SonarCloud"
    sonar-scanner
}

main
