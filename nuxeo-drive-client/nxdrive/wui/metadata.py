# coding: utf-8
""" GUI prompt to manage metadata. """

from PyQt4 import QtCore
from PyQt4.QtCore import Qt

from nxdrive.logging_config import get_logger
from nxdrive.utils import normalized_path
from nxdrive.wui.application import SimpleApplication
from nxdrive.wui.dialog import WebDialog, WebDriveApi
from nxdrive.wui.modal import WebModal

log = get_logger(__name__)

METADATA_WEBVIEW_WIDTH = 800
METADATA_WEBVIEW_HEIGHT = 700


class WebMetadataApi(WebDriveApi):
    def __init__(self, application, engine, remote_ref, dlg=None):
        self._engine = engine
        self._remote_ref = remote_ref
        self.error = dict()
        super(WebMetadataApi, self).__init__(application, dlg)

    @QtCore.pyqtSlot(result=str)
    def get_last_error(self):
        return self._json(self.error)

    @QtCore.pyqtSlot(str, result=str)
    def set_current_file(self, remote_ref):
        try:
            self._remote_ref = str(remote_ref)
            return self._engine.get_document_id(self._remote_ref)
        except Exception as e:
            log.debug(e)
        return None

    @QtCore.pyqtSlot()
    def open_file(self):
        self.open_local(self._engine.uid, self.get_current_file_state().local_path)

    @QtCore.pyqtSlot()
    def open_folder(self):
        self.open_local(self._engine.uid, self.get_current_file_state().local_parent_path)

    def get_current_file_state(self):
        return self._engine.get_dao().get_normal_state_from_remote(self._remote_ref)

    @QtCore.pyqtSlot(result=str)
    def get_current_file(self):
        dao = self._engine.get_dao()
        return self._json(dao.get_normal_state_from_remote(self._remote_ref))

    @QtCore.pyqtSlot(str, result=str)
    def get_next_file(self, mode):
        mode = str(mode)
        return self._json(self._engine.get_next_file(self._remote_ref, mode))

    @QtCore.pyqtSlot(str, result=str)
    def get_previous_file(self, mode):
        mode = str(mode)
        return self._json(self._engine.get_previous_file(self._remote_ref, mode))


class MetadataErrorHandler(QtCore.QObject):
    def __init__(self, dialog, api):
        super(MetadataErrorHandler, self).__init__()
        self.api = api
        # Have to save itself to the dialog to avoid being destroyed by scoping
        dialog._handler = self
        dialog.loadError.connect(self.loadMetadataErrorPage)

    def loadMetadataErrorPage(self, reply):
        self.api.error = reply
        self.sender().load('network_error.html', api=self.api)


def CreateMetadataWebDialog(manager, file_path, application=None):
    if application is None:
        application = QtCore.QCoreApplication.instance()
    try:
        infos = manager.get_metadata_infos(file_path)
    except ValueError:
        values = dict()
        values['file'] = file_path
        dialog = WebModal(application, application.translate("METADATA_FILE_NOT_HANDLE", values))
        dialog.add_button("OK", application.translate("OK"))
        return dialog
    api = WebMetadataApi(application, infos[2], infos[3])
    dialog = WebDialog(application, page=None, title=manager.app_name)
    dialog.token = infos[1]
    MetadataErrorHandler(dialog, api)
    dialog.load(infos[0], api=api)
    dialog.resize(METADATA_WEBVIEW_WIDTH, METADATA_WEBVIEW_HEIGHT)
    dialog.setWindowFlags(Qt.WindowStaysOnTopHint)
    return dialog


class MetadataApplication(SimpleApplication):
    def __init__(self, manager, options):
        super(MetadataApplication, self).__init__(manager, options, [])
        self.manager = manager
        self.options = options
        self.file_path = normalized_path(options.file)
        self.dialog = CreateMetadataWebDialog(manager, self.file_path, self)
        self.dialog.show()

