import os
from unittest import SkipTest
from time import sleep
from nxdrive.client import NuxeoClient
from nxdrive.client import Unauthorized
from nxdrive.client import NotFound
from nxdrive.tests.common import IntegrationTestCase


def wait_for_deletion(client, doc, retries_left=10, delay=0.300,
                      use_trash=True):
    if retries_left <= 0:
        raise ValueError("Document was not deleted before client timeout")
    if not client.exists(doc, use_trash=use_trash):
        # OK: the document has been deleted
        return
    # Wait a bit for the sub-folder deletion asynchronous listner to do its
    # job and then retry
    sleep(delay)
    wait_for_deletion(client, doc, retries_left=retries_left - 1,
                      use_trash=use_trash)


class TestIntegrationNuxeoClient(IntegrationTestCase):

    def test_authentication_failure(self):
        self.assertRaises(Unauthorized, NuxeoClient,
                      self.remote_client.server_url,
                      'someone else', 'test-device',
                      password='bad password')
        self.assertRaises(Unauthorized, NuxeoClient,
                      self.remote_client.server_url,
                      'someone else', 'test-device',
                      token='some-bad-token')


    def test_make_token(self):
        token = self.remote_client.request_token()
        if token is None:
            raise SkipTest('nuxeo-platform-login-token is not deployed')
        self.assertTrue(len(token) > 5)
        self.assertEquals(self.remote_client.auth[0], 'X-Authentication-Token')
        self.assertEquals(self.remote_client.auth[1], token)

        # Requesting token is an idempotent operation
        token2 = self.remote_client.request_token()
        self.assertEquals(token, token2)

        # It's possible to create a new client using the same token
        remote_client2 = NuxeoClient(
            self.remote_client.server_url, self.remote_client.user_id,
            self.remote_client.device_id, token=token, base_folder='/')

        token3 = self.remote_client.request_token()
        self.assertEquals(token, token3)

        # Register a root with client 2 and see it with client one
        folder_1 = remote_client2.make_folder(self.workspace, 'Folder 1')
        remote_client2.register_as_root(folder_1)

        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 1)
        self.assertEquals(roots[0].name, 'Folder 1')

        # The root can also been seen with a new client connected using password
        # based auth
        password = os.environ.get('NXDRIVE_TEST_PASSWORD')
        remote_client3 = NuxeoClient(
            self.remote_client.server_url, self.remote_client.user_id,
            self.remote_client.device_id, password=password, base_folder='/')
        roots = remote_client3.get_roots()
        self.assertEquals(len(roots), 1)
        self.assertEquals(roots[0].name, 'Folder 1')

        # Another device using the same user credentials will get a different token
        self.remote_client4 = NuxeoClient(
            self.remote_client.server_url, self.remote_client.user_id,
            'other-test-device', password=password, base_folder='/')
        token4 = self.remote_client4.request_token()
        self.assertNotEquals(token, token4)

        # A client can revoke a token explicitly and thus loose credentials
        self.remote_client4.revoke_token()
        self.assertRaises(IOError, self.remote_client4.get_roots)


    def test_make_documents(self):
        doc_1 = self.remote_client.make_file(self.workspace, 'Document 1.txt')
        self.assertTrue(self.remote_client.exists(doc_1))
        self.assertEquals(self.remote_client.get_content(doc_1), "")
        doc_1_info = self.remote_client.get_info(doc_1)
        self.assertEquals(doc_1_info.name, 'Document 1.txt')
        self.assertEquals(doc_1_info.uid, doc_1)
        self.assertEquals(doc_1_info.get_digest(), self.EMPTY_DIGEST)
        self.assertEquals(doc_1_info.folderish, False)

        doc_2 = self.remote_client.make_file(self.workspace, 'Document 2.txt',
                                  content=self.SOME_TEXT_CONTENT)
        self.assertTrue(self.remote_client.exists(doc_2))
        self.assertEquals(self.remote_client.get_content(doc_2), self.SOME_TEXT_CONTENT)
        doc_2_info = self.remote_client.get_info(doc_2)
        self.assertEquals(doc_2_info.name, 'Document 2.txt')
        self.assertEquals(doc_2_info.uid, doc_2)
        self.assertEquals(doc_2_info.get_digest(), self.SOME_TEXT_DIGEST)
        self.assertEquals(doc_2_info.folderish, False)

        self.remote_client.delete(doc_2)
        self.assertTrue(self.remote_client.exists(doc_1))
        self.assertFalse(self.remote_client.exists(doc_2))
        self.assertRaises(NotFound, self.remote_client.get_info, doc_2)

        # the document has been put in the trash by default
        self.assertTrue(self.remote_client.exists(doc_2, use_trash=False) is not None)

        # the document is now physically deleted (by calling delete a second time:
        # the 'delete' transition will no longer be available hence physical
        # deletion is used as a fallback)
        self.remote_client.delete(doc_2)
        self.assertFalse(self.remote_client.exists(doc_2, use_trash=False))
        self.assertRaises(NotFound, self.remote_client.get_info, doc_2, use_trash=False)

        # Test folder deletion (with trash)
        folder_1 = self.remote_client.make_folder(self.workspace, 'A new folder')
        self.assertTrue(self.remote_client.exists(folder_1))
        folder_1_info = self.remote_client.get_info(folder_1)
        self.assertEquals(folder_1_info.name, 'A new folder')
        self.assertEquals(folder_1_info.uid, folder_1)
        self.assertEquals(folder_1_info.get_digest(), None)
        self.assertEquals(folder_1_info.folderish, True)

        doc_3 = self.remote_client.make_file(folder_1, 'Document 3.txt',
                                   content=self.SOME_TEXT_CONTENT)
        self.remote_client.delete(folder_1)
        self.assertFalse(self.remote_client.exists(folder_1))
        wait_for_deletion(self.remote_client, doc_3)

        self.assertFalse(self.remote_client.exists(doc_3))

        # Test folder deletion (without trash)
        folder_1 = self.remote_client.make_folder(self.workspace, 'A new folder')
        self.assertTrue(self.remote_client.exists(folder_1))
        folder_1_info = self.remote_client.get_info(folder_1)
        self.assertEquals(folder_1_info.name, 'A new folder')
        self.assertEquals(folder_1_info.uid, folder_1)
        self.assertEquals(folder_1_info.get_digest(), None)
        self.assertEquals(folder_1_info.folderish, True)

        doc_3 = self.remote_client.make_file(folder_1, 'Document 3.txt',
                                   content=self.SOME_TEXT_CONTENT)
        self.remote_client.delete(folder_1, use_trash=False)
        self.assertFalse(self.remote_client.exists(folder_1, use_trash=False))
        wait_for_deletion(self.remote_client, doc_3, use_trash=False)

    def test_complex_filenames(self):
        # create another folder with the same title
        title_with_accents = u"\xc7a c'est l'\xe9t\xe9 !"
        folder_1 = self.remote_client.make_folder(self.workspace, title_with_accents)
        folder_1_info = self.remote_client.get_info(folder_1)
        self.assertEquals(folder_1_info.name, title_with_accents)

        # create another folder with the same title
        title_with_accents = u"\xc7a c'est l'\xe9t\xe9 !"
        folder_2 = self.remote_client.make_folder(self.workspace, title_with_accents)
        folder_2_info = self.remote_client.get_info(folder_2)
        self.assertEquals(folder_2_info.name, title_with_accents)
        self.assertNotEquals(folder_1, folder_2)

        # Create a file
        # TODO: handle sanitization of the '/' character in local name
        long_filename = u"\xe9" * 50 + u"%$#!*()[]{}+_-=';:&^" + ".doc"
        file_1 = self.remote_client.make_file(folder_1, long_filename)
        file_1 = self.remote_client.get_info(file_1)
        self.assertEquals(file_1.name, long_filename)

    def test_missing_document(self):
        self.assertRaises(NotFound, self.remote_client.get_info,
                      '/Something Missing')

    def test_get_children_info(self):
        folder_1 = self.remote_client.make_folder(self.workspace, 'Folder 1')
        folder_2 = self.remote_client.make_folder(self.workspace, 'Folder 2')
        file_1 = self.remote_client.make_file(self.workspace, 'File 1.txt',
                                              content="foo\n")

        # not a direct child of self.workspace
        self.remote_client.make_file(folder_1, 'File 2.txt', content="bar\n")

        # ignored files
        self.remote_client.make_file(self.workspace,
                                     '.File 2.txt', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     '~$File 2.txt', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     'File 2.txt~', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     'File 2.txt.swp', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     'File 2.txt.lock', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     'File 2.txt.LOCK', content="baz\n")
        self.remote_client.make_file(self.workspace,
                                     'File 2.txt.part', content="baz\n")

        workspace_children = self.remote_client.get_children_info(self.workspace)
        self.assertEquals(len(workspace_children), 3)
        self.assertEquals(workspace_children[0].uid, file_1)
        self.assertEquals(workspace_children[0].name, 'File 1.txt')
        self.assertEquals(workspace_children[1].uid, folder_1)
        self.assertEquals(workspace_children[1].name, 'Folder 1')
        self.assertEquals(workspace_children[2].uid, folder_2)
        self.assertEquals(workspace_children[2].name, 'Folder 2')

    def test_get_synchronization_roots_from_server(self):
        # Check that the list of repositories can be introspected
        self.assertEquals(self.remote_client.get_repository_names(), ['default'])

        # By default no root is synchronized
        self.assertEquals(self.remote_client.get_roots(), [])

        # Register one root explicitly
        folder_1 = self.remote_client.make_folder(self.workspace, 'Folder 1')
        folder_2 = self.remote_client.make_folder(self.workspace, 'Folder 2')
        folder_3 = self.remote_client.make_folder(self.workspace, 'Folder 3')
        self.remote_client.register_as_root(folder_1)

        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 1)
        self.assertEquals(roots[0].name, 'Folder 1')

        # registetration is idem-potent
        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 1)
        self.assertEquals(roots[0].name, 'Folder 1')

        self.remote_client.register_as_root(folder_2)
        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 2)
        self.assertEquals(roots[0].name, 'Folder 1')
        self.assertEquals(roots[1].name, 'Folder 2')

        self.remote_client.unregister_as_root(folder_1)
        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 1)
        self.assertEquals(roots[0].name, 'Folder 2')

        # register new roots in another order
        self.remote_client.register_as_root(folder_3)
        self.remote_client.register_as_root(folder_1)
        roots = self.remote_client.get_roots()
        self.assertEquals(len(roots), 3)
        self.assertEquals(roots[0].name, 'Folder 1')
        self.assertEquals(roots[1].name, 'Folder 2')
        self.assertEquals(roots[2].name, 'Folder 3')

        self.remote_client.delete(folder_1, use_trash=True)
        self.remote_client.delete(folder_3, use_trash=False)
        self.remote_client.unregister_as_root(folder_2)
        self.assertEquals(self.remote_client.get_roots(), [])
