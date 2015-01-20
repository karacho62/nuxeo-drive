'''
Created on 8 janv. 2015

@author: Remi Cattiau
'''
from nxdrive.logging_config import get_logger
from nxdrive.engine.engine import Worker
from nxdrive.utils import current_milli_time
from nxdrive.client import NotFound
from time import sleep
from datetime import datetime
from nxdrive.client.common import COLLECTION_SYNC_ROOT_FACTORY_NAME
from nxdrive.client.common import LOCALLY_EDITED_FOLDER_NAME
from nxdrive.client.remote_file_system_client import RemoteFileInfo
import os
log = get_logger(__name__)
from PyQt4.QtCore import pyqtSignal


class RemoteWatcher(Worker):
    initiate = pyqtSignal()
    def __init__(self, engine, dao):
        super(RemoteWatcher, self).__init__(engine)
        self.unhandle_fs_event = False
        self.local_full_scan = dict()
        self._dao = dao

        self._last_sync_date = self._dao.get_config('remote_last_sync_date')
        self._last_event_log_id = self._dao.get_config('remote_last_event_log_id')
        self._last_root_definitions = self._dao.get_config('remote_last_root_definitions')
        self._last_remote_full_scan = self._dao.get_config('remote_last_full_scan')

        self._client = engine.get_remote_client()
        self._metrics = dict()
        self._metrics['last_remote_scan_time'] = -1
        self._metrics['last_remote_update_time'] = -1
        self.server_interval = 30
        self._current_interval = self.server_interval

    def get_metrics(self):
        metrics = super(RemoteWatcher, self).get_metrics()
        metrics['last_remote_sync_date'] = self._last_sync_date
        metrics['last_event_log_id'] = self._last_event_log_id
        metrics['last_root_definitions'] = self._last_root_definitions
        metrics['last_remote_full_scan'] = self._last_remote_full_scan
        metrics['next_polling'] = self._current_interval
        return dict(metrics.items() + self._metrics.items())

    def _execute(self):
        if self._last_remote_full_scan is None:
            self._scan_remote()
        else:
            self._handle_changes()
        self.initiate.emit()
        while (1):
            self._interact()
            if self._current_interval == 0:
                self._current_interval = self.server_interval
                self._handle_changes()
            else:
                self._current_interval = self._current_interval - 1
            sleep(1)

    def _scan_remote(self, from_state=None):
        local_path = None
        """Recursively scan the bound remote folder looking for updates"""
        start_ms = current_milli_time()

        try:
            if from_state is None:
                from_state = self._dao.get_state_from_local('/')
            self._client = self._engine.get_remote_client()
            remote_info = self._client.get_info(from_state.remote_ref)
        except NotFound:
            log.debug("Marking %r as remotely deleted.", from_state)
            # Should unbind ?
            #from_state.update_remote(None)
            self._dao.commit()
            self._metrics['last_remote_scan_time'] = current_milli_time() - start_ms
            return

        self._get_changes()
        self._save_changes_state()
        # recursive update
        self._scan_remote_recursive(from_state, remote_info)
        self._last_remote_full_scan = datetime.utcnow()
        self._dao.update_config('remote_last_full_scan', self._last_remote_full_scan)
        self._dao.commit()
        self._metrics['last_remote_scan_time'] = current_milli_time() - start_ms


    def _scan_remote_recursive(self, doc_pair, remote_info,
        force_recursion=True, mark_unknown=True):
        """Recursively scan the bound remote folder looking for updates

        If force_recursion is True, recursion is done even on
        non newly created children.
        """

        # Check if synchronization thread was suspended
        self._interact()

        if remote_info is None:
            raise ValueError("Cannot bind %r to missing remote info" %
                             doc_pair)

        # Update the pair state from the collected remote info
        self._dao.update_remote_state(doc_pair, remote_info, doc_pair.remote_parent_path)

        if not remote_info.folderish:
            # No children to align, early stop.
            return

        # If a folderish pair state has been remotely updated,
        # recursively unmark its local descendants as 'unsynchronized'
        # by marking them as 'unknown'.
        # This is needed to synchronize unsynchronized items back.
        if mark_unknown:
            # TODO Should be DAO method
            pass

        # Detect recently deleted children
        children_info = self._client.get_children_info(remote_info.uid)

        db_children = self._dao.get_remote_children(doc_pair.remote_ref)
        children = dict()
        to_scan = []
        for child in db_children:
            children[child.remote_ref] = child

        for child_info in children_info:
            child_pair = None
            remote_parent_path = doc_pair.remote_parent_path + '/' + child_info.uid
            new_pair = False
            if child_info.uid in children:
                child_pair = children.pop(child_info.uid)
                self._dao.update_remote_state(child_pair, child_info, remote_parent_path)
            else:
                child_pair, new_pair = self._find_remote_child_match_or_create(
                                                            doc_pair, child_info)
            if ((new_pair or force_recursion)
                and remote_info.folderish):
                    to_scan.append((child_pair, child_info))

        # Delete remaining
        for deleted in children.values():
            # TODO Should be DAO
            self._mark_deleted_remote_recursive(deleted)

        for folder in to_scan:
            self._scan_remote_recursive(folder[0], folder[1], mark_unknown=False)

    def _find_remote_child_match_or_create(self, parent_pair, child_info):
        local_path = os.path.join(parent_pair.local_path, child_info.name)
        remote_parent_path = parent_pair.remote_parent_path + '/' + child_info.uid
        # Try to get the local definition if not linked
        child_pair = self._dao.get_state_from_local(local_path)
        if child_pair is not None:
            # Should compare to xattr remote uid
            if child_pair.remote_ref is not None:
                child_pair = None
            else:
                self._dao.update_remote_state(child_pair, child_info, remote_parent_path)
                if (child_pair.folderish == child_info.folderish
                    and child_pair.local_digest == child_info.digest):
                    # Use version+1 as we just update the remote info
                    self._dao.synchronize_state(child_pair, child_pair.version + 1)
                child_pair = self._dao.get_state_from_id(child_pair.id, from_write=True)
                return child_pair, False
        row_id = self._dao.insert_remote_state(child_info, remote_parent_path,
                                              local_path, parent_pair.local_path)
        child_pair = self._dao.get_state_from_id(row_id, from_write=True)
        return child_pair, True

    def _handle_changes(self):
        self._update_remote_states()
        self._save_changes_state()

    def _save_changes_state(self):
        self._dao.update_config('remote_last_sync_date', self._last_sync_date)
        self._dao.update_config('remote_last_event_log_id', self._last_event_log_id)
        self._dao.update_config('remote_last_root_definitions', self._last_root_definitions)

    def _get_changes(self):
        """Fetch incremental change summary from the server"""
        summary = self._client.get_changes(self._last_root_definitions,
                                    self._last_event_log_id, self._last_sync_date)

        self._last_root_definitions = summary['activeSynchronizationRootDefinitions']
        self._last_sync_date = summary['syncDate']
        if self._client.is_event_log_id_available():
            # If available, read 'upperBound' key as last event log id
            # according to the new implementation of the audit change finder,
            # see https://jira.nuxeo.com/browse/NXP-14826.
            self._last_event_log_id = summary['upperBound']
        else:
            self._last_event_log_id = None
        return summary

    def _update_remote_states(self):
        """Incrementally update the state of documents from a change summary"""
        summary = self._get_changes()

        # Fetch all events and consider the most recent first
        sorted_changes = sorted(summary['fileSystemChanges'],
                                key=lambda x: x['eventDate'], reverse=True)
        n_changes = len(sorted_changes)
        if n_changes > 0:
            log.debug("%d remote changes detected", n_changes)
            self._metrics['last_changes'] = n_changes

        # Scan events and update the related pair states
        refreshed = set()
        for change in sorted_changes:

            # Check if synchronization thread was suspended
            # TODO In case of pause or stop: save the last event id
            self._interact()

            eventId = change.get('eventId')
            remote_ref = change['fileSystemItemId']
            if remote_ref in refreshed:
                # A more recent version was already processed
                continue
            fs_item = change.get('fileSystemItem')
            new_info = self._client.file_to_info(fs_item) if fs_item else None

            # Possibly fetch multiple doc pairs as the same doc can be synchronized at 2 places,
            # typically if under a sync root and locally edited.
            # See https://jira.nuxeo.com/browse/NXDRIVE-125
            doc_pairs = self._dao.get_states_from_remote(remote_ref)
            if not doc_pairs:
                # Relax constraint on factory name in FileSystemItem id to
                # match 'deleted' or 'securityUpdated' events.
                # See https://jira.nuxeo.com/browse/NXDRIVE-167
                doc_pairs = self._dao.get_states_from_partial_remote(remote_ref)

            updated = False
            if doc_pairs:
                for doc_pair in doc_pairs:
                    doc_pair_repr = doc_pair.local_path if doc_pair.local_path is not None else doc_pair.remote_name
                    # This change has no fileSystemItem, it can be either
                    # a "deleted" event or a "securityUpdated" event
                    if fs_item is None:
                        if eventId == 'deleted':
                            log.debug("Marking doc_pair '%s' as deleted",
                                      doc_pair_repr)
                            doc_pair.update_state(remote_state='deleted')
                        elif eventId == 'securityUpdated':
                            log.debug("Security has been updated for"
                                      " doc_pair '%s' denying Read access,"
                                      " marking it as deleted",
                                      doc_pair_repr)
                            doc_pair.update_state(remote_state='deleted')
                        else:
                            log.debug("Unknow event: '%s'", eventId)
                    else:
                        remote_parent_factory = doc_pair.remote_parent_ref.split('#', 1)[0]
                        new_info_parent_factory = new_info.parent_uid.split('#', 1)[0]
                        # Specific cases of a move on a locally edited doc
                        if (eventId == 'documentMoved'
                            and remote_parent_factory == COLLECTION_SYNC_ROOT_FACTORY_NAME):
                                # If moved from a non sync root to a sync root, break to creation case
                                # (updated is False).
                                # If moved from a sync root to a non sync root, break to noop
                                # (updated is True).
                                break
                        elif (eventId == 'documentMoved'
                              and new_info_parent_factory == COLLECTION_SYNC_ROOT_FACTORY_NAME):
                            # If moved from a sync root to a non sync root, delete from local sync root
                            log.debug("Marking doc_pair '%s' as deleted", doc_pair_repr)
                            doc_pair.update_state(remote_state='deleted')
                        else:
                            # Make new_info consistent with actual doc pair parent path for a doc member of a
                            # collection (typically the Locally Edited one) that is also under a sync root.
                            # Indeed, in this case, when adapted as a FileSystemItem, its parent path will be the one
                            # of the sync root because it takes precedence over the collection,
                            # see AbstractDocumentBackedFileSystemItem constructor.
                            consistent_new_info = new_info
                            if remote_parent_factory == COLLECTION_SYNC_ROOT_FACTORY_NAME:
                                new_info_parent_uid = doc_pair.remote_parent_ref
                                new_info_path = (doc_pair.remote_parent_path + '/' + remote_ref)
                                consistent_new_info = RemoteFileInfo(new_info.name, new_info.uid,
                                                            new_info_parent_uid, new_info_path, new_info.folderish,
                                                            new_info.last_modification_time,
                                                            new_info.last_contributor,
                                                            new_info.digest, new_info.digest_algorithm,
                                                            new_info.download_url, new_info.can_rename,
                                                            new_info.can_delete, new_info.can_update,
                                                            new_info.can_create_child)
                            # Perform a regular document update on a document
                            # that has been updated, renamed or moved
                            log.debug("Refreshing remote state info"
                                      " for doc_pair '%s'", doc_pair_repr)
                            eventId = change.get('eventId')
                            self._scan_remote_recursive(
                                doc_pair, consistent_new_info,
                                force_recursion=(eventId == "securityUpdated"))

                    updated = True
                    refreshed.add(remote_ref)

            if new_info and not updated:
                # Handle new document creations
                created = False
                parent_pairs = self._dao.get_states_from_remote(new_info.parent_uid)
                for parent_pair in parent_pairs:

                    child_pair, new_pair = (self
                        ._find_remote_child_match_or_create(
                        parent_pair, new_info))
                    if new_pair:
                        log.debug("Marked doc_pair '%s' as remote creation",
                                  child_pair.remote_name)

                    if child_pair.folderish and new_pair:
                        log.debug('Remote recursive scan of the content of %s',
                                  child_pair.remote_name)
                        self._scan_remote_recursive(child_pair, new_info)

                    created = True
                    refreshed.add(remote_ref)
                    break

                if not created:
                    log.debug("Could not match changed document to a "
                                "bound local folder: %r", new_info)