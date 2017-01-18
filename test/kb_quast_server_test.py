# -*- coding: utf-8 -*-
import unittest
import os  # noqa: F401
import time
import requests

from os import environ
import shutil
import uuid
import hashlib
try:
    from ConfigParser import ConfigParser  # py2 @UnusedImport
except:
    from configparser import ConfigParser  # py3 @UnresolvedImport @Reimport

from Workspace.WorkspaceClient import Workspace
from AbstractHandle.AbstractHandleClient import AbstractHandle as HandleService
from DataFileUtil.DataFileUtilClient import DataFileUtil
from kb_quast.kb_quastImpl import kb_quast
from kb_quast.kb_quastServer import MethodContext


class kb_quastTest(unittest.TestCase):

    WORKDIR = '/kb/module/work/tmp/'

    @classmethod
    def setUpClass(cls):
        cls.token = environ.get('KB_AUTH_TOKEN', None)
        user_id = requests.post(
            'https://kbase.us/services/authorization/Sessions/Login',
            data='token={}&fields=user_id'.format(cls.token)).json()['user_id']
        # WARNING: don't call any logging methods on the context object,
        # it'll result in a NoneType error
        cls.ctx = MethodContext(None)
        cls.ctx.update({'token': cls.token,
                        'user_id': user_id,
                        'provenance': [
                            {'service': 'kb_quast',
                             'method': 'please_never_use_it_in_production',
                             'method_params': []
                             }],
                        'authenticated': 1})
        config_file = environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('kb_quast'):
            cls.cfg[nameval[0]] = nameval[1]
        cls.shockURL = cls.cfg['shock-url']
        cls.ws = Workspace(cls.cfg['workspace-url'], token=cls.token)
        cls.hs = HandleService(url=cls.cfg['handle-service-url'],
                               token=cls.token)
        cls.impl = kb_quast(cls.cfg)
        cls.scratch = cls.cfg['scratch']
        shutil.rmtree(cls.scratch)
        os.mkdir(cls.scratch)
        suffix = int(time.time() * 1000)
        wsName = "test_ReadsUtils_" + str(suffix)
        cls.ws_info = cls.ws.create_workspace({'workspace': wsName})
        cls.dfu = DataFileUtil(os.environ['SDK_CALLBACK_URL'], token=cls.token)
        cls.staged = {}
        cls.nodes_to_delete = []
        cls.handles_to_delete = []
#         cls.setupTestData()
        print('\n\n=============== Starting tests ==================')

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'ws_info'):
            cls.ws.delete_workspace({'id': cls.ws_info[0]})
            print('Deleted test workspace: {}'.format(cls.ws_info[0]))
        if hasattr(cls, 'nodes_to_delete'):
            for node in cls.nodes_to_delete:
                cls.delete_shock_node(node)
        if hasattr(cls, 'handles_to_delete'):
            cls.hs.delete_handles(cls.hs.hids_to_handles(cls.handles_to_delete))
            print('Deleted handles ' + str(cls.handles_to_delete))

    def getWsName(self):
        return self.ws_info[1]

    @classmethod
    def delete_shock_node(cls, node_id):
        header = {'Authorization': 'Oauth {0}'.format(cls.token)}
        requests.delete(cls.shockURL + '/node/' + node_id, headers=header,
                        allow_redirects=True)
        print('Deleted shock node ' + node_id)

    def test_quast_from_1_file(self):
        ret = self.impl.run_QUAST(self.ctx, {'files': [
            {'path': 'data/greengenes_UnAligSeq24606.fa', 'label': 'foo'}]})[0]
        self.check_quast_output(ret, 313780, 313800, '7b5fcb9f4a41d1a047227139fbd8aa60',
                                'cd39eb4fd8ba1dad7e9133814fb0e2bc')

    def check_quast_output(self, ret, minsize, maxsize, repttxtmd5, icarusmd5):
        filename = 'quast_results.zip'

        shocknode = ret['shock_id']
        self.nodes_to_delete.append(shocknode)
        self.handles_to_delete.append(ret['handle']['hid'])
        self.assertEqual(ret['node_file_name'], filename)
        self.assertGreater(ret['size'], minsize)  # zip file size & md5 not repeatable
        self.assertLess(ret['size'], maxsize)
        shockret = requests.get(self.shockURL + '/node/' + shocknode,
                                headers={'Authorization': 'OAuth ' + self.token}).json()['data']
        self.assertEqual(shockret['id'], shocknode)
        shockfile = shockret['file']
        self.assertEqual(shockfile['name'], filename)
        self.assertEqual(shockfile['size'], ret['size'])
        handle = ret['handle']
        self.assertEqual(handle['url'], self.shockURL)
        self.assertEqual(handle['file_name'], filename)
        self.assertEqual(handle['type'], 'shock')
        self.assertEqual(handle['id'], shocknode)
        self.assertEqual(handle['remote_md5'], shockfile['checksum']['md5'])
        hid = handle['hid']
        handleret = self.hs.hids_to_handles([hid])[0]
        self.assertEqual(handleret['url'], self.shockURL)
        self.assertEqual(handleret['hid'], hid)
        self.assertEqual(handleret['file_name'], filename)
        self.assertEqual(handleret['type'], 'shock')
        self.assertEqual(handleret['id'], shocknode)
        self.assertEqual(handleret['remote_md5'], handle['remote_md5'])

        zipdir = os.path.join(self.WORKDIR, str(uuid.uuid4()))
        self.dfu.shock_to_file(
            {'shock_id': shocknode,
             'unpack': 'unpack',
             'file_path': os.path.join(zipdir, filename)
             })
        imd5 = hashlib.md5(open(os.path.join(zipdir, 'icarus.html'), 'rb')
                           .read()).hexdigest()
        self.assertEquals(imd5, icarusmd5)

        rmd5 = hashlib.md5(open(os.path.join(zipdir, 'report.txt'), 'rb')
                           .read()).hexdigest()
        self.assertEquals(rmd5, repttxtmd5)
