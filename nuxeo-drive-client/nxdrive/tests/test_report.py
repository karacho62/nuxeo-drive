'''
Created on 2 juil. 2015

@author: Remi Cattiau
'''
import unittest
from nxdrive.report import Report
from nxdrive.manager import Manager
import os
import tempfile
from nxdrive.logging_config import configure
from nxdrive.logging_config import get_logger

def configure_logger():
    configure(
        console_level='DEBUG',
        command_name='test',
        force_configure=True,
    )

# Configure test logger
configure_logger()
log = get_logger(__name__)


class ReportTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(u'-nxdrive-tests')
        from mock import Mock
        options = Mock()
        options.debug = False
        options.force_locale = None
        options.proxy_server = None
        options.log_level_file = None
        options.update_site_url = None
        options.beta_update_site_url = None
        options.nxdrive_home = self.folder
        self.manager = Manager(options)

    def tearDown(self):
        from shutil import rmtree
        rmtree(self.folder)

    def testLogs(self):
        # NXDRIVE-358
        report = Report(self.manager, os.path.join(self.folder, "report.zip"))
        log.debug("Strange encoding \xe9")
        log.debug(u"Unicode encoding \xe8")
        report.generate()
