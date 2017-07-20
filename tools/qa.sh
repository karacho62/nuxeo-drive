#!/bin/bash
#
# Launch several QA tests. Sync with SonarCloud.
#
# Warning: do not execute this script manually but from Jenkins.
#
set -ex

main() {
    virtualenv -p python2 venv
    . venv/bin/activate
    pip install coverage pylint
    coverage combine .coverage_*
    coverage xml
    pylint nuxeo-drive-client/nxdrive > pylint_report.txt
    sonar-scanner
}

main
